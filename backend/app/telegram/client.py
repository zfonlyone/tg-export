"""
TG Export - Telegram 客户端
使用 Pyrogram 异步库连接 Telegram
"""
import asyncio
from pathlib import Path
from typing import Optional, List, AsyncGenerator
from pyrogram import Client
from pyrogram.types import Chat, Message, Dialog
from pyrogram.enums import ChatType as PyChatType
from pyrogram.errors import SessionPasswordNeeded

from ..config import settings
from ..models import ChatInfo, ChatType, MessageInfo, MediaType


class TelegramClient:
    """Telegram 客户端封装"""
    
    def __init__(self):
        self._client: Optional[Client] = None
        self._is_authorized = False
        self._api_id: Optional[int] = None
        self._api_hash: Optional[str] = None
        self._phone: Optional[str] = None
        self._phone_code_hash: Optional[str] = None
    
    @property
    def is_authorized(self) -> bool:
        return self._is_authorized
    
    @property
    def is_initialized(self) -> bool:
        return self._client is not None
    
    async def init(self, api_id: int, api_hash: str, session_name: str = "tg_export"):
        """初始化客户端（只创建实例，不连接）"""
        # 保存凭证
        self._api_id = api_id
        self._api_hash = api_hash
        
        # 如果已有客户端，先清理
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
            workdir=str(settings.SESSIONS_DIR)
        )
        print(f"[TG] 客户端已初始化: api_id={api_id}")
    
    async def _ensure_connected(self):
        """确保客户端已连接"""
        if not self._client:
            raise RuntimeError("客户端未初始化，请先配置 API ID 和 API Hash")
        
        if not self._client.is_connected:
            print("[TG] 正在连接...")
            await self._client.connect()
            print("[TG] 已连接")
    
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
        except Exception as e:
            print(f"[TG] 启动失败: {e}")
        return False
    
    async def stop(self):
        """停止客户端"""
        if self._client:
            try:
                if self._client.is_connected:
                    await self._client.disconnect()
                print("[TG] 已断开连接")
            except:
                pass
            self._is_authorized = False
    
    async def get_me(self) -> dict:
        """获取当前用户信息"""
        if not self._client or not self._is_authorized:
            return {}
        try:
            me = await self._client.get_me()
            return {
                "id": me.id,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "username": me.username,
                "phone": me.phone_number
            }
        except:
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
    
    async def get_dialogs(self, limit: int = 100) -> List[ChatInfo]:
        """获取对话列表"""
        if not self._client or not self._is_authorized:
            return []
        
        dialogs = []
        async for dialog in self._client.get_dialogs(limit):
            chat = dialog.chat
            dialogs.append(ChatInfo(
                id=chat.id,
                title=chat.title or chat.first_name or "Unknown",
                type=self._convert_chat_type(chat),
                username=chat.username,
                members_count=getattr(chat, 'members_count', None),
                photo_url=None
            ))
        return dialogs
    
    async def get_chat_history(
        self,
        chat_id: int,
        limit: int = 0,
        offset_id: int = 0,
        min_id: int = 0,
        max_id: int = 0
    ) -> AsyncGenerator[Message, None]:
        """获取聊天历史"""
        if not self._client or not self._is_authorized:
            return
        
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
    
    async def get_message_by_id(self, chat_id: int, message_id: int) -> Optional[Message]:
        """获取单条消息（用于刷新 file_reference）"""
        if not self._client or not self._is_authorized:
            return None
        try:
            messages = await self._client.get_messages(chat_id, message_id)
            return messages if isinstance(messages, Message) else None
        except Exception as e:
            print(f"获取消息失败: {e}")
            return None
    
    async def download_media(
        self,
        message: Message,
        file_path: str,
        progress_callback=None
    ) -> Optional[str]:
        """下载媒体文件"""
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
            # 抛出异常让上层处理重试
            raise


# 全局实例
telegram_client = TelegramClient()
