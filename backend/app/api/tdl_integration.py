"""
TDL Integration Module - 使用 TDL 工具下载 Telegram 文件
支持文件监控进度追踪
"""
import os
import asyncio
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class TDLDownloadStatus(str, Enum):
    """TDL 下载状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TDLDownloadItem:
    """TDL 下载项"""
    item_id: str              # 下载项 ID (chat_id_msg_id)
    url: str                  # Telegram 链接
    file_name: str            # 文件名
    file_size: int            # 预期文件大小
    output_path: str          # 输出文件路径
    status: TDLDownloadStatus = TDLDownloadStatus.PENDING
    downloaded_size: int = 0  # 已下载大小
    progress: float = 0.0     # 下载进度 (0-100)
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class TDLBatchTask:
    """TDL 批量下载任务"""
    task_id: str
    items: List[TDLDownloadItem] = field(default_factory=list)
    status: TDLDownloadStatus = TDLDownloadStatus.PENDING
    process: Optional[asyncio.subprocess.Process] = None
    monitor_task: Optional[asyncio.Task] = None
    output_dir: str = "/downloads"
    threads: int = 4
    limit: int = 2
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TDLIntegration:
    """TDL 集成服务 - 支持文件监控进度追踪"""
    
    def __init__(self):
        self.container_name = os.environ.get("TDL_CONTAINER_NAME", "tdl")
        self.batch_tasks: Dict[str, TDLBatchTask] = {}
        self._monitor_interval = 1.0  # 文件监控间隔 (秒)
        self._check_docker_available()
    
    def _check_docker_available(self) -> bool:
        """检查 Docker 是否可用"""
        try:
            result = subprocess.run(
                ["docker", "version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                logger.warning(f"Docker 命令失败: {result.stderr}")
            return result.returncode == 0
        except FileNotFoundError:
            logger.warning("Docker 命令未找到，请确保 Docker socket 已挂载")
            return False
        except Exception as e:
            logger.warning(f"Docker 不可用: {e}")
            return False
    
    def _check_container_running(self) -> tuple:
        """检查 TDL 容器是否运行中，返回 (是否运行, 错误信息)"""
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", self.container_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                error_msg = result.stderr.strip()
                if "No such object" in error_msg:
                    return False, f"容器 '{self.container_name}' 不存在"
                return False, error_msg
            
            is_running = result.stdout.strip() == "true"
            return is_running, None if is_running else "容器未运行"
        except Exception as e:
            return False, str(e)
    
    def get_status(self) -> Dict[str, Any]:
        """获取 TDL 状态"""
        docker_available = self._check_docker_available()
        
        container_running = False
        container_error = None
        
        if docker_available:
            container_running, container_error = self._check_container_running()
        else:
            container_error = "Docker 不可用，请检查 /var/run/docker.sock 是否已挂载"
        
        active_tasks = [t for t in self.batch_tasks.values() 
                       if t.status == TDLDownloadStatus.RUNNING]
        
        return {
            "docker_available": docker_available,
            "container_name": self.container_name,
            "container_running": container_running,
            "container_error": container_error,
            "active_tasks": len(active_tasks),
            "total_tasks": len(self.batch_tasks)
        }
    
    def generate_telegram_link(self, chat_id: int, message_id: int) -> str:
        """
        生成 Telegram 消息链接
        
        对于私有频道/群组，chat_id 通常是负数，需要转换
        例如: chat_id = -1001234567890 -> https://t.me/c/1234567890/123
        """
        if chat_id < 0:
            clean_id = str(abs(chat_id))
            if clean_id.startswith("100"):
                clean_id = clean_id[3:]
            return f"https://t.me/c/{clean_id}/{message_id}"
        else:
            return f"https://t.me/c/{chat_id}/{message_id}"
    
    def _get_file_size(self, file_path: str) -> int:
        """获取文件大小 (通过 docker exec)"""
        try:
            result = subprocess.run(
                ["docker", "exec", self.container_name, "stat", "-c", "%s", file_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except Exception:
            pass
        return 0
    
    def _check_file_exists(self, file_path: str) -> bool:
        """检查文件是否存在"""
        try:
            result = subprocess.run(
                ["docker", "exec", self.container_name, "test", "-f", file_path],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    async def _monitor_download_progress(self, batch_task: TDLBatchTask):
        """监控下载进度 (通过文件大小变化)"""
        logger.info(f"开始监控下载进度: {batch_task.task_id}")
        
        while batch_task.status == TDLDownloadStatus.RUNNING:
            try:
                all_completed = True
                
                for item in batch_task.items:
                    if item.status in [TDLDownloadStatus.COMPLETED, TDLDownloadStatus.FAILED]:
                        continue
                    
                    all_completed = False
                    
                    # 检查文件是否存在
                    if self._check_file_exists(item.output_path):
                        current_size = self._get_file_size(item.output_path)
                        item.downloaded_size = current_size
                        
                        if item.file_size > 0:
                            item.progress = min(100.0, (current_size / item.file_size) * 100)
                        
                        # 标记为运行中
                        if item.status == TDLDownloadStatus.PENDING:
                            item.status = TDLDownloadStatus.RUNNING
                            item.started_at = datetime.now()
                        
                        # 检查是否下载完成
                        if item.file_size > 0 and current_size >= item.file_size:
                            item.status = TDLDownloadStatus.COMPLETED
                            item.progress = 100.0
                            item.completed_at = datetime.now()
                            logger.info(f"文件下载完成: {item.file_name}")
                
                if all_completed:
                    batch_task.status = TDLDownloadStatus.COMPLETED
                    batch_task.completed_at = datetime.now()
                    logger.info(f"批量任务完成: {batch_task.task_id}")
                    break
                
                await asyncio.sleep(self._monitor_interval)
                
            except asyncio.CancelledError:
                logger.info(f"监控任务被取消: {batch_task.task_id}")
                break
            except Exception as e:
                logger.error(f"监控下载进度出错: {e}")
                await asyncio.sleep(self._monitor_interval)
    
    async def start_batch_download(
        self,
        task_id: str,
        items: List[Dict[str, Any]],
        output_dir: str = "/downloads",
        threads: int = 4,
        limit: int = 2,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        启动批量下载任务 (后台运行 + 文件监控)
        
        Args:
            task_id: 任务 ID
            items: 下载项列表，每项需包含 {id, url, file_name, file_size}
            output_dir: 输出目录
            threads: 下载线程数 (-t)
            limit: 最大并发数 (-l)
            progress_callback: 进度回调函数
        
        Returns:
            启动结果
        """
        if not self._check_container_running():
            return {
                "success": False,
                "error": f"TDL 容器 '{self.container_name}' 未运行"
            }
        
        if not items:
            return {"success": False, "error": "下载项列表为空"}
        
        # 创建批量任务
        download_items = []
        urls = []
        
        for item_data in items:
            output_path = f"{output_dir}/{item_data.get('file_name', 'unknown')}"
            
            download_item = TDLDownloadItem(
                item_id=item_data.get("id", ""),
                url=item_data.get("url", ""),
                file_name=item_data.get("file_name", "unknown"),
                file_size=item_data.get("file_size", 0),
                output_path=output_path
            )
            download_items.append(download_item)
            urls.append(download_item.url)
        
        batch_task = TDLBatchTask(
            task_id=task_id,
            items=download_items,
            output_dir=output_dir,
            threads=threads,
            limit=limit,
            started_at=datetime.now()
        )
        
        # 构建命令
        cmd = [
            "docker", "exec", self.container_name,
            "tdl", "dl",
            "-d", output_dir,
            "-t", str(threads),
            "-l", str(limit)
        ]
        
        for url in urls:
            cmd.extend(["-u", url])
        
        logger.info(f"启动 TDL 批量下载: {len(urls)} 个文件, 并发={limit}, 线程={threads}")
        
        try:
            # 后台启动下载进程
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            batch_task.process = process
            batch_task.status = TDLDownloadStatus.RUNNING
            self.batch_tasks[task_id] = batch_task
            
            # 启动文件监控任务
            batch_task.monitor_task = asyncio.create_task(
                self._monitor_download_progress(batch_task)
            )
            
            # 同时监控进程结束
            asyncio.create_task(self._wait_process_complete(batch_task))
            
            return {
                "success": True,
                "task_id": task_id,
                "count": len(urls),
                "message": f"已启动 TDL 下载: {len(urls)} 个文件"
            }
            
        except Exception as e:
            logger.exception(f"启动 TDL 下载失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _wait_process_complete(self, batch_task: TDLBatchTask):
        """等待进程完成"""
        if batch_task.process:
            try:
                stdout, stderr = await batch_task.process.communicate()
                
                if batch_task.process.returncode == 0:
                    logger.info(f"TDL 进程正常结束: {batch_task.task_id}")
                    # 标记所有未完成的项为完成
                    for item in batch_task.items:
                        if item.status == TDLDownloadStatus.RUNNING:
                            item.status = TDLDownloadStatus.COMPLETED
                            item.progress = 100.0
                            item.completed_at = datetime.now()
                else:
                    error_msg = stderr.decode() if stderr else f"Exit code: {batch_task.process.returncode}"
                    logger.error(f"TDL 进程异常结束: {error_msg}")
                    # 标记未完成项为失败
                    for item in batch_task.items:
                        if item.status not in [TDLDownloadStatus.COMPLETED]:
                            item.status = TDLDownloadStatus.FAILED
                            item.error = error_msg
                
                batch_task.status = TDLDownloadStatus.COMPLETED
                batch_task.completed_at = datetime.now()
                
                # 取消监控任务
                if batch_task.monitor_task:
                    batch_task.monitor_task.cancel()
                    
            except Exception as e:
                logger.error(f"等待进程完成出错: {e}")
    
    def get_batch_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取批量任务状态"""
        task = self.batch_tasks.get(task_id)
        if not task:
            return None
        
        items_status = []
        for item in task.items:
            items_status.append({
                "id": item.item_id,
                "file_name": item.file_name,
                "file_size": item.file_size,
                "downloaded_size": item.downloaded_size,
                "progress": item.progress,
                "status": item.status.value,
                "error": item.error
            })
        
        return {
            "task_id": task_id,
            "status": task.status.value,
            "items": items_status,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None
        }
    
    async def cancel_batch_task(self, task_id: str) -> bool:
        """取消批量任务"""
        task = self.batch_tasks.get(task_id)
        if not task:
            return False
        
        if task.process:
            task.process.terminate()
        
        if task.monitor_task:
            task.monitor_task.cancel()
        
        task.status = TDLDownloadStatus.FAILED
        
        for item in task.items:
            if item.status == TDLDownloadStatus.RUNNING:
                item.status = TDLDownloadStatus.FAILED
                item.error = "任务已取消"
        
        return True
    
    # ===== 兼容旧 API =====
    
    async def download(
        self,
        url: str,
        output_dir: str = "/downloads",
        threads: int = 4,
        limit: int = 2
    ) -> Dict[str, Any]:
        """使用 TDL 下载单个文件 (同步等待)"""
        if not self._check_container_running():
            return {
                "success": False,
                "error": f"TDL 容器 '{self.container_name}' 未运行"
            }
        
        cmd = [
            "docker", "exec", self.container_name,
            "tdl", "dl",
            "-u", url,
            "-d", output_dir,
            "-t", str(threads),
            "-l", str(limit)
        ]
        
        logger.info(f"执行 TDL 下载: {' '.join(cmd)}")
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return {"success": True, "url": url, "output": stdout.decode() if stdout else ""}
            else:
                error_msg = stderr.decode() if stderr else f"Exit code: {process.returncode}"
                return {"success": False, "url": url, "error": error_msg}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def batch_download(
        self,
        urls: List[str],
        output_dir: str = "/downloads",
        threads: int = 4,
        limit: int = 2
    ) -> Dict[str, Any]:
        """批量下载 (同步等待)"""
        if not urls:
            return {"success": False, "error": "URL 列表为空"}
        
        if not self._check_container_running():
            return {
                "success": False,
                "error": f"TDL 容器 '{self.container_name}' 未运行"
            }
        
        cmd = [
            "docker", "exec", self.container_name,
            "tdl", "dl",
            "-d", output_dir,
            "-t", str(threads),
            "-l", str(limit)
        ]
        
        for url in urls:
            cmd.extend(["-u", url])
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return {"success": True, "count": len(urls), "output": stdout.decode() if stdout else ""}
            else:
                error_msg = stderr.decode() if stderr else f"Exit code: {process.returncode}"
                return {"success": False, "count": len(urls), "error": error_msg}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def download_by_message(
        self,
        chat_id: int,
        message_id: int,
        output_dir: str = "/downloads"
    ) -> Dict[str, Any]:
        """通过消息 ID 下载"""
        url = self.generate_telegram_link(chat_id, message_id)
        return await self.download(url, output_dir)


# 全局实例
tdl_integration = TDLIntegration()
