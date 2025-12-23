"""
TDL Integration Module - 简化版
TDL 仅作为单文件下载器，下载选择由 tg-export 控制
使用 Docker HTTP API 通过 Unix socket 通信
"""
import os
import json
import logging
import socket
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Docker socket 路径
DOCKER_SOCKET = "/var/run/docker.sock"


class DockerAPIClient:
    """Docker HTTP API 客户端 (通过 Unix socket)"""
    
    def __init__(self, socket_path: str = DOCKER_SOCKET):
        self.socket_path = socket_path
    
    def _make_request(self, method: str, path: str, body: dict = None) -> dict:
        """发送 HTTP 请求到 Docker daemon"""
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect(self.socket_path)
            
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
            sock.sendall(request)
            
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
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
            
            if b"\r\n\r\n" in response:
                header_end = response.find(b"\r\n\r\n")
                header = response[:header_end].decode()
                body = response[header_end + 4:]
                status_line = header.split("\r\n")[0]
                status_code = int(status_line.split()[1])
                
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
        """检查 Docker 是否可用"""
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
        """检查容器是否运行"""
        info = self.get_container_info(container_name)
        if info is None:
            return False, f"容器 '{container_name}' 不存在"
        
        state = info.get("State", {})
        if state.get("Running"):
            return True, None
        return False, f"容器状态: {state.get('Status', 'unknown')}"
    
    def create_exec(self, container_name: str, cmd: list) -> str:
        """创建 exec 实例"""
        result = self._make_request("POST", f"/containers/{container_name}/exec", {
            "AttachStdin": False,
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": False,
            "Cmd": cmd
        })
        if result.get("status_code") == 201:
            return result["data"].get("Id")
        logger.error(f"[TDL] 创建 exec 失败: {result}")
        return None
    
    def start_exec(self, exec_id: str) -> dict:
        """启动 exec"""
        result = self._make_request("POST", f"/exec/{exec_id}/start", {
            "Detach": False,
            "Tty": False
        })
        return result


class TDLDownloader:
    """TDL 下载器 - 简化版，仅提供单文件下载"""
    
    def __init__(self):
        self.container_name = os.environ.get("TDL_CONTAINER_NAME", "tdl")
        self.docker = DockerAPIClient()
        logger.info(f"[TDL] 下载器初始化: container={self.container_name}, socket={DOCKER_SOCKET}")
    
    def get_status(self) -> Dict[str, Any]:
        """获取 TDL 状态"""
        docker_available, docker_error = self.docker.is_available()
        
        container_running = False
        container_error = docker_error
        
        if docker_available:
            container_running, container_error = self.docker.is_container_running(self.container_name)
        
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
        """
        使用 TDL 下载单个文件
        
        Args:
            url: Telegram 消息链接
            output_dir: 下载目录
            threads: 每任务线程数 (-t)
            limit: 并发任务数 (-l)
        
        Returns:
            {"success": bool, "output": str, "error": str}
        """
        logger.info(f"[TDL] 下载: url={url}, dir={output_dir}")
        
        # 检查容器状态
        running, error = self.docker.is_container_running(self.container_name)
        if not running:
            logger.error(f"[TDL] 容器未运行: {error}")
            return {"success": False, "error": error or "TDL 容器未运行"}
        
        # 构建命令: tdl dl -u URL -d DIR -t THREADS -l LIMIT --skip-same
        cmd = [
            "tdl", "dl",
            "-u", url,
            "-d", output_dir,
            "-t", str(threads),
            "-l", str(limit),
            "--skip-same"  # 跳过已存在的相同文件
        ]
        logger.info(f"[TDL] 命令: {' '.join(cmd)}")
        
        # 创建并执行
        exec_id = self.docker.create_exec(self.container_name, cmd)
        if not exec_id:
            return {"success": False, "error": "创建执行失败"}
        
        result = self.docker.start_exec(exec_id)
        status_code = result.get("status_code", 0)
        
        if status_code == 200:
            output = result.get("data", {}).get("raw", "")
            logger.info(f"[TDL] 执行完成: {output[:200] if output else '(无输出)'}")
            return {"success": True, "output": output}
        
        error_msg = result.get("error", f"执行失败 (status={status_code})")
        logger.error(f"[TDL] 执行失败: {error_msg}")
        return {"success": False, "error": error_msg}
    
    async def download_by_message(
        self,
        chat_id: int,
        message_id: int,
        output_dir: str = "/downloads",
        threads: int = 4,
        limit: int = 2
    ) -> Dict[str, Any]:
        """
        通过消息 ID 下载
        
        Args:
            chat_id: 频道/群组 ID
            message_id: 消息 ID
            output_dir: 下载目录
        """
        url = self.generate_telegram_link(chat_id, message_id)
        logger.info(f"[TDL] 消息下载: chat={chat_id}, msg={message_id} -> {url}")
        return await self.download(url, output_dir, threads, limit)


# 全局实例
tdl_integration = TDLDownloader()
