import asyncio
import logging
import time
import os
import random
from pathlib import Path
from typing import Optional, Callable, List, Tuple, Any
from dataclasses import dataclass

from pyrogram import raw
from pyrogram.types import Message
from pyrogram.file_id import FileId, PHOTO_TYPES
from pyrogram.errors import FloodWait, FileReferenceExpired, FileReferenceInvalid

from .client import telegram_client
from ..models import ExportTask, DownloadItem, DownloadStatus

logger = logging.getLogger(__name__)

@dataclass
class ChunkInfo:
    """分块信息"""
    index: int
    offset: int
    limit: int
    real_size: int = 0
    downloaded: bool = False
    error: Optional[str] = None

class ParallelDownloaderMixin:
    """并行下载 Mixin (v2.3.6)"""
    
    CHUNK_SIZE = 1024 * 1024  # 1MB
    BLOCK_ALIGN = 4096 
    MIN_PARALLEL_SIZE = 10 * 1024 * 1024  # 10MB

    async def parallel_download(
        self,
        task: ExportTask,
        item: DownloadItem,
        message: Message,
        file_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[bool, Optional[str]]:
        """实现高性能并行分块下载"""
        file_size = item.file_size
        options = task.options
        
        # 1. 前置检查
        if not options.enable_parallel_chunk or options.parallel_chunk_connections <= 1:
            return False, "并行未启用"
        if file_size < self.MIN_PARALLEL_SIZE:
            return False, "文件过小"

        logger.debug(f"任务 {task.id[:8]}: 启动并行下载 {item.id}")
        
        try:
            # 2. 获取位置并探测 DC
            location = await self._get_file_location(message)
            if not location: return False, "无法解析位置"
            await self._probe_dc(location)
            
            # 3. 计算分块
            chunks = self._calculate_chunks(file_size, options.parallel_chunk_connections)
            
            # 4. 断点续传检查
            existing_size = os.path.getsize(file_path) if file_path.exists() else 0
            for chunk in chunks:
                if chunk.offset + chunk.real_size <= existing_size:
                    chunk.downloaded = True
            
            write_lock = asyncio.Lock()
            total_downloaded = [sum(c.real_size for c in chunks if c.downloaded)]
            
            # 5. 获取任务专用的信号量 (在 ExporterBase 中初始化)
            sem = self._parallel_semaphores.get(task.id)
            if not sem:
                sem = asyncio.Semaphore(options.parallel_chunk_connections * 2)
                self._parallel_semaphores[task.id] = sem

            # 内部下载 Worker 函数
            async def download_chunk_worker(chunk: ChunkInfo, f_handle):
                if chunk.downloaded: return
                
                async with sem:
                    if self.is_paused(task.id) or task.status == TaskStatus.CANCELLED:
                         raise asyncio.CancelledError()
                    
                    # 错峰启动
                    await asyncio.sleep(random.uniform(0.05, 0.2) * (chunk.index % options.parallel_chunk_connections))
                    
                    # 下载数据
                    data = await self._download_chunk_raw(location, chunk.offset, chunk.limit)
                    
                    # 写入
                    async with write_lock:
                        await f_handle.seek(chunk.offset)
                        await f_handle.write(data[:chunk.real_size])
                    
                    chunk.downloaded = True
                    total_downloaded[0] += chunk.real_size
                    if progress_callback:
                        progress_callback(total_downloaded[0], file_size)

            import aiofiles
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if not file_path.exists():
                async with aiofiles.open(file_path, 'wb') as f: pass

            async with aiofiles.open(file_path, 'r+b') as f:
                worker_tasks = [download_chunk_worker(c, f) for c in chunks]
                await asyncio.gather(*worker_tasks)
            
            # 最终检查
            if all(c.downloaded for c in chunks):
                return True, str(file_path)
            return False, "部分分块失败"

        except asyncio.CancelledError:
             raise
        except Exception as e:
            logger.error(f"并行下载异常 {item.id}: {e}")
            return False, str(e)

    def _calculate_chunks(self, file_size: int, connections: int) -> List[ChunkInfo]:
        """计算对齐 4KB 的分块"""
        chunks = []
        offset = 0
        index = 0
        # 动态调整块大小，尽量让每个连接都有活干但又不至于请求太碎
        chunk_size = max(self.CHUNK_SIZE, (file_size // (connections * 4) // self.BLOCK_ALIGN) * self.BLOCK_ALIGN)
        chunk_size = min(chunk_size, 1024 * 1024) # 最大 1MB
        
        while offset < file_size:
            remaining = file_size - offset
            request_limit = min(chunk_size, ((remaining + self.BLOCK_ALIGN - 1) // self.BLOCK_ALIGN) * self.BLOCK_ALIGN)
            chunks.append(ChunkInfo(index=index, offset=offset, limit=request_limit, real_size=min(request_limit, remaining)))
            offset += request_limit
            index += 1
        return chunks

    async def _get_file_location(self, message: Message) -> Optional[Any]:
        """解析 InputFileLocation"""
        try:
            media = message.document or message.video or message.audio or message.voice or message.video_note or message.sticker or message.animation or message.photo
            if not media: return None
            file_id_str = getattr(media, 'file_id', None)
            if not file_id_str: return None
            
            file_id = FileId.decode(file_id_str)
            if file_id.file_type in PHOTO_TYPES:
                return raw.types.InputPhotoFileLocation(id=file_id.media_id, access_hash=file_id.access_hash, file_reference=file_id.file_reference, thumb_size=file_id.thumbnail_size)
            return raw.types.InputDocumentFileLocation(id=file_id.media_id, access_hash=file_id.access_hash, file_reference=file_id.file_reference, thumb_size="")
        except: return None

    async def _probe_dc(self, location: Any):
        """同步 DC 状态"""
        try:
            await telegram_client.invoke(raw.functions.upload.GetFile(location=location, offset=0, limit=4096, precise=True))
        except: pass

    async def _download_chunk_raw(self, location: Any, offset: int, limit: int) -> bytes:
        """调用原始接口下载单块"""
        for attempt in range(3):
            try:
                result = await telegram_client.invoke(raw.functions.upload.GetFile(location=location, offset=offset, limit=limit, precise=True))
                if isinstance(result, raw.types.upload.File):
                    return result.bytes
                return b""
            except (FloodWait, FileReferenceExpired, FileReferenceInvalid):
                raise
            except:
                if attempt < 2: await asyncio.sleep(1)
                else: raise
        return b""
