"""
TG Export - 导出器核心
处理消息导出逻辑
"""
import asyncio
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from pyrogram.types import Message

from ..config import settings
from ..models import (
    ExportTask, ExportOptions, TaskStatus, ChatInfo, 
    MessageInfo, MediaType, ChatType, ExportFormat, FailedDownload,
    DownloadItem, DownloadStatus
)
from .client import telegram_client
from .retry_manager import DownloadRetryManager

logger = logging.getLogger(__name__)


class ExportManager:
    """导出管理器"""
    
    TASKS_FILE = "tasks.json"
    
    def __init__(self):
        self.tasks: Dict[str, ExportTask] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._active_download_tasks: Dict[str, Set[asyncio.Task]] = {} # 任务ID -> 下载协程集合
        self._paused_tasks: set = set()  # 暂停的任务ID
        self._resuming_tasks: set = set() # 正在恢复的任务ID (用于防止取消时重置状态)
        self._task_queues: Dict[str, asyncio.Queue] = {} # 任务ID -> 异步队列
        self._item_to_worker: Dict[str, Dict[str, asyncio.Task]] = {} # 任务ID -> {项ID: 协程任务}
        self._tasks_file = settings.DATA_DIR / self.TASKS_FILE
        # 确保数据目录存在
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        # 启动时加载任务
        self._load_tasks()
        # 脏标记，用于后台保存
        self._needs_save = False
        self._save_lock = asyncio.Lock()
        # 启动后台保存循环
        asyncio.create_task(self._auto_save_loop())
        # [NEW] 每5分钟自动恢复机制
        asyncio.create_task(self._auto_resume_loop())
    
    def _set_777_recursive(self, path: Path):
        """递归设置 777 权限"""
        try:
            import os
            # 设置当前路径权限
            os.chmod(path, 0o777)
            # 如果是目录，递归处理
            if path.is_dir():
                for item in path.iterdir():
                    self._set_777_recursive(item)
        except Exception as e:
            logger.warning(f"无法设置权限 777 为 {path}: {e}")
    
    def _load_tasks(self):
        """从文件加载任务"""
        try:
            if self._tasks_file.exists():
                with open(self._tasks_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"正在加载 {len(data)} 个任务...")
                for task_data in data:
                    try:
                        task = ExportTask.model_validate(task_data)
                        original_status = task.status
                        
                        # 容器重启后，运行中的任务需要暂停（因为没有活动的协程）
                        if task.status in [TaskStatus.RUNNING, TaskStatus.EXTRACTING]:
                            task.status = TaskStatus.PAUSED
                            self._paused_tasks.add(task.id)
                            logger.info(f"任务 '{task.name}' (ID: {task.id[:8]}...) 从 {original_status.value} 恢复为暂停状态")
                        elif task.status == TaskStatus.PAUSED:
                            self._paused_tasks.add(task.id)
                            logger.info(f"任务 '{task.name}' (ID: {task.id[:8]}...) 保持暂停状态")
                        
                        # 精确状态还原：将所有正在下载的项目重置为等待状态
                        for item in task.download_queue:
                            if item.status == DownloadStatus.DOWNLOADING:
                                item.status = DownloadStatus.WAITING
                                item.speed = 0
                            
                        self.tasks[task.id] = task
                    except Exception as e:
                        logger.error(f"加载任务失败: {e}")
                logger.info(f"✅ 已加载 {len(self.tasks)} 个任务，其中 {len(self._paused_tasks)} 个暂停")
            else:
                logger.info("未找到任务文件，从空白开始")
        except Exception as e:
            logger.error(f"加载任务文件失败: {e}")
    
    async def _auto_save_loop(self):
        """后台自动保存循环"""
        while True:
            try:
                await asyncio.sleep(10)  # 每 10 秒检查一次
                if self._needs_save:
                    await self._save_tasks_async()
            except Exception as e:
                logger.error(f"后台保存出错: {e}")

    async def _auto_resume_loop(self):
        """后台循环：每5分钟尝试恢复一个被系统自动暂停的文件"""
        while True:
            try:
                await asyncio.sleep(300) # 5分钟
                for task_id, task in list(self.tasks.items()):
                    if task.status != TaskStatus.RUNNING:
                        continue
                    
                    # 找到一个非手动暂停且处于 PAUSED 状态的项目进行恢复
                    target_item = None
                    for item in task.download_queue:
                        if item.status == DownloadStatus.PAUSED and not getattr(item, 'is_manually_paused', False):
                            target_item = item
                            break
                    
                    if target_item:
                        logger.info(f"任务 {task.id[:8]}: [Auto-Resume] 尝试恢复系统自动暂停项: {target_item.file_name}")
                        target_item.status = DownloadStatus.WAITING
                        # 如果有队列，加入队列
                        if task.id in self._task_queues:
                            self._task_queues[task.id].put_nowait(target_item)
                            await self._notify_progress(task_id, task)
            except Exception as e:
                logger.error(f"Auto-resume 循环出错: {e}")

    def _save_tasks(self):
        """同步保存（用于某些必须立即保存的场景）"""
        try:
            data = [task.model_dump(mode='json') for task in self.tasks.values()]
            with open(self._tasks_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            self._needs_save = False
        except Exception as e:
            logger.error(f"保存任务失败: {e}")

    async def _save_tasks_async(self):
        """异步保存"""
        async with self._save_lock:
            if not self._needs_save:
                return
            try:
                # 在线程池中执行 IO
                data = [task.model_dump(mode='json') for task in self.tasks.values()]
                def save():
                    with open(self._tasks_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                
                await asyncio.get_event_loop().run_in_executor(None, save)
                self._needs_save = False
                logger.debug("任务列表已自动保存")
            except Exception as e:
                logger.error(f"异步保存任务失败: {e}")
    
    def create_task(self, name: str, options: ExportOptions) -> ExportTask:
        """创建导出任务"""
        task = ExportTask(
            id=str(uuid.uuid4()),
            name=name,
            options=options
        )
        self.tasks[task.id] = task
        self._save_tasks()  # 保存到文件
        return task
    
    def get_task(self, task_id: str) -> Optional[ExportTask]:
        """获取任务"""
        return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> List[ExportTask]:
        """获取所有任务"""
        return list(self.tasks.values())
    
    def add_progress_callback(self, task_id: str, callback: Callable):
        """添加进度回调"""
        if task_id not in self._progress_callbacks:
            self._progress_callbacks[task_id] = []
        self._progress_callbacks[task_id].append(callback)
    
    async def _notify_progress(self, task_id: str, task: ExportTask):
        """通知进度更新"""
        # 标记需要保存，不再立即写盘
        self._needs_save = True
        
        callbacks = self._progress_callbacks.get(task_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(task)
                else:
                    callback(task)
            except Exception as e:
                print(f"进度回调错误: {e}")
    
    async def start_export(self, task_id: str) -> bool:
        """启动导出任务"""
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        if task.status == TaskStatus.RUNNING:
            return False
        
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        
        # 创建异步任务
        async_task = asyncio.create_task(self._run_export(task))
        self._running_tasks[task_id] = async_task
        
        return True
    
    async def cancel_export(self, task_id: str) -> bool:
        """取消导出任务"""
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        if task_id in self._running_tasks:
            self._running_tasks[task_id].cancel()
            del self._running_tasks[task_id]
        
        self._paused_tasks.discard(task_id)
        task.status = TaskStatus.CANCELLED
        await self._notify_progress(task_id, task)
        return True
    
    async def pause_export(self, task_id: str) -> bool:
        """暂停导出任务"""
        task = self.tasks.get(task_id)
        if not task or task.status not in [TaskStatus.RUNNING, TaskStatus.EXTRACTING]:
            return False
        
        self._paused_tasks.add(task_id)
        task.status = TaskStatus.PAUSED
        
        # 1. 取消所有正在进行的下载协程，这会立即中断 FloodWait 等待
        if task_id in self._active_download_tasks:
            active_tasks = list(self._active_download_tasks[task_id])
            if active_tasks:
                logger.info(f"正在中断 {len(active_tasks)} 个下载任务以实现立即暂停")
                for t in active_tasks:
                    if not t.done():
                        t.cancel()
        
        # 2. 将所有正在下载的项目标记为暂停
        for item in task.download_queue:
            if item.status == DownloadStatus.DOWNLOADING:
                item.status = DownloadStatus.PAUSED
        
        # [NEW] 显式标记任务状态，但保持在活动任务中，不触发清理
        await self._notify_progress(task_id, task)
        return True
    
    async def resume_export(self, task_id: str) -> bool:
        """恢复导出任务 (支持重跑已完成/失败任务)"""
        task = self.tasks.get(task_id)
        if not task or task.status not in [TaskStatus.PAUSED, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.COMPLETED]:
            logger.warning(f"无法恢复任务 {task_id[:8]}...: 任务不存在或状态不支持恢复 ({task.status if task else 'None'})")
            return False
        
        logger.info(f"正在恢复/重跑任务: '{task.name}' (ID: {task_id[:8]}...)")
        
        # 将所有暂停或失败的下载项恢复为等待状态 (已完成的不再重下)
        reset_count = 0
        for item in task.download_queue:
            if item.status in [DownloadStatus.PAUSED, DownloadStatus.FAILED]:
                item.status = DownloadStatus.WAITING
                item.progress = 0
                item.downloaded_size = 0
                item.speed = 0
                reset_count += 1
        
        if reset_count > 0:
            logger.info(f"同时重置了 {reset_count} 个下载项为等待状态 (全量任务重跑)")
            # 如果是重跑，也要重置任务级的计数
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                task.downloaded_media = 0
                task.downloaded_size = 0
            
        await self._notify_progress(task_id, task)
        
        # 标记为正在恢复，防止旧任务取消时将状态误设为 PAUSED
        self._resuming_tasks.add(task_id)
        
        # 安全地取消可能的旧任务
        if task_id in self._running_tasks:
            try:
                old_task = self._running_tasks[task_id]
                if not old_task.done():
                    logger.info(f"取消旧的运行任务: {task.name}")
                    old_task.cancel()
                    # 给一点时间让 cancelled handler 执行
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"取消旧任务出错: {e}")
                
        # 移除恢复标记
        self._resuming_tasks.discard(task_id)
        
        # 状态切换为运行中
        self._paused_tasks.discard(task_id)
        task.status = TaskStatus.RUNNING

        # 启动处理逻辑
        self._running_tasks[task_id] = asyncio.create_task(self._restart_download_queue(task))
        return True
    
    def _get_export_path(self, task: ExportTask) -> Path:
        """获取任务的导出路径"""
        import re
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', task.name)
        safe_name = safe_name.strip()[:100]  # 限制长度并去除首尾空格
        export_dir_name = safe_name
        export_path = settings.EXPORT_DIR / export_dir_name
        return export_path

    async def retry_file(self, task_id: str, item_id: str) -> bool:
        """重试单个文件 (支持重跑已完成项)"""
        task = self.tasks.get(task_id)
        if not task:
            return False
            
        target_item = None
        for item in task.download_queue:
            if item.id == item_id:
                target_item = item
                break
        
        if not target_item:
            return False
            
        logger.info(f"重试或重跑文件: {target_item.file_name} (Task: {task.name})")
        
        # 重置状态
        target_item.status = DownloadStatus.WAITING
        target_item.error = None
        target_item.progress = 0
        target_item.downloaded_size = 0
        target_item.speed = 0
        
        # 如果任务正在运行 (有队列存在)，将其加入队列
        if task.id in self._task_queues:
            self._task_queues[task.id].put_nowait(target_item)
            logger.info("任务正在运行，已将文件重新加入下载队列")
        else:
            logger.info("任务未运行，文件状态已重置，将在下次任务启动时下载")
            
        await self._notify_progress(task_id, task)
        return True
    
    def is_paused(self, task_id: str) -> bool:
        """检查任务是否暂停"""
        return task_id in self._paused_tasks
    
    async def pause_download_item(self, task_id: str, item_id: str) -> bool:
        """暂停单个下载项 (标记为手动)"""
        task = self.tasks.get(task_id)
        if not task: return False
        for item in task.download_queue:
                if item.id == item_id:
                    if item.status in [DownloadStatus.DOWNLOADING, DownloadStatus.WAITING]:
                        item.status = DownloadStatus.PAUSED
                        item.is_manually_paused = True # 标记为手动暂停
                        logger.info(f"手动暂停文件: {item.file_name}")
                        
                        # [Strong Restoration] 强行中止正在执行该項的协程
                        if task_id in self._item_to_worker and item_id in self._item_to_worker[task_id]:
                            worker_task = self._item_to_worker[task_id][item_id]
                            if not worker_task.done():
                                logger.info(f"任务 {task_id[:8]}: 强行中止卡死的下载协程以释放槽位: {item.file_name}")
                                worker_task.cancel()
                        
                        await self._notify_progress(task_id, task)
                        return True
        return False

    async def resume_download_item(self, task_id: str, item_id: str) -> bool:
        """恢复单个下载项 (清除手动标记)"""
        task = self.tasks.get(task_id)
        if not task: return False
        for item in task.download_queue:
            if item.id == item_id:
                if item.status == DownloadStatus.PAUSED:
                    item.status = DownloadStatus.WAITING
                    item.is_manually_paused = False # 清除手动暂停标记
                    logger.info(f"手动恢复文件: {item.file_name}")
                    if task.id in self._task_queues:
                        self._task_queues[task.id].put_nowait(item)
                    await self._notify_progress(task_id, task)
                    return True
        return False
    
    async def cancel_download_item(self, task_id: str, item_id: str) -> bool:
        """取消 (跳过) 单个下载项"""
        task = self.tasks.get(task_id)
        if not task: return False
        
        target_item = None
        for item in task.download_queue:
            if item.id == item_id:
                target_item = item
                break
        
        if not target_item: return False
        
        # 1. 标记为已跳过
        target_item.status = DownloadStatus.SKIPPED
        target_item.speed = 0
        
        # 2. 如果正在下载，尝试通过协程取消
        if task_id in self._active_download_tasks:
            # 找到对应的 Worker 协程
            # 注意：_active_download_tasks 里的 task 没有直接关联 item_id
            # 我们需要在 _download_item_worker 里维护更细的映射，或者这里简单遍历
            # 为了简单起见，我们在 worker 内部感知状态变化
            pass 
        
        await self._notify_progress(task_id, task)
        return True

    def get_download_queue(self, task_id: str, limit: int = 20, reversed_order: bool = False) -> Dict[str, Any]:
        """获取任务的分段下载队列 (优化：有进度的 WAITING 归入 Active)"""
        task = self.tasks.get(task_id)
        if not task:
            return {
                "downloading": [], "waiting": [], "failed": [], "completed": [],
                "counts": {"active": 0, "waiting": 0, "failed": 0, "completed": 0}
            }
        
        # 统一列表逻辑：
        # 活动中 (Active)：正在下载、已暂停、以及[有进度的等待中项]
        # 有进度的等待中项通常是刚点击“恢复”但还没轮到 worker 的文件，放在这里能防止 UI 跳转
        all_active = [i for i in task.download_queue if i.status in [DownloadStatus.DOWNLOADING, DownloadStatus.PAUSED] or (i.status == DownloadStatus.WAITING and i.progress > 0)]
        
        # 等待中 (Waiting)：状态为等待且进度为 0 的项
        all_waiting = [i for i in task.download_queue if i.status == DownloadStatus.WAITING and i.progress <= 0]
        
        all_failed = [i for i in task.download_queue if i.status == DownloadStatus.FAILED]
        all_completed = [i for i in task.download_queue if i.status in [DownloadStatus.COMPLETED, DownloadStatus.SKIPPED]]
        
        # 排序支持 (默认按 ID 升序)
        if reversed_order:
            all_active.sort(key=lambda x: x.message_id, reverse=True)
            all_waiting.sort(key=lambda x: (x.media_type, x.message_id), reverse=True) # 等待列表额外按类型权衡
            all_failed.sort(key=lambda x: x.message_id, reverse=True)
            all_completed.sort(key=lambda x: x.message_id, reverse=True)
        else:
            all_active.sort(key=lambda x: x.message_id)
            all_waiting.sort(key=lambda x: (x.media_type, x.message_id))
            all_failed.sort(key=lambda x: x.message_id)
            all_completed.sort(key=lambda x: x.message_id)

        # 如果 limit <= 0，则返回全量数据
        res_limit = limit if limit > 0 else 999999
        
        return {
            "downloading": all_active[:res_limit], 
            "waiting": all_waiting[:res_limit],
            "failed": all_failed[:res_limit],
            "completed": all_completed[:res_limit],
            "counts": {
                "active": len(all_active),
                "waiting": len(all_waiting),
                "failed": len(all_failed),
                "completed": len(all_completed)
            },
            "current_concurrency": task.current_max_concurrent_downloads or options.max_concurrent_downloads,
            "active_threads": len([i for i in all_active if i.status == DownloadStatus.DOWNLOADING])
        }
    async def _run_export(self, task: ExportTask):
        """执行导出任务"""
        try:
            options = task.options
            # 使用任务名称作为导出路径（清理特殊字符）
            export_path = self._get_export_path(task)
            
            # 自动创建导出目录并强制设置 777 权限 (支持覆盖/更新)
            export_path.mkdir(parents=True, exist_ok=True)
            self._set_777_recursive(export_path)
            
            # 记录实际导出的目录名供前端链接使用
            task.export_name = export_path.name
            # 更新 options 中的路径以便前端显示
            options.export_path = str(export_path)
            
            # 阶段 1: 提取消息和元数据
            task.status = TaskStatus.EXTRACTING
            task.is_extracting = True
            
            # 获取要导出的聊天列表
            chats = await self._get_chats_to_export(options)
            task.total_chats = len(chats)
            await self._notify_progress(task.id, task)
            
            # 导出数据收集
            all_messages = []
            
            # 遍历每个聊天
            for chat in chats:
                if task.status == TaskStatus.CANCELLED:
                    break
                
                chat_messages = await self._export_chat(task, chat, export_path)
                all_messages.extend(chat_messages)
                task.processed_chats += 1
                await self._notify_progress(task.id, task)
            
            # 生成初步输出文件 (文本已导出)
            if task.status != TaskStatus.CANCELLED:
                from ..exporters import json_exporter, html_exporter
                
                if options.export_format in [ExportFormat.JSON, ExportFormat.BOTH]:
                    await json_exporter.export(task, chats, all_messages, export_path)
                
                if options.export_format in [ExportFormat.HTML, ExportFormat.BOTH]:
                    await html_exporter.export(task, chats, all_messages, export_path)
                
                # 阶段 2: 下载媒体
                task.is_extracting = False
                if task.total_media > task.downloaded_media:
                    task.status = TaskStatus.RUNNING
                    await self._notify_progress(task.id, task)
                    await self._process_download_queue(task, export_path)
                
                if task.status not in [TaskStatus.CANCELLED, TaskStatus.PAUSED]:
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.now()
            
        except asyncio.CancelledError:
            # 如果正在恢复中（被新任务取代），则忽略取消事件，不修改状态
            if task.id in self._resuming_tasks:
                logger.info(f"任务 {task.name} 正在恢复中，忽略旧任务取消事件")
                return

            # 如果状态已经是 CANCELLED，说明是用户手动取消
            # 否则是系统关闭导致的取消，应该设为 PAUSED
            if task.status != TaskStatus.CANCELLED:
                logger.info(f"任务 {task.name} 被系统中断，状态设为暂停")
                task.status = TaskStatus.PAUSED
                self._paused_tasks.add(task.id)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.exception("导出任务执行出错")
        finally:
            await self._notify_progress(task.id, task)

    async def _restart_download_queue(self, task: ExportTask):
        """重新启动下载队列（用于恢复暂停的任务）"""
        try:
            options = task.options
            # 使用任务中已保存的导出路径
            export_path = Path(options.export_path) if options.export_path else settings.EXPORT_DIR / task.id
            
            logger.info(f"恢复下载队列: {task.name} ({len(task.download_queue)} 个文件)")
            
            if task.total_media > task.downloaded_media:
                task.status = TaskStatus.RUNNING
                await self._notify_progress(task.id, task)
                await self._process_download_queue(task, export_path)
            
            if task.status not in [TaskStatus.CANCELLED, TaskStatus.PAUSED]:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
        except asyncio.CancelledError:
            if task.id in self._resuming_tasks:
                logger.info(f"任务 {task.name} 正在恢复中，忽略旧队列取消事件")
                return

            if task.status != TaskStatus.CANCELLED:
                logger.info(f"下载队列被系统中断，状态设为暂停")
                task.status = TaskStatus.PAUSED
                self._paused_tasks.add(task.id)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.exception("恢复下载队列出错")
        finally:
            await self._notify_progress(task.id, task)
            # 清理运行任务记录
            if task.id in self._running_tasks:
                del self._running_tasks[task.id]

    async def _download_item_worker(self, task: ExportTask, item: DownloadItem, export_path: Path):
        """单个文件的下载核心逻辑 (由 Worker 调用)"""
        options = task.options

        # 获取当前协程任务并追踪 (用于强制取消)
        current_task = asyncio.current_task()
        if current_task:
            if task.id not in self._active_download_tasks:
                self._active_download_tasks[task.id] = set()
            self._active_download_tasks[task.id].add(current_task)
        
        try:
            if task.status == TaskStatus.CANCELLED or item.status in [DownloadStatus.COMPLETED, DownloadStatus.SKIPPED]:
                return

            # 等待暂停状态结束 (整体任务暂停 或 个人文件暂停)
            while (self.is_paused(task.id) or item.status == DownloadStatus.PAUSED) and task.status != TaskStatus.CANCELLED:
                await asyncio.sleep(1)
            
            if task.status == TaskStatus.CANCELLED:
                return

            # 获取原始消息对象用于下载
            logger.info(f"任务 {task.id[:8]}: Worker 正在获取消息对象 (ID: {item.message_id})...")
            msg = await telegram_client.get_message_by_id(item.chat_id, item.message_id)
            if not msg:
                item.status = DownloadStatus.FAILED
                item.error = "无法获取消息对象"
                await self._notify_progress(task.id, task)
                return

            # 标记为下载中 (用户能更客观看到并发)
            item.status = DownloadStatus.DOWNLOADING
            await self._notify_progress(task.id, task)

            # [FIX] 简化延迟方案：移除过长的 1s/0.3s 等待，改为极小的 0.1s 以维持异步切换
            await asyncio.sleep(0.1)

            full_path = export_path / item.file_path
            
            # 使用 temp 目录存放下载中的文件
            temp_dir = Path("/tmp/tg-export-downloads")
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file_path = temp_dir / f"{item.id}_{full_path.name}"
            
            retry_manager = DownloadRetryManager(
                max_retries=options.max_download_retries,
                initial_delay=options.retry_delay
            )
            
            # 速度计算需要的变量
            import time
            last_update = {
                'size': item.downloaded_size, 
                'time': time.time(),
                'last_progress_time': time.time()  # 用于卡死检测
            }
            loop = asyncio.get_running_loop()
            
            def progress_cb(current, total):
                now = time.time()
                elapsed = now - last_update['time']
                
                item.downloaded_size = current
                item.file_size = total
                if total > 0:
                    item.progress = (current / total) * 100
                
                # 计算速度 (至少间隔 1.5 秒更新一次)
                if elapsed >= 1.5:
                    now_val = current
                    if now_val > last_update['size']:
                        last_update['last_progress_time'] = now  # 更新最后进展时间
                    
                    # [Stuck Detection] 5分钟无进展自动重试 (仅针对正在下载的项目)
                    # 暂停的任务和等待任务不计算在此内，因为 progress_cb 只在活跃下载时被调用
                    if item.status == DownloadStatus.DOWNLOADING and (now - last_update['last_progress_time'] > 300):
                        logger.warning(f"检测到下载卡死: {item.file_name} (5分钟无进度增长)")
                        raise asyncio.TimeoutError("Download stuck for 5 minutes")

                    # 检查是否在此期间被取消了
                    if item.status == DownloadStatus.SKIPPED:
                        # 抛出取消异常以中止 download_media
                        raise asyncio.CancelledError("Item was skipped by user")
                    
                    if item.status == DownloadStatus.PAUSED:
                         raise asyncio.CancelledError("Item was paused by user")

                    bytes_diff = current - last_update['size']
                    item.speed = bytes_diff / elapsed if elapsed > 0 else 0
                    last_update['size'] = current
                    last_update['time'] = now
                    
                    # [NEW] 并行下载时，安全地通知单个文件的进度变化 (使用 call_soon_threadsafe 修复 loop 错误)
                    if bytes_diff > 0:
                        try:
                            loop.call_soon_threadsafe(
                                lambda: asyncio.create_task(self._notify_progress(task.id, task))
                            )
                        except Exception as e:
                            # 即使通知失败也不要中断任务
                            pass
            # 日志：记录下载路径
            logger.info(f"任务 {task.id[:8]}: 开始执行 download_media -> '{item.file_name}' (Size: {item.file_size})")
            
            # [Adaptive Concurrency] 限速触发时的回调
            async def on_flood_wait_cb(delay_secs):
                task.last_flood_wait_time = datetime.now()
                old_val = task.current_max_concurrent_downloads or options.max_concurrent_downloads
                
                # [Fast Response] 触发限速墙后，更果断地调低并发上限 (减 2 或降至 1)
                new_val = max(1, old_val - 2)
                task.current_max_concurrent_downloads = new_val
                task.consecutive_success_count = 0 
                
                # 同步更新底层 Pyrogram 限额
                telegram_client.set_max_concurrent_transmissions(new_val)
                
                # [Optimization] 激进压制：暂停所有超出新并发限制的正在下载项
                downloading_items = [i for i in task.download_queue if i.status == DownloadStatus.DOWNLOADING]
                if len(downloading_items) > new_val:
                    excess_count = len(downloading_items) - new_val
                    paused_count = 0
                    # 从后往前暂停
                    for i in reversed(task.download_queue):
                        if i.status == DownloadStatus.DOWNLOADING:
                            logger.warning(f"触碰限速墙，系统紧急暂停并发项: {i.file_name}")
                            i.status = DownloadStatus.PAUSED
                            paused_count += 1
                            if paused_count >= excess_count:
                                break
                
                logger.warning(f"任务 {task.id[:8]}: 检测到限速屏障，激进压制并发: {old_val} -> {new_val}")
                await self._notify_progress(task.id, task)

            try:
                success, downloaded_path, failure_info = await retry_manager.download_with_retry(
                    download_func=telegram_client.download_media,
                    message=msg,
                    file_path=temp_file_path,
                    refresh_message_func=telegram_client.get_message_by_id,
                    progress_callback=progress_cb,
                    on_flood_wait_callback=on_flood_wait_cb
                )
            except asyncio.TimeoutError:
                logger.error(f"任务 {task.id[:8]}: 下载文件 {item.file_name} (ID: {item.id}) 严重超时 (TimeoutError)")
                success, downloaded_path = False, None
                failure_info = {
                    "error_type": "timeout",
                    "error_message": "Request timed out during download"
                }

            # 5. 下载结果校验与收尾
            if success and downloaded_path:
                import os
                actual_size = os.path.getsize(downloaded_path) if os.path.exists(downloaded_path) else 0
                if actual_size == 0 and item.file_size > 0:
                    logger.error(f"任务 {task.id[:8]}: 检测到空包! 文件 {item.file_name} 长度为 0，视为下载失败。")
                    if os.path.exists(downloaded_path):
                        try: os.remove(downloaded_path)
                        except: pass
                    success = False

            if success:
                # 下载成功 (注意：downloaded_path 可能是 temp_file_path 或最终路径，视 retry_manager 策略而定)
                item.status = DownloadStatus.COMPLETED
                item.progress = 100.0
                item.speed = 0
                
                # 统一处理路径移动 (如果 downloaded_path 与 full_path 不一致)
                import shutil
                if downloaded_path and os.path.exists(downloaded_path):
                    if str(downloaded_path) != str(full_path):
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        try: os.chmod(full_path.parent, 0o777)
                        except: pass
                        shutil.move(str(downloaded_path), str(full_path))
                    
                    # 权限设置
                    try: os.chmod(full_path, 0o777)
                    except: pass
                    item.file_path = str(full_path.absolute())
                elif temp_file_path.exists():
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    try: os.chmod(full_path.parent, 0o777)
                    except: pass
                    shutil.move(str(temp_file_path), str(full_path))
                    try: os.chmod(full_path, 0o777)
                    except: pass
                    item.file_path = str(full_path.absolute())

                logger.info(f"任务 {task.id[:8]}: 文件 '{item.file_name}' 下载成功: {item.file_path}")
                task.downloaded_media += 1
                await self._notify_progress(task.id, task)
                return

            # 如果走到这里，说明 success 为 False (失败)
            if failure_info:
                item.status = DownloadStatus.FAILED
                item.error = failure_info.get("error_message", "Unknown error")
                
                # 记录到任务的失败列表
                from ..models import FailedDownload
                from datetime import datetime
                failed_download = FailedDownload(
                    message_id=item.message_id,
                    chat_id=item.chat_id,
                    file_name=item.file_name,
                    error_type=failure_info.get("error_type", "unknown"),
                    error_message=item.error,
                    retry_count=failure_info.get("retry_count", 0),
                    last_retry=datetime.now() # 使用当前时间
                )
                task.failed_downloads.append(failed_download)
                logger.error(f"任务 {task.id[:8]}: 文件 {item.file_name} 下载失败: {item.error}")
                await self._notify_progress(task.id, task)

        except asyncio.CancelledError:
            # 任务被取消（暂停或停止）
            logger.info(f"下载任务被取消/暂停: {item.file_name}")
            if item.status == DownloadStatus.DOWNLOADING:
                item.status = DownloadStatus.PAUSED
                item.speed = 0
            raise
        finally:
            if current_task and task.id in self._active_download_tasks:
                self._active_download_tasks[task.id].discard(current_task)

    async def _process_download_queue(self, task: ExportTask, export_path: Path):
        """处理下载队列 (Worker Pool 模式)"""
        options = task.options
        
        # [v1.4.0] 动态设置 Pyrogram 并发传输数，使 UI 配置生效
        telegram_client.set_max_concurrent_transmissions(options.max_concurrent_downloads)
        logger.info(f"任务 {task.id[:8]}: 并发下载数设置为 {options.max_concurrent_downloads}")
        
        # 按 message_id 升序排序
        task.download_queue.sort(key=lambda x: x.message_id)
        
        # 初始化任务队列
        queue = asyncio.Queue()
        self._task_queues[task.id] = queue
        
        # 将待下载项加入队列
        for item in task.download_queue:
            # 状态残留修复：重启或手动恢复时，将之前的“正在下载”项也重置并入队
            if item.status in [DownloadStatus.WAITING, DownloadStatus.PAUSED, DownloadStatus.FAILED, DownloadStatus.DOWNLOADING]:
                item.status = DownloadStatus.WAITING
                queue.put_nowait(item)
        
        # 初始化任务追踪集合
        if task.id not in self._active_download_tasks:
            self._active_download_tasks[task.id] = set()

        # [Adaptive Concurrency] 初始化动态并发状态
        if task.current_max_concurrent_downloads is None:
            task.current_max_concurrent_downloads = options.max_concurrent_downloads
            
        import random
        import time
        self._last_global_start_time = 0
        global_start_lock = asyncio.Lock()

        async def worker_logic(worker_id: int):
            """工协程逻辑"""
            try:
                async with global_start_lock:
                    now = time.time()
                    # [Smooth Startup] 每 5 秒开启一个 Worker 直到满载
                    wait_time = max(0, self._last_global_start_time + 5 - now)
                    if wait_time > 0:
                        await asyncio.sleep(wait_time)
                    self._last_global_start_time = time.time()
                
                logger.info(f"任务 {task.id[:8]}: 下载工协程 #{worker_id} 启动 (Smooth Startup 激活)")
            except Exception as e:
                logger.error(f"Worker #{worker_id} 启动延迟控制出错: {e}")

            while True:
                # 1. 检查任务是否已取消
                if task.status == TaskStatus.CANCELLED:
                    break
                
                # 2. 从队列取出一个待下载项 (阻塞式等待，直到有活干或收到退出信号)
                item = await queue.get()
                
                # 如果收到 None 信号，说明队列已关闭，Worker 应该辞职了
                if item is None:
                    queue.task_done()
                    break

                # 3. [Adaptive Concurrency] 检查当前并发槽位是否允许继续执行 (公平竞争)
                while True:
                    # 统计当前正在下载的项 (通过映射表判断)
                    active_count = len(self._item_to_worker.get(task.id, {}))
                    if active_count < (task.current_max_concurrent_downloads or 1):
                        break
                    
                    # 如果在等待期间任务被取消、全局暂停，或者项目被手动暂停，则跳过
                    if task.status == TaskStatus.CANCELLED:
                        queue.task_done()
                        return
                        
                    if self.is_paused(task.id):
                        # 如果全局暂停，让出 CPU 并循环检查
                        await asyncio.sleep(1)
                        continue
                        
                    if item.status == DownloadStatus.PAUSED or item.is_manually_paused:
                        # 项目被手动暂停，不再等待槽位，直接去 queue_done
                        break
                        
                    await asyncio.sleep(0.5)
                
                # 如果排队期间项目被用户手动暂停了，直接跳过
                if item.status == DownloadStatus.PAUSED or item.is_manually_paused:
                    queue.task_done()
                    continue

                # 4. 执行下载
                # [Strong Restoration] 注册映射，标记此 item 正在由当前协程处理
                if task.id not in self._item_to_worker:
                    self._item_to_worker[task.id] = {}
                self._item_to_worker[task.id][item.id] = asyncio.current_task()
                
                try:
                    # 记录下载前状态，用于捕获限速
                    await self._download_item_worker(task, item, export_path)
                    
                    # [Adaptive Concurrency] 成功下载后尝试恢复并发
                    # 如果没有异常（即 success 为 True 且没触发 FloodWait），则增加连续成功计数
                    if item.status == DownloadStatus.COMPLETED:
                        task.consecutive_success_count += 1
                        
                        # 每连续成功 15 个文件，尝试恢复 1 个并发槽位
                        if task.consecutive_success_count >= 15:
                            if (task.current_max_concurrent_downloads or 1) < options.max_concurrent_downloads:
                                old_val = task.current_max_concurrent_downloads
                                task.current_max_concurrent_downloads += 1
                                # [Adaptive] 同步恢复底层限额
                                telegram_client.set_max_concurrent_transmissions(task.current_max_concurrent_downloads)
                                logger.info(f"任务 {task.id[:8]}: 运行稳定，自动恢复并发: {old_val} -> {task.current_max_concurrent_downloads}")
                            task.consecutive_success_count = 0
                    
                    # 6. [Random Jitter] 下载完成后随机冷却 (3~10s)
                    if task.status != TaskStatus.CANCELLED and not self.is_paused(task.id):
                        jitter = random.uniform(3.0, 10.0)
                        logger.info(f"任务 {task.id[:8]}: Worker #{worker_id} 下载完成，进入 {jitter:.1f}s 随机冷却...")
                        await asyncio.sleep(jitter)
                except asyncio.CancelledError:
                    # [Persistence FIX] 如果任务被系统暂停或限速被迫中止，重回循环，不要退出
                    if item and item.status == DownloadStatus.DOWNLOADING:
                        item.status = DownloadStatus.PAUSED
                    logger.info(f"任务 {task.id[:8]}: Worker #{worker_id} 的下载项被取消/暂停: {item.file_name if item else 'Unknown'}")
                except Exception as e:
                    # 如果在这里捕获到直接异常，重置成功计数
                    task.consecutive_success_count = 0
                    
                    # 如果在这里捕获到 FloodWait（虽重试管理器会先处理），确保并发降低
                    err_str = str(e).lower()
                    if "flood" in err_str or "wait" in err_str:
                        old_val = task.current_max_concurrent_downloads
                        task.current_max_concurrent_downloads = max(1, (task.current_max_concurrent_downloads or 1) - 1)
                        logger.warning(f"检测到限速，动态降低并发: {old_val} -> {task.current_max_concurrent_downloads}")
                    
                    logger.error(f"Worker #{worker_id} 下载出错: {e}")
                finally:
                    # [Strong Restoration] 工作结束，不管是成功、失败还是被取消，都解绑映射
                    if item and task.id in self._item_to_worker:
                        self._item_to_worker[task.id].pop(item.id, None)
                    queue.task_done()
            
            logger.info(f"任务 {task.id[:8]}: 下载工协程 #{worker_id} 正常退出")

        # 启动工作协程池
        worker_tasks = []
        for i in range(options.max_concurrent_downloads):
            # 立即创建任务，由 worker_logic 内部通过 global_start_lock 自动排队实现 5s 间隔
            t = asyncio.create_task(worker_logic(i))
            worker_tasks.append(t)
            self._active_download_tasks[task.id].add(t)

        # 速度更新任务
        async def speed_updater():
            while True:
                await asyncio.sleep(3)
                if task.status not in [TaskStatus.RUNNING, TaskStatus.EXTRACTING]:
                    break
                    
                total_speed = sum(
                    i.speed for i in task.download_queue 
                    if i.status == DownloadStatus.DOWNLOADING
                )
                task.download_speed = total_speed
                await self._notify_progress(task.id, task)
        
        speed_task = asyncio.create_task(speed_updater())
        
        try:
            # 等待所有队列项处理完毕
            while True:
                # 检查是否还有处于活动状态的下载项
                active_downloads = sum(1 for i in task.download_queue if i.status == DownloadStatus.DOWNLOADING)
                pending_count = queue.qsize()
                
                if active_downloads == 0 and pending_count == 0:
                    # 队列空了，且没有正在下载的，说明这波活干完了
                    # 发送 None 信号给所有 worker 让它们有序下班
                    for _ in range(options.max_concurrent_downloads):
                        queue.put_nowait(None)
                    break
                
                # 如果任务取消，退出循环
                if task.status == TaskStatus.CANCELLED:
                    break
                    
                await asyncio.sleep(1)
                
        finally:
            # 清理
            speed_task.cancel()
            # 取消所有 worker
            for t in worker_tasks:
                if not t.done():
                    t.cancel()
            # 移除队列引用
            if task.id in self._task_queues:
                del self._task_queues[task.id]
            # 清理任务记录
            if task.id in self._active_download_tasks:
                self._active_download_tasks[task.id].clear()
            # [Strong Restoration] 清理项映射
            self._item_to_worker.pop(task.id, None)
    
    async def _get_chats_to_export(self, options: ExportOptions) -> List[ChatInfo]:
        """获取要导出的聊天列表"""
        all_chats = await telegram_client.get_dialogs()
        filtered_chats = []
        
        # 标准化指定的聊天 ID (处理可能缺失的 -100 前缀)
        standardized_specific_ids = []
        if options.specific_chats:
            for cid in options.specific_chats:
                standard_id = telegram_client.resolve_chat_id(str(cid))
                if isinstance(standard_id, int):
                    standardized_specific_ids.append(standard_id)
                else:
                    standardized_specific_ids.append(cid)
        
        for chat in all_chats:
            # 如果指定了特定聊天，只导出这些
            if standardized_specific_ids:
                if chat.id in standardized_specific_ids:
                    filtered_chats.append(chat)
                continue
            
            # 根据类型筛选
            if chat.type == ChatType.PRIVATE and options.private_chats:
                filtered_chats.append(chat)
            elif chat.type == ChatType.BOT and options.bot_chats:
                filtered_chats.append(chat)
            elif chat.type == ChatType.GROUP and options.private_groups:
                filtered_chats.append(chat)
            elif chat.type == ChatType.SUPERGROUP:
                # 区分公开和私密群组
                if chat.username and options.public_groups:
                    filtered_chats.append(chat)
                elif not chat.username and options.private_groups:
                    filtered_chats.append(chat)
            elif chat.type == ChatType.CHANNEL:
                # 区分公开和私密频道
                if chat.username and options.public_channels:
                    filtered_chats.append(chat)
                elif not chat.username and options.private_channels:
                    filtered_chats.append(chat)
        
        return filtered_chats
    
    async def _export_chat(
        self, 
        task: ExportTask, 
        chat: ChatInfo, 
        export_path: Path
    ) -> List[MessageInfo]:
        """导出单个聊天"""
        options = task.options
        messages: List[MessageInfo] = []
        
        # 创建 Telegram Desktop 风格的目录结构
        # export_path/chats/chat_ID/
        chats_dir = export_path / "chats"
        chat_dir = chats_dir / f"chat_{abs(chat.id)}"
        chat_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建媒体目录 - 匹配 Telegram Desktop 命名
        media_dirs = {
            MediaType.PHOTO: chat_dir / "photos",
            MediaType.VIDEO: chat_dir / "video_files",
            MediaType.VOICE: chat_dir / "voice_messages", 
            MediaType.VIDEO_NOTE: chat_dir / "round_video_messages",
            MediaType.AUDIO: chat_dir / "audio_files",
            MediaType.DOCUMENT: chat_dir / "files",
            MediaType.STICKER: chat_dir / "stickers",
            MediaType.ANIMATION: chat_dir / "gifs",
        }
        
        for dir_path in media_dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # 加载断点续传状态
        progress_file = chat_dir / ".export_progress.json"
        downloaded_ids = set()
        if options.resume_download and progress_file.exists():
            import json
            with open(progress_file, "r") as f:
                progress_data = json.load(f)
                downloaded_ids = set(progress_data.get("downloaded_message_ids", []))
        
        # 获取消息范围
        msg_from = options.message_from
        msg_to = options.message_to  # 0 表示最新
        
        # 获取消息
        async for msg in telegram_client.get_chat_history(chat.id):
            if task.status == TaskStatus.CANCELLED:
                break
            
            # 限制请求速率 (用户需求: 控制请求所有文本消息的api速率防止被限制)
            await asyncio.sleep(0.1)
            
            # 等待暂停状态结束
            while task.status == TaskStatus.PAUSED:
                await asyncio.sleep(1)
                if task.status == TaskStatus.CANCELLED:
                    break
            
            # 消息ID范围筛选 (1-0 表示全部, 1-100 表示1到100)
            if msg_to > 0 and msg.id > msg_to:
                continue  # 跳过比结束ID更新的消息
            if msg.id < msg_from:
                break  # 早于起始ID的消息，停止迭代
            
            # 时间范围筛选
            if options.date_from and msg.date < options.date_from:
                continue
            if options.date_to and msg.date > options.date_to:
                continue
            
            # 只导出我的消息
            if options.only_my_messages:
                me = await telegram_client.get_me()
                if msg.from_user and msg.from_user.id != me.get("id"):
                    continue
            
            # 断点续传 - 跳过已处理的消息
            if options.skip_existing and msg.id in downloaded_ids:
                task.processed_messages += 1
                continue
            
            # 消息过滤
            if options.filter_mode == "skip":
                # 跳过模式: 跳过指定的消息
                if msg.id in options.filter_messages:
                    continue
            elif options.filter_mode == "specify":
                # 指定模式: 只处理指定的消息
                if msg.id not in options.filter_messages:
                    continue
            
            task.total_messages += 1
            
            # 处理媒体
            media_type = telegram_client.get_media_type(msg)
            media_path = None
            
            if media_type:
                task.total_media += 1
                
                # 检查是否需要下载该类型
                should_download = self._should_download_media(media_type, options)
                
                if should_download:
                    # 准备下载目录
                    media_dir = media_dirs.get(media_type, chat_dir / "other")
                    media_dir.mkdir(parents=True, exist_ok=True)
                    
                    file_name = self._get_media_filename(msg, media_type)
                    file_path = media_dir / file_name
                    
                    # 创建下载项并加入队列
                    item_id = f"{chat.id}_{msg.id}"
                    download_item = DownloadItem(
                        id=item_id,
                        message_id=msg.id,
                        chat_id=chat.id,
                        file_name=file_name,
                        file_size=self._get_file_size(msg) or 0,
                        media_type=media_type,
                        file_path=str(file_path.relative_to(export_path))
                    )
                    
                    # 检查是否已经存在
                    if options.skip_existing and file_path.exists():
                        download_item.status = DownloadStatus.SKIPPED
                        download_item.downloaded_size = download_item.file_size
                        download_item.progress = 100.0
                        media_path = download_item.file_path
                        task.downloaded_media += 1
                    
                    task.download_queue.append(download_item)
            
            # 构建消息信息
            msg_info = MessageInfo(
                id=msg.id,
                date=msg.date,
                from_user_id=msg.from_user.id if msg.from_user else None,
                from_user_name=self._get_user_name(msg.from_user) if msg.from_user else None,
                text=msg.text or msg.caption,
                media_type=media_type,
                media_path=media_path,
                file_name=self._get_file_name(msg),
                file_size=self._get_file_size(msg),
                reply_to_message_id=msg.reply_to_message_id,
                message_link=telegram_client.get_message_link(msg.chat.id, msg.id, msg.chat.username)
            )
            
            messages.append(msg_info)
            task.processed_messages += 1
            
            # 记录已下载的消息ID
            downloaded_ids.add(msg.id)
            
            # 定期更新进度和保存断点
            if task.processed_messages % 50 == 0:
                await self._notify_progress(task.id, task)
                # 保存断点进度
                if options.resume_download:
                    import json
                    with open(progress_file, "w") as f:
                        json.dump({"downloaded_message_ids": list(downloaded_ids)}, f)
        
        # 保存最终进度
        if options.resume_download:
            import json
            with open(progress_file, "w") as f:
                json.dump({"downloaded_message_ids": list(downloaded_ids)}, f)
        
        return messages
    
    def _should_download_media(self, media_type: MediaType, options: ExportOptions) -> bool:
        """检查是否应该下载该媒体类型"""
        mapping = {
            MediaType.PHOTO: options.photos,
            MediaType.VIDEO: options.videos,
            MediaType.VOICE: options.voice_messages,
            MediaType.VIDEO_NOTE: options.video_messages,
            MediaType.AUDIO: options.files,
            MediaType.DOCUMENT: options.files,
            MediaType.STICKER: options.stickers,
            MediaType.ANIMATION: options.gifs,
        }
        return mapping.get(media_type, False)
    
    def _safe_filename(self, name: str) -> str:
        """生成安全的文件名 - 移除 emoji 和特殊符号"""
        import re
        # 移除 emoji (Unicode 表情符号范围)
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # 表情符号
            "\U0001F300-\U0001F5FF"  # 符号和象形文字
            "\U0001F680-\U0001F6FF"  # 交通和地图符号
            "\U0001F1E0-\U0001F1FF"  # 旗帜
            "\U00002702-\U000027B0"  # 杂项符号
            "\U0001F900-\U0001F9FF"  # 补充符号
            "\U0001FA00-\U0001FA6F"  # 国际象棋符号
            "\U0001FA70-\U0001FAFF"  # 扩展符号
            "\U00002600-\U000026FF"  # 杂项符号
            "]+", 
            flags=re.UNICODE
        )
        name = emoji_pattern.sub('', name)
        
        # 只保留: 字母、数字、中文、下划线、点、连字符
        name = re.sub(r'[^\w\u4e00-\u9fff.\-]', '_', name)
        
        # 合并连续下划线
        name = re.sub(r'_+', '_', name)
        
        # 去除首尾下划线
        name = name.strip('_')
        
        return name[:100] if name else 'unnamed'
    
    def _get_media_filename(self, msg: Message, media_type: MediaType) -> str:
        """获取媒体文件名 - 格式: 消息id-群id-文件名"""
        chat_id = abs(msg.chat.id)  # 去掉负号
        msg_id = msg.id
        
        if msg.document and msg.document.file_name:
            # 有原始文件名: msg_id-chat_id-格式化后的文件名
            safe_name = self._safe_filename(msg.document.file_name)
            return f"{msg_id}-{chat_id}-{safe_name}"
        
        ext_map = {
            MediaType.PHOTO: "jpg",
            MediaType.VIDEO: "mp4",
            MediaType.VOICE: "ogg",
            MediaType.VIDEO_NOTE: "mp4",
            MediaType.AUDIO: "mp3",
            MediaType.STICKER: "webp",
            MediaType.ANIMATION: "mp4",
        }
        ext = ext_map.get(media_type, "bin")
        # 无原始文件名: msg_id-chat_id-日期时间.扩展名
        date_str = msg.date.strftime("%Y%m%d_%H%M%S")
        return f"{msg_id}-{chat_id}-{date_str}.{ext}"
    
    def _get_user_name(self, user) -> str:
        """获取用户名"""
        if not user:
            return "未知"
        if user.first_name:
            name = user.first_name
            if user.last_name:
                name += f" {user.last_name}"
            return name
        return user.username or "未知"
    
    def _get_file_name(self, msg: Message) -> Optional[str]:
        """获取文件名"""
        if msg.document:
            return msg.document.file_name
        return None
    
    def _get_file_size(self, msg: Message) -> Optional[int]:
        """获取文件大小"""
        if msg.photo:
            return msg.photo.file_size
        elif msg.video:
            return msg.video.file_size
        elif msg.document:
            return msg.document.file_size
        elif msg.audio:
            return msg.audio.file_size
        return None
    
    def _update_download_progress(self, task: ExportTask, current: int):
        """更新下载进度"""
        task.downloaded_size = current


# 全局导出管理器
export_manager = ExportManager()
