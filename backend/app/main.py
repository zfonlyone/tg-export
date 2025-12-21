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


# 创建 FastAPI 应用
app = FastAPI(
    title="TG Export",
    description="Telegram 全功能导出工具",
    version="1.0.0",
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

if frontend_path.exists():
    app.mount("/assets", StaticFiles(directory=frontend_path / "assets"), name="assets")
    
    @app.get("/")
    async def serve_frontend():
        return FileResponse(frontend_path / "index.html")
    
    @app.get("/{path:path}")
    async def serve_frontend_routes(path: str):
        file_path = frontend_path / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_path / "index.html")

# 导出文件访问
exports_path = settings.EXPORT_DIR
if exports_path.exists():
    app.mount("/exports", StaticFiles(directory=exports_path), name="exports")


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


@app.on_event("shutdown")
async def shutdown_event():
    """关闭事件"""
    from .telegram import telegram_client
    await telegram_client.stop()


# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "ok", "version": settings.APP_VERSION}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        reload=settings.DEBUG
    )
