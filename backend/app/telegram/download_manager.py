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
        """处理任务下载队列 (v2.4.4 - 动态 Worker 池)"""
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
        
        # Worker 存储 {worker_id: asyncio.Task}
        workers: Dict[int, asyncio.Task] = {}

        async def worker_logic(worker_id: int):
            """内部工协程"""
            # 平滑启动
            async with global_start_lock:
                now = time.time()
                wait_time = max(0, self._last_global_start_time + 3 - now)
                if wait_time > 0: await asyncio.sleep(wait_time)
                self._last_global_start_time = time.time()
            
            logger.info(f"任务 {task.id[:8]}: Worker #{worker_id} 已启动")

            while True:
                if task.status == TaskStatus.CANCELLED: break
                # 动态缩容: 如果自己的 ID >= 当前最大并发数，退出
                if worker_id >= task.options.max_concurrent_downloads:
                    logger.info(f"任务 {task.id[:8]}: Worker #{worker_id} 因缩容退出")
                    break
                
                # 全局暂停等待
                while self.is_paused(task.id) and task.status != TaskStatus.CANCELLED:
                    await asyncio.sleep(1)
                if task.status == TaskStatus.CANCELLED: break

                try:
                    # 使用超时避免阻塞，便于响应并发变更
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=2.0)
                    except asyncio.TimeoutError:
                        continue  # 无任务，继续循环检查状态
                    
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
                    jitter = random.uniform(0.1, 0.3) if task.tdl_mode else random.uniform(1.0, 3.0)
                    await asyncio.sleep(jitter)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Task {task.id[:8]} Worker error: {e}")
                    await asyncio.sleep(1)

        # 5. Worker Supervisor: 动态管理 Worker 池
        def spawn_workers(target_count: int):
            """启动新 Worker 直到达到目标数量"""
            for i in range(target_count):
                if i not in workers or workers[i].done():
                    workers[i] = asyncio.create_task(worker_logic(i))
                    logger.debug(f"任务 {task.id[:8]}: 创建 Worker #{i}")

        # 初始启动
        spawn_workers(options.max_concurrent_downloads)
        
        try:
            while task.status == TaskStatus.RUNNING:
                # 动态扩容检查: 如果 max_concurrent_downloads 增加，启动新 Worker
                current_max = task.options.max_concurrent_downloads
                if len([w for w in workers.values() if not w.done()]) < current_max:
                    spawn_workers(current_max)
                
                # 队列空且无正在下载的则退出
                if queue.empty() and not any(i.status == DownloadStatus.DOWNLOADING for i in task.download_queue):
                    break
                await asyncio.sleep(2)
        finally:
            # 清理所有 Worker
            for _ in range(len(workers)): queue.put_nowait(None)
            for w in workers.values(): w.cancel()
            self._task_queues.pop(task.id, None)

    async def _download_item_worker(self, task: ExportTask, item: DownloadItem, export_path: Path):
        """核心单文件下载算法 (整合了 TDL 和常规下载)"""
        if task.status == TaskStatus.CANCELLED: return
        options = task.options

        try:
            # 1. TDL 触发逻辑
            if task.tdl_mode:
                 target_sub_dir = export_path / item.file_path
                 target_sub_dir = target_sub_dir.parent
                 target_sub_dir.mkdir(parents=True, exist_ok=True)
                 
                 # [v2.4.4] 立即将状态设为下载中，让 UI 显示正在处理
                 item.status = DownloadStatus.DOWNLOADING
                 download_start_time = time.time()
                 logger.info(f"[TDL开始] 群:{item.chat_id} | 消息:{item.message_id} | 文件:{item.file_name} | 预期大小:{item.file_size/1024/1024:.2f}MB")
                 await self._notify_progress(task.id, task)
                 
                 # [v2.4.4] 根据并发数决定下载模式
                 # 并发数=1：直接调用 TDL 单项下载，不聚合
                 # 并发数>1：使用 TDL 批量聚合器
                 if options.max_concurrent_downloads <= 1:
                     # 单项下载模式 - 直接调用 TDL
                     from ..api.tdl_integration import tdl_integration
                     url = tdl_integration.generate_telegram_link(item.chat_id, item.message_id)
                     
                     # 获取代理设置
                     proxy_url = task.proxy_url if task.proxy_enabled and task.proxy_url else None
                     
                     result = await tdl_integration.download(
                         url=url,
                         output_dir=str(target_sub_dir),
                         threads=options.download_threads,
                         limit=1,
                         proxy=proxy_url
                     )
                     
                     # 更新权限
                     self._set_777_recursive(target_sub_dir)
                     
                     # 回填下载结果
                     if result.get("success"):
                         # 查找下载的文件并更新大小
                         search_prefix = f"{item.message_id}-{abs(item.chat_id)}-"
                         try:
                             for f in target_sub_dir.iterdir():
                                 if f.name.startswith(search_prefix) and not f.name.endswith(('.temp', '.tdl', '.tmp', '.part')):
                                     if item.file_size <= 0: item.file_size = f.stat().st_size
                                     item.downloaded_size = f.stat().st_size
                                     break
                         except: pass
                         if item.file_size > 0: item.downloaded_size = item.file_size
                 else:
                     # 批量聚合模式 - 使用 tdl_batcher
                     result = await self.tdl_batcher.add_item(task, item, str(target_sub_dir), manager_inst=self)
                 
                 download_duration = time.time() - download_start_time
                 if result.get("success"):
                      item.status = DownloadStatus.COMPLETED
                      item.progress = 100.0
                      logger.info(f"[TDL完成] 群:{item.chat_id} | 消息:{item.message_id} | 文件:{item.file_name} | 大小:{item.downloaded_size/1024/1024:.2f}MB | 耗时:{download_duration:.1f}s")
                 else:
                      item.status = DownloadStatus.FAILED
                      item.error = result.get("error", "TDL 失败")
                      logger.error(f"[TDL失败] 群:{item.chat_id} | 消息:{item.message_id} | 文件:{item.file_name} | 耗时:{download_duration:.1f}s | 错误:{item.error}")
                 await self._notify_progress(task.id, task)
                 return

            # 2. 常规/并行下载逻辑 (使用重试管理)
            item.status = DownloadStatus.DOWNLOADING
            download_start_time = time.time()
            msg = await telegram_client.get_message_by_id(item.chat_id, item.message_id)
            if not msg:
                 item.status = DownloadStatus.FAILED
                 item.error = "找不到消息"
                 return
            
            # [v2.4.5] 统一下载路径: 直接下载到输出路径，使用 .temp 后缀
            # 这与 TDL 的行为保持一致，简化文件完整性检查
            full_path = export_path / item.file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = full_path.with_suffix(full_path.suffix + ".temp")
            
            # 定义下载执行函数 (供 RetryManager 调用)
            async def core_download(m, p, **kwargs):
                # 仅在用户显式开启分块下载时才使用 (v2.4.3 Fix)
                use_parallel = options.enable_parallel_chunk and options.parallel_chunk_connections > 1
                if use_parallel and item.file_size >= self.MIN_PARALLEL_SIZE:
                    success, err = await self.parallel_download(task, item, m, p, progress_callback=kwargs.get('progress_callback'))
                    if success: return True, p
                
                # 回退到标准下载
                success, path, _ = await telegram_client.download_media(m, p, progress_callback=kwargs.get('progress_callback'))
                return success, path

            # 进度转发回调 - 添加速度计算 (v2.4.3)
            last_update = {"time": time.time(), "bytes": 0}
            def p_callback(current, total):
                now = time.time()
                elapsed = now - last_update["time"]
                if elapsed > 0.5:  # 每0.5秒更新一次速度
                    bytes_diff = current - last_update["bytes"]
                    item.speed = bytes_diff / elapsed if elapsed > 0 else 0
                    last_update["time"] = now
                    last_update["bytes"] = current
                    
                    # 更新任务级总速度 (所有正在下载的 item 速度之和)
                    total_speed = sum(i.speed for i in task.download_queue if i.status == DownloadStatus.DOWNLOADING)
                    task.download_speed = total_speed
                    
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
                 # [v2.4.5] 重命名移除 .temp 后缀
                 if temp_path.exists():
                     if full_path.exists():
                         full_path.unlink()  # 删除旧文件
                     temp_path.rename(full_path)
                 item.status = DownloadStatus.COMPLETED
                 item.progress = 100.0
                 
                 # 详细下载日志 (v2.4.3)
                 download_duration = time.time() - download_start_time
                 dc_id = getattr(msg, 'dc_id', 'N/A') if hasattr(msg, 'dc_id') else (getattr(msg.media, 'dc_id', 'N/A') if msg.media else 'N/A')
                 logger.info(
                     f"[下载完成] DC:{dc_id} | 群:{item.chat_id} | 消息:{item.message_id} | "
                     f"文件:{full_path.name} | 大小:{item.file_size/1024/1024:.2f}MB | 耗时:{download_duration:.1f}s"
                 )
            else:
                 item.status = DownloadStatus.FAILED
                 download_duration = time.time() - download_start_time
                 logger.error(f"[下载失败] 群:{item.chat_id} | 消息:{item.message_id} | 文件:{item.file_name} | 耗时:{download_duration:.1f}s | 错误:{item.error}")
            
        except asyncio.CancelledError:
             item.status = DownloadStatus.PAUSED
             logger.info(f"[下载暂停] 群:{item.chat_id} | 消息:{item.message_id} | 文件:{item.file_name}")
             raise
        except Exception as e:
             logger.error(f"[下载异常] 群:{item.chat_id} | 消息:{item.message_id} | 文件:{item.file_name} | 异常:{e}")
             item.status = DownloadStatus.FAILED
             item.error = str(e)
        finally:
             await self._notify_progress(task.id, task)

    async def _sync_task_with_disk(self, task: ExportTask, export_path: Path):
        """磁盘同步逻辑 (v2.4.5 - 统一路径检查)"""
        for item in task.download_queue:
            if item.status == DownloadStatus.COMPLETED:
                continue  # 已完成的跳过
                
            # 1. 检查标准路径 (常规下载)
            standard_path = export_path / item.file_path
            if standard_path.exists() and not standard_path.name.endswith('.temp'):
                s = standard_path.stat().st_size
                # 放宽检查：文件存在且大小合理即认为完成
                if s > 0 and (item.file_size <= 0 or s >= item.file_size * 0.99):
                    item.status = DownloadStatus.COMPLETED
                    item.downloaded_size = s
                    if item.file_size <= 0: item.file_size = s
                    item.progress = 100.0
                    continue
            
            # 2. 检查 TDL 命名格式 (TDL 下载)
            # TDL 格式: {message_id}-{chat_id}-{filename}
            parent_dir = standard_path.parent
            if parent_dir.exists():
                search_prefix = f"{item.message_id}-{abs(item.chat_id)}-"
                try:
                    for f in parent_dir.iterdir():
                        if f.name.startswith(search_prefix) and not f.name.endswith(('.temp', '.tdl', '.tmp', '.part')):
                            s = f.stat().st_size
                            if s > 0 and (item.file_size <= 0 or s >= item.file_size * 0.99):
                                item.status = DownloadStatus.COMPLETED
                                item.downloaded_size = s
                                if item.file_size <= 0: item.file_size = s
                                item.progress = 100.0
                                break
                except: pass
        
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

    async def adjust_task_concurrency(
        self, 
        task_id: str, 
        max_concurrent: Optional[int] = None,
        download_threads: Optional[int] = None,
        parallel_chunk: Optional[int] = None
    ) -> bool:
        """运行中动态调整任务并发设置 (v2.4.1)"""
        task = self.get_task(task_id)
        if not task: return False
        
        options = task.options
        changed = False
        
        if max_concurrent is not None:
            options.max_concurrent_downloads = max(1, min(20, max_concurrent))
            task.current_max_concurrent_downloads = options.max_concurrent_downloads
            # 同步更新全局连接池限制
            telegram_client.set_max_concurrent_transmissions(options.max_concurrent_downloads)
            
            # 动态调整信号量 (Adaptive Scaling)
            if task_id in self._parallel_semaphores:
                chunk_multiplier = 3 if options.enable_parallel_chunk else 1
                new_limit = min(30, max(8, options.max_concurrent_downloads * chunk_multiplier))
                # 注意：Python 的 Semaphore 不支持直接修改 _value，这里我们通过创建一个新的信号量来实现
                # 这在异步环境下是安全的，因为后续 worker 会获取新的信号量
                self._parallel_semaphores[task_id] = asyncio.Semaphore(new_limit)
            
            # 如果管线空了且并发数增加，尝试重新填充
            if task.status == TaskStatus.RUNNING:
                self.refill_task_queue(task)
            changed = True
            
        if download_threads is not None:
            options.download_threads = max(1, min(20, download_threads))
            changed = True
            
        if parallel_chunk is not None:
            options.parallel_chunk_connections = max(1, min(8, parallel_chunk))
            options.enable_parallel_chunk = parallel_chunk > 1
            changed = True
            
        if changed:
            self._save_tasks()
            await self._notify_progress(task_id, task)
            logger.info(f"任务 {task_id[:8]} 并发配置已更新: 并发={options.max_concurrent_downloads}, 分块={options.parallel_chunk_connections}")
            return True
        return False
