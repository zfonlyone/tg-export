"""
TDL Integration Module - 异步版本
TDL 仅作为单文件下载器，使用异步 Docker API 通信
"""
import os
import json
import asyncio
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Docker socket 路径
DOCKER_SOCKET = "/var/run/docker.sock"


class AsyncDockerClient:
    """异步 Docker API 客户端 (通过 Unix socket)"""
    
    def __init__(self, socket_path: str = DOCKER_SOCKET):
        self.socket_path = socket_path
    
    async def _make_request(self, method: str, path: str, body: dict = None, timeout: float = 10.0) -> dict:
        """异步发送 HTTP 请求到 Docker daemon"""
        try:
            # 检查 socket 是否存在
            if not os.path.exists(self.socket_path):
                return {"status_code": 0, "error": f"Docker socket 不存在: {self.socket_path}"}
            
            # 异步连接 Unix socket
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path),
                timeout=timeout
            )
            
            # 构建 HTTP 请求
            body_bytes = json.dumps(body).encode() if body else b""
            request = (
                f"{method} {path} HTTP/1.1\r\n"
                f"Host: localhost\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + body_bytes
            
            # 发送请求
            writer.write(request)
            await writer.drain()
            
            # 读取响应 (限制大小防止内存溢出)
            response = await asyncio.wait_for(
                reader.read(65536),
                timeout=timeout
            )
            
            writer.close()
            await writer.wait_closed()
            
            # 解析响应
            if b"\r\n\r\n" in response:
                header_end = response.find(b"\r\n\r\n")
                header = response[:header_end].decode()
                body_data = response[header_end + 4:]
                
                # 获取状态码
                status_line = header.split("\r\n")[0]
                parts = status_line.split()
                status_code = int(parts[1]) if len(parts) >= 2 else 0
                
                # 解析 JSON body
                try:
                    result = json.loads(body_data.decode()) if body_data.strip() else {}
                except json.JSONDecodeError:
                    result = {"raw": body_data.decode()}
                
                return {"status_code": status_code, "data": result}
            
            return {"status_code": 500, "error": "无效响应"}
            
        except asyncio.TimeoutError:
            return {"status_code": 0, "error": "连接超时"}
        except FileNotFoundError:
            return {"status_code": 0, "error": f"Docker socket 不存在: {self.socket_path}"}
        except ConnectionRefusedError:
            return {"status_code": 0, "error": "Docker daemon 拒绝连接"}
        except Exception as e:
            return {"status_code": 0, "error": str(e)}
    
    async def is_available(self) -> tuple:
        """检查 Docker 是否可用"""
        if not os.path.exists(self.socket_path):
            return False, f"Docker socket 不存在: {self.socket_path}"
        
        result = await self._make_request("GET", "/version", timeout=5.0)
        if result.get("status_code") == 200:
            return True, None
        return False, result.get("error", "无法连接 Docker")
    
    async def is_container_running(self, container_name: str) -> tuple:
        """检查容器是否运行"""
        result = await self._make_request("GET", f"/containers/{container_name}/json", timeout=5.0)
        
        if result.get("status_code") == 404:
            return False, f"容器 '{container_name}' 不存在"
        
        if result.get("status_code") == 200:
            data = result.get("data", {})
            state = data.get("State", {})
            if state.get("Running"):
                return True, None
            return False, f"容器状态: {state.get('Status', 'unknown')}"
        
        return False, result.get("error", "检查失败")
    
    async def exec_command(self, container_name: str, cmd: list, timeout: float = 300.0) -> dict:
        """在容器中执行命令"""
        # 创建 exec
        create_result = await self._make_request(
            "POST", 
            f"/containers/{container_name}/exec",
            {
                "AttachStdin": False,
                "AttachStdout": True,
                "AttachStderr": True,
                "Tty": False,
                "Cmd": cmd
            },
            timeout=10.0
        )
        
        if create_result.get("status_code") != 201:
            return {"success": False, "error": f"创建 exec 失败: {create_result.get('error')}"}
        
        exec_id = create_result.get("data", {}).get("Id")
        if not exec_id:
            return {"success": False, "error": "未获取到 exec ID"}
        
        # 启动 exec
        start_result = await self._make_request(
            "POST",
            f"/exec/{exec_id}/start",
            {"Detach": False, "Tty": False},
            timeout=timeout
        )
        
        if start_result.get("status_code") == 200:
            output = start_result.get("data", {}).get("raw", "")
            return {"success": True, "output": output}
        
        return {"success": False, "error": start_result.get("error", "执行失败")}


class TDLDownloader:
    """TDL 下载器 - 异步版本"""
    
    def __init__(self):
        self.container_name = os.environ.get("TDL_CONTAINER_NAME", "tdl")
        self.docker = AsyncDockerClient()
        logger.info(f"[TDL] 下载器初始化: container={self.container_name}, socket={DOCKER_SOCKET}")
    
    async def get_status(self) -> Dict[str, Any]:
        """获取 TDL 状态（异步）"""
        docker_available, docker_error = await self.docker.is_available()
        
        container_running = False
        container_error = docker_error
        
        if docker_available:
            container_running, container_error = await self.docker.is_container_running(self.container_name)
        
        status = {
            "docker_available": docker_available,
            "container_name": self.container_name,
            "container_running": container_running,
            "container_error": container_error
        }
        logger.info(f"[TDL] 状态: docker={docker_available}, container={container_running}, error={container_error}")
        return status
    
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
        """使用 TDL 下载单个文件（异步）"""
        logger.info(f"[TDL] 下载: url={url}, dir={output_dir}")
        
        # 检查容器状态
        running, error = await self.docker.is_container_running(self.container_name)
        if not running:
            logger.error(f"[TDL] 容器未运行: {error}")
            return {"success": False, "error": error or "TDL 容器未运行"}
        
        # 构建命令
        cmd = [
            "tdl", "dl",
            "-u", url,
            "-d", output_dir,
            "-t", str(threads),
            "-l", str(limit),
            "--skip-same"
        ]
        logger.info(f"[TDL] 命令: {' '.join(cmd)}")
        
        # 执行命令
        result = await self.docker.exec_command(self.container_name, cmd, timeout=600.0)
        
        if result.get("success"):
            logger.info(f"[TDL] 下载完成: {result.get('output', '')[:200]}")
        else:
            logger.error(f"[TDL] 下载失败: {result.get('error')}")
        
        return result
    
    async def download_by_message(
        self,
        chat_id: int,
        message_id: int,
        output_dir: str = "/downloads",
        threads: int = 4,
        limit: int = 2
    ) -> Dict[str, Any]:
        """通过消息 ID 下载（异步）"""
        url = self.generate_telegram_link(chat_id, message_id)
        logger.info(f"[TDL] 消息下载: chat={chat_id}, msg={message_id} -> {url}")
        return await self.download(url, output_dir, threads, limit)


# 全局实例
tdl_integration = TDLDownloader()
