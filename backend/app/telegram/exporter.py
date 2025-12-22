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
from typing import Dict, List, Optional, Callable
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
        self._task_semaphores: Dict[str, asyncio.Semaphore] = {} # 任务ID -> 信号量
        self._progress_callbacks: Dict[str, List[Callable]] = {}
        self._paused_tasks: set = set()  # 暂停的任务ID
        self._tasks_file = settings.DATA_DIR / self.TASKS_FILE
        # 确保数据目录存在
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        # 启动时加载任务
        self._load_tasks()
    
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
                        else:
                            logger.info(f"任务 '{task.name}' (ID: {task.id[:8]}...) 状态: {task.status.value}")
                            
                        self.tasks[task.id] = task
                    except Exception as e:
                        logger.error(f"加载任务失败: {e}")
                logger.info(f"✅ 已加载 {len(self.tasks)} 个任务，其中 {len(self._paused_tasks)} 个暂停")
            else:
                logger.info("未找到任务文件，从空白开始")
        except Exception as e:
            logger.error(f"加载任务文件失败: {e}")
    
    def _save_tasks(self):
        """保存任务到文件"""
        try:
            data = [task.model_dump(mode='json') for task in self.tasks.values()]
            with open(self._tasks_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"保存任务失败: {e}")
    
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
        # 保存任务状态到文件
        self._save_tasks()
        
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
        
        await self._notify_progress(task_id, task)
        return True
    
    async def resume_export(self, task_id: str) -> bool:
        """恢复导出任务"""
        task = self.tasks.get(task_id)
        if not task or task.status not in [TaskStatus.PAUSED, TaskStatus.CANCELLED, TaskStatus.FAILED]:
            logger.warning(f"无法恢复任务 {task_id[:8]}...: 任务不存在或状态不支持恢复 ({task.status if task else 'None'})")
            return False
        
        logger.info(f"正在恢复任务: '{task.name}' (ID: {task_id[:8]}...)")
        self._paused_tasks.discard(task_id)
        task.status = TaskStatus.RUNNING
        
        # 将所有暂停的下载项恢复为等待状态
        paused_count = sum(1 for item in task.download_queue if item.status == DownloadStatus.PAUSED)
        for item in task.download_queue:
            if item.status == DownloadStatus.PAUSED:
                item.status = DownloadStatus.WAITING
        
        if paused_count > 0:
            logger.info(f"  - 恢复了 {paused_count} 个暂停的下载项")
        
        await self._notify_progress(task_id, task)
        
        # 如果任务有下载队列但没有活动的运行任务，重新启动
        # 这种情况发生在容器重启后恢复暂停的任务时
        if task_id not in self._running_tasks and len(task.download_queue) > 0:
            waiting_count = sum(1 for i in task.download_queue if i.status == DownloadStatus.WAITING)
            logger.info(f"  - 重新启动下载队列 ({waiting_count} 个待下载文件)")
            async_task = asyncio.create_task(self._restart_download_queue(task))
            self._running_tasks[task_id] = async_task
        
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
        """重试单个文件"""
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
            
        # 只能重试非完成状态的文件
        if target_item.status == DownloadStatus.COMPLETED:
            return False
            
        logger.info(f"重试文件: {target_item.file_name} (Task: {task.name})")
        
        # 重置状态
        target_item.status = DownloadStatus.WAITING
        target_item.error = None
        target_item.progress = 0
        target_item.speed = 0
        
        # 如果任务正在运行 (有信号量存在)，立即触发下载
        if task.id in self._task_semaphores:
            export_path = self._get_export_path(task)
            asyncio.create_task(self._download_item_worker(task, target_item, export_path))
            logger.info("任务正在运行，已动态添加下载协程")
        else:
            logger.info("任务未运行，文件状态已重置，将在下次任务启动时下载")
            
        await self._notify_progress(task_id, task)
        return True
    
    def is_paused(self, task_id: str) -> bool:
        """检查任务是否暂停"""
        return task_id in self._paused_tasks
    
    async def pause_download_item(self, task_id: str, item_id: str) -> bool:
        """暂停单个下载项"""
        task = self.tasks.get(task_id)
        if not task: return False
        for item in task.download_queue:
            if item.id == item_id:
                if item.status == DownloadStatus.DOWNLOADING or item.status == DownloadStatus.WAITING:
                    item.status = DownloadStatus.PAUSED
                    return True
        return False

    async def resume_download_item(self, task_id: str, item_id: str) -> bool:
        """恢复单个下载项"""
        task = self.tasks.get(task_id)
        if not task: return False
        for item in task.download_queue:
            if item.id == item_id:
                if item.status == DownloadStatus.PAUSED:
                    item.status = DownloadStatus.WAITING
                    return True
        return False

    def get_download_queue(self, task_id: str) -> List[DownloadItem]:
        """获取任务的下载队列"""
        task = self.tasks.get(task_id)
        return task.download_queue if task else []
    async def _run_export(self, task: ExportTask):
        """执行导出任务"""
        try:
            options = task.options
            # 使用任务名称作为导出路径（清理特殊字符）
            export_path = self._get_export_path(task)
            
            # 如果目录已存在且不是当前任务的目录（防止重启任务时重复创建），需要处理冲突
            # 但考虑到用户想要覆盖或续传，我们直接使用该目录
            # 只有当它被其他任务占用时才会有问题，但目前简化处理
            
            export_path.mkdir(parents=True, exist_ok=True)
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
                
                if task.status != TaskStatus.CANCELLED:
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.now()
            
        except asyncio.CancelledError:
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
            
            if task.status != TaskStatus.CANCELLED:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
        except asyncio.CancelledError:
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
        """单个文件的下载工作协程"""
        options = task.options
        semaphore = self._task_semaphores.get(task.id)
        if not semaphore:
            return

        # 获取当前协程任务并追踪
        current_task = asyncio.current_task()
        if current_task:
            self._active_download_tasks[task.id].add(current_task)
        
        try:
            async with semaphore:
                if task.status == TaskStatus.CANCELLED or item.status in [DownloadStatus.COMPLETED, DownloadStatus.SKIPPED]:
                    return

                # 等待暂停状态结束 (整体任务暂停 或 个人文件暂停)
                while (self.is_paused(task.id) or item.status == DownloadStatus.PAUSED) and task.status != TaskStatus.CANCELLED:
                    await asyncio.sleep(1)
                
                if task.status == TaskStatus.CANCELLED:
                    return

                # 获取原始消息对象用于下载
                msg = await telegram_client.get_message_by_id(item.chat_id, item.message_id)
                if not msg:
                    item.status = DownloadStatus.FAILED
                    item.error = "无法获取消息对象"
                    return


                # 智能延迟方案：减少 FloodWait
                # 大文件(>10MB)延迟1秒，小文件延迟0.3秒
                delay = 1.0 if item.file_size > 10 * 1024 * 1024 else 0.3
                await asyncio.sleep(delay)

                item.status = DownloadStatus.DOWNLOADING
                full_path = export_path / item.file_path
                
                # 日志：记录下载路径
                logger.info(f"开始下载文件: {item.file_name}")
                
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
                last_update = {'size': 0, 'time': time.time()}
                
                def progress_cb(current, total):
                    now = time.time()
                    elapsed = now - last_update['time']
                    
                    item.downloaded_size = current
                    item.file_size = total
                    if total > 0:
                        item.progress = (current / total) * 100
                    
                    # 计算速度 (至少间隔 0.5 秒更新一次)
                    if elapsed >= 0.5:
                        bytes_diff = current - last_update['size']
                        item.speed = bytes_diff / elapsed if elapsed > 0 else 0
                        last_update['size'] = current
                        last_update['time'] = now
                
                success, downloaded, failure_info = await retry_manager.download_with_retry(
                    download_func=telegram_client.download_media,
                    message=msg,
                    file_path=temp_file_path,
                    refresh_message_func=telegram_client.get_message_by_id,
                    progress_callback=progress_cb
                )
                
                if success and downloaded:
                    if temp_file_path.exists():
                        # 确保目标目录存在
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        # 从 temp 移动到最终位置
                        import shutil
                        shutil.move(str(temp_file_path), str(full_path))
                        logger.info(f"✅ 文件已保存: {full_path}")
                    item.status = DownloadStatus.COMPLETED
                    item.progress = 100.0
                    item.speed = 0  # 下载完成，速度归零
                    task.downloaded_media += 1
                    
                    # 计算任务总速度 (只在完成时计算一次)
                    task.download_speed = sum(
                        i.speed for i in task.download_queue 
                        if i.status == DownloadStatus.DOWNLOADING
                    )
                    
                    # 每完成一个下载，通知一次进度
                    await self._notify_progress(task.id, task)
                elif failure_info:
                    item.status = DownloadStatus.FAILED
                    item.error = failure_info.get("error_message")
                    # 记录到任务的失败列表
                    from ..models import FailedDownload
                    failed_download = FailedDownload(
                        message_id=item.message_id,
                        chat_id=item.chat_id,
                        file_name=item.file_name,
                        error_type=failure_info["error_type"],
                        error_message=failure_info["error_message"],
                        retry_count=failure_info["retry_count"],
                        last_retry=datetime.fromisoformat(failure_info["last_retry"])
                    )
                    task.failed_downloads.append(failed_download)

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
        """处理下载队列"""
        options = task.options
        
        # 按 message_id 升序排序，先下载较早的消息
        task.download_queue.sort(key=lambda x: x.message_id)
        
        # 限制并发下载数
        self._task_semaphores[task.id] = asyncio.Semaphore(options.max_concurrent_downloads)
        
        # 初始化任务追踪集合
        if task.id not in self._active_download_tasks:
            self._active_download_tasks[task.id] = set()

        # 启动初始下载任务
        for item in task.download_queue:
            if item.status != DownloadStatus.COMPLETED and item.status != DownloadStatus.SKIPPED:
                asyncio.create_task(self._download_item_worker(task, item, export_path))

        # 速度更新任务 - 独立运行，避免阻塞下载 wait 循环
        async def speed_updater():
            while True:
                await asyncio.sleep(3)  # 每3秒更新一次
                if task.status not in [TaskStatus.RUNNING, TaskStatus.EXTRACTING]:
                    break
                    
                # 计算总速度
                total_speed = sum(
                    i.speed for i in task.download_queue 
                    if i.status == DownloadStatus.DOWNLOADING
                )
                task.download_speed = total_speed
                
                # 如果没有正在下载的任务且速度为0，可能是因为所有任务都在等待或已完成
                # 但这里只负责更新显示速度
                
                await self._notify_progress(task.id, task)
        
        speed_task = asyncio.create_task(speed_updater())
        
        try:
            # 等待所有下载任务完成
            # 使用循环检查而不是 gather，因为我们可能在运行时动态添加重试任务
            while True:
                # 获取当前活跃任务的副本
                active_tasks = self._active_download_tasks.get(task.id, set())
                active_count = len(active_tasks)
                
                # 如果没有任何活跃任务，检查是否真的完成了
                if active_count == 0:
                    # 再次确认所有非跳过/完成的任务是否都已结束
                    # 注意：如果有任务处于 WAITING 状态但没有 worker，说明出问题了
                    # 但在这里我们假设所有 WAITING 任务都已启动了 worker
                    break
                
                await asyncio.sleep(1)
                
        finally:
            # 清理
            speed_task.cancel()
            if task.id in self._task_semaphores:
                del self._task_semaphores[task.id]
    
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
