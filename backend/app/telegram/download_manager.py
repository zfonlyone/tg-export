import asyncio
import logging
import time
import random
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Union

from pyrogram.errors import FloodWait
from pyrogram.types import Message

from ..config import settings
from ..models import (
    ExportTask, ExportOptions, TaskStatus, DownloadItem, DownloadStatus, MediaType
)
from .client import telegram_client

logger = logging.getLogger(__name__)

class DownloadManagerMixin:
    """下载管理核心逻辑 Mixin (v2.3.4)"""

    async def _run_export(self, task: ExportTask):
        """核心导出流程"""
        try:
            logger.info(f"任务 {task.id[:8]}: 开始执行主导出流程")
            export_path = self._get_export_path(task)
            export_path.mkdir(parents=True, exist_ok=True)
            
            # 如果是刚创建的任务且还没扫描过，先扫描
            if task.status == TaskStatus.RUNNING and task.processed_messages == 0:
                  task.status = TaskStatus.EXTRACTING
                  task.is_extracting = True
                  await self._scan_messages_worker(task.id, full=True)
            
            # 进入下载队列处理阶段
            if task.status != TaskStatus.CANCELLED:
                task.status = TaskStatus.RUNNING
                await self._process_download_queue(task, export_path)
                
            # 最终检查
            if task.status != TaskStatus.CANCELLED:
                if task.downloaded_media >= task.total_media:
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.now()
                else:
                    task.status = TaskStatus.PAUSED
                    
        except asyncio.CancelledError:
            logger.info(f"任务 {task.id[:8]} 主协程已被取消")
        except Exception as e:
            logger.error(f"任务 {task.id[:8]} 执行致命错误: {e}", exc_info=True)
            task.status = TaskStatus.FAILED
            task.error = str(e)
        finally:
            self._save_tasks()
            await self._notify_progress(task.id, task)

    async def _process_download_queue(self, task: ExportTask, export_path: Path):
        """处理任务下载队列 (Worker Pool 模式)"""
        await self._sync_task_with_disk(task, export_path)
        options = task.options
        
        # 1. 初始化客户端并发
        telegram_client.set_max_concurrent_transmissions(options.max_concurrent_downloads)
        
        # 2. 准备运行中的下载管线 (Consumer Pipe)
        queue = asyncio.Queue()
        self._task_queues[task.id] = queue
        
        # 3. 维护者逻辑：从待处理池初始填充管线
        self.refill_task_queue(task)
        
        if task.id not in self._active_download_tasks:
            self._active_download_tasks[task.id] = set()

        # 4. 初始化限额控制 (Adaptive)
        chunk_multiplier = 3 if options.enable_parallel_chunk else 1
        sem_limit = min(30, max(8, options.max_concurrent_downloads * chunk_multiplier))
        self._parallel_semaphores[task.id] = asyncio.Semaphore(sem_limit)

        self._last_global_start_time = 0
        global_start_lock = asyncio.Lock()

        async def worker_logic(worker_id: int):
            """内部工协程"""
            # 平滑启动
            async with global_start_lock:
                now = time.time()
                wait_time = max(0, self._last_global_start_time + 5 - now)
                if wait_time > 0: await asyncio.sleep(wait_time)
                self._last_global_start_time = time.time()
            
            logger.debug(f"Task {task.id[:8]}: Worker #{worker_id} started")

            while True:
                if task.status == TaskStatus.CANCELLED: break
                if worker_id >= task.options.max_concurrent_downloads: break
                
                # 全局暂停等待
                while self.is_paused(task.id) and task.status != TaskStatus.CANCELLED:
                    await asyncio.sleep(1)
                if task.status == TaskStatus.CANCELLED: break

                priority_item = None
                from_queue = False
                
                # 优先级探测 P1/P2/P4 ...
                # (此处逻辑为了演示已精简，实际会包含完整的调度逻辑)
                try:
                    item = await queue.get()
                    if item is None:
                        queue.task_done()
                        break
                    
                    # 下载核心调用
                    if task.id not in self._item_to_worker: self._item_to_worker[task.id] = {}
                    self._item_to_worker[task.id][item.id] = asyncio.current_task()
                    
                    try:
                        await self._download_item_worker(task, item, export_path)
                    finally:
                        self._item_to_worker[task.id].pop(item.id, None)
                        queue.task_done()
                    
                    # 动力衰减冷却
                    jitter = random.uniform(0.1, 0.3) if task.tdl_mode else random.uniform(2.0, 5.0)
                    await asyncio.sleep(jitter)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Task {task.id[:8]} Worker error: {e}")
                    await asyncio.sleep(1)

        # 启动工作协程池
        workers = [asyncio.create_task(worker_logic(i)) for i in range(options.max_concurrent_downloads)]
        
        # 速度更新与动态监控略
        try:
             while task.status == TaskStatus.RUNNING:
                 # 只要队列不空或者还有正在下载的，就继续
                 if queue.empty() and not any(i.status == DownloadStatus.DOWNLOADING for i in task.download_queue):
                     break
                 await asyncio.sleep(2)
        finally:
            for _ in range(options.max_concurrent_downloads): queue.put_nowait(None)
            for w in workers: w.cancel()
            self._task_queues.pop(task.id, None)

    async def _download_item_worker(self, task: ExportTask, item: DownloadItem, export_path: Path):
        """核心单文件下载算法 (整合了 TDL 和常规下载)"""
        if task.status == TaskStatus.CANCELLED: return
        options = task.options

        try:
            # 1. TDL 触发逻辑
            if task.tdl_mode:
                 # 使用 tdl_batcher (来自 ExporterBase)
                 target_sub_dir = export_path / item.file_path
                 target_sub_dir = target_sub_dir.parent
                 target_sub_dir.mkdir(parents=True, exist_ok=True)
                 
                 result = await self.tdl_batcher.add_item(task, item, str(target_sub_dir), manager_inst=self)
                 if result.get("success"):
                      item.status = DownloadStatus.COMPLETED
                      item.progress = 100.0
                 else:
                      item.status = DownloadStatus.FAILED
                      item.error = result.get("error", "TDL 失败")
                 await self._notify_progress(task.id, task)
                 return

            # 2. 常规/并行下载逻辑 (使用重试管理)
            item.status = DownloadStatus.DOWNLOADING
            msg = await telegram_client.get_message_by_id(item.chat_id, item.message_id)
            if not msg:
                 item.status = DownloadStatus.FAILED
                 item.error = "找不到消息"
                 return
            
            full_path = export_path / item.file_path
            temp_path = settings.DATA_DIR / "temp" / f"{item.id}_{full_path.name}"
            
            # 定义下载执行函数 (供 RetryManager 调用)
            async def core_download(m, p, **kwargs):
                # 尝试并行下载
                if options.enable_parallel_chunk and item.file_size >= self.MIN_PARALLEL_SIZE:
                    success, err = await self.parallel_download(task, item, m, p, progress_callback=kwargs.get('progress_callback'))
                    if success: return True, p
                
                # 回退到标准下载
                success, path, _ = await telegram_client.download_media(m, p, progress_callback=kwargs.get('progress_callback'))
                return success, path

            # 进度转发回调
            def p_callback(current, total):
                item.downloaded_size = current
                item.progress = (current / total * 100) if total > 0 else 0
            
            success, result_path = await self.download_with_retry(
                task=task,
                item=item,
                download_func=core_download,
                message=msg,
                file_path=temp_path,
                progress_callback=p_callback
            )

            if success:
                 self._safe_move(temp_path, full_path)
                 item.status = DownloadStatus.COMPLETED
                 item.progress = 100.0
            else:
                 item.status = DownloadStatus.FAILED
                 # item.error 已在 download_with_retry 中设置
            
        except asyncio.CancelledError:
             item.status = DownloadStatus.PAUSED
             raise
        except Exception as e:
             logger.error(f"Download error for {item.id}: {e}")
             item.status = DownloadStatus.FAILED
             item.error = str(e)
        finally:
             await self._notify_progress(task.id, task)

    async def _sync_task_with_disk(self, task: ExportTask, export_path: Path):
        """磁盘同步逻辑"""
        for item in task.download_queue:
            p = export_path / item.file_path
            if p.exists():
                s = p.stat().st_size
                if item.file_size > 0 and s == item.file_size:
                    item.status = DownloadStatus.COMPLETED
                    item.downloaded_size = s
                    item.progress = 100.0
        self._update_task_stats(task)

    def _update_task_stats(self, task: ExportTask):
        """更新统计数据"""
        stats = {"completed": 0, "size": 0, "total": 0, "total_size": 0}
        for i in task.download_queue:
            stats["total"] += 1
            stats["total_size"] += i.file_size
            if i.status in [DownloadStatus.COMPLETED, DownloadStatus.SKIPPED]:
                stats["completed"] += 1
                stats["size"] += i.file_size
        task.downloaded_media = stats["completed"]
        task.downloaded_size = stats["size"]
        task.total_media = stats["total"]
        task.total_size = stats["total_size"]
