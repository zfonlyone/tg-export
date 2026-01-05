import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from ..models import (
    ExportTask, ExportOptions, DownloadItem, DownloadStatus
)

logger = logging.getLogger(__name__)

class TDLBatcher:
    """TDL 批量请求聚合器 (v1.6.9)
    
    用于将多个 Worker 的 TDL 下载请求按目录聚合，
    从而利用 TDL 的多连接并发能力，同时规避 Session 冲突。
    """
    def __init__(self):
        self._queue = asyncio.Queue()
        # key: (task_id, target_sub_dir) -> List[Tuple[DownloadItem, asyncio.Future]]
        self._active_batches = {}
        self._loop_task = None
        
    async def add_item(self, task: ExportTask, item: DownloadItem, target_sub_dir: str, manager_inst=None):
        """提交一个下载项到批量器 (v1.6.9)"""
        if not self._loop_task or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._batch_loop())
            
        future = asyncio.Future()
        await self._queue.put((task, item, target_sub_dir, future, manager_inst))
        return await future

    async def _batch_loop(self):
        """批量聚合循环"""
        try:
            while True:
                # 等待第一个项进入
                task, item, target_sub_dir, future, manager_inst = await self._queue.get()
                batch_key = (task.id, target_sub_dir)
                
                if batch_key not in self._active_batches:
                    self._active_batches[batch_key] = []
                    # 启动定时刷新
                    asyncio.create_task(self._trigger_batch_after_delay(batch_key, task.options, manager_inst))
                
                self._active_batches[batch_key].append((item, future))
        except asyncio.CancelledError:
            pass

    async def _trigger_batch_after_delay(self, batch_key, options: ExportOptions, manager_inst):
        """等到一小段时间后执行批量下载 (v2.4.7 - 增加暂停检查)"""
        # 动态聚合延迟：如果任务量大，可以稍微等久一点点
        await asyncio.sleep(0.3) 
        
        batch = self._active_batches.pop(batch_key, [])
        if not batch: return
        
        # 延迟导入以避免循环依赖
        from ..api.tdl_integration import tdl_integration
        task_id, target_sub_dir = batch_key
        
        # [v2.4.7] 检查任务是否已暂停，如果暂停则取消批量下载
        if manager_inst and manager_inst.is_paused(task_id):
            logger.info(f"任务 {task_id[:8]}: [TDLBatcher] 任务已暂停，取消批量下载")
            for it, fut in batch:
                if not fut.done():
                    it.status = DownloadStatus.WAITING
                    fut.set_result({"success": False, "error": "任务已暂停", "output": ""})
            return
        
        # 提取 URL 列表
        urls = [tdl_integration.generate_telegram_link(it.chat_id, it.message_id) for it, fut in batch]
        
        if len(urls) > 1:
            logger.info(f"任务 {task_id[:8]}: [TDLBatcher] 聚合了 {len(urls)} 个下载项到目录: {target_sub_dir}")
        
        # [v2.3.1] 完善异常捕获，防止 Worker 卡死
        try:
            # 获取代理设置
            proxy_url = None
            try:
                task_obj = manager_inst.get_task(task_id) if manager_inst else None
                if task_obj and task_obj.proxy_enabled and task_obj.proxy_url:
                    proxy_url = task_obj.proxy_url
            except:
                pass
            
            # [v2.3.1] 启动磁盘嗅探监视器 (每 10 秒刷新一次进度)
            monitor_stop_event = asyncio.Event()
            asyncio.create_task(self._monitor_temp_files(batch, target_sub_dir, monitor_stop_event, task_id, manager_inst))
            
            try:
                # [v2.3.2] 统一权限与路径纠偏
                # 批量下载完成后，立即对该子目录执行递归 777
                if manager_inst:
                    manager_inst._set_777_recursive(Path(target_sub_dir))
                
                result = await tdl_integration.download(
                    url=urls,
                    output_dir=target_sub_dir,
                    threads=options.download_threads,
                    limit=len(urls),
                    proxy=proxy_url
                )
            finally:
                # 下载结束（无论成功失败），通知监视器停止
                monitor_stop_event.set()
                # 批量完成后再次刷新权限，确保新产生文件的所有权
                if manager_inst:
                    manager_inst._set_777_recursive(Path(target_sub_dir))
            
            # 分发结果给所有等待的 Worker
            for it, fut in batch:
                if not fut.done():
                    # [CRITICAL FIX] 确权信号与真实路径回填 (批量版)
                    if result.get("success"):
                        it.status = DownloadStatus.COMPLETED
                        it.progress = 100.0
                        
                        # 检测路径并回填 (解决 99% 卡死)
                        sub_path = Path(target_sub_dir)
                        search_prefix = f"{it.message_id}-{abs(it.chat_id)}-"
                        try:
                            # 遍历目录进行回填
                            for f in sub_path.iterdir():
                                if f.name.startswith(search_prefix) and not f.name.endswith(('.temp', '.tdl', '.tmp', '.part')):
                                    # 找到了真实落地文件，更新下载大小
                                    if it.file_size <= 0: it.file_size = f.stat().st_size
                                    it.downloaded_size = f.stat().st_size
                                    break
                        except:
                            pass
                        
                        if it.file_size > 0: it.downloaded_size = it.file_size
                    fut.set_result(result)
        except Exception as e:
            logger.exception(f"任务 {task_id[:8]}: [TDLBatcher] 批量下载发生致命错误")
            # [CRITICAL] 必须释放所有 Future，否则 Worker 永远卡死在下载中
            for it, fut in batch:
                if not fut.done():
                    fut.set_result({"success": False, "error": f"批量执行异常: {str(e)}", "output": ""})
        finally:
            # [Robustness] 确保所有 future 都有结果，这是最后一道防线
            for it, fut in batch:
                if not fut.done():
                    fut.set_result({"success": False, "error": "批量任务异常中止", "output": ""})

    async def _monitor_temp_files(self, batch, target_sub_dir: str, stop_event: asyncio.Event, task_id: str, manager_inst=None):
        """磁盘嗅探监视器 (v2.4.6 - 增强匹配逻辑)"""
        sub_path = Path(target_sub_dir)
        logger.info(f"任务 {task_id[:8]}: [磁盘嗅探] 开始监控目录: {target_sub_dir}")
        
        # 缩短监控间隔以提高进度更新频率
        monitor_interval = 3.0  # 每 3 秒检查一次
        
        while not stop_event.is_set():
            try:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=monitor_interval)
                    break 
                except asyncio.TimeoutError:
                    pass
                
                if not sub_path.exists():
                    continue
                
                # [v2.4.6] 增强的临时文件匹配：遍历目录中所有文件
                all_files = []
                try:
                    all_files = list(sub_path.iterdir())
                except:
                    continue
                
                updated_count = 0
                for it, fut in batch:
                    if it.status != DownloadStatus.DOWNLOADING:
                        continue
                    
                    # [v2.4.6] 增强匹配逻辑：支持多种临时文件命名模式
                    # TDL 可能的文件模式：
                    # 1. {message_id}-{chat_id}-{filename}.temp
                    # 2. {message_id}-{chat_id}-{filename}.tdl
                    # 3. {message_id}-{chat_id}-{filename} (正在写入)
                    # 4. 其他包含 message_id 的文件
                    found = False
                    prefix = f"{it.message_id}-"
                    alt_prefix = f"{it.message_id}_{abs(it.chat_id)}"  # 备选格式
                    
                    for f in all_files:
                        fname = f.name
                        # 匹配以 message_id- 开头的文件（包括临时文件和正在写入的目标文件）
                        if fname.startswith(prefix) or fname.startswith(alt_prefix):
                            try:
                                current_size = f.stat().st_size
                                # 判断是否为临时文件
                                is_temp = any(fname.endswith(ext) for ext in ['.temp', '.tdl', '.tmp', '.part', '.downloading'])
                                
                                if it.file_size > 0:
                                    it.downloaded_size = current_size
                                    # 临时文件进度最高 99.9%，完成文件才能 100%
                                    if is_temp:
                                        it.progress = min(99.9, (current_size / it.file_size) * 100.0)
                                    else:
                                        # 非临时文件且大小接近期望值，可能已完成
                                        if current_size >= it.file_size * 0.99:
                                            it.progress = 100.0
                                        else:
                                            it.progress = (current_size / it.file_size) * 100.0
                                    updated_count += 1
                                    found = True
                            except: 
                                pass
                            break  # 找到匹配后退出内层循环
                    
                    # 容错：如果找不到匹配文件但有 file_path，尝试直接检查目标文件
                    if not found and it.file_path:
                        f_path = sub_path / Path(it.file_path).name
                        if f_path.exists():
                            try:
                                current_size = f_path.stat().st_size
                                if it.file_size > 0:
                                    it.downloaded_size = current_size
                                    it.progress = min(99.9, (current_size / it.file_size) * 100.0)
                                    updated_count += 1
                            except: 
                                pass

                # [v2.4.6] 始终尝试通知进度，确保 UI 更新
                # 即使 updated_count 为 0，也定期发送心跳以保持 UI 活跃
                if manager_inst:
                    task = manager_inst.get_task(task_id)
                    if task:
                        # 核心：必须更新任务总计统计，否则 UI 上的总进度条不动
                        if hasattr(manager_inst, '_update_task_stats'):
                            manager_inst._update_task_stats(task)
                        await manager_inst._notify_progress(task_id, task)
                        
            except Exception as e:
                logger.error(f"[磁盘嗅探] 核心循环出错: {e}")
                await asyncio.sleep(5)

