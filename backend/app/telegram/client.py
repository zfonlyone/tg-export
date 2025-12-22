"""
TG Export - Telegram 客户端
使用 Pyrogram 异步库连接 Telegram
"""
import asyncio
import os
import logging
from pathlib import Path
from typing import Optional, List, AsyncGenerator
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
    
    @property
    def is_authorized(self) -> bool:
        return self._is_authorized
    
    @property
    def is_initialized(self) -> bool:
        return self._client is not None
    
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
            self._client = Client(
                name=str(session_path),
                api_id=api_id,
                api_hash=api_hash,
                workdir=str(settings.SESSIONS_DIR),
                device_model="TG Export Web",
                system_version="Linux",
                sleep_threshold=60
            )
            print(f"[TG] 客户端已初始化: api_id={api_id}")
    
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
        """获取当前用户信息 (带自动重连)"""
        if not self._client:
            return {}
        try:
            # 确保连接状态
            await self._ensure_connected()
            me = await self._client.get_me()
            if me:
                self._is_authorized = True
                return {
                    "id": me.id,
                    "first_name": me.first_name,
                    "last_name": me.last_name,
                    "username": me.username,
                    "phone": me.phone_number
                }
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
        max_id: int = 0
    ) -> AsyncGenerator[Message, None]:
        """获取聊天历史"""
        await self._ensure_connected()
        if not self._is_authorized:
            return
        
        try:
            async for message in self._client.get_chat_history(
                chat_id,
                limit=limit,
                offset_id=offset_id
            ):
                # 过滤消息范围
                if min_id and message.id < min_id:
                    continue
                if max_id and message.id > max_id:
                    break
                yield message
        except Exception as e:
            print(f"[TG] 获取聊天历史出错: {e}")
    
    async def get_message_by_id(self, chat_id: int, message_id: int) -> Optional[Message]:
        """获取单条消息（用于刷新 file_reference）"""
        await self._ensure_connected()
        if not self._is_authorized:
            return None
        try:
            # 尝试直接获取
            messages = await self._client.get_messages(chat_id, message_id)
            return messages if isinstance(messages, Message) else None
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
        except FloodWait as e:
            print(f"[TG] 下载媒体遇到限制，需等待 {e.value} 秒")
            await asyncio.sleep(e.value)
            # 重试一次
            return await self.download_media(message, file_path, progress_callback)
        except Exception as e:
            # 抛出异常让上层处理重试
            raise


# 全局实例
telegram_client = TelegramClient()
