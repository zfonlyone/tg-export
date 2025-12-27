import logging
import asyncio
import re
from pathlib import Path
from typing import Dict, Set, Union, Optional, List
from pyrogram.types import Message
from ..models import ExportTask, MediaType, DownloadItem, DownloadStatus

logger = logging.getLogger(__name__)

class ExporterBase:
    """导出器基础状态与实用工具"""
    
    def __init__(self):
        self.tasks: Dict[str, ExportTask] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._paused_tasks: Set[str] = set()
        self._item_to_worker: Dict[str, Dict[str, asyncio.Task]] = {}
        self._task_queues: Dict[str, asyncio.Queue] = {}
        self._progress_callbacks: Dict[str, List] = {}
        self._active_download_tasks: Dict[str, Set[asyncio.Task]] = {}
        self._parallel_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._needs_save = False
        
        from .tdl_manager import TDLBatcher
        self.tdl_batcher = TDLBatcher()
        
    def _set_777_recursive(self, path: Path):
        """递归设置 777 权限"""
        try:
            import os
            os.chmod(path, 0o777)
            if path.is_dir():
                for item in path.iterdir():
                    self._set_777_recursive(item)
        except Exception:
            pass

    def _get_export_path(self, task: ExportTask) -> Path:
        """获取任务导出路径"""
        from ..config import settings
        if task.options.export_path:
            return Path(task.options.export_path).expanduser()
        return settings.EXPORT_DIR / task.name

    def is_paused(self, task_id: str) -> bool:
        """检查任务是否处于暂停状态"""
        return task_id in self._paused_tasks

    def _safe_move(self, src: Union[str, Path], dst: Union[str, Path]) -> bool:
        """稳健的文件移动"""
        import shutil
        src_path = Path(src)
        dst_path = Path(dst)
        if not src_path.exists(): return False
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if dst_path.exists():
                dst_path.unlink()
            shutil.move(str(src_path), str(dst_path))
            return True
        except Exception as e:
            logger.error(f"文件移动失败: {e}")
            return False

    def _get_file_size(self, msg: Message) -> Optional[int]:
        """获取消息中的媒体文件大小"""
        for attr in ['photo', 'video', 'document', 'audio', 'voice', 'video_note', 'sticker', 'animation']:
            media = getattr(msg, attr, None)
            if media:
                if attr == 'photo' and isinstance(media, list):
                     return media[-1].file_size
                return getattr(media, 'file_size', None)
        return None

    def _get_media_filename(self, msg: Message, media_type: MediaType) -> str:
        """获取媒体文件名 - 格式: 消息id-群id-文件名"""
        chat_id = abs(msg.chat.id)
        msg_id = msg.id
        
        if msg.document and msg.document.file_name:
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
        date_str = msg.date.strftime("%Y%m%d_%H%M%S")
        return f"{msg_id}-{chat_id}-{date_str}.{ext}"

    def _safe_filename(self, name: str) -> str:
        """生成安全的文件名"""
        import re
        emoji_pattern = re.compile("[" "\U0001F600-\U0001F64F" "\U0001F300-\U0001F5FF" "\U0001F680-\U0001F6FF" "\U0001F1E0-\U0001F1FF" "\U00002702-\U000027B0" "\U0001F900-\U0001F9FF" "\U0001FA00-\U0001FA6F" "\U0001FA70-\U0001FAFF" "\U00002600-\U000026FF" "]+", flags=re.UNICODE)
        name = emoji_pattern.sub('', name)
        name = re.sub(r'[^\w\u4e00-\u9fff.\-]', '_', name)
        name = re.sub(r'_+', '_', name).strip('_')
        return name[:100] if name else 'unnamed'

    async def _check_tdl_stuck(self, task: ExportTask, item: DownloadItem, target_sub_dir: str) -> bool:
        """检查 TDL 下载是否卡死"""
        try:
            sub_path = Path(target_sub_dir)
            if not sub_path.exists(): return False 
            prefix = f"{item.message_id}-"
            relevant_files = [f for f in sub_path.iterdir() if f.name.startswith(prefix)]
            if not relevant_files: return False
            import time
            now = time.time()
            for f in relevant_files:
                try:
                    if now - f.stat().st_mtime < 180: return False
                except: pass
            return True
        except Exception:
            return False
