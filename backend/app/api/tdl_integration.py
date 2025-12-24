"""
TDL Integration Module - 异步版本
TDL 仅作为单文件下载器，使用异步 Docker API 通信
"""
import os
import json
import asyncio
import logging
from typing import Optional, Dict, Any, Union, List

logger = logging.getLogger(__name__)

# Docker socket 路径
DOCKER_SOCKET = "/var/run/docker.sock"


class AsyncDockerClient:
    """异步 Docker API 客户端 (通过 Unix socket)"""
    
    def __init__(self, socket_path: str = DOCKER_SOCKET):
        self.socket_path = socket_path
    
    def _decode_chunked(self, data: bytes) -> bytes:
        """解码 chunked transfer encoding"""
        result = []
        pos = 0
        while pos < len(data):
            # 查找 chunk size 行结束
            line_end = data.find(b"\r\n", pos)
            if line_end == -1:
                break
            
            # 解析 chunk size (16进制)
            try:
                chunk_size = int(data[pos:line_end].decode().strip(), 16)
            except ValueError:
                break
            
            if chunk_size == 0:
                break  # 最后一个 chunk
            
            # 提取 chunk 数据
            chunk_start = line_end + 2
            chunk_end = chunk_start + chunk_size
            if chunk_end > len(data):
                result.append(data[chunk_start:])
                break
            
            result.append(data[chunk_start:chunk_end])
            pos = chunk_end + 2  # 跳过 \r\n
        
        return b"".join(result)
    
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
            
            # 循环读取完整响应直到 EOF
            chunks = []
            try:
                while True:
                    chunk = await asyncio.wait_for(reader.read(8192), timeout=timeout)
                    if not chunk:
                        break
                    chunks.append(chunk)
            except asyncio.TimeoutError:
                pass  # 读取超时，使用已读取的数据
            
            response = b"".join(chunks)
            
            writer.close()
            try:
                await writer.wait_closed()
            except:
                pass
            
            # 解析响应
            if b"\r\n\r\n" in response:
                header_end = response.find(b"\r\n\r\n")
                header = response[:header_end].decode()
                body_data = response[header_end + 4:]
                
                # 获取状态码
                status_line = header.split("\r\n")[0]
                parts = status_line.split()
                status_code = int(parts[1]) if len(parts) >= 2 else 0
                
                # 检查是否是 chunked 编码
                if "transfer-encoding: chunked" in header.lower():
                    body_data = self._decode_chunked(body_data)
                
                # 解析 JSON body
                try:
                    # 使用 errors='replace' 以防止 UnicodeDecodeError
                    decoded_body = body_data.decode(errors='replace')
                    result = json.loads(decoded_body) if decoded_body.strip() else {}
                except json.JSONDecodeError as e:
                    logger.debug(f"[TDL] JSON 解析失败 (可能为流响应): {e}")
                    # 记录原始字节用于流式处理
                    result = {
                        "raw": body_data.decode(errors='replace')[:1000],
                        "raw_bytes": body_data
                    }
                
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

    def _decode_docker_stream(self, data: bytes) -> str:
        """解析 Docker 多路复用流 (Header: 8 bytes) (v2.1.1)"""
        if not data: return ""
        if len(data) < 8 or data[0] not in [1, 2]:
            return data.decode(errors='replace')
        
        result = []
        offset = 0
        while offset + 8 <= len(data):
            try:
                import struct
                size = struct.unpack(">I", data[offset+4:offset+8])[0]
                offset += 8
                if offset + size <= len(data):
                    result.append(data[offset:offset+size].decode(errors='replace'))
                    offset += size
                else:
                    result.append(data[offset:].decode(errors='replace'))
                    break
            except:
                return data.decode(errors='replace')
        return "".join(result)
    
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
        
        status_code = result.get("status_code", 0)
        logger.debug(f"[TDL] 容器检查响应: status_code={status_code}")
        
        if status_code == 404:
            return False, f"容器 '{container_name}' 不存在"
        
        if status_code == 200:
            data = result.get("data", {})
            # 调试: 打印 data 类型和部分内容
            logger.debug(f"[TDL] 响应数据类型: {type(data)}, 键: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
            
            state = data.get("State", {}) if isinstance(data, dict) else {}
            running = state.get("Running", False)
            status = state.get("Status", "unknown")
            
            logger.debug(f"[TDL] State: Running={running}, Status={status}")
            
            if running:
                return True, None
            return False, f"容器状态: {status}"
        
        return False, result.get("error", f"检查失败 (status={status_code})")

    
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
        
        if start_result.get("status_code") != 200:
            return {"success": False, "error": start_result.get("error", "执行失败")}
            
        # [FIX] 增加 ExitCode 检查，确保命令真正成功运行 (v1.6.8)
        inspect_result = await self._make_request(
            "GET",
            f"/exec/{exec_id}/json",
            timeout=10.0
        )
        
        # [FIX] 解析 Docker 多路复用流，获取纯净输出 (v2.1.1)
        raw_data = start_result.get("data", {}).get("raw_bytes", b"")
        output = self._decode_docker_stream(raw_data)
        
        if inspect_result.get("status_code") == 200:
            exec_info = inspect_result.get("data", {})
            exit_code = exec_info.get("ExitCode", -1)
            running = exec_info.get("Running", False)
            
            logger.debug(f"[TDL] Exec 状态检查: ExitCode={exit_code}, Running={running}")
            
            if exit_code == 0:
                return {"success": True, "output": output}
            else:
                return {
                    "success": False, 
                    "error": f"命令执行失败 (ExitCode={exit_code})", 
                    "output": output
                }
        
        # 如果无法获取 ExitCode，由于启动成功，暂时返回 True 但记录警告
        logger.warning(f"[TDL] 无法获取命令退出码 ({inspect_result.get('error')})，假设执行成功")
        return {"success": True, "output": output}


class TDLDownloader:
    """TDL 下载器 - 异步版本"""
    
    def __init__(self):
        self.container_name = os.environ.get("TDL_CONTAINER_NAME", "tdl")
        self.docker = AsyncDockerClient()
        # [FIX] TDL 全局信号量，防止同一个 Session 并发导致崩溃 (v1.6.8)
        self._semaphore = asyncio.Semaphore(1)
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
        url: Union[str, List[str]],
        output_dir: str = "/downloads",
        threads: int = 8,
        limit: int = 1,
        file_template: str = None
    ) -> Dict[str, Any]:
        """使用 TDL 下载文件 (支持单链接或列表批量下载)
        
        Args:
            url: Telegram 消息链接或链接列表
            output_dir: 下载目录
            threads: 每个文件下载的并行线程数 (-t)
            limit: 同时下载的文件数 (-l)
            file_template: 文件名模板
        """
        urls = [url] if isinstance(url, str) else url
        logger.info(f"[TDL] 下载任务启动: count={len(urls)}, threads={threads}, limit={limit}, dir={output_dir}")
        
        # 检查容器状态
        running, error = await self.docker.is_container_running(self.container_name)
        if not running:
            logger.error(f"[TDL] 容器未运行: {error}")
            return {"success": False, "error": error or "TDL 容器未运行"}
        
        # 构建基础命令
        cmd = ["tdl", "dl"]
        
        # 批量添加链接
        for u in urls:
            cmd.extend(["-u", u])
            
        # 添加其他参数
        cmd.extend([
            "-d", output_dir,
            "-t", str(threads),
            "-l", str(limit),
            "--skip-same"
        ])
        
        # 使用文件名模板 (v2.2.0 Fix)
        if file_template:
            cmd.extend(["--template", file_template])
        else:
            # 兼容逻辑: {ID}-{abs(PeerID)}-{FileName} -> 匹配项目标准 (剥离负号)
            cmd.extend(["--template", '{{.ID}}-{{replace .PeerID "-" ""}}-{{.FileName}}'])
        
        logger.info(f"[TDL] 正在执行批量命令 (url数量: {len(urls)})")
        
        # 执行命令 (使用信号量保护)
        async with self._semaphore:
            result = await self.docker.exec_command(self.container_name, cmd, timeout=600.0)
        
        if result.get("success"):
            logger.info(f"[TDL] 下载完成: {result.get('output', '')[:200]}")
        else:
            logger.error(f"[TDL] 下载失败: {result.get('error')}")
            # 如果下载失败，返回包含错误信息的详情
        
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
