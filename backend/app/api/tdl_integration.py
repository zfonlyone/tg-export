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
                    # [v2.3.1] 对于 exec/start 等流响应，JSON 解析失败是预期的，不应视为错误
                    if "/exec/" not in path or "/start" not in path:
                         logger.debug(f"[TDL] JSON 解析失败: {e}")
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

    
    async def exec_command(self, container_name: str, cmd: list, timeout: float = 3600.0, stuck_check_callback=None) -> dict:
        """在容器中执行命令 (v2.3.2 Polling Mode)"""
        # 1. 创建 exec 实例
        create_result = await self._make_request(
            "POST", 
            f"/containers/{container_name}/exec",
            {
                "AttachStdin": False,
                "AttachStdout": True,
                "AttachStderr": True,
                "Tty": False, # 关闭 TTY 以便清晰区分 stdout/stderr
                "Cmd": cmd
            },
            timeout=10.0
        )
        
        if create_result.get("status_code") != 201:
            return {"success": False, "error": f"创建 exec 失败: {create_result.get('error')}"}
        
        exec_id = create_result.get("data", {}).get("Id")
        if not exec_id:
            return {"success": False, "error": "未获取到 exec ID"}
        
        # 2. 启动 exec (Detached 模式)
        # 我们不在这里读取流，因为流读取受限于 Python 库的各种超时和缓冲区问题
        # 改用 Detached 启动，然后轮询状态，最后一次性获取产生的日志
        start_result = await self._make_request(
            "POST",
            f"/exec/{exec_id}/start",
            {"Detach": True, "Tty": False},
            timeout=10.0
        )
        
        if start_result.get("status_code") != 200:
            return {"success": False, "error": start_result.get("error", "启动执行失败")}
            
        # 3. 轮询等待结束
        import time
        start_time = time.time()
        exit_code = -1
        
        while True:
            # 检查是否超时
            if time.time() - start_time > timeout:
                return {"success": False, "error": "执行超时 (Polling Timeout)"}
            
            inspect_result = await self._make_request(
                "GET",
                f"/exec/{exec_id}/json",
                timeout=5.0
            )
            
            if inspect_result.get("status_code") != 200:
                await asyncio.sleep(1.0)
                continue
                
            info = inspect_result.get("data", {})
            running = info.get("Running", True) # 默认认为运行中，防止误判
            
            if not running:
                exit_code = info.get("ExitCode", -1)
                break
            
            await asyncio.sleep(0.5)
            
        # 4. 获取日志 (通过 logs 接口回溯，或者如果 docker API 支持从 exec 获取流也可以)
        # 由于 Docker API 没有直接获取 exec 日志的便捷 HTTP 接口 (通常是 start 时 attach)
        # 且我们使用了 Detached，我们需要一种方式获取输出。
        # 实际上 Detached exec 的输出很难通过标准 API 再次获取，除非配置了 logging driver
        # 所以更稳妥的 Polling 方式其实是：Keep Attached but read in small chunks? No, that hangs.
        
        # 修正策略：为了修复 "信号捕获" 问题，核心是不要依赖 stream close event
        # 我们使用 Docker SDK 风格的 "Socket Read" 但配合超时控制
        # 然而为了彻底解决，我们还是切回 (Detach=False) 但优化读取循环 ?
        
        # 不，用户报告的问题是"无法捕获成功信号"，意味着 Python 以为还在运行或者读取超时了。
        # 最稳的方案 (针对 TDL 这种可能长时间无输出的):
        # 还是得用 Attached 模式，但是要处理 socket 读取超时。
        
        # 考虑到当前架构限制，我们使用一个混合方案：
        # 启动时 Attach，但使用 asyncio.wait_for 包装 read，并且容忍超时 (超时不代表结束)
        # 同时并发检查 exec inspect。
        
        # 但既然已经写了 Detached 的开头，我们换个思路：
        # 对于 TDL download，我们其实不太关心 stdout 内容，除非出错。
        # ExitCode 0 才是硬指标。
        # 如果 ExitCode=0，我们就认为成功。Detail 交给 verify 阶段。
        # 如果非 0，我们即便拿不到完整 log，拿个大概也行。
        
        # 但为了调试，我们最好还是能拿到输出。
        # 遗憾 Docker HTTP API 对 Detached Exec 的日志获取支持有限。
        # 因此，回退到：Attach 模式，但重写 _make_request 里的读取逻辑？
        # 更简单的：改回 Detached=False，但是在读取流时，使用 inspect 辅助判断是否该退出？
        
        # Let's stick to the Attached mode logic BUT fix the stream reader hanging issue.
        # The previous implementation relies on `reader.read(8192)` returning empty bytes for EOF.
        # If TDL holds open stdout but sends nothing, it hangs.
        
        # 经过思考，针对 "tdl下载无法正确捕获成功下载信号"：
        # 最好的办法是【不依赖】输出流的结束，而是依赖【进程状态】的结束。
        # 所以 Polling ExitCode 是最正确的。
        # 问题是：Polling 时怎么拿日志？
        # 各种 Docker 库的做法是：Detach=False (Streaming), 但单独开个 Tasks 去读 Stream，主流程 Wait 状态。
        
        # 这里为了简化且稳健：
        # 1. Start exec (Detach=False)
        # 2. 读取 Response Body (Hijacked stream)
        # 3. 解析 Log
        
        # 原有实现的问题在于 `await reader.read` 可能会永久挂起如果对方不关闭流。
        # 我们改写这个简单的 exec_command，让它更鲁棒。
        
        # 方案：使用 Detach=False，常规 http 请求。
        # 但是！如果下载一个大文件，http response 会非常长/久。
        # 之前的实现也是一次性读取或者简单的 chunk read。
        
        # 让我们实施【Polling 检查 + 忽略实时输出 (TDL会写文件)】策略?
        # 不行，出错得看日志。
        
        # 最终决定方案：
        # 使用 Detach=True 启动。
        # 这样请求会立即返回。
        # 然后我们轮询 Inspect API 等待 Running=False。
        # 这样绝对能捕获 ExitCode。
        # 【缺点】：拿不到 stdout/stderr。
        # 【弥补】：TDL 下载成功与否主要看文件是否存在+大小。失败时没日志确实是个痛点。
        # 但用户痛点是 "卡住" 和 "无法捕获成功"。
        # 既然是 TDL，我们可以让 TDL 把日志写到文件里吗？
        # 或者，我们可以 trust TDL is robust enough.
        
        # 还是回头看 `_make_request`。它里面有 `timeout`。
        # 如果命令执行超过 timeout (默认 300s)，_make_request 就会报错 Timeout。
        # 这就是问题所在！TDL 下载可能很久。
        # 原代码 `timeout=3600.0` 传给了 `_make_request`。
        # `asyncio.open_unix_connection` 的 timeout 是连接超时。
        # 但 `reader.read` 的 timeout 也是传进去的 3600。
        
        # 如果 TDL 下载了 2 小时，这里就超时报错了，但其实还在下。
        # 或者 TDL 没有任何输出，reader.read 卡住。
        
        # 修正：Polling 模式是必须的。不要 hold 一个长连接 1 小时。
        # 实现 Polling 模式，且放弃获取日志 (或者只获取 TDL 自身的日志文件，如果支持)。
        # 实际上，只要 ExitCode=0，我们就不需要日志。
        # 如果 ExitCode!=0，我们可能丢失日志，但解决了卡死问题。
        # 考虑到 TDL 失败通常是因为网络或文件系统，用户重试即可。
        # 权衡之下，解决 "卡住" 是第一优先级。
        
        # 实施 Polling 模式 (Detach=True)。
        
        start_result = await self._make_request(
            "POST",
            f"/exec/{exec_id}/start",
            {"Detach": True, "Tty": False},
            timeout=10.0 # 只要启动指令发送成功即可
        )
        
        if start_result.get("status_code") != 200:
            return {"success": False, "error": start_result.get("error", "启动执行失败")}
            
        # 轮询
        import time
        start_time = time.time()
        
        while True:
            if time.time() - start_time > timeout:
                return {"success": False, "error": "执行超时"}
            
            inspect_result = await self._make_request(
                "GET",
                f"/exec/{exec_id}/json",
                timeout=5.0
            )
            
            if inspect_result.get("status_code") == 200:
                data = inspect_result.get("data", {})
                if not data.get("Running"):
                    exit_code = data.get("ExitCode")
                    if exit_code == 0:
                        return {"success": True, "output": "(Polling Mode: Success)"}
                    else:
                        return {"success": False, "error": f"ExitCode={exit_code}", "output": ""}
            
            # [Optimization] 卡死检测逻辑 (Stuck Detection)
            # 如果提供了检查回调，且返回 True (表示卡死)，则终止进程
            # 外部回调通常检查文件大小是否在增长
            if stuck_check_callback:
                try:
                    if asyncio.iscoroutinefunction(stuck_check_callback):
                        is_stuck = await stuck_check_callback()
                    else:
                        is_stuck = stuck_check_callback()
                    
                    if is_stuck:
                        logger.error(f"[TDL] 检测到执行卡死 (Stuck Detected)，强制终止: {container_name}")
                        # 尝试 kill 容器内的主进程 (tdl) 
                        # 由于这是 exec，我们实际上需要杀掉 exec 进程或者容器内的 tdl 进程
                        # 简单起见，我们在容器内执行 killall
                        await self._make_request(
                            "POST", 
                            f"/containers/{container_name}/exec",
                            {
                                "AttachStdin": False, "AttachStdout": False, "AttachStderr": False,
                                "Cmd": ["sh", "-c", "killall -9 tdl"]
                            },
                        )
                        # 同时尝试 resize exec 以触发信号? 不，直接返回超时/失败让外部处理
                        return {"success": False, "error": "Stuck detected (File not growing)"}
                except Exception as e:
                    logger.warning(f"[TDL] 卡死检测回调执行出错: {e}")

            await asyncio.sleep(2.0)


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
        file_template: str = None,
        proxy: str = None,
        stuck_check_callback: callable = None
    ) -> Dict[str, Any]:
        """使用 TDL 下载文件 (v2.1.8 稳定版)"""
        urls = [url] if isinstance(url, str) else url
        logger.info(f"[TDL] 下载任务启动: count={len(urls)}, threads={threads}, limit={limit}, dir={output_dir}")
        
        # 检查容器状态
        running, error = await self.docker.is_container_running(self.container_name)
        if not running:
            return {"success": False, "error": error or "TDL 容器未运行"}
        
        # 构建基础命令
        cmd = ["tdl", "dl"]
        for u in urls: cmd.extend(["-u", u])
        cmd.extend(["-d", output_dir, "-t", str(threads), "-l", str(limit), "--skip-same", "--continue"])
        
        if file_template:
            cmd.extend(["--template", file_template])
        else:
            cmd.extend(["--template", '{{.MessageID}}-{{printf "%d" .DialogID | replace "-" ""}}-{{.FileName}}'])
        
        if proxy:
            cmd.extend(["--proxy", proxy])
        
        async with self._semaphore:
            max_retries = 2
            result = {"success": False, "error": "Unknown error"}
            for attempt in range(max_retries):
                # 清理
                await self.docker.exec_command(self.container_name, ["sh", "-c", "killall -9 tdl || pkill -9 tdl || true"], timeout=10.0)
                # 执行 (1 小时超时)
                result = await self.docker.exec_command(
                    self.container_name, 
                    cmd, 
                    timeout=3600.0,
                    stuck_check_callback=stuck_check_callback
                )
                
                if result.get("success"): break
                if "database is used by another process" in result.get("output", ""):
                    await asyncio.sleep(2.0)
                    continue
                break
        if result.get("success"):
            logger.info(f"[TDL] 下载完成: {result.get('output', '')[:200]}")
        else:
            logger.error(f"[TDL] 下载失败: {result.get('error')}")
            # 输出前 200 个字符的错误信息帮助调试
            if result.get("output"):
                logger.error(f"[TDL] 错误输出: {result.get('output')[:200]}")
        
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
