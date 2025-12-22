"""
TG Export - JSON 导出器
生成机器可读的 JSON 格式
"""
import json
from pathlib import Path
from typing import List
from datetime import datetime

from ..models import ExportTask, ChatInfo, MessageInfo


class DateTimeEncoder(json.JSONEncoder):
    """日期时间 JSON 编码器"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


async def export(
    task: ExportTask,
    chats: List[ChatInfo],
    messages: List[MessageInfo],
    export_path: Path
) -> str:
    """
    导出为 JSON 格式
    
    生成结构:
    {
        "export_info": {...},
        "chats": [...],
        "messages": {...}
    }
    """
    # 按聊天分组消息
    messages_by_chat = {}
    for msg in messages:
        # 这里需要chat_id信息，暂时用文件路径分组
        pass
    
    # 构建导出数据
    export_data = {
        "export_info": {
            "app": "TG Export",
            "version": "1.2.8",
            "exported_at": datetime.now().isoformat(),
            "task_name": task.name,
            "options": task.options.model_dump()
        },
        "statistics": {
            "total_chats": task.total_chats,
            "total_messages": task.processed_messages,
            "total_media": task.downloaded_media,
            "total_size_bytes": task.downloaded_size
        },
        "chats": [
            {
                "id": chat.id,
                "title": chat.title,
                "type": chat.type.value,
                "username": chat.username,
                "members_count": chat.members_count
            }
            for chat in chats
        ],
        "messages": [
            {
                "id": msg.id,
                "date": msg.date.isoformat() if msg.date else None,
                "from_user_id": msg.from_user_id,
                "from_user_name": msg.from_user_name,
                "text": msg.text,
                "media": {
                    "type": msg.media_type.value if msg.media_type else None,
                    "file": msg.media_path,
                    "file_name": msg.file_name,
                    "file_size": msg.file_size
                } if msg.media_type else None,
                "reply_to": msg.reply_to_message_id
            }
            for msg in messages
        ]
    }
    
    # 写入文件
    output_file = export_path / "export.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2, cls=DateTimeEncoder)
    
    return str(output_file)
