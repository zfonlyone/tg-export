"""
TG Export - 配置管理
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """应用配置"""
    
    # 基础配置
    APP_NAME: str = "TG Export"
    APP_VERSION: str = "1.5.0"  # 并行分块下载版本
    DEBUG: bool = False
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
    WEB_PORT: int = int(os.getenv("WEB_PORT", 9528))
    
    # 路径配置
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", BASE_DIR.parent / "data"))
    TEMP_DIR: Path = Path(os.getenv("TEMP_DIR", DATA_DIR / "temp"))
    EXPORT_DIR: Path = Path(os.getenv("EXPORT_DIR", DATA_DIR / "exports"))
    SESSIONS_DIR: Path = Path(os.getenv("SESSIONS_DIR", DATA_DIR / "sessions"))
    
    # 数据库/配置路径
    SESSION_NAME: str = "tg_export"
    
    # Telegram API
    API_ID: int = int(os.getenv("API_ID", 0))
    API_HASH: str = os.getenv("API_HASH", "")
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    
    # Web 认证
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-fallback-secret-key")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # 导出设置
    MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", 5))
    CHUNK_SIZE: int = 1024 * 1024  # 1MB
    
    # 并行分块下载设置 (单文件多连接)
    PARALLEL_CHUNK_CONNECTIONS: int = int(os.getenv("PARALLEL_CHUNK_CONNECTIONS", 4))
    MIN_PARALLEL_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB，小于此值不启用并行
    ENABLE_PARALLEL_DOWNLOAD: bool = os.getenv("ENABLE_PARALLEL_DOWNLOAD", "true").lower() == "true"
    
    class Config:
        env_file = ".env"

settings = Settings()
