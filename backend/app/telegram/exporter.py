import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Union

from .exporter_base import ExporterBase
from .task_manager import TaskManagerMixin
from .queue_manager import QueueManagerMixin
from .download_manager import DownloadManagerMixin
from .retry_manager import RetryManagerMixin
from .parallel_downloader import ParallelDownloaderMixin

logger = logging.getLogger(__name__)

class ExportManager(ExporterBase, TaskManagerMixin, DownloadManagerMixin, QueueManagerMixin, RetryManagerMixin, ParallelDownloaderMixin):
    """
    导出管理器 (v2.3.4 Refactored)
    采用 Mixin 架构，将功能拆分为：
    - ExporterBase: 基础状态与实用工具
    - TaskManagerMixin: 任务生命周期与消息扫描
    - DownloadManagerMixin: 下载引擎逻辑
    - QueueManagerMixin: 队列展示与细粒度控制
    """
    
    def __init__(self):
        # 显式初始化所有父类
        ExporterBase.__init__(self)
        
        self._needs_save = False
        self._save_lock = asyncio.Lock()
        
        # 加载历史任务
        self._load_tasks()
        
        logger.info("✅ ExportManager (Refactored) 初始化完成")

    async def _notify_progress(self, task_id: str, task: Any):
        """通知进度回调"""
        if task_id in self._progress_callbacks:
            for callback in self._progress_callbacks[task_id]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(task)
                    else:
                        callback(task)
                except Exception as e:
                    logger.error(f"通知回调失败: {e}")
        
        self._needs_save = True

    def add_progress_callback(self, task_id: str, callback: callable):
        """添加进度回调"""
        if task_id not in self._progress_callbacks:
            self._progress_callbacks[task_id] = []
        self._progress_callbacks[task_id].append(callback)

    def get_task(self, task_id: str) -> Optional[Any]:
        """获取任务"""
        return self.tasks.get(task_id)

    def get_all_tasks(self) -> List[Any]:
        """获取所有任务列表"""
        return list(self.tasks.values())
        
# 全局导出管理器实例
export_manager = ExportManager()
