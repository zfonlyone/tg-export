"""
TG Export - 数据模型
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field, computed_field


class ChatType(str, Enum):
    """聊天类型"""
    PRIVATE = "private"           # 私聊
    BOT = "bot"                   # 机器人对话
    GROUP = "group"               # 私密群组
    SUPERGROUP = "supergroup"     # 公开群组
    CHANNEL = "channel"           # 频道


class MediaType(str, Enum):
    """媒体类型"""
    PHOTO = "photo"               # 图片
    VIDEO = "video"               # 视频文件
    AUDIO = "audio"               # 音频
    VOICE = "voice"               # 语音消息
    VIDEO_NOTE = "video_note"     # 视频消息 (圆形)
    DOCUMENT = "document"         # 文件
    STICKER = "sticker"           # 贴纸
    ANIMATION = "animation"       # GIF 动态图


class ExportFormat(str, Enum):
    """导出格式"""
    HTML = "html"                 # 人类可读的 HTML
    JSON = "json"                 # 机器可读的 JSON
    BOTH = "both"                 # 以上两者


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"           # 等待中
    EXTRACTING = "extracting"     # 正在提取消息
    RUNNING = "running"           # 正在下载媒体
    PAUSED = "paused"             # 已暂停
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"             # 失败
    CANCELLED = "cancelled"       # 已取消


class DownloadStatus(str, Enum):
    """单独文件的下载状态"""
    WAITING = "waiting"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DownloadItem(BaseModel):
    """单个媒体文件的下载项"""
    id: str                               # 唯一ID (chat_id-msg_id)
    message_id: int
    chat_id: int
    file_name: str
    file_size: int = 0
    downloaded_size: int = 0
    status: DownloadStatus = DownloadStatus.WAITING
    error: Optional[str] = None
    media_type: MediaType
    file_path: Optional[str] = None
    progress: float = 0.0
    speed: float = 0.0                    # 下载速度 (字节/秒)


class ExportOptions(BaseModel):
    """导出选项 - 对应官方导出功能"""
    
    # 账号信息
    account_info: bool = False
    contacts: bool = False
    
    # 历史记录导出设置
    private_chats: bool = True          # 私聊
    bot_chats: bool = False             # 机器人对话
    private_groups: bool = True         # 私密群组
    private_channels: bool = True       # 私密频道
    public_groups: bool = False         # 公开群组
    public_channels: bool = False       # 公开频道
    only_my_messages: bool = False      # 只导出我的消息
    
    # 指定聊天 (可选)
    specific_chats: List[int] = Field(default_factory=list)  # 指定的聊天 ID
    
    # 消息范围 (单频道/群组导出)
    # message_from=1, message_to=0 表示从第1条到最新
    # message_from=1, message_to=100 表示第1条到第100条
    message_from: int = 1               # 起始消息 ID
    message_to: int = 0                 # 结束消息 ID (0=最新)
    
    # 断点续传
    resume_download: bool = True        # 启用断点续传
    skip_existing: bool = True          # 跳过已下载的文件
    
    # 媒体文件导出设置
    photos: bool = True                 # 图片
    videos: bool = True                 # 视频文件
    voice_messages: bool = True         # 语音消息
    video_messages: bool = True         # 视频消息
    stickers: bool = False              # 贴纸
    gifs: bool = True                   # GIF 动态图
    files: bool = True                  # 文件
    
    # 其它
    active_sessions: bool = False       # 活跃会话
    other_data: bool = False            # 其它数据
    
    # 时间范围
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    
    # 保存路径/格式
    export_path: str = "/downloads"
    export_format: ExportFormat = ExportFormat.HTML
    
    # 下载设置 (Telegram 免费用户限制)
    max_concurrent_downloads: int = 10   # 最大并发下载数
    download_threads: int = 10           # 下载线程数
    download_speed_limit: int = 0        # 下载速度限制 (KB/s, 0=无限制)
    
    # 重试设置
    max_download_retries: int = 5        # 最大重试次数
    retry_delay: float = 2.0             # 重试初始延迟 (秒)
    auto_retry_failed: bool = True       # 自动重试失败的下载
    
    # 消息过滤 (skip=跳过指定消息, specify=只下载指定消息)
    filter_mode: str = "none"            # none/skip/specify
    filter_messages: List[int] = Field(default_factory=list)  # 过滤的消息 ID 列表


class ChatInfo(BaseModel):
    """聊天信息"""
    id: int
    title: str
    type: ChatType
    username: Optional[str] = None
    members_count: Optional[int] = None
    photo_path: Optional[str] = None
    is_selected: bool = False


class MessageInfo(BaseModel):
    """消息信息"""
    id: int
    date: datetime
    from_user_id: Optional[int] = None
    from_user_name: Optional[str] = None
    text: Optional[str] = None
    media_type: Optional[MediaType] = None
    media_path: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None      # 文件大小 (字节)
    reply_to_message_id: Optional[int] = None # 回复的消息 ID
    message_link: Optional[str] = None    # 消息原始直链 (t.me)


class FailedDownload(BaseModel):
    """下载失败记录"""
    message_id: int
    chat_id: int
    file_name: Optional[str] = None
    error_type: str                       # connection_lost, file_ref_expired, peer_invalid
    error_message: str
    retry_count: int = 0
    last_retry: Optional[datetime] = None
    resolved: bool = False


class ExportTask(BaseModel):
    """导出任务"""
    id: str
    name: str
    status: TaskStatus = TaskStatus.PENDING
    options: ExportOptions
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    export_name: Optional[str] = None      # 导出的实际目录名
    
    # 进度信息
    total_chats: int = 0
    processed_chats: int = 0
    total_messages: int = 0
    processed_messages: int = 0
    total_media: int = 0
    downloaded_media: int = 0
    total_size: int = 0
    downloaded_size: int = 0
    
    # 下载管理
    is_extracting: bool = False           # 是否处于消息提取阶段
    download_queue: List[DownloadItem] = Field(default_factory=list) # 下载队列
    
    # 错误信息
    error: Optional[str] = None
    
    # 失败下载跟踪
    failed_downloads: List["FailedDownload"] = Field(default_factory=list)
    retry_downloads: int = 0              # 重试成功的数量
    download_speed: float = 0.0           # 总下载速度 (字节/秒)
    
    @computed_field
    @property
    def progress(self) -> float:
        """计算总进度"""
        if self.status == TaskStatus.EXTRACTING:
            if self.total_chats == 0: return 0.0
            return (self.processed_chats / self.total_chats) * 100
            
        if self.total_media == 0:
            if self.total_messages == 0: return 0.0
            return (self.processed_messages / self.total_messages) * 100
            
        # 媒体下载进度
        return (self.downloaded_media / self.total_media) * 100

    def get_download_item(self, message_id: int, chat_id: int) -> Optional[DownloadItem]:
        """获取特定的下载项"""
        item_id = f"{chat_id}_{message_id}"
        for item in self.download_queue:
            if item.id == item_id:
                return item
        return None


class User(BaseModel):
    """用户模型"""
    username: str
    password_hash: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class TokenResponse(BaseModel):
    """Token 响应"""
    access_token: str
    token_type: str = "bearer"
