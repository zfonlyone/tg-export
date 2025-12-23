"""
TG Export - 并行分块下载器 (Parallel Chunk Downloader)
实现单文件多连接并发下载，突破 Telegram 单连接限速

基于 Pyrogram raw API 实现，使用 upload.GetFile 请求特定字节范围
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Callable, List, Tuple, Any
from dataclasses import dataclass

from pyrogram import Client, raw
from pyrogram.types import Message
from pyrogram.file_id import FileId, FileType, PHOTO_TYPES
from pyrogram.errors import FloodWait, FileReferenceExpired, FileReferenceInvalid

logger = logging.getLogger(__name__)


@dataclass
class ChunkInfo:
    """分块信息"""
    index: int
    offset: int
    limit: int
    downloaded: bool = False
    error: Optional[str] = None


class ParallelChunkDownloader:
    """
    高性能并行分块下载器
    
    核心原理：
    1. 将大文件分割为 N 个 chunks
    2. 使用 asyncio.gather() 并发下载所有 chunks
    3. 每个 chunk 使用独立的 raw API 请求 (upload.GetFile)
    4. 下载完成后按顺序合并写入磁盘
    
    配置建议：
    - Premium 账号: 6-8 并行连接
    - 免费账号: 3-4 并行连接
    """
    
    # MTProto 标准块大小 (必须是 4KB 的倍数，最大 1MB)
    CHUNK_SIZE = 1024 * 1024  # 1MB
    
    # 触发并行下载的最小文件大小
    MIN_PARALLEL_SIZE = 10 * 1024 * 1024  # 10MB
    
    def __init__(
        self,
        client: Client,
        parallel_connections: int = 4,
        chunk_size: int = CHUNK_SIZE
    ):
        """
        初始化并行下载器
        
        Args:
            client: Pyrogram Client 实例
            parallel_connections: 并行连接数 (免费账号建议 3-4)
            chunk_size: 每次请求的块大小 (默认 1MB)
        """
        self.client = client
        self.parallel_connections = parallel_connections
        self.chunk_size = chunk_size
        self._download_semaphore = asyncio.Semaphore(parallel_connections)
    
    async def download(
        self,
        message: Message,
        file_path: Path,
        file_size: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        并行分块下载文件
        
        Args:
            message: 包含媒体的消息对象
            file_path: 目标文件路径
            file_size: 文件大小 (字节)
            progress_callback: 进度回调 (current, total)
            cancel_check: 取消检查函数，返回 True 表示需要取消
            
        Returns:
            (success, error_message)
        """
        # 小文件不使用并行下载
        if file_size < self.MIN_PARALLEL_SIZE:
            logger.debug(f"文件 {file_path.name} 小于 {self.MIN_PARALLEL_SIZE // 1024 // 1024}MB，跳过并行下载")
            return False, "文件过小，不适用并行下载"
        
        logger.info(f"启动并行分块下载: {file_path.name} ({file_size / 1024 / 1024:.1f}MB, {self.parallel_connections} 连接)")
        
        try:
            # 1. 解析文件位置信息
            location = await self._get_file_location(message)
            if not location:
                return False, "无法解析文件位置"
            
            # 2. 计算分块策略
            chunks = self._calculate_chunks(file_size)
            logger.info(f"文件分割为 {len(chunks)} 个块")
            
            # 3. 准备目标文件 (预分配空间，确保非阻塞)
            import aiofiles
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 创建写锁，保护 seek/write 操作
            write_lock = asyncio.Lock()
            
            # 4. 并发下载与流式写入
            total_downloaded = [0]
            start_time = time.time()
            chunk_count = len(chunks)
            last_log_percent = 0
            
            async def download_and_write_chunk(chunk: ChunkInfo, f_handle):
                """下载分块并立即写入文件"""
                try:
                    async with self._download_semaphore:
                        if cancel_check and cancel_check():
                            chunk.error = "已取消"
                            return
                        
                        # 下载数据
                        data = await self._download_chunk(location, chunk.offset, chunk.limit)
                        
                        # 立即写入文件 (内存安全：写完即丢弃 data)
                        async with write_lock:
                            await f_handle.seek(chunk.offset)
                            await f_handle.write(data)
                        
                        chunk.downloaded = True
                        # 释放内存
                        del data
                        
                        # 更新进度
                        total_downloaded[0] += chunk.limit
                        percent = (total_downloaded[0] / file_size) * 100
                        
                        # 每 20% 记录一次日志，避免日志刷屏
                        nonlocal last_log_percent
                        if percent >= last_log_percent + 20:
                            logger.info(f"并行下载进度: {percent:.1f}% ({total_downloaded[0]}/{file_size})")
                            last_log_percent = int(percent // 20) * 20

                        if progress_callback:
                            progress_callback(total_downloaded[0], file_size)
                            
                except FloodWait as e:
                    logger.warning(f"分块 #{chunk.index} (offset={chunk.offset}) 触发限速，等待 {e.value} 秒")
                    chunk.error = f"FloodWait: {e.value}s"
                    raise
                except Exception as e:
                    logger.error(f"分块 #{chunk.index} (offset={chunk.offset}) 下载失败: {e}")
                    chunk.error = str(e)
                    raise

            
            # 使用 r+b 模式打开文件并行写入
            # 先创建空文件并设置大小
            async with aiofiles.open(file_path, 'wb') as f:
                pass
            
            async with aiofiles.open(file_path, 'r+b') as f:
                # 并发任务
                tasks = [download_and_write_chunk(chunk, f) for chunk in chunks]
                await asyncio.gather(*tasks, return_exceptions=True)
            
            # 5. 检查结果
            failed_chunks = [c for c in chunks if not c.downloaded]
            if failed_chunks:
                errors = [f"块{c.index}: {c.error}" for c in failed_chunks[:3]]
                return False, f"部分分块下载失败: {'; '.join(errors)}"
            
            elapsed = time.time() - start_time
            speed = file_size / elapsed / 1024 / 1024 if elapsed > 0 else 0
            logger.info(f"并行下载完成: {file_path.name} ({speed:.1f} MB/s)")
            
            return True, None
            
        except FloodWait as e:
            return False, f"触发 Telegram 限速 ({e.value}s)，请稍后重试"
        except Exception as e:
            logger.exception(f"并行下载失败: {e}")
            return False, str(e)

    
    async def _get_file_location(self, message: Message) -> Optional[Any]:
        """
        从消息中解析文件位置信息
        
        返回可用于 upload.GetFile 的 InputFileLocation 对象
        """
        try:
            # 获取媒体对象
            media = (
                message.document or
                message.video or
                message.audio or
                message.voice or
                message.video_note or
                message.sticker or
                message.animation or
                message.photo
            )
            
            if not media:
                logger.error("消息中没有媒体")
                return None
            
            # 获取 file_id
            if hasattr(media, 'file_id'):
                file_id_str = media.file_id
            else:
                logger.error("无法获取 file_id")
                return None
            
            # 解析 file_id 获取位置信息
            file_id = FileId.decode(file_id_str)
            
            # 根据文件类型构建不同的 InputFileLocation
            if file_id.file_type in PHOTO_TYPES:
                # 照片使用 InputPhotoFileLocation
                location = raw.types.InputPhotoFileLocation(
                    id=file_id.media_id,
                    access_hash=file_id.access_hash,
                    file_reference=file_id.file_reference,
                    thumb_size=file_id.thumbnail_size
                )
            else:
                # 文档/视频等使用 InputDocumentFileLocation
                location = raw.types.InputDocumentFileLocation(
                    id=file_id.media_id,
                    access_hash=file_id.access_hash,
                    file_reference=file_id.file_reference,
                    thumb_size=""
                )
            
            return location
            
        except Exception as e:
            logger.error(f"解析文件位置失败: {e}")
            return None
    
    def _calculate_chunks(self, file_size: int) -> List[ChunkInfo]:
        """
        计算分块策略
        
        将文件分成 parallel_connections 个大致相等的部分，
        每个部分内部按 chunk_size 请求
        """
        chunks = []
        
        # 计算每个连接负责的字节范围
        part_size = file_size // self.parallel_connections
        # 确保 part_size 是 chunk_size 的整数倍
        part_size = (part_size // self.chunk_size + 1) * self.chunk_size
        
        offset = 0
        index = 0
        
        while offset < file_size:
            # 当前块的大小 (不超过 chunk_size，也不超过剩余大小)
            remaining = file_size - offset
            limit = min(self.chunk_size, remaining)
            
            chunks.append(ChunkInfo(
                index=index,
                offset=offset,
                limit=limit
            ))
            
            offset += limit
            index += 1
        
        return chunks
    
    async def _download_chunk(
        self,
        location: Any,
        offset: int,
        limit: int
    ) -> bytes:
        """
        下载文件的特定字节范围
        
        使用 Pyrogram raw API 直接调用 upload.GetFile
        
        Args:
            location: InputFileLocation 对象
            offset: 起始字节偏移
            limit: 请求的字节数
            
        Returns:
            下载的字节数据
        """
        try:
            # 调用 raw API
            result = await self.client.invoke(
                raw.functions.upload.GetFile(
                    location=location,
                    offset=offset,
                    limit=limit,
                    precise=True,  # 禁用限制检查，适合流式下载
                    cdn_supported=False
                )
            )
            
            # 结果可能是 upload.File 或 upload.FileCdnRedirect
            if isinstance(result, raw.types.upload.File):
                return result.bytes
            else:
                logger.warning(f"收到非预期的响应类型: {type(result)}")
                return b""
                
        except FloodWait:
            raise
        except (FileReferenceExpired, FileReferenceInvalid) as e:
            logger.error(f"文件引用过期: {e}")
            raise
        except Exception as e:
            err_str = str(e)
            if "FILE_MIGRATE_" in err_str:
                logger.warning(f"检测到 DC 迁移错误: {err_str}。分块下载将触发重试或回退。")
            else:
                logger.error(f"下载块失败 (offset={offset}, limit={limit}): {e}")
            raise



# 便捷函数：创建下载器并执行下载
async def parallel_download_media(
    client: Client,
    message: Message,
    file_path: Path,
    file_size: int,
    parallel_connections: int = 4,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> Tuple[bool, Optional[str]]:
    """
    并行下载媒体文件的便捷函数
    
    Args:
        client: Pyrogram Client
        message: 消息对象
        file_path: 目标路径
        file_size: 文件大小
        parallel_connections: 并行连接数
        progress_callback: 进度回调
        
    Returns:
        (success, error_message)
    """
    downloader = ParallelChunkDownloader(
        client=client,
        parallel_connections=parallel_connections
    )
    return await downloader.download(
        message=message,
        file_path=file_path,
        file_size=file_size,
        progress_callback=progress_callback
    )
