import asyncio
import json
import uuid
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, Set, Tuple, Union

from ..config import settings
from ..models import (
    ExportTask, ExportOptions, TaskStatus, ChatInfo, 
    MessageInfo, MediaType, ChatType, ExportFormat,
    DownloadItem, DownloadStatus
)
from .client import telegram_client

logger = logging.getLogger(__name__)

class TaskManagerMixin:
    """任务管理与扫描逻辑 Mixin (v2.3.4)"""

    def _load_tasks(self):
        """从文件加载任务"""
        try:
            tasks_file = settings.DATA_DIR / "tasks.json"
            if tasks_file.exists():
                with open(tasks_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"正在加载 {len(data)} 个任务...")
                for task_data in data:
                    try:
                        # 迁移与补全逻辑
                        if "options" in task_data:
                            opts = task_data["options"]
                            if "download_threads" in opts and "parallel_chunk_connections" not in opts:
                                opts["parallel_chunk_connections"] = min(8, max(1, opts["download_threads"]))
                            opts.setdefault("incremental_scan_enabled", True)
                            opts.setdefault("enable_parallel_chunk", True)
                            opts.setdefault("parallel_chunk_connections", 4)
                        
                        task_data.setdefault("last_scanned_id", 0)
                        task = ExportTask.model_validate(task_data)
                        
                        if task.status in [TaskStatus.RUNNING, TaskStatus.EXTRACTING]:
                            task.status = TaskStatus.PAUSED
                            self._paused_tasks.add(task.id)
                        elif task.status == TaskStatus.PAUSED:
                            self._paused_tasks.add(task.id)
                        
                        for item in task.download_queue:
                            if item.status == DownloadStatus.DOWNLOADING:
                                item.status = DownloadStatus.WAITING
                                item.speed = 0
                            
                        self.tasks[task.id] = task
                    except Exception as e:
                        logger.error(f"加载任务失败: {e}")
                logger.info(f"✅ 已加载 {len(self.tasks)} 个任务")
            else:
                 logger.info("未找到任务文件")
        except Exception as e:
            logger.error(f"加载文件失败: {e}")

    def _save_tasks(self):
        """同步保存"""
        try:
            tasks_file = settings.DATA_DIR / "tasks.json"
            data = [task.model_dump(mode='json') for task in self.tasks.values()]
            with open(tasks_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            self._needs_save = False
        except Exception as e:
            logger.error(f"保存失败: {e}")

    async def _save_tasks_async(self):
        """异步保存"""
        async with self._save_lock:
            if not self._needs_save: return
            try:
                data = [task.model_dump(mode='json') for task in self.tasks.values()]
                def save():
                    tasks_file = settings.DATA_DIR / "tasks.json"
                    with open(tasks_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                await asyncio.get_event_loop().run_in_executor(None, save)
                self._needs_save = False
            except Exception as e:
                logger.error(f"异步保存失败: {e}")

    def create_task(self, name: str, options: ExportOptions) -> ExportTask:
        """创建导出任务"""
        task = ExportTask(
            id=str(uuid.uuid4()),
            name=name,
            options=options
        )
        self.tasks[task.id] = task
        self._save_tasks()
        return task

    async def start_export(self, task_id: str) -> bool:
        """启动/恢复导出任务"""
        task = self.tasks.get(task_id)
        if not task: return False
        if task_id in self._running_tasks:
            if not self._running_tasks[task_id].done(): return False
            del self._running_tasks[task_id]
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        self._paused_tasks.discard(task_id)
        async_task = asyncio.create_task(self._run_export(task))
        self._running_tasks[task_id] = async_task
        return True

    async def pause_export(self, task_id: str) -> bool:
        """暂停导出任务"""
        task = self.tasks.get(task_id)
        if not task: return False
        task.status = TaskStatus.PAUSED
        self._paused_tasks.add(task_id)
        if task_id in self._running_tasks:
            self._running_tasks[task_id].cancel()
        await self._notify_progress(task_id, task)
        self._save_tasks()
        return True

    async def cancel_export(self, task_id: str) -> bool:
        """取消导出任务"""
        task = self.tasks.get(task_id)
        if not task: return False
        task.status = TaskStatus.CANCELLED
        if task_id in self._running_tasks:
            self._running_tasks[task_id].cancel()
        await self._notify_progress(task_id, task)
        self._save_tasks()
        return True

    async def scan_messages(self, task_id: str, full: bool = False) -> Dict[str, Any]:
        """触发异步消息扫描"""
        task = self.tasks.get(task_id)
        if not task: return {"status": "error", "message": "任务不存在"}
        if task.status == TaskStatus.EXTRACTING: return {"status": "error", "message": "已经在扫描中"}
        task.status = TaskStatus.EXTRACTING
        task.is_extracting = True
        asyncio.create_task(self._scan_messages_worker(task_id, full))
        return {"status": "initiated", "message": f"正在后台{'全量' if full else '增量'}扫描新消息..."}

    async def _scan_messages_worker(self, task_id: str, full: bool = False):
        """后台扫描消息协程"""
        task = self.tasks.get(task_id)
        if not task: return
        try:
            export_path = self._get_export_path(task)
            export_path.mkdir(parents=True, exist_ok=True)
            chats = await self._get_chats_to_export(task.options)
            task.total_chats = len(chats)
            task.processed_chats = 0
            all_new_messages = []
            for chat in chats:
                if task.status in [TaskStatus.CANCELLED, TaskStatus.PAUSED]: break
                task._force_full_scan = full
                chat_messages, highest_id = await self._export_chat(task, chat, export_path)
                all_new_messages.extend(chat_messages)
                if highest_id > task.last_scanned_ids.get(chat.id, 0):
                    task.last_scanned_ids[chat.id] = highest_id
                task.processed_chats += 1
                await self._notify_progress(task_id, task)
            if all_new_messages and task.status not in [TaskStatus.CANCELLED, TaskStatus.PAUSED]:
                from ..exporters import json_exporter, html_exporter
                if task.options.export_format in [ExportFormat.JSON, ExportFormat.BOTH]:
                    await json_exporter.export(task, chats, all_new_messages, export_path)
                if task.options.export_format in [ExportFormat.HTML, ExportFormat.BOTH]:
                    await html_exporter.export(task, chats, all_new_messages, export_path)
        except Exception as e:
            logger.error(f"扫描任务出错: {e}", exc_info=True)
            task.error = f"扫描出错: {str(e)}"
        finally:
            task.is_extracting = False
            if task.total_media > task.downloaded_media:
                task.status = TaskStatus.RUNNING
            else:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
            self._save_tasks()
            await self._notify_progress(task_id, task)

    async def _export_chat(self, task: ExportTask, chat: ChatInfo, export_path: Path):
        """核心扫描逻辑"""
        options = task.options
        messages = []
        highest_id_this_scan = 0
        from_id = 0 if getattr(task, '_force_full_scan', False) else task.last_scanned_ids.get(chat.id, 0)
        
        chat_dir = export_path / "chats" / f"chat_{abs(chat.id)}"
        chat_dir.mkdir(parents=True, exist_ok=True)
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
        for d in media_dirs.values(): d.mkdir(parents=True, exist_ok=True)

        # [Optimization] 从旧到新扫描 (reverse=True)
        # offset_id 对 get_chat_history 是包含起始点的
        # 如果是增量扫描，我们希望从 from_id 之后的第一条开始
        history_iter = telegram_client.get_chat_history(
            chat.id, 
            offset_id=from_id, 
            limit=0, 
            reverse=True
        )

        async for msg in history_iter:
            if task.status in [TaskStatus.CANCELLED, TaskStatus.PAUSED]: break
            
            # [CRITICAL FIX] 增量正序扫描时，Pyrogram 会包含 offset_id 本身
            # 如果该 ID 已经被扫描过，我们需要显式跳过
            if from_id > 0 and msg.id <= from_id:
                continue
            
            # 由于 reverse=True，ID 是递增的
            highest_id_this_scan = max(highest_id_this_scan, msg.id)
            
            task.total_messages += 1
            media_type = telegram_client.get_media_type(msg)
            if media_type:
                task.total_media += 1
                if self._should_download_media(media_type, options):
                    item = task.get_download_item(msg.id, chat.id)
                    if not item:
                        file_name = self._get_media_filename(msg, media_type)
                        item = DownloadItem(
                            id=f"{chat.id}_{msg.id}", message_id=msg.id, chat_id=chat.id,
                            file_name=file_name, file_size=self._get_file_size(msg) or 0,
                            media_type=media_type, 
                            file_path=str((media_dirs.get(media_type, chat_dir/"other") / file_name).relative_to(export_path))
                        )
                        # [Refinement] 生产者逻辑：仅负责注册，将维护权交给 QueueManager
                        self.enqueue_item(task, item)
            
            if task.total_messages % 100 == 0: await self._notify_progress(task.id, task)
            await asyncio.sleep(0.05 + random.uniform(0, 0.05))

        return messages, highest_id_this_scan

    def _should_download_media(self, media_type: MediaType, options: ExportOptions) -> bool:
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

    async def _get_chats_to_export(self, options: ExportOptions) -> List[ChatInfo]:
        all_chats = await telegram_client.get_dialogs()
        if not options.specific_chats:
             # 按类型初步筛选逻辑已在 exporter.py 原有方法实现，此处简化
             return [c for c in all_chats if (c.type == ChatType.PRIVATE and options.private_chats) or (c.type == ChatType.CHANNEL and options.private_channels)]
        target_ids = options.specific_chats
        return [c for c in all_chats if c.id in target_ids]
