"""
TG Export - API 路由
"""
from datetime import timedelta
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from ..config import settings
from ..models import (
    ExportTask, ExportOptions, ChatInfo, TaskStatus, DownloadStatus,
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
    try:
        await telegram_client.init(api_id, api_hash)
        return {"status": "ok", "message": "客户端已初始化"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/telegram/send-code")
async def send_code(
    phone: str,
    current_user: User = Depends(get_current_user)
):
    """发送验证码"""
    import os
    try:
        # 自动从环境变量初始化客户端
        if not telegram_client.is_initialized:
            api_id = os.environ.get("API_ID") or settings.API_ID
            api_hash = os.environ.get("API_HASH") or settings.API_HASH
            if api_id and api_hash:
                await telegram_client.init(int(api_id), api_hash)
            else:
                raise RuntimeError("请先配置 API ID 和 API Hash")
        
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
    try:
        success = await telegram_client.sign_in(phone, code, phone_code_hash, password)
        if success:
            return {"status": "ok", "message": "登录成功"}
        raise RuntimeError("登录异常终止")
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        # 转换常见错误，提供更好看的消息
        if "flood" in error_msg.lower():
            raise HTTPException(status_code=429, detail=error_msg)
        if "password" in error_msg.lower() or "2FA" in error_msg:
            # 这是一个特定流程，使用 403 区分于 401 (Web Token 过期)
            raise HTTPException(status_code=403, detail="SESSION_PASSWORD_NEEDED")
        raise HTTPException(status_code=400, detail=error_msg)


@router.post("/telegram/disconnect")
async def disconnect_telegram(current_user: User = Depends(get_current_user)):
    """断开 Telegram 连接"""
    await telegram_client.stop()
    return {"status": "ok", "message": "已断开连接"}


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


@router.post("/export/{task_id}/file/{item_id}/retry")
async def retry_file(
    task_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user)
):
    """重试单个文件 (重置状态并尝试重新下载)"""
    success = await export_manager.retry_file(task_id, item_id)
    if success:
        return {"status": "ok", "message": "文件已重置，将尝试重新下载"}
    raise HTTPException(status_code=400, detail="操作失败：文件不存在或无法重试")


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


@router.get("/export/{task_id}/downloads")
async def get_download_queue(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """获取详细下载队列"""
    queue = export_manager.get_download_queue(task_id)
    return queue


@router.post("/export/{task_id}/retry")
async def retry_all_failed(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """重试所有失败的下载"""
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    count = 0
    for item in task.download_queue:
        if item.status == DownloadStatus.FAILED:
            item.status = DownloadStatus.WAITING
            item.error = None
            count += 1
    
    if count > 0:
        export_manager._save_tasks()
        return {"status": "ok", "message": f"已重置 {count} 个失败文件"}
    
    raise HTTPException(status_code=400, detail="没有失败的文件")


@router.post("/export/{task_id}/download/{item_id}/pause")
async def pause_download_item(
    task_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user)
):
    """暂停单个下载项"""
    success = await export_manager.pause_download_item(task_id, item_id)
    if success:
        return {"status": "ok", "message": "已暂停"}
    raise HTTPException(status_code=400, detail="暂停失败")


@router.post("/export/{task_id}/download/{item_id}/resume")
async def resume_download_item(
    task_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user)
):
    """恢复单个下载项"""
    success = await export_manager.resume_download_item(task_id, item_id)
    if success:
        return {"status": "ok", "message": "已恢复"}
    raise HTTPException(status_code=400, detail="恢复失败")


@router.post("/export/{task_id}/retry/{item_id}")
async def retry_single_file(
    task_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user)
):
    """重试单个失败的下载"""
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    for item in task.download_queue:
        if item.id == item_id and item.status == DownloadStatus.FAILED:
            item.status = DownloadStatus.WAITING
            item.error = None
            export_manager._save_tasks()
            return {"status": "ok", "message": "已重置为等待状态"}
    
    raise HTTPException(status_code=400, detail="文件不存在或不是失败状态")


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
    export_manager._save_tasks()  # 保存更改
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
    import os
    api_id = os.environ.get("API_ID") or settings.API_ID
    api_hash = os.environ.get("API_HASH") or settings.API_HASH
    
    return {
        "export_path": os.environ.get("DOWNLOAD_DIR", "/downloads"),
        "max_concurrent_downloads": settings.MAX_CONCURRENT_DOWNLOADS,
        "api_id": api_id,
        "has_api_config": bool(api_id and api_hash),  # 是否已配置 API
        "has_bot_token": bool(os.environ.get("BOT_TOKEN", settings.BOT_TOKEN))
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


@router.post("/settings/bot-token")
async def save_bot_token(
    token: str,
    current_user: User = Depends(get_current_user)
):
    """保存 Bot Token"""
    # 保存到环境变量或配置文件
    import os
    os.environ["BOT_TOKEN"] = token
    return {"status": "ok", "message": "Bot Token 已保存"}
