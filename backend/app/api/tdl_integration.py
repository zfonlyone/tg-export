"""
TDL Integration Module - 使用 TDL 工具下载 Telegram 文件
"""
import os
import asyncio
import logging
import subprocess
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TDLDownloadStatus(str, Enum):
    """TDL 下载状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TDLDownloadTask:
    """TDL 下载任务"""
    task_id: str
    url: str
    output_dir: str
    status: TDLDownloadStatus = TDLDownloadStatus.PENDING
    error: Optional[str] = None
    progress: float = 0.0


class TDLIntegration:
    """TDL 集成服务"""
    
    def __init__(self):
        self.container_name = os.environ.get("TDL_CONTAINER_NAME", "tdl")
        self.download_tasks: Dict[str, TDLDownloadTask] = {}
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
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"Docker 不可用: {e}")
            return False
    
    def _check_container_running(self) -> bool:
        """检查 TDL 容器是否运行中"""
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", self.container_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout.strip() == "true"
        except Exception as e:
            logger.warning(f"检查容器状态失败: {e}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """获取 TDL 状态"""
        docker_available = self._check_docker_available()
        container_running = self._check_container_running() if docker_available else False
        
        return {
            "docker_available": docker_available,
            "container_name": self.container_name,
            "container_running": container_running,
            "active_tasks": len([t for t in self.download_tasks.values() 
                               if t.status == TDLDownloadStatus.RUNNING])
        }
    
    def generate_telegram_link(self, chat_id: int, message_id: int) -> str:
        """
        生成 Telegram 消息链接
        
        对于私有频道/群组，chat_id 通常是负数，需要转换
        例如: chat_id = -1001234567890 -> https://t.me/c/1234567890/123
        """
        # 私有频道/群组的 chat_id 格式: -100XXXXXXXXXX
        if chat_id < 0:
            # 移除 -100 前缀
            clean_id = str(abs(chat_id))
            if clean_id.startswith("100"):
                clean_id = clean_id[3:]
            return f"https://t.me/c/{clean_id}/{message_id}"
        else:
            # 公开频道/用户
            return f"https://t.me/c/{chat_id}/{message_id}"
    
    async def download(
        self,
        url: str,
        output_dir: str = "/downloads",
        threads: int = 4,
        limit: int = 2
    ) -> Dict[str, Any]:
        """
        使用 TDL 下载文件
        
        Args:
            url: Telegram 消息链接
            output_dir: 输出目录 (TDL 容器内路径)
            threads: 下载线程数
            limit: 最大并发数
        
        Returns:
            下载结果
        """
        if not self._check_container_running():
            return {
                "success": False,
                "error": f"TDL 容器 '{self.container_name}' 未运行"
            }
        
        try:
            # 构建 docker exec 命令
            cmd = [
                "docker", "exec", self.container_name,
                "tdl", "dl",
                "-u", url,
                "-d", output_dir,
                "-t", str(threads),
                "-l", str(limit)
            ]
            
            logger.info(f"执行 TDL 下载: {' '.join(cmd)}")
            
            # 异步执行命令
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"TDL 下载成功: {url}")
                return {
                    "success": True,
                    "url": url,
                    "output": stdout.decode() if stdout else ""
                }
            else:
                error_msg = stderr.decode() if stderr else f"Exit code: {process.returncode}"
                logger.error(f"TDL 下载失败: {error_msg}")
                return {
                    "success": False,
                    "url": url,
                    "error": error_msg
                }
                
        except asyncio.TimeoutError:
            return {"success": False, "error": "下载超时"}
        except Exception as e:
            logger.exception(f"TDL 下载异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def batch_download(
        self,
        urls: List[str],
        output_dir: str = "/downloads",
        threads: int = 4,
        limit: int = 2
    ) -> Dict[str, Any]:
        """
        批量下载多个链接
        
        Args:
            urls: Telegram 消息链接列表
            output_dir: 输出目录
            threads: 下载线程数
            limit: 最大并发数
        
        Returns:
            批量下载结果
        """
        if not urls:
            return {"success": False, "error": "URL 列表为空"}
        
        if not self._check_container_running():
            return {
                "success": False,
                "error": f"TDL 容器 '{self.container_name}' 未运行"
            }
        
        try:
            # TDL 支持多个 -u 参数
            cmd = [
                "docker", "exec", self.container_name,
                "tdl", "dl",
                "-d", output_dir,
                "-t", str(threads),
                "-l", str(limit)
            ]
            
            # 添加所有 URL
            for url in urls:
                cmd.extend(["-u", url])
            
            logger.info(f"执行 TDL 批量下载: {len(urls)} 个链接")
            
            # 异步执行命令
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"TDL 批量下载成功")
                return {
                    "success": True,
                    "count": len(urls),
                    "output": stdout.decode() if stdout else ""
                }
            else:
                error_msg = stderr.decode() if stderr else f"Exit code: {process.returncode}"
                logger.error(f"TDL 批量下载失败: {error_msg}")
                return {
                    "success": False,
                    "count": len(urls),
                    "error": error_msg
                }
                
        except Exception as e:
            logger.exception(f"TDL 批量下载异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def download_by_message(
        self,
        chat_id: int,
        message_id: int,
        output_dir: str = "/downloads"
    ) -> Dict[str, Any]:
        """
        通过消息 ID 下载
        
        Args:
            chat_id: 聊天 ID
            message_id: 消息 ID
            output_dir: 输出目录
        """
        url = self.generate_telegram_link(chat_id, message_id)
        return await self.download(url, output_dir)


# 全局实例
tdl_integration = TDLIntegration()
