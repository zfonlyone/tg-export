"""
TG Export - HTML 导出器
生成与 Telegram Desktop 官方导出完全兼容的 HTML 格式
"""
from pathlib import Path
from typing import List, Dict
from datetime import datetime
import html
import shutil

from ..models import ExportTask, ChatInfo, MessageInfo, MediaType
from ..config import settings


def _escape_html(text: str) -> str:
    """转义 HTML 特殊字符"""
    if not text:
        return ""
    return html.escape(text).replace('\n', '<br>')


def _format_date(dt: datetime) -> str:
    """格式化日期时间"""
    if not dt:
        return ""
    return dt.strftime("%H:%M")


def _format_date_title(dt: datetime) -> str:
    """格式化日期时间标题"""
    if not dt:
        return ""
    return dt.strftime("%d.%m.%Y %H:%M:%S")


def _format_date_header(dt: datetime) -> str:
    """格式化日期头"""
    if not dt:
        return ""
    return dt.strftime("%d %B %Y")


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


def _get_userpic_class(user_id: int) -> str:
    """获取用户头像颜色类"""
    colors = ['userpic1', 'userpic2', 'userpic3', 'userpic4', 'userpic5', 'userpic6', 'userpic7', 'userpic8']
    return colors[abs(user_id or 0) % len(colors)]


def _get_initials(name: str) -> str:
    """获取名称首字"""
    if not name:
        return "?"
    return name[0].upper()


def _get_media_type_class(media_type: MediaType) -> str:
    """获取媒体类型的 CSS 类"""
    mapping = {
        MediaType.PHOTO: 'media_photo',
        MediaType.VIDEO: 'media_video',
        MediaType.AUDIO: 'media_audio_file',
        MediaType.VOICE: 'media_voice_message',
        MediaType.VIDEO_NOTE: 'media_video',
        MediaType.DOCUMENT: 'media_file',
        MediaType.STICKER: 'media_photo',
        MediaType.ANIMATION: 'media_video',
    }
    return mapping.get(media_type, 'media_file')


def _generate_message_html(msg: MessageInfo, is_joined: bool = False) -> str:
    """生成单条消息的 HTML - 官方格式"""
    joined_class = 'joined' if is_joined else ''
    
    # 用户头像
    userpic_html = ''
    from_name_html = ''
    if not is_joined:
        userpic_class = _get_userpic_class(msg.from_user_id)
        initials = _get_initials(msg.from_user_name)
        userpic_html = f'''
      <div class="pull_left userpic_wrap">
       <div class="userpic {userpic_class}" style="width: 42px; height: 42px">
        <div class="initials" style="line-height: 42px">{initials}</div>
       </div>
      </div>'''
        from_name_html = f'''
       <div class="from_name">
{_escape_html(msg.from_user_name or "未知")} 
       </div>'''
    
    # 媒体内容
    media_html = ''
    if msg.media_type and msg.file_name:
        media_class = _get_media_type_class(msg.media_type)
        file_size = _format_size(msg.file_size) if msg.file_size else ''
        
        if msg.media_path:
            # 已下载
            if msg.media_type == MediaType.PHOTO:
                media_html = f'''
       <div class="media_wrap clearfix">
        <a class="photo_wrap clearfix pull_left" href="{msg.media_path}">
         <img class="photo" src="{msg.media_path}" style="max-width: 300px;">
        </a>
       </div>'''
            elif msg.media_type == MediaType.VIDEO:
                media_html = f'''
       <div class="media_wrap clearfix">
        <div class="video_file_wrap clearfix pull_left">
         <video class="video_file" src="{msg.media_path}" controls style="max-width: 400px;"></video>
        </div>
       </div>'''
            elif msg.media_type in [MediaType.VOICE, MediaType.AUDIO]:
                media_html = f'''
       <div class="media_wrap clearfix">
        <audio src="{msg.media_path}" controls></audio>
       </div>'''
            else:
                media_html = f'''
       <div class="media_wrap clearfix">
        <div class="media clearfix pull_left {media_class}">
         <div class="fill pull_left"></div>
         <div class="body">
          <div class="title bold"><a href="{msg.media_path}">{_escape_html(msg.file_name)}</a></div>
          <div class="status details">{file_size}</div>
         </div>
        </div>
       </div>'''
        else:
            # 未下载
            media_html = f'''
       <div class="media_wrap clearfix">
        <div class="media clearfix pull_left {media_class}">
         <div class="fill pull_left"></div>
         <div class="body">
          <div class="title bold">{_escape_html(msg.file_name)}</div>
          <div class="description">Not downloaded</div>
          <div class="status details">{file_size}</div>
         </div>
        </div>
       </div>'''
    
    # 文本内容
    text_html = ''
    if msg.text:
        text_html = f'''
       <div class="text">{_escape_html(msg.text)}</div>'''
    
    return f'''
     <div class="message default clearfix {joined_class}" id="message{msg.id}">
{userpic_html}
      <div class="body">
       <div class="pull_right date details" title="{_format_date_title(msg.date)}">{_format_date(msg.date)}</div>
{from_name_html}
{media_html}
{text_html}
      </div>
     </div>
'''


async def export(
    task: ExportTask,
    chats: List[ChatInfo],
    messages: List[MessageInfo],
    export_path: Path
) -> str:
    """
    导出为 HTML 格式
    完全兼容 Telegram Desktop 官方导出
    """
    # 获取模板目录
    templates_dir = Path(__file__).parent / "templates"
    
    # 复制静态资源
    if templates_dir.exists():
        for folder in ['css', 'js', 'images']:
            src = templates_dir / folder
            dst = export_path / folder
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)
    
    # 创建 lists 目录
    lists_dir = export_path / "lists"
    lists_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建 chats 目录
    chats_dir = export_path / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成聊天列表页面
    chat_links = []
    for chat in chats:
        chat_folder = f"chat_{abs(chat.id)}"
        chat_links.append(f'''
     <a class="entry block_link clearfix" href="../chats/{chat_folder}/messages.html">
      <div class="pull_left userpic_wrap">
       <div class="userpic {_get_userpic_class(chat.id)}" style="width: 48px; height: 48px">
        <div class="initials" style="line-height: 48px">{_get_initials(chat.title)}</div>
       </div>
      </div>
      <div class="body">
       <div class="name bold">{_escape_html(chat.title)}</div>
       <div class="details">{chat.type.value}</div>
      </div>
     </a>''')
    
    chats_list_html = f'''<!DOCTYPE html>
<html>
 <head>
  <meta charset="utf-8"/>
  <title>Chats</title>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <link href="../css/style.css" rel="stylesheet"/>
  <script src="../js/script.js" type="text/javascript"></script>
 </head>
 <body onload="CheckLocation();">
  <div class="page_wrap list_page">
   <div class="page_header">
    <a class="content block_link" href="../export_results.html" onclick="return GoBack(this)">
     <div class="text bold">Chats</div>
    </a>
   </div>
   <div class="page_body">
    <div class="entry_list">
{''.join(chat_links)}
    </div>
   </div>
  </div>
 </body>
</html>'''
    
    with open(lists_dir / "chats.html", "w", encoding="utf-8") as f:
        f.write(chats_list_html)
    
    # 为每个聊天生成消息页面
    # 按聊天ID分组消息
    messages_by_chat: Dict[int, List[MessageInfo]] = {}
    for msg in messages:
        chat_id = msg.from_user_id or 0  # 临时使用
        # 实际应该从消息中获取 chat_id
        messages_by_chat.setdefault(0, []).append(msg)
    
    for chat in chats:
        chat_folder = chats_dir / f"chat_{abs(chat.id)}"
        chat_folder.mkdir(parents=True, exist_ok=True)
        
        # 获取该聊天的消息
        chat_messages = [m for m in messages if True]  # 暂时使用所有消息
        
        # 生成消息 HTML
        messages_html_parts = []
        last_date = None
        last_user = None
        
        for msg in chat_messages:
            # 添加日期分隔
            if msg.date:
                msg_date = msg.date.date()
                if msg_date != last_date:
                    messages_html_parts.append(f'''
     <div class="message service" id="message-date-{msg.id}">
      <div class="body details">{_format_date_header(msg.date)}</div>
     </div>''')
                    last_date = msg_date
                    last_user = None
            
            # 判断是否连续消息
            is_joined = (msg.from_user_id == last_user)
            messages_html_parts.append(_generate_message_html(msg, is_joined))
            last_user = msg.from_user_id
        
        messages_page_html = f'''<!DOCTYPE html>
<html>
 <head>
  <meta charset="utf-8"/>
  <title>{_escape_html(chat.title)}</title>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <link href="../../css/style.css" rel="stylesheet"/>
  <script src="../../js/script.js" type="text/javascript"></script>
 </head>
 <body onload="CheckLocation();">
  <div class="page_wrap">
   <div class="page_header">
    <a class="content block_link" href="../../lists/chats.html" onclick="return GoBack(this)">
     <div class="text bold">{_escape_html(chat.title)}</div>
    </a>
   </div>
   <div class="page_body chat_page">
    <div class="history">
{''.join(messages_html_parts)}
    </div>
   </div>
  </div>
 </body>
</html>'''
        
        with open(chat_folder / "messages.html", "w", encoding="utf-8") as f:
            f.write(messages_page_html)
    
    # 生成入口页面
    export_results_html = f'''<!DOCTYPE html>
<html>
 <head>
  <meta charset="utf-8"/>
  <title>Exported Data</title>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <link href="css/style.css" rel="stylesheet"/>
  <script src="js/script.js" type="text/javascript"></script>
 </head>
 <body onload="CheckLocation();">
  <div class="page_wrap">
   <div class="page_header">
    <div class="content">
     <div class="text bold">Exported Data</div>
    </div>
   </div>
   <div class="page_body">
    <div class="sections">
     <a class="section block_link chats" href="lists/chats.html#allow_back">
      <div class="counter details">{len(chats)}</div>
      <div class="label bold">Chats</div>
     </a>
    </div>
    <div class="page_about details with_divider">
导出时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br>
消息数: {task.processed_messages} | 媒体数: {task.downloaded_media}
    </div>
   </div>
  </div>
 </body>
</html>'''
    
    with open(export_path / "export_results.html", "w", encoding="utf-8") as f:
        f.write(export_results_html)
    
    return str(export_path / "export_results.html")


def _safe_filename(name: str) -> str:
    """生成安全的文件名"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name[:50]
