"""
TDL Integration Module - 使用 Docker HTTP API 与 TDL 容器通信
无需安装 Docker CLI，直接通过 Unix socket 调用 Docker API
"""
import os
import json
import asyncio
import logging
import socket
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)

# Docker socket 路径
DOCKER_SOCKET = "/var/run/docker.sock"


class TDLDownloadStatus(str, Enum):
    """TDL 下载状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TDLDownloadItem:
    """TDL 下载项"""
    item_id: str
    url: str
    file_name: str
    file_size: int
    output_path: str
    status: TDLDownloadStatus = TDLDownloadStatus.PENDING
    downloaded_size: int = 0
    progress: float = 0.0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class TDLBatchTask:
    """TDL 批量下载任务"""
    task_id: str
    items: List[TDLDownloadItem] = field(default_factory=list)
    status: TDLDownloadStatus = TDLDownloadStatus.PENDING
    exec_id: Optional[str] = None
    output_dir: str = "/downloads"
    threads: int = 4
    limit: int = 2
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DockerAPIClient:
    """Docker HTTP API 客户端 (通过 Unix socket)"""
    
    def __init__(self, socket_path: str = DOCKER_SOCKET):
        self.socket_path = socket_path
    
    def _make_request(self, method: str, path: str, body: dict = None) -> dict:
        """发送 HTTP 请求到 Docker daemon"""
        try:
            # 创建 Unix socket 连接
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect(self.socket_path)
            
            # 构建 HTTP 请求
            body_bytes = json.dumps(body).encode() if body else b""
            headers = [
                f"{method} {path} HTTP/1.1",
                "Host: localhost",
                "Content-Type: application/json",
                f"Content-Length: {len(body_bytes)}",
                "",
                ""
            ]
            request = "\r\n".join(headers).encode() + body_bytes
            
            # 发送请求
            sock.sendall(request)
            
            # 读取响应
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                # 检查是否读取完毕 (简单检测)
                if b"\r\n\r\n" in response:
                    header_end = response.find(b"\r\n\r\n")
                    header = response[:header_end].decode()
                    if "Content-Length:" in header:
                        for line in header.split("\r\n"):
                            if line.startswith("Content-Length:"):
                                content_len = int(line.split(":")[1].strip())
                                body_start = header_end + 4
                                if len(response) >= body_start + content_len:
                                    break
                    elif "Transfer-Encoding: chunked" not in header:
                        break
            
            sock.close()
            
            # 解析响应
            if b"\r\n\r\n" in response:
                header_end = response.find(b"\r\n\r\n")
                header = response[:header_end].decode()
                body = response[header_end + 4:]
                
                # 获取状态码
                status_line = header.split("\r\n")[0]
                status_code = int(status_line.split()[1])
                
                # 解析 JSON body
                try:
                    result = json.loads(body.decode()) if body else {}
                except:
                    result = {"raw": body.decode()}
                
                return {"status_code": status_code, "data": result}
            
            return {"status_code": 500, "error": "Invalid response"}
            
        except FileNotFoundError:
            return {"status_code": 0, "error": f"Docker socket 不存在: {self.socket_path}"}
        except socket.error as e:
            return {"status_code": 0, "error": f"Socket 错误: {e}"}
        except Exception as e:
            return {"status_code": 0, "error": str(e)}
    
    def is_available(self) -> tuple:
        """检查 Docker 是否可用，返回 (是否可用, 错误信息)"""
        if not os.path.exists(self.socket_path):
            return False, f"Docker socket 不存在: {self.socket_path}"
        
        result = self._make_request("GET", "/version")
        if result.get("status_code") == 200:
            return True, None
        return False, result.get("error", "无法连接 Docker")
    
    def get_container_info(self, container_name: str) -> dict:
        """获取容器信息"""
        result = self._make_request("GET", f"/containers/{container_name}/json")
        if result.get("status_code") == 200:
            return result["data"]
        return None
    
    def is_container_running(self, container_name: str) -> tuple:
        """检查容器是否运行，返回 (是否运行, 错误信息)"""
        info = self.get_container_info(container_name)
        if info is None:
            return False, f"容器 '{container_name}' 不存在"
        
        state = info.get("State", {})
        if state.get("Running"):
            return True, None
        return False, f"容器状态: {state.get('Status', 'unknown')}"
    
    def create_exec(self, container_name: str, cmd: List[str]) -> str:
        """创建 exec 实例，返回 exec ID"""
        result = self._make_request("POST", f"/containers/{container_name}/exec", {
            "AttachStdin": False,
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": False,
            "Cmd": cmd
        })
        if result.get("status_code") == 201:
            return result["data"].get("Id")
        logger.error(f"创建 exec 失败: {result}")
        return None
    
    def start_exec(self, exec_id: str) -> dict:
        """启动 exec 并获取输出"""
        result = self._make_request("POST", f"/exec/{exec_id}/start", {
            "Detach": False,
            "Tty": False
        })
        return result


class TDLIntegration:
    """TDL 集成服务 - 使用 Docker HTTP API"""
    
    def __init__(self):
        self.container_name = os.environ.get("TDL_CONTAINER_NAME", "tdl")
        self.batch_tasks: Dict[str, TDLBatchTask] = {}
        self.docker = DockerAPIClient()
        self._monitor_interval = 1.0
    
    def get_status(self) -> Dict[str, Any]:
        """获取 TDL 状态"""
        docker_available, docker_error = self.docker.is_available()
        
        container_running = False
        container_error = docker_error
        
        if docker_available:
            container_running, container_error = self.docker.is_container_running(self.container_name)
        
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
        """生成 Telegram 消息链接"""
        if chat_id < 0:
            clean_id = str(abs(chat_id))
            if clean_id.startswith("100"):
                clean_id = clean_id[3:]
            return f"https://t.me/c/{clean_id}/{message_id}"
        else:
            return f"https://t.me/c/{chat_id}/{message_id}"
    
    async def download(
        self,
        url: str,
        output_dir: str = "/downloads",
        threads: int = 4,
        limit: int = 2
    ) -> Dict[str, Any]:
        """使用 TDL 下载单个文件"""
        running, error = self.docker.is_container_running(self.container_name)
        if not running:
            return {"success": False, "error": error or "TDL 容器未运行"}
        
        cmd = ["tdl", "dl", "-u", url, "-d", output_dir, "-t", str(threads), "-l", str(limit)]
        
        exec_id = self.docker.create_exec(self.container_name, cmd)
        if not exec_id:
            return {"success": False, "error": "创建 exec 失败"}
        
        result = self.docker.start_exec(exec_id)
        
        if result.get("status_code") == 200:
            return {"success": True, "url": url, "output": result.get("data", {}).get("raw", "")}
        return {"success": False, "error": result.get("error", "执行失败")}
    
    async def batch_download(
        self,
        urls: List[str],
        output_dir: str = "/downloads",
        threads: int = 4,
        limit: int = 2
    ) -> Dict[str, Any]:
        """批量下载"""
        if not urls:
            return {"success": False, "error": "URL 列表为空"}
        
        running, error = self.docker.is_container_running(self.container_name)
        if not running:
            return {"success": False, "error": error or "TDL 容器未运行"}
        
        cmd = ["tdl", "dl", "-d", output_dir, "-t", str(threads), "-l", str(limit)]
        for url in urls:
            cmd.extend(["-u", url])
        
        exec_id = self.docker.create_exec(self.container_name, cmd)
        if not exec_id:
            return {"success": False, "error": "创建 exec 失败"}
        
        result = self.docker.start_exec(exec_id)
        
        if result.get("status_code") == 200:
            return {"success": True, "count": len(urls), "output": result.get("data", {}).get("raw", "")}
        return {"success": False, "error": result.get("error", "执行失败")}
    
    async def start_batch_download(
        self,
        task_id: str,
        items: List[Dict[str, Any]],
        output_dir: str = "/downloads",
        threads: int = 4,
        limit: int = 2,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """启动批量下载任务"""
        running, error = self.docker.is_container_running(self.container_name)
        if not running:
            return {"success": False, "error": error or "TDL 容器未运行"}
        
        if not items:
            return {"success": False, "error": "下载项列表为空"}
        
        urls = [item.get("url", "") for item in items]
        
        # 直接执行批量下载
        result = await self.batch_download(urls, output_dir, threads, limit)
        
        return {
            "success": result.get("success"),
            "task_id": task_id,
            "count": len(urls),
            "message": f"已启动 TDL 下载: {len(urls)} 个文件" if result.get("success") else result.get("error")
        }
    
    def get_batch_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取批量任务状态"""
        task = self.batch_tasks.get(task_id)
        if not task:
            return None
        return {"task_id": task_id, "status": task.status.value}
    
    async def cancel_batch_task(self, task_id: str) -> bool:
        """取消批量任务"""
        if task_id in self.batch_tasks:
            del self.batch_tasks[task_id]
            return True
        return False
    
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
