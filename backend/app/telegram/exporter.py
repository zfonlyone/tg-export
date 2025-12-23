"""
TG Export - 导出器核心
处理消息导出逻辑
"""
import asyncio
import os
import json
import uuid
import time
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, Tuple
from pyrogram.types import Message

from ..config import settings
from ..models import (
    ExportTask, ExportOptions, TaskStatus, ChatInfo, 
    MessageInfo, MediaType, ChatType, ExportFormat, FailedDownload,
    DownloadItem, DownloadStatus
)
from pyrogram.errors import FloodWait
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
        self._progress_callbacks: Dict[str, List[Callable]] = {}
        self._paused_tasks: set = set()  # 暂停的任务ID
        self._resuming_tasks: set = set() # 正在恢复的任务ID (用于防止取消时重置状态)
        self._task_queues: Dict[str, asyncio.Queue] = {} # 任务ID -> 异步队列
        self._item_to_worker: Dict[str, Dict[str, asyncio.Task]] = {} # 任务ID -> {项ID: 协程任务}
        self._parallel_semaphores: Dict[str, asyncio.Semaphore] = {} # 任务ID -> 并行连接信号量
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
                        # [v1.6.1] 自动添加新版本字段 & 迁移逻辑
                        if "options" in task_data:
                            opts = task_data["options"]
                            # [v1.6.5 Migration] 将旧的 "download_threads" 逻辑迁移至 "parallel_chunk_connections" (分块数)
                            if "download_threads" in opts and "parallel_chunk_connections" not in opts:
                                old_threads = opts["download_threads"]
                                logger.info(f"迁移任务配置: 使用旧线程数 {old_threads} 作为新的分块数")
                                opts["parallel_chunk_connections"] = min(8, max(1, old_threads))
                            
                            opts.setdefault("incremental_scan_enabled", True)
                            opts.setdefault("enable_parallel_chunk", True)
                            opts.setdefault("parallel_chunk_connections", 4)
                        
                        task_data.setdefault("last_scanned_id", 0)
                        
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
                await asyncio.sleep(60)  # 每 60 秒检查一次 (v1.6.4 优化频率)
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
        
        # 将所有暂停或失败的下载项恢复为等待状态
        reset_count = 0
        for item in task.download_queue:
            if item.status in [DownloadStatus.PAUSED, DownloadStatus.FAILED]:
                # 如果是手动暂停的任务，保持其进度显示，只改状态为等待
                # 如果是执行失败的任务，则重置进度以重新开始
                if item.status == DownloadStatus.FAILED:
                    item.progress = 0
                    item.downloaded_size = 0
                
                item.status = DownloadStatus.WAITING
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
        """获取任务的导出路径 (带标识符后缀以防同名冲突)"""
        import re
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', task.name)
        safe_name = safe_name.strip()[:100]  # 限制长度并去除首尾空格
        
        # [FIX] 增加 ID 后缀，防止同名任务覆盖同一个文件夹
        # 使用 ID 的前 5 位作为后缀
        suffix = f"_{task.id[:5]}"
        export_dir_name = f"{safe_name}{suffix}"
        
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
        
        # 重置状态并标记为重试 (提高优先级)
        target_item.status = DownloadStatus.WAITING
        target_item.is_retry = True
        target_item.resume_timestamp = 0  # 重置恢复时间戳
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
        """暂停单个下载项 (释放槽位，Worker 去处理其他任务)"""
        task = self.tasks.get(task_id)
        if not task: return False
        for item in task.download_queue:
            if item.id == item_id:
                if item.status in [DownloadStatus.DOWNLOADING, DownloadStatus.WAITING]:
                    item.status = DownloadStatus.PAUSED
                    item.is_manually_paused = True
                    logger.info(f"暂停文件 (释放槽位): {item.file_name}")
                    
                    if task_id in self._item_to_worker and item_id in self._item_to_worker[task_id]:
                        worker_task = self._item_to_worker[task_id][item_id]
                        if not worker_task.done():
                            worker_task.cancel()
                    
                    await self._notify_progress(task_id, task)
                    return True
        return False


    async def resume_download_item(self, task_id: str, item_id: str) -> bool:
        """恢复单个下载项 (清除状态标记)"""
        task = self.tasks.get(task_id)
        if not task: return False
        for item in task.download_queue:
            if item.id == item_id:
                if item.status == DownloadStatus.PAUSED:
                    item.status = DownloadStatus.WAITING
                    item.is_manually_paused = False
                    item.resume_timestamp = time.time()  # 设置恢复时间戳，用于最高优先级调度
                    logger.info(f"恢复文件: {item.file_name}")
                    
                    # 总是将其推回队列，不再处理驻留信号
                    if task.id in self._task_queues:
                        self._task_queues[task.id].put_nowait(item)
                        
                    await self._notify_progress(task_id, task)
                    return True
        return False
    
    async def adjust_task_concurrency(self, task_id: str, max_concurrent: int = None, 
                                       download_threads: int = None, 
                                       parallel_chunk: int = None) -> bool:
        """运行时调整任务并发设置 (v1.6.5)
        
        并发数改变会立即触发 Worker Manager 的扩缩容。
        分块数改变会影响后续开始下载的文件。
        """
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        changes = []
        if max_concurrent is not None:
            max_concurrent = max(1, min(20, max_concurrent))
            task.options.max_concurrent_downloads = max_concurrent
            # 更新客户端内部限制 (立即生效)
            telegram_client.set_max_concurrent_transmissions(max_concurrent)
            changes.append(f"并发: {max_concurrent}")
        
        if parallel_chunk is not None:
            parallel_chunk = max(1, min(8, parallel_chunk))
            task.options.parallel_chunk_connections = parallel_chunk
            changes.append(f"分块: {parallel_chunk}")
            
        if changes:
            logger.info(f"任务 {task_id[:8]} 并发设置已更新: {', '.join(changes)}")
            # 唤醒队列 (如果并发数增加，且队列中有任务)
            if max_concurrent is not None and task.id in self._task_queues:
                queue = self._task_queues[task.id]
                # 尝试推入几个项目以激活新 Worker
                count = 0
                for item in task.download_queue:
                    if item.status == DownloadStatus.WAITING and item.id not in self._item_to_worker.get(task.id, {}):
                        queue.put_nowait(item)
                        count += 1
                        if count >= 5: break
            
            await self._save_tasks_async()
            await self._notify_progress(task.id, task)
            return True
        return False
        return False
    async def verify_integrity(self, task_id: str) -> Dict[str, Any]:
        """完整性校验 (异步触发接口) (v1.6.4)"""
        task = self.tasks.get(task_id)
        if not task:
            return {"status": "error", "message": "任务不存在"}
        
        if task.status == TaskStatus.RUNNING:
             return {"status": "error", "message": "任务正在运行中，请先暂停后再校验"}
        
        if task.is_verifying:
            return {"status": "error", "message": "后台校验任务已在运行中"}

        # 标记正在校验并启动后台协程
        task.is_verifying = True
        task.last_verify_result = "正在校验中..."
        asyncio.create_task(self._verify_integrity_worker(task_id))
        
        logger.info(f"任务 {task_id[:8]} 触发异步完整性校验")
        return {"status": "initiated", "message": "校验任务已在后台启动，请留意进度更新"}

    async def _verify_integrity_worker(self, task_id: str):
        """后台校验协程逻辑 (v1.6.4)"""
        task = self.tasks.get(task_id)
        if not task: return
        
        logger.info(f"开始执行后台完整性校验 (Task: {task_id[:8]})")
        
        # 记录原始状态以便恢复
        old_status = task.status
        
        try:
            options = task.options
            export_path = Path(options.export_path).expanduser()
            
            # 1. 扫描阶段: 触发全量消息提取
            task.status = TaskStatus.EXTRACTING
            task.is_extracting = True
            task._force_full_scan = True 
            await self._notify_progress(task_id, task)
            
            # 获取要导出的聊天列表
            chats = await self._get_chats_to_export(options)
            task.total_chats = len(chats)
            task.processed_chats = 0
            
            # 执行全量提取
            for chat in chats:
                if task.status in [TaskStatus.CANCELLED, TaskStatus.PAUSED]: 
                    logger.info(f"校验任务被取消或暂停 (Task: {task_id[:8]})")
                    break
                
                logger.debug(f"校验扫描 - 正在扫描聊天: {chat.title} ({chat.id})")
                _, highest_id = await self._export_chat(task, chat, export_path)
                
                # 更新增量扫描 ID
                if highest_id > task.last_scanned_ids.get(chat.id, 0):
                    task.last_scanned_ids[chat.id] = highest_id
                    
                task.processed_chats += 1
                await self._notify_progress(task_id, task)

            task.is_extracting = False
            task._force_full_scan = False
            
            if task.status == TaskStatus.CANCELLED:
                task.is_verifying = False
                return

            # 2. 物理检查与文件名发现阶段
            logger.info(f"扫描阶段完成，开始物理文件检查 (Task: {task_id[:8]})")
            
            # 统计
            passed_count = 0
            failed_count = 0 
            missing_count = 0
            recovered_count = 0
            discovered_count = 0
            moved_for_resume = 0
            
            # 2.1 遍历目录扫描未在 queue 中的文件 (自动发现)
            # 格式: {msg_id}-{chat_id}-{name}
            pattern = re.compile(r"^(\d+)-(\d+)-(.*)$")
            task.current_scanning_chat = "正在磁盘扫描..."
            
            # 预处理 queue 中的路径以避免重复检查
            queued_paths = {item.file_path for item in task.download_queue if item.file_path}
            
            file_check_count = 0
            for root, dirs, files in os.walk(export_path):
                for file_name in files:
                    file_check_count += 1
                    match = pattern.match(file_name)
                    if not match: continue
                    
                    msg_id = int(match.group(1))
                    chat_id_abs = int(match.group(2))
                    
                    # [v1.6.4] 更新发现进度
                    task.current_scanning_msg_id = msg_id
                    if file_check_count % 50 == 0:
                        await self._notify_progress(task_id, task)
                        
                    # 查找对应项
                    target_item = None
                    # Telegram 聊天 ID 通常是负数，尝试带负号的
                    target_item = task.get_download_item(msg_id, -chat_id_abs)
                    if not target_item:
                        # 尝试正号 (部分私聊/特殊情况)
                        target_item = task.get_download_item(msg_id, chat_id_abs)
                        
                    if target_item:
                        full_path = Path(root) / file_name
                        relative_path = str(full_path.relative_to(export_path))
                        
                        # 如果已经在队列中且路径一致，由于是在 os.walk 中发现的，标记为已处理以防后续 queue 检查重复
                        # (这里暂不标记，直接走逻辑)
                        
                        try:
                            actual_size = full_path.stat().st_size
                        except: continue
                        
                        # 大小检查
                        if target_item.file_size > 0 and actual_size != target_item.file_size:
                            logger.warning(f"完整性校验: 发现文件大小不匹配: {file_name} (预期: {target_item.file_size}, 实际: {actual_size})")
                            # 移动到 temp 以备 resume
                            if await self._move_to_temp_for_resume(task, target_item, full_path):
                                moved_for_resume += 1
                            
                            target_item.status = DownloadStatus.WAITING
                            target_item.downloaded_size = 0
                            target_item.progress = 0
                            failed_count += 1
                        else:
                            # 验证通过
                            if target_item.status != DownloadStatus.COMPLETED:
                                logger.info(f"完整性校验: 自动关联并恢复文件: {file_name}")
                                target_item.status = DownloadStatus.COMPLETED
                                target_item.downloaded_size = target_item.file_size
                                target_item.progress = 100.0
                                target_item.file_path = relative_path
                                discovered_count += 1
                            passed_count += 1

            # 2.2 检查 Queue 中原有项的物理丢失情况 (针对刚才 walk 没扫到的路径)
            for item in task.download_queue:
                full_path = export_path / item.file_path
                if not full_path.exists():
                    if item.status == DownloadStatus.COMPLETED:
                        logger.warning(f"完整性校验: 已完成文件物理丢失, 重置为等待: {item.file_name}")
                        item.status = DownloadStatus.WAITING
                        item.downloaded_size = 0
                        item.progress = 0
                        missing_count += 1
                else:
                    # 如果刚才 walk 没扫到(路径不服从正则)，但文件确实在，也补一下状态
                    if item.status not in [DownloadStatus.COMPLETED, DownloadStatus.SKIPPED]:
                        try:
                            actual_size = full_path.stat().st_size
                            if item.file_size > 0 and actual_size == item.file_size:
                                item.status = DownloadStatus.COMPLETED
                                item.downloaded_size = item.file_size
                                item.progress = 100.0
                                recovered_count += 1
                            elif item.file_size > 0:
                                # 之前可能没扫到正则，但路径在 queue 里，且大小不一致
                                if await self._move_to_temp_for_resume(task, item, full_path):
                                    moved_for_resume += 1
                                item.status = DownloadStatus.WAITING
                                item.downloaded_size = 0
                                item.progress = 0
                        except: pass
            
            # 更新统计
            self._update_task_stats(task)
            task.last_verify_result = f"校验完成: 恢复/发现 {discovered_count + recovered_count} 个, 修复物理丢失 {missing_count} 个, 移动 {moved_for_resume} 个文件到缓存以备断点续传"
            logger.info(f"任务 {task_id[:8]} 校验完成: {task.last_verify_result}")
            
        except Exception as e:
            logger.error(f"完整性校验后台任务出错 (Task: {task_id[:8]}): {e}", exc_info=True)
            task.last_verify_result = f"校验过程中出错: {str(e)}"
        finally:
            task.is_verifying = False
            task.status = TaskStatus.PAUSED
            self._save_tasks()
            await self._notify_progress(task_id, task)

    async def _move_to_temp_for_resume(self, task: ExportTask, item: DownloadItem, full_path: Path) -> bool:
        """将不完整文件移动到 temp 目录以便后续断点续传 (v1.6.4)"""
        try:
            # 使用配置中的临时目录
            temp_dir = settings.DATA_DIR / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            # 遵循 _download_item_worker 的命名规则: {item.id}_{full_path.name}
            temp_file_name = f"{item.id}_{full_path.name}"
            temp_file_path = temp_dir / temp_file_name
            
            if full_path.exists():
                logger.debug(f"正在移动不完整文件到缓存以备断点续传: {full_path.name} -> {temp_file_name}")
                # 如果目标已存在，删除之以覆盖 (可能是旧的残余)
                if temp_file_path.exists():
                    os.remove(temp_file_path)
                shutil.move(str(full_path), str(temp_file_path))
                return True
        except Exception as e:
            logger.error(f"移动文件到缓存失败: {e}")
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
            "current_concurrency": task.current_max_concurrent_downloads or task.options.max_concurrent_downloads,
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
                
                chat_messages, highest_id = await self._export_chat(task, chat, export_path)
                all_messages.extend(chat_messages)
                
                # [v1.6.3] 更新扫描进度
                if highest_id > task.last_scanned_ids.get(chat.id, 0):
                    task.last_scanned_ids[chat.id] = highest_id
                    # 兼容旧字段
                    task.last_scanned_id = max(task.last_scanned_id, highest_id)
                    logger.info(f"聊天 {chat.id} 扫描完成, 更新进度: {highest_id}")
                    
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
            
            # [v1.6.3] 恢复时先进行一次增量扫描，发现可能的新消息
            if options.incremental_scan_enabled:
                logger.info(f"任务 {task.id[:8]} 恢复中: 执行增量扫描以获取新消息...")
                task.is_extracting = True
                await self._notify_progress(task.id, task)
                
                chats = await self._get_chats_to_export(options)
                for chat in chats:
                    if task.status == TaskStatus.CANCELLED: break
                    # 增量扫描 [v1.6.3]
                    _, highest_id = await self._export_chat(task, chat, export_path)
                    if highest_id > task.last_scanned_ids.get(chat.id, 0):
                        task.last_scanned_ids[chat.id] = highest_id
                        task.last_scanned_id = max(task.last_scanned_id, highest_id)
                    
                task.is_extracting = False
                await self._notify_progress(task.id, task)

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
            
            # 使用项目 data 目录存放下载中的文件 (对应宿主机 /opt/tg-export/data/temp)
            temp_dir = Path("/app/data/temp")
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file_path = temp_dir / f"{item.id}_{full_path.name}"
            
            retry_manager = DownloadRetryManager(
                max_retries=options.max_download_retries,
                initial_delay=options.retry_delay
            )
            
            # 5. 下载主逻辑 (带自适应并发与断点续传感知)
            import os
            import time
            
            # [Optimization] 断点续传：初始化时先检测磁盘上已有的临时文件大小
            disk_size = os.path.getsize(temp_file_path) if temp_file_path.exists() else 0
            if disk_size > 0:
                item.downloaded_size = disk_size
                item.progress = (disk_size / item.file_size) * 100 if item.file_size > 0 else 0
                logger.info(f"任务 {task.id[:8]}: 检测到断点续传文件 '{item.file_name}', 已下载: {disk_size} 字节")

            # [Optimization] 如果磁盘文件已经完整，直接跳过下载
            if item.file_size > 0 and disk_size == item.file_size:
                logger.info(f"任务 {task.id[:8]}: 文件 '{item.file_name}' 在临时目录已完整，跳过下载阶段。")
                success, downloaded_path, failure_info = True, temp_file_path, None
            else:
                last_update = {
                    'size': item.downloaded_size, 
                    'time': time.time(),
                    'last_progress_size': item.downloaded_size,  # 用于卡死检测的记录点
                    'last_progress_time': time.time()  # 上次进度有变的时间
                }
                loop = asyncio.get_running_loop()
                
                def progress_cb(current, total):
                    now = time.time()
                    
                    # 更新进度
                    item.progress = (current / total) * 100 if total > 0 else 0
                    item.downloaded_size = current
                    
                    # [Speed Fix] 计算瞬时速度 (每秒更新一次)
                    elapsed = now - last_update['time']
                    if elapsed >= 1.0:
                        bytes_diff = current - last_update['size']
                        item.speed = max(0, bytes_diff / elapsed)
                        last_update['size'] = current
                        last_update['time'] = now
                    
                    # [Stuck Detection] 卡死检测逻辑 (v1.6.5 优化)
                    # 只要字节有增长，就重置计时器
                    if current > last_update['last_progress_size']:
                        last_update['last_progress_size'] = current
                        last_update['last_progress_time'] = now
                    
                    # 超时条件：无进度增长超过 10 分钟 (针对大文件并行下载放宽限制)
                    # 对于普通下载，Pyrogram 调用频繁，此逻辑也很稳健
                    if now - last_update['last_progress_time'] > 600: 
                        logger.error(f"任务 {task.id[:8]}: 文件 {item.file_name} 下载卡死 (10分钟无进度增长)")
                        raise asyncio.TimeoutError("Download stuck for more than 10 minutes")

                    # 用户手动暂停检测
                    if item.status == DownloadStatus.PAUSED or item.is_manually_paused:
                        item.speed = 0 # 暂停时清空速度
                        raise asyncio.CancelledError("Item was paused by user")

                # 日志：记录下载路径
                logger.info(f"任务 {task.id[:8]}: 开始执行 download_media -> '{item.file_name}' (Size: {item.file_size})")
                
                # [Adaptive Concurrency] 限速触发时的回调
                async def on_flood_wait_cb(delay_secs):
                    task.last_flood_wait_time = datetime.now()
                    old_concurrency = task.current_max_concurrent_downloads or 1
                    new_concurrency = max(1, old_concurrency - 1)
                    
                    if old_concurrency > 1:
                        task.current_max_concurrent_downloads = new_concurrency
                        # 同步降低客户端并发限额
                        telegram_client.set_max_concurrent_transmissions(new_concurrency)
                        
                        # 强行暂停队尾项
                        downloading_items = [i for i in task.download_queue if i.status == DownloadStatus.DOWNLOADING]
                        if len(downloading_items) > new_concurrency:
                            excess_count = len(downloading_items) - new_concurrency
                            paused_count = 0
                            for i in reversed(task.download_queue):
                                if i.status == DownloadStatus.DOWNLOADING and i.id != item.id:
                                    logger.warning(f"触发自适应降压：暂停额外项 {i.file_name}")
                                    i.status = DownloadStatus.PAUSED
                                    paused_count += 1
                                    if paused_count >= excess_count: break
                        await self._notify_progress(task.id, task)

                try:
                    # [v1.5.0] 并行分块下载：大文件使用多连接并发
                    MIN_PARALLEL_SIZE = 10 * 1024 * 1024  # 10MB
                    use_parallel = (
                        options.enable_parallel_chunk and 
                        item.file_size >= MIN_PARALLEL_SIZE
                    )
                    
                    if use_parallel:
                        # 大文件使用并行分块下载
                        logger.info(f"任务 {task.id[:8]}: 启动并行分块下载 ({options.parallel_chunk_connections} 连接)")
                        
                        def cancel_check():
                            return item.status == DownloadStatus.PAUSED or item.is_manually_paused
                        
                        try:
                            downloaded_path = await telegram_client.download_media_parallel(
                                message=msg,
                                file_path=str(temp_file_path),
                                file_size=item.file_size,
                                parallel_connections=options.parallel_chunk_connections,
                                progress_callback=progress_cb,
                                cancel_check=cancel_check,
                                task_semaphore=self._parallel_semaphores.get(task.id)
                            )

                            
                            if downloaded_path:
                                success = True
                                failure_info = None
                            else:
                                success = False
                                failure_info = {"error_type": "parallel_download_failed", "error_message": "并行下载失败 (未知原因)"}
                        except FloodWait as e:
                            logger.warning(f"任务 {task.id[:8]}: 并行下载触发 FloodWait ({e.value}s)")
                            # 触发自适应降压
                            await on_flood_wait_cb(e.value)
                            success = False
                            failure_info = {"error_type": "flood_wait", "error_message": f"FloodWait: {e.value}s"}
                        except Exception as e:
                            logger.error(f"任务 {task.id[:8]}: 并行下载发生错误: {e}")
                            success = False
                            failure_info = {"error_type": "parallel_error", "error_message": str(e)}
                    else:

                        # 小文件使用常规下载 + 重试
                        success, downloaded_path, failure_info = await retry_manager.download_with_retry(
                            download_func=telegram_client.download_media,
                            message=msg,
                            file_path=temp_file_path,
                            refresh_message_func=telegram_client.get_message_by_id,
                            progress_callback=progress_cb,
                            on_flood_wait_callback=on_flood_wait_cb
                        )
                except asyncio.TimeoutError:
                    logger.error(f"任务 {task.id[:8]}: 文件 {item.file_name} 下载超时")
                    success, downloaded_path = False, None
                    failure_info = {"error_type": "timeout", "error_message": "Request timed out"}
                finally:
                    item.speed = 0 # 确保退出下载阶段后速度归零

            # [CRITICAL FIX] 检查是否是因为暂停/取消而结束
            # 如果 item.status 被标记为 PAUSED，说明是被 progress_cb 里的异常中止的
            # 这种情况下 success 可能为 True (Pyrogram 返回了部分文件路径)，但我们绝不应执行完整性校验
            if item.status == DownloadStatus.PAUSED or item.is_manually_paused:
                logger.info(f"任务 {task.id[:8]}: 下载被用户或系统暂停，跳过校验阶段: {item.file_name}")
                raise asyncio.CancelledError("Download skipped/paused")

            # 5. 下载结果校验与收尾
            if success and downloaded_path:
                import os
                actual_size = os.path.getsize(downloaded_path) if os.path.exists(downloaded_path) else 0
                
                # [Integrity Check] 严格校验文件大小 (解决用户反馈的未下载完却标记完成的问题)
                if item.file_size > 0 and actual_size != item.file_size:
                    logger.error(f"任务 {task.id[:8]}: 文件完整性校验失败! {item.file_name} 预期: {item.file_size}, 实际: {actual_size}")
                    success = False
                    failure_info = {
                        "error_type": "integrity_error",
                        "error_message": f"文件大小不匹配 (完整性校验失败): 预期 {item.file_size}，实际 {actual_size}"
                    }
                elif actual_size == 0 and item.file_size > 0:
                    logger.error(f"任务 {task.id[:8]}: 检测到空包! 文件 {item.file_name} 长度为 0，视为下载失败。")
                    if os.path.exists(downloaded_path):
                        try: os.remove(downloaded_path)
                        except: pass
                    success = False

            if success:
                # 下载成功 (注意：downloaded_path 可能是 temp_file_path 或最终路径，视 retry_manager 策略而定)
                item.status = DownloadStatus.COMPLETED
                item.downloaded_size = actual_size # [NEW] 记录物理磁盘上的实际大小
                item.progress = 100.0
                item.speed = 0
                
                # 统一处理路径移动 (如果 downloaded_path 与 full_path 不一致)
                import shutil
                if downloaded_path and os.path.exists(downloaded_path):
                    if str(downloaded_path) != str(full_path):
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        try: os.chmod(full_path.parent, 0o777)
                        except: pass
                        # [Optimization] 重试下载后，如果目标目录已存在同名文件，执行覆盖移动
                        if full_path.exists():
                            try: os.remove(full_path)
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
                    # [Optimization] 同上
                    if full_path.exists():
                        try: os.remove(full_path)
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

    async def _sync_task_with_disk(self, task: ExportTask, export_path: Path):
        """
        同步任务状态与磁盘文件 (v1.6.0)
        
        功能:
        1. 检查已下载的文件是否存在。
        2. 如果存在，校验大小是否一致。
        3. 如果一致且任务未标记完成，标记为 COMPLETED。
        4. 如果不一致，删除本地文件并标记为 WAITING。
        5. 如果任务标记为完成但文件丢失，标记为 WAITING。
        """
        import os
        logger.info(f"任务 {task.id[:8]}: 正在执行磁盘同步...")
        
        completed_count = 0
        reset_count = 0
        
        for item in task.download_queue:
            # 完整物理路径
            full_path = export_path / item.file_path
            
            # [CASE 1] 本地文件存在
            if full_path.exists():
                actual_size = os.path.getsize(full_path)
                
                # [A] 大小完全匹配
                if item.file_size > 0 and actual_size == item.file_size:
                    if item.status != DownloadStatus.COMPLETED:
                        item.status = DownloadStatus.COMPLETED
                        item.downloaded_size = actual_size
                        item.progress = 100.0
                        completed_count += 1
                
                # [B] 大小不匹配 (损坏或不完整)
                elif item.file_size > 0 and actual_size != item.file_size:
                    logger.warning(f"同步: 文件 {item.file_name} 大小不一致 (预期 {item.file_size}, 实际 {actual_size}), 将重新下载")
                    try:
                        os.remove(full_path)
                    except:
                        pass
                    item.status = DownloadStatus.WAITING
                    item.downloaded_size = 0
                    item.progress = 0
                    reset_count += 1
            
            # [CASE 2] 本地文件不存在
            else:
                # 如果标记为已完成但物理文件没了
                if item.status == DownloadStatus.COMPLETED:
                    logger.warning(f"同步: 文件 {item.file_name} 已完成但物理文件丢失, 已重置为等待状态")
                    item.status = DownloadStatus.WAITING
                    item.downloaded_size = 0
                    item.progress = 0
                    reset_count += 1
                    
        if completed_count > 0 or reset_count > 0:
            logger.info(f"同步完成: 补全了 {completed_count} 个完成项, 重置了 {reset_count} 个错误/丢失项")
            # 重新计算任务总进度
            task.downloaded_media = sum(1 for i in task.download_queue if i.status == DownloadStatus.COMPLETED)
            await self._notify_progress(task.id, task)

    async def _process_download_queue(self, task: ExportTask, export_path: Path):
        """处理下载队列 (Worker Pool 模式)"""
        # [FIX] 启动前先进行一次磁盘同步
        await self._sync_task_with_disk(task, export_path)
        options = task.options
        
        # [v1.4.0] 动态设置 Pyrogram 并发传输数，使 UI 配置生效
        telegram_client.set_max_concurrent_transmissions(options.max_concurrent_downloads)
        logger.info(f"任务 {task.id[:8]}: 并发下载数设置为 {options.max_concurrent_downloads}")
        
        # [v1.6.1] 按优先级和 message_id 排序初始化队列
        # 优先级规则: is_retry(True优先) > message_id(升序)
        task.download_queue.sort(key=lambda x: (not getattr(x, 'is_retry', False), x.message_id))
        
        # 初始化任务队列
        queue = asyncio.Queue()
        self._task_queues[task.id] = queue
        
        # 将待下载项加入队列
        for item in task.download_queue:
            # 状态残留修复：重启或手动恢复时，将之前的“正在下载”及“已暂停”项也重置并入队
            # [v1.6.2] 清除手动暂停标记，确保任务恢复后不再因手动暂停而被跳过
            if item.status in [DownloadStatus.WAITING, DownloadStatus.PAUSED, DownloadStatus.FAILED, DownloadStatus.DOWNLOADING]:
                item.status = DownloadStatus.WAITING
                item.is_manually_paused = False
                queue.put_nowait(item)
        
        # 初始化任务追踪集合
        if task.id not in self._active_download_tasks:
            self._active_download_tasks[task.id] = set()

        # [Adaptive Concurrency] 初始化动态并发状态
        if task.current_max_concurrent_downloads is None:
            task.current_max_concurrent_downloads = options.max_concurrent_downloads
            
        # [Adaptive Concurrency] 初始化全局任务信号量，限制总连接数 (防止 10 workers * 4 connections = 40 连接触发封号)
        # 建议总连接数控制在 max_concurrent_downloads * 2 左右
        self._parallel_semaphores[task.id] = asyncio.Semaphore(options.max_concurrent_downloads * 2)
        logger.info(f"任务 {task.id[:8]}: 全局并行连接限额设置为 {options.max_concurrent_downloads * 2}")
            
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
                
                # [Dynamic Scaling] 如果当前 Worker ID 超过了设置的并发数，则退出 (v1.6.5)
                if worker_id >= task.options.max_concurrent_downloads:
                    logger.info(f"任务 {task.id[:8]}: 并发数调低，下载协程 #{worker_id} 退出")
                    break
                
                # [NEW Compliance] 如果整体任务处于暂停状态，Worker 应在此挂起待命，禁止从队列中“申请”新下载项
                # 直到用户手动点击“恢复”
                while self.is_paused(task.id) and task.status != TaskStatus.CANCELLED:
                    await asyncio.sleep(1)
                
                if task.status == TaskStatus.CANCELLED:
                    break
                
                # [v1.6.1] [三级优先级调度]
                # P1: 用户点击恢复的任务 (resume_timestamp)
                # P2: 标记为重试的任务 (is_retry)
                # P3: 队列中提取的标准任务 (已按 msg_id 排序)
                priority_item = None
                
                # P1: 查找恢复项
                best_resumed = None
                for candidate in task.download_queue:
                    if (candidate.status == DownloadStatus.WAITING 
                        and getattr(candidate, 'resume_timestamp', 0) > 0
                        and candidate.id not in self._item_to_worker.get(task.id, {})):
                        if not best_resumed or candidate.resume_timestamp > best_resumed.resume_timestamp:
                            best_resumed = candidate
                
                if best_resumed:
                    priority_item = best_resumed
                    priority_item.resume_timestamp = 0
                    logger.info(f"任务 {task.id[:8]}: [P1] 优先提取恢复文件: {priority_item.file_name}")
                
                # P2: 查找重试项
                if not priority_item:
                    for candidate in task.download_queue:
                        if (candidate.status == DownloadStatus.WAITING 
                            and getattr(candidate, 'is_retry', False)
                            and candidate.id not in self._item_to_worker.get(task.id, {})):
                            priority_item = candidate
                            logger.info(f"任务 {task.id[:8]}: [P2] 优先提取重试文件: {priority_item.file_name}")
                            break
                    # 2. 否则从 FIFO 队列中获取（队列已按 message_id 升序预排列）
                    # 3. 移除了扫描式 P2 策略，以绝死循环和乱序 Bug

                    # [Task Selection] 优先级：P1 (手动恢复) > P4 (主队列)
                    # 移除了 P2 (扫描器)，因为它会导致乱序和重复下载
                    
                    if priority_item:
                        # 找到了优先任务（手动恢复）
                        item = priority_item
                        from_queue = False
                        
                        # 立即注册到 _item_to_worker
                        if task.id not in self._item_to_worker:
                            self._item_to_worker[task.id] = {}
                        self._item_to_worker[task.id][item.id] = asyncio.current_task()
                    else:
                        # P4: 从队列取出一个待下载项 (阻塞式等待)
                        item = await queue.get()
                        from_queue = True
                        
                        # 如果收到 None 信号，说明队列已关闭
                        if item is None:
                            queue.task_done()
                            break
                        
                        # [Duplicate Check] 检查该项是否已经在下载中，或者已经完成
                        # (由于 adjust_concurrency 可能导致重复入队)
                        active_map = self._item_to_worker.get(task.id, {})
                        if item.id in active_map or item.status in [DownloadStatus.COMPLETED, DownloadStatus.SKIPPED]:
                            logger.debug(f"任务 {task.id[:8]}: 队列项 {item.message_id} 已在执行或已完成，跳过。")
                            queue.task_done()
                            continue
                        

                        # 注册
                        if task.id not in self._item_to_worker:
                            self._item_to_worker[task.id] = {}
                        self._item_to_worker[task.id][item.id] = asyncio.current_task()
                        logger.info(f"任务 {task.id[:8]}: Worker #{worker_id} [P4] 从队列获取任务 (msg#{item.message_id})")


                # 3. [Adaptive Concurrency] 检查当前并发槽位是否允许继续执行 (公平竞争)
                waiting_logged = False
                while True:
                    # 统计当前正在下载的项 (通过映射表判断)
                    active_count = len(self._item_to_worker.get(task.id, {}))
                    max_concurrent = task.current_max_concurrent_downloads or 1
                    
                    if active_count <= max_concurrent:
                        if waiting_logged:
                            logger.info(f"任务 {task.id[:8]}: Worker #{worker_id} 获得槽位 (当前活跃: {active_count}/{max_concurrent})")
                        break
                    
                    if not waiting_logged:
                        logger.info(f"任务 {task.id[:8]}: Worker #{worker_id} 等待下载槽位... (当前活跃: {active_count}/{max_concurrent})")
                        waiting_logged = True
                    
                    # 如果在等待期间任务被取消、全局暂停，或者项目被手动暂停，则跳过
                    if task.status == TaskStatus.CANCELLED:
                        if from_queue:
                            queue.task_done()
                        return
                        
                    if self.is_paused(task.id):
                        # 如果全局暂停，让出 CPU 并循环检查
                        await asyncio.sleep(1)
                        continue
                        
                    if item.status == DownloadStatus.PAUSED:
                        # 项目被手动暂停，不再等待槽位，直接去 queue_done
                        break
                        
                    await asyncio.sleep(0.5)
                
                # 如果排队期间项目被用户手动暂停了，直接跳过
                if item.status == DownloadStatus.PAUSED:
                    if from_queue:
                        queue.task_done()
                    continue

                # 4. 执行下载 (带驻留逻辑，支持单项暂停占位)
                try:
                    # [Resident Worker] 核心：建立驻留循环，使 Worker 能紧紧“抓牢”当前项
                    while True:
                        # 注册/更新映射，确保下载期间或驻留期间槽位始终被占用
                        if task.id not in self._item_to_worker:
                            self._item_to_worker[task.id] = {}
                        self._item_to_worker[task.id][item.id] = asyncio.current_task()
                        
                        try:
                            # 执行实际下载步骤
                            await self._download_item_worker(task, item, export_path)
                            # 如果下载完成（成功或预期内失败退出），跳出驻留循环
                            break
                        except asyncio.CancelledError:
                            # [v1.6.2] 简化逻辑：所有暂停均释放槽位，不再驻留
                            logger.info(f"任务 {task.id[:8]}: Worker #{worker_id} 暂停并释放槽位: {item.file_name}")
                            break
                except asyncio.CancelledError:
                    # [Persistence FIX] 系统级暂停，重置状态
                    if item and item.status == DownloadStatus.DOWNLOADING:
                        item.status = DownloadStatus.PAUSED
                    logger.info(f"任务 {task.id[:8]}: Worker #{worker_id} 的下载流被外部中断 (Item: {item.id})")
                except Exception as e:
                    # 记录并打印非预期错误
                    task.consecutive_success_count = 0
                    logger.error(f"Worker #{worker_id} 处理下载项时发生非预期错误: {e}")
                finally:
                    # [Resident Worker] 只有当项目真正脱离 Worker 控制时，才解绑映射
                    if item and task.id in self._item_to_worker:
                        self._item_to_worker[task.id].pop(item.id, None)
                    # 只有从队列获取的任务才调用 task_done()
                    if from_queue:
                        queue.task_done()
                    
                    # [Adaptive Concurrency] 成功下载后尝试恢复并发
                    if item.status == DownloadStatus.COMPLETED:
                        task.consecutive_success_count += 1
                        if task.consecutive_success_count >= 15:
                            if (task.current_max_concurrent_downloads or 1) < options.max_concurrent_downloads:
                                old_val = task.current_max_concurrent_downloads
                                task.current_max_concurrent_downloads += 1
                                telegram_client.set_max_concurrent_transmissions(task.current_max_concurrent_downloads)
                                logger.info(f"任务 {task.id[:8]}: 运行稳定，自动恢复并发: {old_val} -> {task.current_max_concurrent_downloads}")
                            task.consecutive_success_count = 0
                    
                    # 随机冷却 (冷却期间不占用槽位，故放在 finally 之后或 task_done 之后)
                    if task.status != TaskStatus.CANCELLED and not self.is_paused(task.id):
                        jitter = random.uniform(3.0, 10.0)
                        await asyncio.sleep(jitter)
            
            logger.info(f"任务 {task.id[:8]}: 下载工协程 #{worker_id} 正常退出")

        # 启动工作协程池 (v1.6.5 动态管理)
        worker_tasks = {} # Dict[int, Task]
        for i in range(options.max_concurrent_downloads):
            t = asyncio.create_task(worker_logic(i))
            worker_tasks[i] = t
            self._active_download_tasks[task.id].add(t)

        # [NEW] 动态 Worker 管理协程
        async def worker_manager():
            while task.status not in [TaskStatus.CANCELLED, TaskStatus.COMPLETED, TaskStatus.FAILED]:
                try:
                    target = task.options.max_concurrent_downloads
                    current_count = len([t for t in worker_tasks.values() if not t.done()])
                    
                    # 扩容
                    if target > current_count:
                        # 查找空缺的 ID 或追加
                        for i in range(target):
                            if i not in worker_tasks or worker_tasks[i].done():
                                logger.info(f"任务 {task.id[:8]}: 动态增加下载协程 #{i}")
                                t = asyncio.create_task(worker_logic(i))
                                worker_tasks[i] = t
                                self._active_download_tasks[task.id].add(t)
                                # 错峰启动
                                await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Worker Manager 出错: {e}")
                await asyncio.sleep(3)
        
        manager_task = asyncio.create_task(worker_manager())

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
            manager_task.cancel()
            # 取消所有 worker
            for t in worker_tasks.values():
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
    ) -> Tuple[List[MessageInfo], int]:
        """导出单个聊天, 返回 (消息列表, 本次最高消息ID)"""
        task.current_scanning_chat = chat.title
        options = task.options
        messages: List[MessageInfo] = []
        
        # 创建 Telegram Desktop 风格的目录结构
        chats_dir = export_path / "chats"
        chat_dir = chats_dir / f"chat_{abs(chat.id)}"
        chat_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建媒体目录
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
            try:
                import json
                with open(progress_file, "r") as f:
                    progress_data = json.load(f)
                    downloaded_ids = set(progress_data.get("downloaded_message_ids", []))
            except: pass
        
        # 获取消息范围
        msg_from = options.message_from
        msg_to = options.message_to  # 0 表示最新
        
        # 获取消息
        me_id = None
        if options.only_my_messages:
            try:
                me = await telegram_client.get_me()
                me_id = me.get("id")
            except: pass

        highest_id_this_scan = 0
        last_scanned_id = task.last_scanned_ids.get(chat.id, 0)
        
        # [v1.6.0] 慢速扫描策略
        scan_delay = 0.2  # 基础延迟
        
        async for msg in telegram_client.get_chat_history(chat.id):
            if task.status == TaskStatus.CANCELLED:
                break
            
            # [v1.6.4] 更新扫描状态
            task.current_scanning_msg_id = msg.id
            if task.processed_messages % 20 == 0:
                await self._notify_progress(task.id, task)
            
            # 记录本次扫描到的最高 ID (Telegram 历史是从新到旧)
            if highest_id_this_scan == 0:
                highest_id_this_scan = msg.id
                
            # [v1.6.3] 增量扫描逻辑
            # 只有开启增量扫描 且 不是强制全量扫描 且 已经有扫描记录时 才触发断开
            force_full = getattr(task, '_force_full_scan', False)
            if options.incremental_scan_enabled and not force_full and last_scanned_id > 0 and msg.id <= last_scanned_id:
                logger.info(f"聊天 {chat.id}: 增量扫描到达上次位置 {last_scanned_id}, 停止扫描")
                break

            # 限制请求速率
            import random
            await asyncio.sleep(scan_delay + random.uniform(0.05, 0.15))
            
            # 等待暂停状态结束
            while task.status == TaskStatus.PAUSED:
                await asyncio.sleep(1)
                if task.status == TaskStatus.CANCELLED: break
            
            # 消息ID范围筛选
            if msg_to > 0 and msg.id > msg_to: continue
            if msg.id < msg_from: break
            
            # 时间范围筛选
            if options.date_from and msg.date < options.date_from: continue
            if options.date_to and msg.date > options.date_to: continue
            
            # 只导出我的消息
            if options.only_my_messages and msg.from_user and msg.from_user.id != me_id:
                continue
            
            # 断点续传 - 跳过已处理的消息
            if options.skip_existing and msg.id in downloaded_ids:
                task.processed_messages += 1
                continue
            
            # 消息过滤
            if options.filter_mode == "skip" and msg.id in options.filter_messages: continue
            if options.filter_mode == "specify" and msg.id not in options.filter_messages: continue
            
            task.total_messages += 1
            
            # 处理媒体
            media_type = telegram_client.get_media_type(msg)
            media_path = None
            
            if media_type:
                task.total_media += 1
                
                # 检查是否需要下载该类型
                should_download = self._should_download_media(media_type, options)
                
                if should_download:
                    # 检查是否已经在队列中
                    download_item = task.get_download_item(msg.id, chat.id)
                    if not download_item:
                        # 准备下载目录
                        media_dir = media_dirs.get(media_type, chat_dir / "other")
                        media_dir.mkdir(parents=True, exist_ok=True)
                        
                        file_name = self._get_media_filename(msg, media_type)
                        file_path = media_dir / file_name
                        
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
                            # 简单检查大小是否匹配 (快速跳过)
                            if file_path.stat().st_size == download_item.file_size:
                                download_item.status = DownloadStatus.SKIPPED
                                download_item.downloaded_size = download_item.file_size
                                download_item.progress = 100.0
                                media_path = download_item.file_path
                                task.downloaded_media += 1
                        
                        if download_item.status != DownloadStatus.SKIPPED:
                            task.download_queue.append(download_item)
                    else:
                        # 如果已经在队列中且已完成，则记录路径
                        if download_item.status in [DownloadStatus.COMPLETED, DownloadStatus.SKIPPED]:
                            media_path = download_item.file_path
            
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
            
            # 记录已处理的消息ID
            downloaded_ids.add(msg.id)
            
            # 定期更新进度
            if task.processed_messages % 50 == 0:
                await self._notify_progress(task.id, task)
                if options.resume_download:
                    try:
                        import json
                        with open(progress_file, "w") as f:
                            json.dump({"downloaded_message_ids": list(downloaded_ids)}, f)
                    except: pass
        
        # 保存最终进度
        if options.resume_download:
            try:
                import json
                with open(progress_file, "w") as f:
                    json.dump({"downloaded_message_ids": list(downloaded_ids)}, f)
            except: pass
        
        return messages, highest_id_this_scan
    
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

    def _update_task_stats(self, task: ExportTask):
        """更新任务统计信息 (下载数和大小) (v1.6.4)"""
        downloaded_count = 0
        downloaded_size = 0
        total_media = 0
        total_size = 0
        
        for item in task.download_queue:
            total_media += 1
            total_size += item.file_size
            if item.status in [DownloadStatus.COMPLETED, DownloadStatus.SKIPPED]:
                downloaded_count += 1
                downloaded_size += item.file_size
            elif item.status == DownloadStatus.DOWNLOADING:
                downloaded_size += getattr(item, 'downloaded_size', 0)
                
        task.downloaded_media = downloaded_count
        task.downloaded_size = downloaded_size
        task.total_media = total_media
        task.total_size = total_size


# 全局导出管理器
export_manager = ExportManager()
