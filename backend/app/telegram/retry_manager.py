import asyncio
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Callable, Any, Tuple, Dict
from enum import Enum

from pyrogram.types import Message
from pyrogram.errors import (
    FloodWait,
    FileReferenceExpired,
    FileReferenceInvalid,
    PeerIdInvalid,
    ChannelInvalid,
    ChannelPrivate,
)

from ..models import ExportTask, DownloadItem, DownloadStatus

logger = logging.getLogger(__name__)

class ErrorType(str, Enum):
    """错误类型分类"""
    CONNECTION_LOST = "connection_lost"
    FILE_REF_EXPIRED = "file_ref_expired"
    PEER_INVALID = "peer_invalid"
    FLOOD_WAIT = "flood_wait"
    UNKNOWN = "unknown"

class RetryManagerMixin:
    """下载重试管理 Mixin (v2.3.6)"""

    def classify_error(self, error: Exception) -> ErrorType:
        """根据异常类型分类错误"""
        error_str = str(error).lower()
        if isinstance(error, (FileReferenceExpired, FileReferenceInvalid)) or "file reference" in error_str:
            return ErrorType.FILE_REF_EXPIRED
        if isinstance(error, (PeerIdInvalid, ChannelInvalid, ChannelPrivate)) or "peer_id_invalid" in error_str:
            return ErrorType.PEER_INVALID
        if isinstance(error, FloodWait) or "flood" in error_str:
            return ErrorType.FLOOD_WAIT
        if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            return ErrorType.CONNECTION_LOST
            
        connection_keywords = ["connection", "disconnect", "timeout", "reset", "network", "eof", "broken pipe", "connection lost"]
        if any(kw in error_str for kw in connection_keywords):
            return ErrorType.CONNECTION_LOST
        return ErrorType.UNKNOWN

    def is_retryable(self, error_type: ErrorType) -> bool:
        """判断错误是否可重试"""
        return error_type in {
            ErrorType.CONNECTION_LOST,
            ErrorType.FILE_REF_EXPIRED,
            ErrorType.FLOOD_WAIT,
            ErrorType.UNKNOWN
        }

    def get_retry_delay(self, task: ExportTask, attempt: int, error: Exception) -> float:
        """计算重试延迟时间"""
        if isinstance(error, FloodWait):
            # [v1.6.6] N + 2 秒安全冗余
            return error.value + 2.0 + random.uniform(1.0, 3.0)
        
        # 使用任务选项中的重试延迟
        base_delay = task.options.retry_delay
        delay = base_delay * (2 ** attempt)  # 指数倍数
        return min(delay, 60.0) # 最大延迟 60s

    async def download_with_retry(
        self,
        task: ExportTask,
        item: DownloadItem,
        download_func: Callable,
        message: Message,
        file_path: Path,
        **kwargs
    ) -> Tuple[bool, Optional[str]]:
        """
        带重试逻辑的通用下载包装器
        """
        max_retries = task.options.max_download_retries
        last_error = None
        
        for attempt in range(max_retries):
            if self.is_paused(task.id) or task.status == DownloadStatus.PAUSED:
                 # 让外部逻辑处理暂停，此处直接抛出取消
                 raise asyncio.CancelledError()

            try:
                # 执行实际下载 (可能是并行下载或常规下载)
                success, result_path = await download_func(message, file_path, **kwargs)
                if success:
                    return True, result_path
            except Exception as e:
                last_error = e
                error_type = self.classify_error(e)
                logger.warning(f"下载尝试 {attempt + 1}/{max_retries} 失败: {item.id} - {error_type.value}")
                
                if not self.is_retryable(error_type):
                    item.error = f"不可重试错误: {error_type.value}"
                    return False, None
                
                # 处理限速
                if error_type == ErrorType.FLOOD_WAIT:
                    wait_time = int(self.classify_error(e) == ErrorType.FLOOD_WAIT and getattr(e, 'value', 30))
                    task.last_flood_wait_time = datetime.now()
                    await self._notify_progress(task.id, task)
                
                if attempt < max_retries - 1:
                    delay = self.get_retry_delay(task, attempt, e)
                    await asyncio.sleep(delay)
                else:
                    item.error = str(last_error)
        
        return False, None

    def _record_failure(self, task: ExportTask, item: DownloadItem, error: Exception):
        """记录失败信息到任务模型"""
        error_type = self.classify_error(error)
        failure = {
            "message_id": item.message_id,
            "chat_id": item.chat_id,
            "file_name": item.file_name,
            "error_type": error_type.value,
            "error_message": str(error)[:500],
            "retry_count": task.options.max_download_retries,
            "last_retry": datetime.now().isoformat(),
            "resolved": False
        }
        # 避免重复记录同一消息
        task.failed_downloads = [f for f in task.failed_downloads if not (f.chat_id == item.chat_id and f.message_id == item.message_id)]
        task.failed_downloads.append(failure)
