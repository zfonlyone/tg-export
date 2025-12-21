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

from ..config import settings
from ..models import ChatInfo, ChatType, MessageInfo, MediaType


class TelegramClient:
    """Telegram 客户端封装"""
    
    def __init__(self):
        self._client: Optional[Client] = None
        self._is_authorized = False
    
    @property
    def is_authorized(self) -> bool:
        return self._is_authorized
    
    async def init(self, api_id: int, api_hash: str, session_name: str = "tg_export"):
        """初始化客户端"""
        session_path = settings.SESSIONS_DIR / session_name
        self._client = Client(
            name=str(session_path),
            api_id=api_id,
            api_hash=api_hash,
            workdir=str(settings.SESSIONS_DIR)
        )
    
    async def start(self) -> bool:
        """启动客户端"""
        if not self._client:
            return False
        try:
            await self._client.start()
            self._is_authorized = True
            return True
        except Exception as e:
            print(f"启动失败: {e}")
            return False
    
    async def stop(self):
        """停止客户端"""
        if self._client:
            await self._client.stop()
            self._is_authorized = False
    
    async def send_code(self, phone: str) -> str:
        """发送验证码"""
        if not self._client:
            raise RuntimeError("客户端未初始化")
        sent_code = await self._client.send_code(phone)
        return sent_code.phone_code_hash
    
    async def sign_in(self, phone: str, code: str, phone_code_hash: str, password: str = None) -> bool:
        """登录验证"""
        try:
            if password:
                await self._client.check_password(password)
            else:
                await self._client.sign_in(phone, phone_code_hash, code)
            self._is_authorized = True
            return True
        except Exception as e:
            print(f"登录失败: {e}")
            return False
    
    async def get_me(self) -> dict:
        """获取当前用户信息"""
        if not self._client:
            return {}
        me = await self._client.get_me()
        return {
            "id": me.id,
            "first_name": me.first_name,
            "last_name": me.last_name,
            "username": me.username,
            "phone": me.phone_number
        }
    
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
    
    async def get_dialogs(self) -> List[ChatInfo]:
        """获取所有对话列表"""
        if not self._client:
            return []
        
        dialogs: List[ChatInfo] = []
        async for dialog in self._client.get_dialogs():
            chat = dialog.chat
            dialogs.append(ChatInfo(
                id=chat.id,
                title=chat.title or chat.first_name or "未知",
                type=self._convert_chat_type(chat),
                username=chat.username,
                members_count=chat.members_count
            ))
        return dialogs
    
    async def get_chat_history(
        self,
        chat_id: int,
        limit: int = 0,
        offset_date: int = None
    ) -> AsyncGenerator[Message, None]:
        """获取聊天历史记录"""
        if not self._client:
            return
        
        async for message in self._client.get_chat_history(
            chat_id=chat_id,
            limit=limit,
            offset_date=offset_date
        ):
            yield message
    
    async def get_messages_count(self, chat_id: int) -> int:
        """获取消息总数"""
        if not self._client:
            return 0
        try:
            # 获取第一条消息来估算总数
            async for msg in self._client.get_chat_history(chat_id, limit=1):
                return msg.id
        except:
            return 0
        return 0
    
    async def get_message_by_id(self, chat_id: int, message_id: int) -> Optional[Message]:
        """根据消息ID获取消息（用于刷新文件引用）"""
        if not self._client:
            return None
        try:
            messages = await self._client.get_messages(chat_id, message_id)
            if messages:
                return messages if isinstance(messages, Message) else messages[0]
            return None
        except Exception as e:
            print(f"获取消息失败: {e}")
            return None
    
    async def download_media(
        self,
        message: Message,
        file_path: Path,
        progress_callback = None
    ) -> Optional[str]:
        """下载媒体文件"""
        if not self._client or not message.media:
            return None
        
        # 直接调用下载，不捕获异常，让上层处理重试逻辑
        path = await self._client.download_media(
            message,
            file_name=str(file_path),
            progress=progress_callback
        )
        return path
    
    def get_media_type(self, message: Message) -> Optional[MediaType]:
        """获取消息的媒体类型"""
        if message.photo:
            return MediaType.PHOTO
        elif message.video:
            return MediaType.VIDEO
        elif message.audio:
            return MediaType.AUDIO
        elif message.voice:
            return MediaType.VOICE
        elif message.video_note:
            return MediaType.VIDEO_NOTE
        elif message.document:
            return MediaType.DOCUMENT
        elif message.sticker:
            return MediaType.STICKER
        elif message.animation:
            return MediaType.ANIMATION
        return None


# 全局客户端实例
telegram_client = TelegramClient()
