"""
TG Export - FastAPI 主入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from .config import settings
from .api import router, init_admin_user, websocket_endpoint
import logging
import sys
from logging.handlers import RotatingFileHandler


# 配置日志
log_dir = settings.DATA_DIR / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "tg-export.log"

# 配置根logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        # 控制台输出
        logging.StreamHandler(sys.stdout),
        # 文件输出（自动轮转，最大10MB，保留5个备份）
        RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
    ]
)

logger = logging.getLogger(__name__)
logger.info(f"日志已配置，存储路径: {log_file}")

# 创建 FastAPI 应用
app = FastAPI(
    title="TG Export",
    description="Telegram 全功能导出工具",
    version="1.2.2",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 路由
app.include_router(router, prefix="/api")

# WebSocket 路由
app.websocket("/ws")(websocket_endpoint)

# 静态文件 - 前端
# Docker 中路径为 /app/frontend/dist，开发环境为相对路径
frontend_path = Path(__file__).parent.parent / "frontend" / "dist"
if not frontend_path.exists():
    # 尝试 Docker 环境路径
    frontend_path = Path("/app/frontend/dist")

# 导出文件访问
exports_path = settings.EXPORT_DIR

if frontend_path.exists():
    app.mount("/assets", StaticFiles(directory=frontend_path / "assets"), name="assets")
    
    # exports 路由必须在 catch-all 之前
    if exports_path.exists():
        app.mount("/exports", StaticFiles(directory=exports_path, html=True), name="exports")
    
    @app.get("/")
    async def serve_frontend():
        return FileResponse(frontend_path / "index.html")
    
    # 这个 catch-all 路由最后定义，但 mount 的优先级更高
    @app.get("/{path:path}")
    async def serve_frontend_routes(path: str):
        # 对于 exports 开头的路径，返回 404 让 mount 处理（实际上不会执行到这里）
        if path.startswith("exports"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        file_path = frontend_path / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_path / "index.html")


@app.on_event("startup")
async def startup_event():
    """启动事件"""
    print(f"""
╔═══════════════════════════════════════════════════╗
║               TG Export v{settings.APP_VERSION}                    ║
╠═══════════════════════════════════════════════════╣
║  Web 面板: http://{settings.WEB_HOST}:{settings.WEB_PORT}                 ║
║  API 文档: http://{settings.WEB_HOST}:{settings.WEB_PORT}/api/docs        ║
╚═══════════════════════════════════════════════════╝
    """)
    # 初始化管理员用户
    init_admin_user()
    
    # 尝试自动恢复 Telegram 会话
    import os
    from .telegram import telegram_client
    
    api_id = os.environ.get("API_ID") or settings.API_ID
    api_hash = os.environ.get("API_HASH") or settings.API_HASH
    
    if api_id and api_hash:
        session_file = settings.SESSIONS_DIR / "tg_export.session"
        if session_file.exists():
            print("[TG] 发现已保存的会话，尝试自动登录...")
            try:
                await telegram_client.init(int(api_id), api_hash)
                if await telegram_client.start():
                    print("[TG] ✅ 自动登录成功！")
                else:
                    print("[TG] 会话无效，需要重新登录")
            except Exception as e:
                print(f"[TG] 自动登录失败: {e}")
        else:
            print("[TG] 未找到会话文件，请在设置页面登录 Telegram")
    else:
        print("[TG] 未配置 API_ID/API_HASH，请在设置页面配置")


@app.on_event("shutdown")
async def shutdown_event():
    """关闭事件"""
    from .telegram import telegram_client
    await telegram_client.stop()


# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.2.2"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        reload=settings.DEBUG
    )
