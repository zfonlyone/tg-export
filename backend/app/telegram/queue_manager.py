import asyncio
import logging
from typing import Dict, List, Optional, Any, Set, Union
from pathlib import Path

from ..models import (
    ExportTask, ExportOptions, TaskStatus, DownloadItem, DownloadStatus
)

logger = logging.getLogger(__name__)

class QueueManagerMixin:
    """队列维护逻辑 Mixin (Maintainer)"""

    def enqueue_item(self, task: ExportTask, item: DownloadItem):
        """
        生产者的入口：将新项目存入维护列表，并视情况推入运行队列
        (v2.3.5) 实现生产-维护-消费分离
        """
        # 1. 确保项目状态为等待中
        if item.status == DownloadStatus.WAITING:
             # 可以根据需要在这里处理重复检查等逻辑
             pass
        
        # 2. 如果项目不在持久化列表中，则添加
        if not any(it.id == item.id for it in task.download_queue):
            task.download_queue.append(item)
            logger.debug(f"项目 {item.id} 已进入待处理池 (WAITING)")

        # 3. 维护者逻辑：只有任务正在运行时，才推送到运行中的下载队列 (Consumer 管线)
        if task.status == TaskStatus.RUNNING and task.id in self._task_queues:
            self._task_queues[task.id].put_nowait(item)
            logger.debug(f"维护者：由于任务运行中，已将项目 {item.id} 推送至下载管线")
        else:
            logger.debug(f"维护者：任务未运行 (当前状态: {task.status})，项目 {item.id} 在池中等待")

    def refill_task_queue(self, task: ExportTask):
        """
        维护者逻辑：从待处理池中提取所有 WAITING 项目，填入下载管线
        通常在任务启动或从暂停恢复时调用
        """
        queue = self._task_queues.get(task.id)
        if not queue:
            logger.warning(f"任务 {task.id[:8]} 没有活跃的下载管线")
            return
            
        count = 0
        # 排序：重试优先，然后按消息 ID
        pending_items = sorted(
            [i for i in task.download_queue if i.status in [DownloadStatus.WAITING, DownloadStatus.PAUSED, DownloadStatus.FAILED]],
            key=lambda x: (not getattr(x, 'is_retry', False), x.message_id)
        )
        
        for item in pending_items:
            # 重置状态
            if not item.is_manually_paused:
                item.status = DownloadStatus.WAITING
                queue.put_nowait(item)
                count += 1
        
        logger.info(f"维护者：已为任务 {task.id[:8]} 重新填充下载管线 (项数: {count})")

    def get_download_queue(self, task_id: str, limit: int = 20, reversed_order: bool = False) -> Dict[str, Any]:
        """获取任务的分段下载队列 (v1.6.7)"""
        task = self.get_task(task_id) # 假设主类有 get_task
        if not task:
            return {
                "downloading": [], "waiting": [], "failed": [], "completed": [],
                "counts": {"active": 0, "waiting": 0, "failed": 0, "completed": 0}
            }
        
        # 活动中: 包含正在下载、已暂停 (手动)、以及[有进度的等待中项]
        all_active = [i for i in task.download_queue if i.status in [DownloadStatus.DOWNLOADING, DownloadStatus.PAUSED] or (i.status == DownloadStatus.WAITING and i.progress > 0)]
        
        # 等待中: 状态为等待且进度为 0 的项
        all_waiting = [i for i in task.download_queue if i.status == DownloadStatus.WAITING and i.progress <= 0]
        
        all_failed = [i for i in task.download_queue if i.status == DownloadStatus.FAILED]
        all_completed = [i for i in task.download_queue if i.status in [DownloadStatus.COMPLETED, DownloadStatus.SKIPPED]]
        
        # 排序
        if reversed_order:
            all_active.sort(key=lambda x: x.message_id, reverse=True)
            all_waiting.sort(key=lambda x: (x.media_type, x.message_id), reverse=True)
            all_failed.sort(key=lambda x: x.message_id, reverse=True)
            all_completed.sort(key=lambda x: x.message_id, reverse=True)
        else:
            all_active.sort(key=lambda x: x.message_id)
            all_waiting.sort(key=lambda x: (x.media_type, x.message_id))
            all_failed.sort(key=lambda x: x.message_id)
            all_completed.sort(key=lambda x: x.message_id)

        res_limit = limit if limit > 0 else 999999
        
        # 统计当前活跃线程 (真正处于 DOWNLOADING 状态的)
        active_threads = len([i for i in all_active if i.status == DownloadStatus.DOWNLOADING])

        return {
            "downloading": all_active[:res_limit], 
            "waiting": all_waiting[:res_limit],
            "failed": all_failed[:res_limit],
            "completed": all_completed[:res_limit],
            "counts": {
                "active": len(all_active),
                "waiting": len(all_waiting),
                "failed": len(all_failed),
                "completed": len(all_completed)
            },
            "current_concurrency": task.current_max_concurrent_downloads or task.options.max_concurrent_downloads,
            "active_threads": active_threads
        }

    async def pause_download_item(self, task_id: str, item_id: str) -> bool:
        """暂停单个下载项"""
        task = self.get_task(task_id)
        if not task: return False
        
        item = task.get_download_item_by_full_id(item_id) if hasattr(task, 'get_download_item_by_full_id') else None
        # 如果模型里没有这个方法，我们在 ExportTask 中补一个，或者这里手动找
        if not item:
            for it in task.download_queue:
                if it.id == item_id:
                    item = it; break
        
        if not item: return False
        
        item.status = DownloadStatus.PAUSED
        item.is_manually_paused = True
        
        # 找到对应的 Worker 并取消 (如果在下载的话)
        if task_id in self._item_to_worker and item_id in self._item_to_worker[task_id]:
            worker_task = self._item_to_worker[task_id][item_id]
            if not worker_task.done():
                worker_task.cancel()
        
        await self._notify_progress(task_id, task)
        return True

    async def resume_download_item(self, task_id: str, item_id: str) -> bool:
        """恢复单个下载项"""
        task = self.get_task(task_id)
        if not task: return False
        
        item = None
        for it in task.download_queue:
            if it.id == item_id:
                item = it; break
        if not item: return False
        
        item.status = DownloadStatus.WAITING
        item.is_manually_paused = False
        item.resume_timestamp = asyncio.get_event_loop().time()
        
        # [Refinement] 维护者：如果任务正在运行，推送到管线
        self.enqueue_item(task, item)
        
        if task.status == TaskStatus.COMPLETED:
            task.status = TaskStatus.RUNNING
            if task_id not in self._running_tasks:
                asyncio.create_task(self.start_export(task_id))
        
        await self._notify_progress(task_id, task)
        return True

    async def retry_file(self, task_id: str, item_id: str) -> bool:
        """重试单个文件"""
        task = self.get_task(task_id)
        if not task: return False
        
        item = None
        for it in task.download_queue:
            if it.id == item_id:
                item = it; break
        if not item: return False
        
        item.status = DownloadStatus.WAITING
        item.is_retry = True
        item.downloaded_size = 0
        item.progress = 0
        item.error = None
        
        # [Refinement] 维护者：填入管线
        self.enqueue_item(task, item)
        
        if task.status == TaskStatus.COMPLETED:
            task.status = TaskStatus.RUNNING
            if task_id not in self._running_tasks:
                asyncio.create_task(self.start_export(task_id))
                
        await self._notify_progress(task_id, task)
        return True

    async def cancel_download_item(self, task_id: str, item_id: str) -> bool:
        """取消 (跳过) 单个下载项"""
        task = self.get_task(task_id)
        if not task: return False
        
        item = None
        for it in task.download_queue:
            if it.id == item_id:
                item = it; break
        if not item: return False
        
        item.status = DownloadStatus.SKIPPED
        if task_id in self._item_to_worker and item_id in self._item_to_worker[task_id]:
            worker_task = self._item_to_worker[task_id][item_id]
            if not worker_task.done():
                worker_task.cancel()
                
        await self._notify_progress(task_id, task)
        return True
