"""
TG Export - HTML 导出器
生成类似 Telegram Desktop 官方导出的 HTML 格式
"""
from pathlib import Path
from typing import List, Dict
from datetime import datetime
import html

from ..models import ExportTask, ChatInfo, MessageInfo, MediaType


# HTML 模板 - 类似 Telegram Desktop 官方风格
HTML_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - TG Export</title>
    <style>
        :root {{
            --bg-color: #ffffff;
            --text-color: #000000;
            --message-bg: #ffffff;
            --message-border: #e0e0e0;
            --link-color: #168acd;
            --time-color: #999999;
            --name-color: #168acd;
        }}
        
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg-color: #212121;
                --text-color: #ffffff;
                --message-bg: #2d2d2d;
                --message-border: #404040;
                --link-color: #71baf2;
                --time-color: #888888;
                --name-color: #71baf2;
            }}
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            font-size: 14px;
            line-height: 1.5;
            background-color: var(--bg-color);
            color: var(--text-color);
            padding: 20px;
            max-width: 800px;
            margin: 0 auto;
        }}
        
        .header {{
            text-align: center;
            padding: 20px 0;
            border-bottom: 1px solid var(--message-border);
            margin-bottom: 20px;
        }}
        
        .header h1 {{
            font-size: 24px;
            margin-bottom: 10px;
        }}
        
        .header .info {{
            color: var(--time-color);
            font-size: 13px;
        }}
        
        .chat-info {{
            background: var(--message-bg);
            border: 1px solid var(--message-border);
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 20px;
        }}
        
        .chat-info h2 {{
            font-size: 18px;
            margin-bottom: 10px;
        }}
        
        .chat-info .meta {{
            color: var(--time-color);
            font-size: 13px;
        }}
        
        .messages {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        
        .message {{
            background: var(--message-bg);
            border: 1px solid var(--message-border);
            border-radius: 8px;
            padding: 12px;
        }}
        
        .message .header-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }}
        
        .message .from {{
            font-weight: 600;
            color: var(--name-color);
        }}
        
        .message .date {{
            font-size: 12px;
            color: var(--time-color);
        }}
        
        .message .text {{
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
        
        .message .media {{
            margin-top: 10px;
        }}
        
        .message .media img {{
            max-width: 100%;
            border-radius: 4px;
        }}
        
        .message .media video {{
            max-width: 100%;
            border-radius: 4px;
        }}
        
        .message .media audio {{
            width: 100%;
        }}
        
        .message .media .file {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            background: var(--bg-color);
            border: 1px solid var(--message-border);
            border-radius: 4px;
            text-decoration: none;
            color: var(--link-color);
        }}
        
        .message .media .file:hover {{
            background: var(--message-border);
        }}
        
        .message .reply {{
            font-size: 12px;
            color: var(--time-color);
            border-left: 2px solid var(--link-color);
            padding-left: 8px;
            margin-bottom: 6px;
        }}
        
        .nav {{
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid var(--message-border);
        }}
        
        .nav a {{
            color: var(--link-color);
            text-decoration: none;
        }}
        
        .nav a:hover {{
            text-decoration: underline;
        }}
        
        .stats {{
            text-align: center;
            margin: 20px 0;
            padding: 15px;
            background: var(--message-bg);
            border-radius: 8px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📥 TG Export</h1>
        <div class="info">导出时间: {export_time}</div>
    </div>
    
    {content}
    
    <div class="stats">
        <strong>导出统计</strong><br>
        聊天: {total_chats} | 消息: {total_messages} | 媒体: {total_media}
    </div>
    
    <div class="nav">
        <a href="index.html">首页</a>
        <a href="export.json">JSON 数据</a>
    </div>
</body>
</html>
'''

CHAT_TEMPLATE = '''
<div class="chat-info">
    <h2>{chat_title}</h2>
    <div class="meta">
        类型: {chat_type} | ID: {chat_id}
    </div>
</div>

<div class="messages">
{messages_html}
</div>
'''

MESSAGE_TEMPLATE = '''
<div class="message" id="msg-{msg_id}">
    {reply_html}
    <div class="header-row">
        <span class="from">{from_name}</span>
        <span class="date">{date}</span>
    </div>
    {text_html}
    {media_html}
</div>
'''


def _escape_html(text: str) -> str:
    """转义 HTML 特殊字符"""
    if not text:
        return ""
    return html.escape(text)


def _format_date(dt: datetime) -> str:
    """格式化日期"""
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _get_media_html(msg: MessageInfo, base_path: str = "") -> str:
    """生成媒体 HTML"""
    if not msg.media_type or not msg.media_path:
        return ""
    
    media_path = msg.media_path
    
    if msg.media_type == MediaType.PHOTO:
        return f'<div class="media"><img src="{media_path}" alt="photo" loading="lazy"></div>'
    
    elif msg.media_type == MediaType.VIDEO:
        return f'<div class="media"><video src="{media_path}" controls></video></div>'
    
    elif msg.media_type in [MediaType.VOICE, MediaType.AUDIO]:
        return f'<div class="media"><audio src="{media_path}" controls></audio></div>'
    
    elif msg.media_type == MediaType.VIDEO_NOTE:
        return f'<div class="media"><video src="{media_path}" controls style="border-radius: 50%; width: 200px; height: 200px; object-fit: cover;"></video></div>'
    
    elif msg.media_type == MediaType.ANIMATION:
        return f'<div class="media"><video src="{media_path}" autoplay loop muted></video></div>'
    
    elif msg.media_type == MediaType.STICKER:
        return f'<div class="media"><img src="{media_path}" alt="sticker" style="max-width: 200px;"></div>'
    
    else:
        file_name = msg.file_name or "文件"
        file_size = f" ({_format_size(msg.file_size)})" if msg.file_size else ""
        return f'<div class="media"><a href="{media_path}" class="file">📎 {_escape_html(file_name)}{file_size}</a></div>'


def _format_size(size: int) -> str:
    """格式化文件大小"""
    if not size:
        return ""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    else:
        return f"{size / 1024 / 1024 / 1024:.1f} GB"


def _generate_message_html(msg: MessageInfo) -> str:
    """生成单条消息的 HTML"""
    reply_html = ""
    if msg.reply_to_message_id:
        reply_html = f'<div class="reply">回复消息 #{msg.reply_to_message_id}</div>'
    
    text_html = ""
    if msg.text:
        text_html = f'<div class="text">{_escape_html(msg.text)}</div>'
    
    media_html = _get_media_html(msg)
    
    return MESSAGE_TEMPLATE.format(
        msg_id=msg.id,
        reply_html=reply_html,
        from_name=_escape_html(msg.from_user_name or "未知"),
        date=_format_date(msg.date),
        text_html=text_html,
        media_html=media_html
    )


async def export(
    task: ExportTask,
    chats: List[ChatInfo],
    messages: List[MessageInfo],
    export_path: Path
) -> str:
    """
    导出为 HTML 格式
    类似 Telegram Desktop 官方导出样式
    """
    # 生成索引页
    index_content = ""
    
    # 按聊天列表生成链接
    index_content += '<div class="chat-info"><h2>导出的聊天</h2></div>'
    index_content += '<div class="messages">'
    
    chat_type_names = {
        "private": "私聊",
        "bot": "机器人",
        "group": "群组",
        "supergroup": "超级群组",
        "channel": "频道"
    }
    
    for chat in chats:
        chat_filename = _safe_filename(chat.title) + ".html"
        type_name = chat_type_names.get(chat.type.value, chat.type.value)
        index_content += f'''
        <div class="message">
            <div class="header-row">
                <span class="from"><a href="{chat_filename}">{_escape_html(chat.title)}</a></span>
                <span class="date">{type_name}</span>
            </div>
        </div>
        '''
    
    index_content += '</div>'
    
    # 写入索引页
    index_html = HTML_TEMPLATE.format(
        title="导出列表",
        export_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        content=index_content,
        total_chats=task.total_chats,
        total_messages=task.processed_messages,
        total_media=task.downloaded_media
    )
    
    index_file = export_path / "index.html"
    with open(index_file, "w", encoding="utf-8") as f:
        f.write(index_html)
    
    # 为每个聊天生成独立页面
    # (这里简化处理，实际应该按聊天分组消息)
    if messages:
        messages_html = "\n".join(_generate_message_html(msg) for msg in messages)
        
        content = CHAT_TEMPLATE.format(
            chat_title="所有消息",
            chat_type="混合",
            chat_id="all",
            messages_html=messages_html
        )
        
        messages_file = export_path / "messages.html"
        messages_page = HTML_TEMPLATE.format(
            title="所有消息",
            export_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            content=content,
            total_chats=task.total_chats,
            total_messages=task.processed_messages,
            total_media=task.downloaded_media
        )
        
        with open(messages_file, "w", encoding="utf-8") as f:
            f.write(messages_page)
    
    return str(index_file)


def _safe_filename(name: str) -> str:
    """生成安全的文件名"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name[:50]
