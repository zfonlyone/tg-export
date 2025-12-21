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
    MessageInfo, MediaType, ChatType, ExportFormat, FailedDownload
)
from .client import telegram_client
from .retry_manager import DownloadRetryManager

logger = logging.getLogger(__name__)


class ExportManager:
    """导出管理器"""
    
    def __init__(self):
        self.tasks: Dict[str, ExportTask] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._progress_callbacks: Dict[str, List[Callable]] = {}
        self._paused_tasks: set = set()  # 暂停的任务ID
    
    def create_task(self, name: str, options: ExportOptions) -> ExportTask:
        """创建导出任务"""
        task = ExportTask(
            id=str(uuid.uuid4()),
            name=name,
            options=options
        )
        self.tasks[task.id] = task
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
        if not task or task.status != TaskStatus.RUNNING:
            return False
        
        self._paused_tasks.add(task_id)
        task.status = TaskStatus.PAUSED
        await self._notify_progress(task_id, task)
        return True
    
    async def resume_export(self, task_id: str) -> bool:
        """恢复导出任务"""
        task = self.tasks.get(task_id)
        if not task or task.status != TaskStatus.PAUSED:
            return False
        
        self._paused_tasks.discard(task_id)
        task.status = TaskStatus.RUNNING
        await self._notify_progress(task_id, task)
        return True
    
    def is_paused(self, task_id: str) -> bool:
        """检查任务是否暂停"""
        return task_id in self._paused_tasks
    
    async def _run_export(self, task: ExportTask):
        """执行导出任务"""
        try:
            options = task.options
            export_path = Path(options.export_path)
            export_path.mkdir(parents=True, exist_ok=True)
            
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
            
            # 生成最终输出文件
            if task.status != TaskStatus.CANCELLED:
                from ..exporters import json_exporter, html_exporter
                
                if options.export_format in [ExportFormat.JSON, ExportFormat.BOTH]:
                    await json_exporter.export(task, chats, all_messages, export_path)
                
                if options.export_format in [ExportFormat.HTML, ExportFormat.BOTH]:
                    await html_exporter.export(task, chats, all_messages, export_path)
                
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
            
        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
        finally:
            await self._notify_progress(task.id, task)
    
    async def _get_chats_to_export(self, options: ExportOptions) -> List[ChatInfo]:
        """获取要导出的聊天列表"""
        all_chats = await telegram_client.get_dialogs()
        filtered_chats = []
        
        for chat in all_chats:
            # 如果指定了特定聊天，只导出这些
            if options.specific_chats:
                if chat.id in options.specific_chats:
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
        
        # 创建聊天目录
        chat_dir = export_path / self._safe_filename(chat.title)
        chat_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建媒体目录
        media_dirs = {
            MediaType.PHOTO: chat_dir / "photos",
            MediaType.VIDEO: chat_dir / "videos",
            MediaType.VOICE: chat_dir / "voice_messages",
            MediaType.VIDEO_NOTE: chat_dir / "video_messages",
            MediaType.AUDIO: chat_dir / "audio",
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
            
            task.total_messages += 1
            
            # 处理媒体
            media_type = telegram_client.get_media_type(msg)
            media_path = None
            
            if media_type:
                task.total_media += 1
                
                # 检查是否需要下载该类型
                should_download = self._should_download_media(media_type, options)
                
                if should_download:
                    # 下载媒体
                    media_dir = media_dirs.get(media_type, chat_dir / "other")
                    media_dir.mkdir(parents=True, exist_ok=True)
                    
                    file_name = self._get_media_filename(msg, media_type)
                    file_path = media_dir / file_name
                    
                    # 断点续传 - 检查文件是否已存在
                    if options.skip_existing and file_path.exists():
                        media_path = str(file_path.relative_to(export_path))
                        task.downloaded_media += 1
                    else:
                        # 使用临时文件名下载 (.downloading 后缀)
                        temp_file_path = file_path.with_suffix(file_path.suffix + ".downloading")
                        
                        # 等待暂停状态结束
                        while self.is_paused(task.id):
                            await asyncio.sleep(1)
                            if task.status == TaskStatus.CANCELLED:
                                break
                        
                        if task.status == TaskStatus.CANCELLED:
                            break
                        
                        # 使用重试管理器下载
                        retry_manager = DownloadRetryManager(
                            max_retries=options.max_download_retries,
                            initial_delay=options.retry_delay
                        )
                        
                        success, downloaded, failure_info = await retry_manager.download_with_retry(
                            download_func=telegram_client.download_media,
                            message=msg,
                            file_path=temp_file_path,
                            refresh_message_func=telegram_client.get_message_by_id,
                            progress_callback=lambda c, t: self._update_download_progress(task, c)
                        )
                        
                        if success and downloaded:
                            # 下载完成，重命名为正式文件名
                            if temp_file_path.exists():
                                temp_file_path.rename(file_path)
                            media_path = str(file_path.relative_to(export_path))
                            task.downloaded_media += 1
                        elif failure_info:
                            # 记录失败
                            failed_download = FailedDownload(
                                message_id=failure_info["message_id"],
                                chat_id=failure_info["chat_id"],
                                file_name=failure_info["file_name"],
                                error_type=failure_info["error_type"],
                                error_message=failure_info["error_message"],
                                retry_count=failure_info["retry_count"],
                                last_retry=datetime.fromisoformat(failure_info["last_retry"])
                            )
                            task.failed_downloads.append(failed_download)
                            logger.warning(f"下载失败已记录: {file_name} ({failure_info['error_type']})")
            
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
                reply_to_message_id=msg.reply_to_message_id
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
        """生成安全的文件名"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name[:100]  # 限制长度
    
    def _get_media_filename(self, msg: Message, media_type: MediaType) -> str:
        """获取媒体文件名"""
        date_str = msg.date.strftime("%Y%m%d_%H%M%S")
        
        if msg.document and msg.document.file_name:
            return f"{date_str}_{msg.document.file_name}"
        
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
        return f"{date_str}_{msg.id}.{ext}"
    
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
