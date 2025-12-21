"""
TG Export - API 路由
"""
from datetime import timedelta
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from ..config import settings
from ..models import (
    ExportTask, ExportOptions, ChatInfo, TaskStatus,
    LoginRequest, TokenResponse, User
)
from ..telegram import telegram_client, export_manager
from .auth import (
    authenticate_user, create_access_token, get_current_user,
    create_user, get_user
)


router = APIRouter()


# ===== 认证相关 =====

@router.post("/auth/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """用户登录"""
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return TokenResponse(access_token=access_token)


@router.get("/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return {
        "username": current_user.username,
        "is_active": current_user.is_active
    }


# ===== Telegram 相关 =====

@router.post("/telegram/init")
async def init_telegram(
    api_id: int,
    api_hash: str,
    current_user: User = Depends(get_current_user)
):
    """初始化 Telegram 客户端"""
    await telegram_client.init(api_id, api_hash)
    return {"status": "ok", "message": "客户端已初始化"}


@router.post("/telegram/send-code")
async def send_code(
    phone: str,
    current_user: User = Depends(get_current_user)
):
    """发送验证码"""
    try:
        phone_code_hash = await telegram_client.send_code(phone)
        return {"status": "ok", "phone_code_hash": phone_code_hash}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/telegram/sign-in")
async def sign_in(
    phone: str,
    code: str,
    phone_code_hash: str,
    password: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """登录验证"""
    success = await telegram_client.sign_in(phone, code, phone_code_hash, password)
    if success:
        return {"status": "ok", "message": "登录成功"}
    raise HTTPException(status_code=400, detail="登录失败")


@router.get("/telegram/status")
async def telegram_status(current_user: User = Depends(get_current_user)):
    """获取 Telegram 状态"""
    if telegram_client.is_authorized:
        me = await telegram_client.get_me()
        return {"authorized": True, "user": me}
    return {"authorized": False}


@router.get("/telegram/dialogs", response_model=List[ChatInfo])
async def get_dialogs(current_user: User = Depends(get_current_user)):
    """获取对话列表"""
    if not telegram_client.is_authorized:
        raise HTTPException(status_code=401, detail="请先登录 Telegram")
    return await telegram_client.get_dialogs()


# ===== 导出任务相关 =====

@router.post("/export/create", response_model=ExportTask)
async def create_export_task(
    name: str,
    options: ExportOptions,
    current_user: User = Depends(get_current_user)
):
    """创建导出任务"""
    if not telegram_client.is_authorized:
        raise HTTPException(status_code=401, detail="请先登录 Telegram")
    task = export_manager.create_task(name, options)
    return task


@router.post("/export/{task_id}/start")
async def start_export(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """启动导出任务"""
    success = await export_manager.start_export(task_id)
    if success:
        return {"status": "ok", "message": "任务已启动"}
    raise HTTPException(status_code=400, detail="启动失败")


@router.post("/export/{task_id}/cancel")
async def cancel_export(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """取消导出任务"""
    success = await export_manager.cancel_export(task_id)
    if success:
        return {"status": "ok", "message": "任务已取消"}
    raise HTTPException(status_code=400, detail="取消失败")


@router.post("/export/{task_id}/pause")
async def pause_export(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """暂停导出任务"""
    success = await export_manager.pause_export(task_id)
    if success:
        return {"status": "ok", "message": "任务已暂停"}
    raise HTTPException(status_code=400, detail="暂停失败")


@router.post("/export/{task_id}/resume")
async def resume_export(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """恢复导出任务"""
    success = await export_manager.resume_export(task_id)
    if success:
        return {"status": "ok", "message": "任务已恢复"}
    raise HTTPException(status_code=400, detail="恢复失败")


@router.get("/export/{task_id}/failed")
async def get_failed_downloads(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """获取失败的下载列表"""
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "task_id": task_id,
        "failed_count": len(task.failed_downloads),
        "failed_downloads": task.failed_downloads
    }


@router.post("/export/{task_id}/retry")
async def retry_failed_downloads(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """重试所有失败的下载 (目前记录失败供后续重试)"""
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    failed_count = len(task.failed_downloads)
    # TODO: 实现实际的重试逻辑
    return {
        "status": "ok",
        "message": f"已标记 {failed_count} 个失败项待重试",
        "failed_count": failed_count
    }


@router.delete("/export/{task_id}")
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """删除导出任务"""
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 如果任务正在运行，先取消
    if task.status == TaskStatus.RUNNING:
        await export_manager.cancel_export(task_id)
    
    del export_manager.tasks[task_id]
    return {"status": "ok", "message": "任务已删除"}


@router.get("/export/tasks", response_model=List[ExportTask])
async def get_tasks(current_user: User = Depends(get_current_user)):
    """获取所有任务"""
    return export_manager.get_all_tasks()


@router.get("/export/{task_id}", response_model=ExportTask)
async def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """获取任务详情"""
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


# ===== 设置相关 =====

@router.get("/settings")
async def get_settings(current_user: User = Depends(get_current_user)):
    """获取设置"""
    return {
        "export_path": str(settings.EXPORT_DIR),
        "max_concurrent_downloads": settings.MAX_CONCURRENT_DOWNLOADS,
        "api_id": settings.API_ID,
        "has_api_hash": bool(settings.API_HASH),
        "has_bot_token": bool(settings.BOT_TOKEN)
    }


@router.post("/settings")
async def update_settings(
    export_path: Optional[str] = None,
    max_concurrent_downloads: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    """更新设置"""
    # 这里可以实现设置保存逻辑
    return {"status": "ok"}

