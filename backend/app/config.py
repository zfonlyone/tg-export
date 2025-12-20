"""
TG Export - 配置管理
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""
    
    # 基础配置
    APP_NAME: str = "TG Export"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # 路径配置
    BASE_DIR: Path = Path(__file__).parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    EXPORT_DIR: Path = DATA_DIR / "exports"
    SESSIONS_DIR: Path = DATA_DIR / "sessions"
    
    # Telegram API 配置
    API_ID: Optional[int] = None
    API_HASH: Optional[str] = None
    BOT_TOKEN: Optional[str] = None
    
    # Web 配置
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 9528
    
    # 认证配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""  # 首次运行自动生成
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天
    
    # 导出配置
    MAX_CONCURRENT_DOWNLOADS: int = 5
    CHUNK_SIZE: int = 1024 * 1024  # 1MB
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
    
    def init_dirs(self):
        """初始化目录"""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        self.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.init_dirs()
