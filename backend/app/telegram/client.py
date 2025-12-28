"""
TG Export - Telegram 客户端
使用 Pyrogram 异步库连接 Telegram
"""
import asyncio
import os
import logging
from pathlib import Path
from typing import Optional, List, AsyncGenerator, Union
from pyrogram import Client
from pyrogram.types import Chat, Message, Dialog
from pyrogram.enums import ChatType as PyChatType
from pyrogram.errors import (
    SessionPasswordNeeded, FloodWait, PhoneCodeInvalid, 
    PhoneCodeExpired, PhoneNumberInvalid, Unauthorized,
    UserDeactivated
)

from ..config import settings
from ..models import ChatInfo, ChatType, MessageInfo, MediaType

logger = logging.getLogger(__name__)

class TelegramClient:
    """Telegram 客户端封装"""
    
    def __init__(self):
        self._client: Optional[Client] = None
        self._is_authorized = False
        self._api_id: Optional[int] = None
        self._api_hash: Optional[str] = None
        self._phone: Optional[str] = None
        self._phone_code_hash: Optional[str] = None
        self._lock = asyncio.Lock() # 用于保护连接和初始化过程
        self._message_cache = {} # { (chat_id, msg_id): (message_obj, timestamp) }
        self._me_cache = None    # 缓存 get_me 结果
        self._me_cache_time = 0  # 缓存时间戳
        self._cache_lock = asyncio.Lock()
    
    @property
    def is_authorized(self) -> bool:
        return self._is_authorized
    
    @property
    def is_initialized(self) -> bool:
        return self._client is not None
    
    def _check_ipv6_support(self) -> bool:
        """检测系统是否支持 IPv6 连接到 Telegram"""
        import socket
        
        # Telegram IPv6 服务器地址 (DC2)
        telegram_ipv6_hosts = [
            ("2001:67c:4e8:f002::a", 443),  # DC2 IPv6
            ("2001:67c:4e8:f003::a", 443),  # DC3 IPv6
        ]
        
        for host, port in telegram_ipv6_hosts:
            try:
                sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((host, port))
                sock.close()
                print(f"[TG] IPv6 连接测试成功: {host}")
                return True
            except (socket.error, OSError) as e:
                print(f"[TG] IPv6 连接测试失败 ({host}): {e}")
                continue
        
        return False
    
    async def init(self, api_id: int, api_hash: str, session_name: str = "tg_export"):
        """初始化客户端（只创建实例，不连接）"""
        async with self._lock:
            # 如果配置没变且已初始化，则无需重新创建
            if self._client and self._api_id == api_id and self._api_hash == api_hash:
                print(f"[TG] API 配置未变，跳过初始化")
                return

            # 保存凭证
            self._api_id = api_id
            self._api_hash = api_hash
            
            # 清理旧客户端
            if self._client:
                try:
                    if self._client.is_connected:
                        await self._client.disconnect()
                except:
                    pass
                self._client = None
            
            session_path = settings.SESSIONS_DIR / session_name
            
            # IPv6 自动检测与回退
            use_ipv6 = settings.USE_IPV6
            if use_ipv6:
                use_ipv6 = self._check_ipv6_support()
                if not use_ipv6:
                    print("[TG] IPv6 不可用，自动切换到 IPv4")
            
            self._client = Client(
                name=str(session_path),
                api_id=api_id,
                api_hash=api_hash,
                workdir=str(settings.SESSIONS_DIR),
                device_model="TG Export Web",
                system_version="Linux",
                ipv6=use_ipv6,  # IPv6 支持 (自动检测)
                sleep_threshold=0, # [Fast Response] 禁用内置自动等待，让异常立即抛出
                workers=100, # [FIX] 提升内部线程数，处理更高并发 (v1.6.5 自动化)
                max_concurrent_transmissions=10  # [FIX v1.3.9] 关键参数：允许最多 10 个并发传输
            )
            print(f"[TG] 客户端已初始化: api_id={api_id}, ipv6={use_ipv6}")
    
    async def _ensure_connected(self):
        """确保客户端已连接"""
        if not self._client:
            raise RuntimeError("客户端未初始化，请先配置 API ID 和 API Hash")
        
        if not self._client.is_connected:
            async with self._lock:
                # 双重检查模式，防止重复连接
                if not self._client.is_connected:
                    print("[TG] 正在连接...")
                    try:
                        await self._client.connect()
                        print("[TG] 已连接")
                    except Exception as e:
                        print(f"[TG] 连接异常: {e}")
                        raise

    def set_max_concurrent_transmissions(self, value: int):
        """动态设置最大并发传输数 (v1.4.0)
        
        允许用户通过 Web UI 配置的 max_concurrent_downloads 生效。
        Pyrogram 的 Client 对象在运行时支持修改此属性。
        """
        if self._client:
            # [FIX] 确保并发传输数不超过内部 workers 数，防止 Pyrogram 内部死锁
            safe_value = min(value, self._client.workers)
            self._client.max_concurrent_transmissions = safe_value
            print(f"[TG] 已设置最大并发传输数: {safe_value} (原始请求: {value})")
        else:
            print(f"[TG] 警告: 客户端未初始化，无法设置并发数")
    
    async def send_code(self, phone: str) -> str:
        """发送验证码"""
        await self._ensure_connected()
        
        self._phone = phone
        print(f"[TG] 发送验证码到 {phone}...")
        
        try:
            sent_code = await self._client.send_code(phone)
            self._phone_code_hash = sent_code.phone_code_hash
            print(f"[TG] 验证码已发送，hash: {self._phone_code_hash[:10]}...")
            return self._phone_code_hash
        except FloodWait as e:
            print(f"[TG] 需要等待 {e.value} 秒后再操作")
            raise RuntimeError(f"请求过于频繁，请等待 {e.value} 秒后再试")
        except PhoneNumberInvalid:
            raise RuntimeError("手机号码无效")
        except Exception as e:
            print(f"[TG] 发送验证码失败: {e}")
            raise
    
    async def sign_in(self, phone: str, code: str, phone_code_hash: str, password: str = None) -> bool:
        """登录验证"""
        await self._ensure_connected()
        
        try:
            if password:
                # 两步验证
                print(f"[TG] 使用两步验证密码登录...")
                await self._client.check_password(password)
            else:
                # 验证码登录
                print(f"[TG] 使用验证码登录: {code}")
                await self._client.sign_in(phone, phone_code_hash, code)
            
            self._is_authorized = True
            print("[TG] 登录成功!")
            return True
            
        except SessionPasswordNeeded:
            print("[TG] 需要两步验证密码")
            raise RuntimeError("需要两步验证密码 (2FA)")
        except PhoneCodeInvalid:
            raise RuntimeError("验证码错误")
        except PhoneCodeExpired:
            raise RuntimeError("验证码已过期")
        except FloodWait as e:
            raise RuntimeError(f"请等待 {e.value} 秒后再尝试登录")
        except Exception as e:
            print(f"[TG] 登录失败: {e}")
            raise
    
    async def start(self) -> bool:
        """启动客户端（如果已有会话则直接登录）"""
        if not self._client:
            return False
        try:
            await self._ensure_connected()
            # 尝试获取当前用户，如果成功说明已登录
            me = await self._client.get_me()
            if me:
                self._is_authorized = True
                print(f"[TG] 已登录: {me.first_name} (@{me.username})")
                return True
        except Unauthorized:
            print("[TG] 会话已过期或未授权")
        except Exception as e:
            print(f"[TG] 启动失败: {e}")
        return False
    
    async def stop(self):
        """停止客户端"""
        async with self._lock:
            if self._client:
                try:
                    if self._client.is_connected:
                        await self._client.disconnect()
                    print("[TG] 已断开连接")
                except:
                    pass
                self._is_authorized = False
    
    async def get_me(self) -> dict:
        """获取当前用户信息 (带自动重连和缓存)"""
        if not self._client:
            return {}
            
        import time
        # 1. 检查缓存 (5分钟有效)
        async with self._cache_lock:
            if self._me_cache and (time.time() - self._me_cache_time < 300):
                return self._me_cache

        try:
            # 确保连接状态
            await self._ensure_connected()
            me = await self._client.get_me()
            if me:
                res = {
                    "id": me.id,
                    "first_name": me.first_name,
                    "last_name": me.last_name,
                    "username": me.username,
                    "phone": me.phone_number
                }
                # 2. 更新缓存
                async with self._cache_lock:
                    self._me_cache = res
                    self._me_cache_time = time.time()
                
                self._is_authorized = True
                return res
        except Unauthorized:
            self._is_authorized = False
            print("[TG] 会话已失效，需要重新登录")
            return {}
        except Exception as e:
            print(f"[TG] 获取用户信息失败: {e}")
            return {}
    
    def _convert_chat_type(self, chat: Chat) -> ChatType:
        """转换聊天类型"""
        if chat.type == PyChatType.PRIVATE:
            return ChatType.PRIVATE
        elif chat.type == PyChatType.BOT:
            return ChatType.BOT
        elif chat.type == PyChatType.GROUP:
            return ChatType.GROUP
        elif chat.type == PyChatType.SUPERGROUP:
            return ChatType.SUPERGROUP
        elif chat.type == PyChatType.CHANNEL:
            return ChatType.CHANNEL
        return ChatType.PRIVATE
    
    def get_media_type(self, msg: Message) -> Optional[MediaType]:
        """获取消息中的媒体类型"""
        if not msg:
            return None
            
        if msg.photo:
            return MediaType.PHOTO
        elif msg.video:
            return MediaType.VIDEO
        elif msg.audio:
            return MediaType.AUDIO
        elif msg.voice:
            return MediaType.VOICE
        elif msg.video_note:
            return MediaType.VIDEO_NOTE
        elif msg.document:
            return MediaType.DOCUMENT
        elif msg.sticker:
            return MediaType.STICKER
        elif msg.animation:
            return MediaType.ANIMATION
            
        return None
    
    async def get_chat(self, chat_id: Union[int, str]) -> ChatInfo:
        """获取单个对话信息 (v2.4.0)"""
        await self._ensure_connected()
        try:
            chat = await self._client.get_chat(chat_id)
            return ChatInfo(
                id=chat.id,
                title=chat.title or chat.first_name or "Unknown",
                type=self._convert_chat_type(chat),
                username=chat.username,
                members_count=chat.members_count
            )
        except Exception as e:
            logger.error(f"[TG] 获取对话 {chat_id} 失败: {e}")
            raise

    async def get_dialogs(self, limit: int = 100) -> List[ChatInfo]:
        """获取最近对话列表 (增加缓存优化)"""
        await self._ensure_connected()
        if not self._is_authorized:
            return []
        
        # 简单缓存机制 (30秒内不再重复拉取)
        import time
        if hasattr(self, '_dialogs_cache') and (time.time() - self._dialogs_last_fetch < 30):
            return self._dialogs_cache

        chats = []
        try:
            async for dialog in self._client.get_dialogs(limit=limit):
                chat = dialog.chat
                chats.append(ChatInfo(
                    id=chat.id,
                    title=chat.title or chat.first_name or "Unknown",
                    type=ChatType(chat.type.value),
                    username=chat.username,
                    members_count=chat.members_count
                ))
            
            self._dialogs_cache = chats
            self._dialogs_last_fetch = time.time()
            return chats
        except Exception as e:
            print(f"[TG] 获取对话列表出错: {e}")
            return []
    
    def get_message_link(self, chat_id: int, message_id: int, username: Optional[str] = None) -> str:
        """
        生成消息直链 (参考 telegram_media_downloader)
        1. 公开群组/频道: https://t.me/username/123
        2. 私密群组/频道: https://t.me/c/1234567890/123
        """
        if username:
            return f"https://t.me/{username}/{message_id}"
        
        # 私密链接需要去掉 -100 前缀
        clean_id = str(chat_id)
        if clean_id.startswith("-100"):
            clean_id = clean_id[4:]
        elif clean_id.startswith("-"):
            clean_id = clean_id[1:]
            
        return f"https://t.me/c/{clean_id}/{message_id}"

    def resolve_chat_id(self, chat_id_input: str) -> int:
        """
        解析并标准化 Chat ID (参考 telegram_media_downloader)
        确保私密频道/超级群组带有 -100 前缀
        """
        try:
            if not chat_id_input:
                return 0
            
            # 如果是链接，提取最后一部分
            if "t.me/" in str(chat_id_input):
                # 区分公开(t.me/username)和私密(t.me/c/12345/678)
                parts = str(chat_id_input).strip().split("/")
                if len(parts) >= 2 and parts[-2] == "c":
                    # 私密链接，倒数第二部分是 c，倒数第一部分可能是 message_id，倒数第三部分可能是 chat_id
                    # 比如 https://t.me/c/12345678/999 -> chat_id 为 12345678
                    chat_id_part = parts[-2] # 默认为 c
                    for i, p in enumerate(parts):
                        if p == "c" and i + 1 < len(parts):
                            chat_id_input = parts[i+1] # 获取 c 后面那一项
                            break
                else:
                    chat_id_input = parts[-1]
                
                if chat_id_input.isdigit():
                    pass # 继续数字处理
                else:
                    return chat_id_input # 返回用户名

            # 如果已经是数字，或者甚至是带负号的字符串
            str_id = str(chat_id_input).strip()
            
            # 这里的逻辑是：如果用户输的是 1234567890 (10位+)，很大可能是超级群组 ID
            # 如果它不是以 - 开头，且长度 >= 9，我们帮他加 -100 (私密频道 ID 转换)
            if str_id.isdigit():
                val = int(str_id)
                if val > 0 and len(str_id) >= 9:
                    return int(f"-100{str_id}")
                return val
            
            # 处理带 - 但不带 -100 的情况
            if str_id.startswith("-") and not str_id.startswith("-100") and len(str_id) > 10:
                 # 已经是负数但没加 -100 的 10 位以上 ID 通常也要补全
                 return int(f"-100{str_id[1:]}")

            return int(str_id)
        except (ValueError, TypeError):
            # 如果无法转为数字，可能是用户名，由 Pyrogram 自行解析
            return str(chat_id_input).strip()
    
    async def get_chat_history(
        self,
        chat_id: int,
        limit: int = 0,
        offset_id: int = 0,
        min_id: int = 0,
        max_id: int = 0,
        reverse: bool = False
    ) -> AsyncGenerator[Message, None]:
        """获取聊天历史 (支持正序/倒序)"""
        await self._ensure_connected()
        if not self._is_authorized:
            return
        
        try:
            async for message in self._client.get_chat_history(
                chat_id,
                limit=limit,
                offset_id=offset_id,
                reverse=reverse
            ):
                # 过滤消息范围
                if max_id and message.id > max_id:
                    if reverse: break # 正序流下遇到比最大值还大的，后面都没意义了
                    continue
                if min_id and message.id < min_id:
                    if not reverse: break # 倒序流下遇到比最小值还小的，后面都没意义了
                    continue
                yield message
        except Exception as e:
            logger.error(f"[TG] 获取聊天历史出错: {e}")
    
    async def get_message_by_id(self, chat_id: int, message_id: int) -> Optional[Message]:
        """获取单条消息（用于刷新 file_reference，增加缓存避免 API 损耗）"""
        await self._ensure_connected()
        if not self._is_authorized:
            return None
            
        cache_key = (chat_id, message_id)
        import time
        
        # 1. 检查缓存 (1小时内有效，因为 file_reference 至少维持一段时间)
        async with self._cache_lock:
            if cache_key in self._message_cache:
                msg, ts = self._message_cache[cache_key]
                if time.time() - ts < 3600:
                    return msg
        
        try:
            # 2. 尝试解析 Peer 问题 (Peer id invalid 等)
            # 尝试直接获取
            messages = await self._client.get_messages(chat_id, message_id)
            msg = messages if isinstance(messages, Message) else None
            
            # 3. 写入缓存
            if msg:
                async with self._cache_lock:
                    self._message_cache[cache_key] = (msg, time.time())
                return msg
            
            return None
        except Exception as e:
            error_str = str(e)
            # 如果遇到 Peer id invalid，尝试先获取一次 Chat 以强制解析并缓存 Peer
            if "Peer id invalid" in error_str or "Could not find the input entity" in error_str:
                logger.warning(f"获取消息遇到 Peer 问题，尝试强制解析 Chat ID: {chat_id}")
                try:
                    logger.info(f"直接解析失败，尝试获取 Chat ID: {chat_id}")
                    await self._client.get_chat(chat_id)
                    # 再次尝试获取消息
                    messages = await self._client.get_messages(chat_id, message_id)
                    return messages if isinstance(messages, Message) else None
                except Exception as ex:
                    logger.warning(f"强制 get_chat 失败 ({ex})，尝试终极方案：遍历对话列表...")
                    # 终极方案：获取最近的对话列表，这会强制下载所有 Peer 实体
                    try:
                        async for dialog in self._client.get_dialogs(limit=50):
                            if dialog.chat.id == chat_id:
                                logger.info(f"通过对话列表成功定位 Peer: {chat_id}")
                        # 定位后再次尝试
                        messages = await self._client.get_messages(chat_id, message_id)
                        return messages if isinstance(messages, Message) else None
                    except Exception as final_ex:
                        logger.error(f"终极方案解析仍无法获取消息: {final_ex}")
            else:
                logger.error(f"获取消息失败: {e}")
            return None
    
    async def download_media(
        self,
        message: Message,
        file_path: str,
        progress_callback=None
    ) -> Optional[str]:
        """下载媒体文件"""
        await self._ensure_connected()
        if not self._client:
            return None
        
        try:
            result = await self._client.download_media(
                message,
                file_name=file_path,
                progress=progress_callback
            )
            return result
        except Exception as e:
            # [Fast Response] 不在这里捕获 FloodWait，直接抛出，让 exporter 层的自适应逻辑第一时间响应
            raise

    async def download_media_parallel(
        self,
        message: Message,
        file_path: str,
        file_size: int,
        parallel_connections: int = 4,
        progress_callback=None,
        cancel_check=None,
        task_semaphore: Optional[asyncio.Semaphore] = None,
        enable_parallel: bool = True
    ) -> Optional[str]:
        """
        高性能并行分块下载 (v1.5.0)
        
        对于大文件 (>10MB) 使用多连接并发下载，
        突破 Telegram 单连接限速，速度提升 3-8 倍。
        
        Args:
            message: 消息对象
            file_path: 目标文件路径
            file_size: 文件大小 (字节)
            parallel_connections: 并行连接数 (免费账号建议 3-4)
            progress_callback: 进度回调 (current, total)
            cancel_check: 取消检查函数
            task_semaphore: 全局任务信号量 (可选)
            
        Returns:
            成功返回文件路径，失败返回 None
        """
        await self._ensure_connected()
        if not self._client:
            return None
        
        from pathlib import Path
        from .parallel_downloader import ParallelChunkDownloader
        
        try:
            downloader = ParallelChunkDownloader(
                client=self._client,
                parallel_connections=parallel_connections,
                task_semaphore=task_semaphore,
                enable_parallel=enable_parallel
            )
            
            success, error = await downloader.download(
                message=message,
                file_path=Path(file_path),
                file_size=file_size,
                progress_callback=progress_callback,
                cancel_check=cancel_check
            )
            
            if success:
                logger.info(f"并行下载成功: {file_path}")
                return file_path
            else:
                # 并行下载失败或文件过小，回退到常规下载 (v1.6.7.3 日志优化)
                error_str = error or ""
                if "未启用" in error_str or "文件过小" in error_str:
                    logger.debug(f"并行下载由于策略回退: {error_str}, 使用常规下载: {file_path}")
                else:
                    logger.warning(f"并行下载失败 ({error_str})，回退到常规下载")
                
                return await self.download_media(message, file_path, progress_callback)
                    
        except Exception as e:
            logger.error(f"并行下载异常: {e}")
            # 异常时也回退到常规下载
            return await self.download_media(message, file_path, progress_callback)


def apply_pyrogram_patch():
    """
    深度补丁：强行拦截 Pyrogram 内部限速睡眠逻辑。
    即使 sleep_threshold=0，某些情况下 Pyrogram Session 仍可能触发内部 sleep。
    此补丁直接重写 Session.handle_flood，确保一旦触发 FloodWait 立即向上层抛出异常，
    从而激活 ExportManager 的自适应降压逻辑。
    """
    import pyrogram.session.session as pyrogram_session
    from pyrogram.errors import FloodWait
    
    # 记录原始方法以便参考 (可选)
    # _original_handle_flood = pyrogram_session.Session.handle_flood

    async def patched_handle_flood(self, flood_wait):
        # 拒绝进入任何内部睡眠，直接把锅甩级上层业务逻辑处理
        logger.warning(f"硬拦截补丁拦截到限速信号 ({flood_wait.value}s)，强制抛出异常以激活降速引擎。")
        raise flood_wait

    pyrogram_session.Session.handle_flood = patched_handle_flood
    logger.info("已应用 Pyrogram Session.handle_flood 深度限速拦截补丁")

# 全局实例
telegram_client = TelegramClient()

# 应用补丁
apply_pyrogram_patch()
