"""
TG Export - 下载重试管理器
提供指数退避重试、错误分类和失败记录功能
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Callable, Any
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

logger = logging.getLogger(__name__)


class ErrorType(str, Enum):
    """错误类型分类"""
    CONNECTION_LOST = "connection_lost"      # 连接中断，可重试
    FILE_REF_EXPIRED = "file_ref_expired"    # 文件引用过期，需刷新后重试
    PEER_INVALID = "peer_invalid"            # 频道无效，不可重试
    FLOOD_WAIT = "flood_wait"                # 限流，等待后重试
    UNKNOWN = "unknown"                      # 未知错误


class DownloadRetryManager:
    """下载重试管理器"""
    
    def __init__(
        self,
        max_retries: int = 5,
        initial_delay: float = 2.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self._failures: List[dict] = []
    
    def classify_error(self, error: Exception) -> ErrorType:
        """根据异常类型分类错误"""
        error_str = str(error).lower()
        
        # 文件引用过期
        if isinstance(error, (FileReferenceExpired, FileReferenceInvalid)):
            return ErrorType.FILE_REF_EXPIRED
        if "file reference" in error_str:
            return ErrorType.FILE_REF_EXPIRED
        
        # 频道/对等体无效
        if isinstance(error, (PeerIdInvalid, ChannelInvalid, ChannelPrivate)):
            return ErrorType.PEER_INVALID
        if "peer_id_invalid" in error_str:
            return ErrorType.PEER_INVALID
        
        # 限流
        if isinstance(error, FloodWait):
            return ErrorType.FLOOD_WAIT
        if "flood" in error_str:
            return ErrorType.FLOOD_WAIT
        
        # 连接问题
        if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            return ErrorType.CONNECTION_LOST
            
        connection_keywords = [
            "connection", "disconnect", "timeout", "reset",
            "network", "eof", "broken pipe", "connection lost"
        ]
        if any(kw in error_str for kw in connection_keywords):
            return ErrorType.CONNECTION_LOST
        
        return ErrorType.UNKNOWN
    
    def is_retryable(self, error_type: ErrorType) -> bool:
        """判断错误是否可重试"""
        return error_type in {
            ErrorType.CONNECTION_LOST,
            ErrorType.FILE_REF_EXPIRED,
            ErrorType.FLOOD_WAIT,
            ErrorType.UNKNOWN  # 未知错误也尝试重试
        }
    
    def get_retry_delay(self, attempt: int, error: Exception) -> float:
        """计算重试延迟时间"""
        # FloodWait 有特殊等待时间
        if isinstance(error, FloodWait):
            # [v1.6.0] 增加随机抖动 (5-15秒)，更稳健地避开限速墙
            import random
            return min(error.value + random.uniform(5.0, 15.0), self.max_delay * 10) # 允许超过基础 max_delay
        
        # 指数退避
        delay = self.initial_delay * (self.backoff_factor ** attempt)
        return min(delay, self.max_delay)
    
    async def download_with_retry(
        self,
        download_func: Callable,
        message: Message,
        file_path: Path,
        refresh_message_func: Optional[Callable] = None,
        progress_callback: Optional[Callable] = None,
        on_flood_wait_callback: Optional[Callable[[int], Any]] = None,
    ) -> tuple[bool, Optional[str], Optional[dict]]:
        """
        带重试的下载函数
        
        Args:
            download_func: 实际下载函数
            message: 消息对象
            file_path: 目标文件路径
            refresh_message_func: 刷新消息的函数（用于处理文件引用过期）
            progress_callback: 进度回调
            
        Returns:
            (success, downloaded_path, failure_info)
        """
        last_error = None
        current_message = message
        
        for attempt in range(self.max_retries):
            try:
                # 尝试下载
                result = await download_func(
                    current_message,
                    file_path,
                    progress_callback
                )
                
                if result:
                    if attempt > 0:
                        logger.info(f"下载成功 (重试 {attempt} 次): {file_path.name}")
                    return True, result, None
                    
            except Exception as e:
                last_error = e
                error_type = self.classify_error(e)
                
                logger.warning(
                    f"下载失败 [{error_type.value}] (尝试 {attempt + 1}/{self.max_retries}): "
                    f"{file_path.name} - {str(e)[:100]}"
                )
                
                # 不可重试的错误，直接返回
                if not self.is_retryable(error_type):
                    failure_info = self._create_failure_info(
                        message, file_path, error_type, e, attempt + 1
                    )
                    return False, None, failure_info
                
                # 文件引用过期，需要刷新消息
                if error_type == ErrorType.FILE_REF_EXPIRED and refresh_message_func:
                    try:
                        current_message = await refresh_message_func(
                            message.chat.id, message.id
                        )
                        if current_message:
                            logger.info(f"已刷新消息引用: {message.id}")
                        else:
                            logger.warning(f"无法刷新消息引用: {message.id}")
                    except Exception as refresh_error:
                        logger.error(f"刷新消息失败: {refresh_error}")
                
                # 还有重试机会
                if attempt < self.max_retries - 1:
                    delay = self.get_retry_delay(attempt, e)
                    
                    # [Adaptive Concurrency] 触发回调通知外部实时调整
                    if error_type == ErrorType.FLOOD_WAIT and on_flood_wait_callback:
                        try:
                            if asyncio.iscoroutinefunction(on_flood_wait_callback):
                                await on_flood_wait_callback(int(delay))
                            else:
                                on_flood_wait_callback(int(delay))
                        except Exception as cb_err:
                            logger.error(f"限速回调执行失败: {cb_err}")

                    logger.info(f"等待 {delay:.1f} 秒后重试...")
                    await asyncio.sleep(delay)
        
        # 所有重试都失败
        failure_info = self._create_failure_info(
            message, file_path, 
            self.classify_error(last_error) if last_error else ErrorType.UNKNOWN,
            last_error, self.max_retries
        )
        return False, None, failure_info
    
    def _create_failure_info(
        self,
        message: Message,
        file_path: Path,
        error_type: ErrorType,
        error: Optional[Exception],
        retry_count: int
    ) -> dict:
        """创建失败记录信息"""
        return {
            "message_id": message.id,
            "chat_id": message.chat.id,
            "file_name": file_path.name if file_path else None,
            "error_type": error_type.value,
            "error_message": str(error)[:500] if error else "Unknown error",
            "retry_count": retry_count,
            "last_retry": datetime.now().isoformat(),
            "resolved": False
        }
    
    def record_failure(self, failure_info: dict):
        """记录失败"""
        self._failures.append(failure_info)
    
    def get_failures(self) -> List[dict]:
        """获取所有失败记录"""
        return self._failures.copy()
    
    def clear_failures(self):
        """清空失败记录"""
        self._failures.clear()
    
    @staticmethod
    def load_failures(chat_dir: Path) -> List[dict]:
        """从文件加载失败记录"""
        failure_file = chat_dir / ".failed_downloads.json"
        if failure_file.exists():
            try:
                with open(failure_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载失败记录出错: {e}")
        return []
    
    @staticmethod
    def save_failures(chat_dir: Path, failures: List[dict]):
        """保存失败记录到文件"""
        failure_file = chat_dir / ".failed_downloads.json"
        try:
            with open(failure_file, "w", encoding="utf-8") as f:
                json.dump(failures, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存失败记录出错: {e}")
    
    @staticmethod
    def merge_failures(existing: List[dict], new_failures: List[dict]) -> List[dict]:
        """合并失败记录，避免重复"""
        existing_ids = {(f["chat_id"], f["message_id"]) for f in existing}
        merged = existing.copy()
        
        for failure in new_failures:
            key = (failure["chat_id"], failure["message_id"])
            if key not in existing_ids:
                merged.append(failure)
            else:
                # 更新已有记录
                for i, f in enumerate(merged):
                    if (f["chat_id"], f["message_id"]) == key:
                        merged[i] = failure
                        break
        
        return merged
