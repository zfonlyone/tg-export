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
        if not task or task.status not in [TaskStatus.RUNNING, TaskStatus.EXTRACTING]:
            return False
        
        self._paused_tasks.add(task_id)
        task.status = TaskStatus.PAUSED
        
        # 将所有正在下载的项目也设为暂停，这样下载循环会在当前文件完成后暂停
        for item in task.download_queue:
            if item.status == DownloadStatus.DOWNLOADING:
                item.status = DownloadStatus.PAUSED
        
        await self._notify_progress(task_id, task)
        return True
    
    async def resume_export(self, task_id: str) -> bool:
        """恢复导出任务"""
        task = self.tasks.get(task_id)
        if not task or task.status != TaskStatus.PAUSED:
            return False
        
        self._paused_tasks.discard(task_id)
        task.status = TaskStatus.RUNNING
        
        # 将所有暂停的下载项恢复为等待状态
        for item in task.download_queue:
            if item.status == DownloadStatus.PAUSED:
                item.status = DownloadStatus.WAITING
        
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
            export_path = Path(options.export_path)
            export_path.mkdir(parents=True, exist_ok=True)
            
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
            task.status = TaskStatus.CANCELLED
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.exception("导出任务执行出错")
        finally:
            await self._notify_progress(task.id, task)

    async def _process_download_queue(self, task: ExportTask, export_path: Path):
        """处理下载队列"""
        options = task.options
        
        # 限制并发下载数
        semaphore = asyncio.Semaphore(options.max_concurrent_downloads)
        
        async def download_worker(item: DownloadItem):
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

                item.status = DownloadStatus.DOWNLOADING
                full_path = export_path / item.file_path
                temp_file_path = full_path.with_suffix(full_path.suffix + ".downloading")
                
                retry_manager = DownloadRetryManager(
                    max_retries=options.max_download_retries,
                    initial_delay=options.retry_delay
                )
                
                def progress_cb(current, total):
                    item.downloaded_size = current
                    item.file_size = total
                    if total > 0:
                        item.progress = (current / total) * 100
                
                success, downloaded, failure_info = await retry_manager.download_with_retry(
                    download_func=telegram_client.download_media,
                    message=msg,
                    file_path=temp_file_path,
                    refresh_message_func=telegram_client.get_message_by_id,
                    progress_callback=progress_cb
                )
                
                if success and downloaded:
                    if temp_file_path.exists():
                        temp_file_path.rename(full_path)
                    item.status = DownloadStatus.COMPLETED
                    item.progress = 100.0
                    task.downloaded_media += 1
                    # 每完成一个下载，通知一次进度 (对于大批量下载，可以考虑节流)
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

        # 创建并启动所有下载任务
        download_tasks = [download_worker(item) for item in task.download_queue]
        await asyncio.gather(*download_tasks)
    
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
