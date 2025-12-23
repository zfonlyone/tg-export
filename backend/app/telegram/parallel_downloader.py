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
    real_size: int = 0             # [v1.6.6] 实际写入的大小
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
    # [v1.6.6] 增加默认大小到 1MB 以减少请求密度
    CHUNK_SIZE = 1024 * 1024  # 1024KB (1MB)
    
    # 强制块对齐大小 (1KB 或 4KB)
    BLOCK_ALIGN = 4096 
    
    # 触发并行下载的最小文件大小
    MIN_PARALLEL_SIZE = 10 * 1024 * 1024  # 10MB
    
    def __init__(
        self,
        client: Client,
        parallel_connections: int = 4,
        chunk_size: int = CHUNK_SIZE,
        task_semaphore: Optional[asyncio.Semaphore] = None,
        enable_parallel: bool = True
    ):
        """
        初始化并行下载器
        
        Args:
            client: Pyrogram Client 实例
            parallel_connections: 单文件并行连接数
            chunk_size: 每次请求的块大小 (默认 1MB)
            task_semaphore: 全局任务信号量 (可选)
            enable_parallel: 是否启用并行功能 (v1.6.7.3)
        """
        self.client = client
        self.enable_parallel = enable_parallel
        
        # 内部状态对齐：如果禁用并行，连接数强制为 1
        self.parallel_connections = parallel_connections if enable_parallel else 1
        
        self.chunk_size = chunk_size
        self.current_dc = None 
        # 信号量限额与连接数保持一致
        self._download_semaphore = task_semaphore or asyncio.Semaphore(self.parallel_connections)

    
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
        # [v1.6.0] 支持开关与常规下载
        if not getattr(self, "enable_parallel", True) or self.parallel_connections <= 1:
            logger.debug(f"并行下载已禁用或连接数为1, 使用标准下载: {file_path.name}")
            return False, "并行下载未启用"

        # 小文件不使用并行下载
        if file_size < self.MIN_PARALLEL_SIZE:
            logger.debug(f"文件 {file_path.name} 小于 {self.MIN_PARALLEL_SIZE // 1024 // 1024}MB，跳过并行下载")
            return False, "文件过小，不适用并行下载"
        
        logger.info(f"启动并行分块下载: {file_path.name} ({file_size / 1024 / 1024:.1f}MB, {self.parallel_connections} 连接)")
        
        try:
            location = await self._get_file_location(message)
            if not location:
                return False, "无法解析文件位置"
            
            # [v1.6.6] 下载前先探测 DC，避免并发时由于 FILE_MIGRATE 导致的连接风暴
            await self._probe_dc(location)
            
            # 2. 计算分块策略
            chunks = self._calculate_chunks(file_size)
            logger.info(f"文件分割为 {len(chunks)} 个块")
            
            # 3. 准备目标文件 (预分配空间，确保非阻塞)
            import aiofiles
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # [v1.6.7.6] 断点续传支持：检测已存在的文件大小并跳过已下载分块
            import os
            existing_size = os.path.getsize(file_path) if file_path.exists() else 0
            skipped_chunks = 0
            
            if existing_size > 0:
                # 标记已完整下载的分块
                for chunk in chunks:
                    chunk_end = chunk.offset + chunk.real_size
                    if chunk_end <= existing_size:
                        chunk.downloaded = True
                        skipped_chunks += 1
                
                if skipped_chunks > 0:
                    logger.info(f"断点续传: 跳过 {skipped_chunks}/{len(chunks)} 个已下载分块 (已有 {existing_size / 1024 / 1024:.1f}MB)")
            
            # 创建写锁，保护 seek/write 操作
            write_lock = asyncio.Lock()
            
            # 4. 并发下载与流式写入 (从已下载位置继续)
            total_downloaded = [existing_size]  # 从已下载大小开始
            start_time = time.time()
            chunk_count = len(chunks)
            last_log_percent = int((existing_size / file_size) * 100 // 20) * 20 if file_size > 0 else 0
            
            async def download_and_write_chunk(chunk: ChunkInfo, f_handle):
                """下载分块并立即写入文件"""
                try:
                    # [v1.6.7.6] 跳过已下载的分块（断点续传）
                    if chunk.downloaded:
                        return
                    
                    async with self._download_semaphore:
                        if cancel_check and cancel_check():
                            chunk.error = "已取消"
                            return
                        
                        # [v1.6.6] 增强阶梯式错峰启动：根据 index 增加随机阶梯延迟
                        # 避免所有连接同时瞬间发送握手/请求
                        import random
                        # 延迟公式：(0.1 ~ 0.3s) * (当前槽位索引)
                        delay = random.uniform(0.1, 0.3) * (chunk.index % self.parallel_connections)
                        if chunk.index >= self.parallel_connections:
                            await asyncio.sleep(delay)
                        elif chunk.index > 0:
                            await asyncio.sleep(0.1)

                        # 下载数据
                        data = await self._download_chunk(location, chunk.offset, chunk.limit)
                        
                        # 立即写入文件 (内存安全：写完即丢弃 data)
                        async with write_lock:
                            await f_handle.seek(chunk.offset)
                            # [v1.6.6] 仅写入 real_size 大小，防止文件尾部对齐填充导致文件变大
                            await f_handle.write(data[:chunk.real_size])
                        
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

            
            # [FIX v1.6.6] 断点续传逻辑修复：不再使用 'wb' 模式打开文件（即不再每次都抹除文件）
            # 改为以 'r+b' 模式打开并行写入。如果文件不存在则先创建。
            async with aiofiles.open(file_path, 'a') as f:
                pass # 确保文件存在
            
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
        计算分块策略 (v1.6.6 严格优化)
        
        Telegram 要求 offset 和 limit 必须是 4KB(4096) 的倍数。
        最后一个块的 limit 如果不是倍数，某些 DC 会报 LIMIT_INVALID 或触发 FloodWait。
        
        策略：
        1. 保持所有请求 limit 对齐 4KB。
        2. 最后一个块可能请求略大一点，但在写入磁盘时按 real_size 截断。
        """
        chunks = []
        offset = 0
        index = 0
        standard_limit = self.chunk_size
        
        while offset < file_size:
            remaining = file_size - offset
            
            # [v1.6.6] 确保 limit 必须对齐 4KB，哪怕超过了文件末尾 (Telegram 内部会自动截断)
            # 这可以有效防止部分 DC 返回 LIMIT_INVALID
            request_limit = min(standard_limit, ((remaining + self.BLOCK_ALIGN - 1) // self.BLOCK_ALIGN) * self.BLOCK_ALIGN)
            
            chunks.append(ChunkInfo(
                index=index,
                offset=offset,
                limit=request_limit,
                real_size=min(request_limit, remaining) # 记录磁盘写入上限
            ))
            
            offset += request_limit 
            index += 1
        
        return chunks
    
    async def _probe_dc(self, location: Any):
        """
        通过一个小请求探测该文件所属的 DC (v1.6.7.4)
        
        触发一次请求让 Pyrogram 自行处理 FILE_MIGRATE 错误，
        后续请求会自动使用正确的 DC。
        """
        try:
            # 请求起始的 4KB 数据，让 Pyrogram 自动处理 DC 迁移
            await self.client.invoke(
                raw.functions.upload.GetFile(
                    location=location,
                    offset=0,
                    limit=4096,
                    precise=True
                )
            )
        except Exception as e:
            err_str = str(e)
            if "FILE_MIGRATE_" in err_str:
                import re
                match = re.search(r"FILE_MIGRATE_(\d+)", err_str)
                if match:
                    target_dc = int(match.group(1))
                    logger.info(f"探测到文件所在 DC 为 {target_dc}，Pyrogram 将自动处理迁移。")
            # 探测阶段捕获所有错误但不抛出，由后续实际下载逻辑接手
            pass

    async def _download_chunk(
        self,
        location: Any,
        offset: int,
        limit: int,
        retries: int = 3
    ) -> bytes:
        """
        下载文件的特定字节范围 (v1.6.7.4 修复)
        
        Pyrogram 会自动处理 FILE_MIGRATE 错误，无需手动指定 dc_id。
        """
        for attempt in range(retries):
            try:
                # 调用 raw API，Pyrogram 自动处理 DC 迁移
                result = await self.client.invoke(
                    raw.functions.upload.GetFile(
                        location=location,
                        offset=offset,
                        limit=limit,
                        precise=True,
                        cdn_supported=False
                    )
                )
                
                if isinstance(result, raw.types.upload.File):
                    return result.bytes
                else:
                    logger.warning(f"收到非预期的响应类型: {type(result)}")
                    return b""
                    
            except FloodWait:
                raise
            except (FileReferenceExpired, FileReferenceInvalid):
                raise
            except Exception as e:
                err_str = str(e)
                # FILE_MIGRATE 现在由 Pyrogram 自动处理，只需记录日志
                if "FILE_MIGRATE_" in err_str:
                    logger.info(f"检测到 DC 迁移请求 ({err_str}), Pyrogram 将自动重试...")
                    if attempt < retries - 1:
                        await asyncio.sleep(0.5) 
                        continue
                    raise
                
                if "LIMIT_INVALID" in err_str:
                    logger.error(f"LIMIT_INVALID: offset={offset}, limit={limit}. 请检查对齐设置。")
                    raise
                
                if attempt < retries - 1:
                    logger.warning(f"分块下载失败 ({err_str}), 正在重试 ({attempt+1}/{retries})...")
                    await asyncio.sleep(1)
                    continue
                raise



# 便捷函数：创建下载器并执行下载
async def parallel_download_media(
    client: Client,
    message: Message,
    file_path: Path,
    file_size: int,
    parallel_connections: int = 4,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    task_semaphore: Optional[asyncio.Semaphore] = None
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
        task_semaphore: 全局任务信号量 (可选)
        
    Returns:
        (success, error_message)
    """
    downloader = ParallelChunkDownloader(
        client=client,
        parallel_connections=parallel_connections,
        task_semaphore=task_semaphore
    )

    return await downloader.download(
        message=message,
        file_path=file_path,
        file_size=file_size,
        progress_callback=progress_callback
    )
