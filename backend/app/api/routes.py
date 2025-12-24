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
from .tdl_integration import tdl_integration


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


@router.post("/export/{task_id}/retry_file/{item_id}")
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
    limit: int = 20,
    reversed_order: bool = False,
    current_user: User = Depends(get_current_user)
):
    """获取分段下载队列 (支持倒序切换)"""
    queue_data = export_manager.get_download_queue(task_id, limit=limit, reversed_order=reversed_order)
    return queue_data


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
            item.is_retry = True  # [v1.6.1] 标记为重试，提高优先级
            item.error = None
            count += 1
    
    if count > 0:
        export_manager._save_tasks()
        return {"status": "ok", "message": f"已重置 {count} 个失败文件"}
    
    raise HTTPException(status_code=400, detail="没有失败的文件")


@router.post("/export/{task_id}/scan")
async def scan_messages(
    task_id: str,
    full: bool = False,
    current_user: User = Depends(get_current_user)
):
    """扫描消息 (v1.6.7)
    
    Args:
        task_id: 任务 ID
        full: 是否全量扫描
    """
    result = await export_manager.scan_messages(task_id, full=full)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.post("/export/{task_id}/verify")
async def verify_integrity(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """批量完整性校验：仅执行纯本地文件扫描 (v1.6.7)"""
    result = await export_manager.verify_integrity(task_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.post("/export/{task_id}/download/{item_id}/pause")
async def pause_download_item(
    task_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user)
):
    """暂停单个下载项 (释放槽位)"""
    success = await export_manager.pause_download_item(task_id, item_id)
    if success:
        return {"status": "ok", "message": "已暂停 (释放槽位)"}
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


@router.post("/export/{task_id}/download/{item_id}/cancel")
async def cancel_download_item(
    task_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user)
):
    """取消/跳过单个下载项"""
    success = await export_manager.cancel_download_item(task_id, item_id)
    if success:
        return {"status": "ok", "message": "已取消"}
    raise HTTPException(status_code=400, detail="取消失败")


@router.post("/export/{task_id}/concurrency")
async def update_task_concurrency(
    task_id: str,
    max_concurrent_downloads: Optional[int] = None,
    download_threads: Optional[int] = None,
    parallel_chunk_connections: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    """
    运行时更新任务并发配置 (v1.5.0)
    
    Args:
        max_concurrent_downloads: 最大并发下载数 (1-20)
        download_threads: 下载线程数 (1-20)
        parallel_chunk_connections: 单文件并行连接数 (1-8)
    """
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 使用新的 adjust_task_concurrency 方法，会自动唤醒 Worker
    result = await export_manager.adjust_task_concurrency(
        task_id,
        max_concurrent=max_concurrent_downloads,
        download_threads=download_threads,
        parallel_chunk=parallel_chunk_connections
    )
    
    if result:
        changes = []
        if max_concurrent_downloads is not None:
            changes.append(f"最大并发: {max_concurrent_downloads}")
        if download_threads is not None:
            changes.append(f"下载线程: {download_threads}")
        if parallel_chunk_connections is not None:
            changes.append(f"分块连接: {parallel_chunk_connections}")
        return {"status": "ok", "message": "已更新: " + ", ".join(changes)}
    
    raise HTTPException(status_code=400, detail="未指定任何参数")


@router.get("/export/{task_id}/concurrency")
async def get_task_concurrency(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """获取任务当前并发配置"""
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return {
        "max_concurrent_downloads": task.options.max_concurrent_downloads,
        "current_max_concurrent_downloads": task.current_max_concurrent_downloads or task.options.max_concurrent_downloads,
        "download_threads": task.options.download_threads,
        "parallel_chunk_connections": task.options.parallel_chunk_connections,
        "enable_parallel_chunk": task.options.enable_parallel_chunk
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
    export_manager._save_tasks()  # 保存更改
    return {"status": "ok", "message": "任务已删除"}


@router.get("/export/tasks", response_model=List[ExportTask])
async def get_tasks(current_user: User = Depends(get_current_user)):
    """获取所有任务 (不带冗长队列)"""
    tasks = export_manager.get_all_tasks()
    # 手动排除大字段以减少响应体积
    return [task.model_dump(exclude={"download_queue", "failed_downloads"}) for task in tasks]


@router.get("/export/{task_id}", response_model=ExportTask)
async def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """获取任务详情 (不带冗长队列)"""
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.model_dump(exclude={"download_queue", "failed_downloads"})


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


# ===== TDL 集成 =====

@router.get("/tdl/status")
async def get_tdl_status(current_user: User = Depends(get_current_user)):
    """获取 TDL 状态"""
    return await tdl_integration.get_status()


@router.post("/tdl/download")
async def tdl_download(
    url: str,
    output_dir: str = "/downloads",
    threads: int = 4,
    limit: int = 2,
    current_user: User = Depends(get_current_user)
):
    """使用 TDL 下载单个链接"""
    result = await tdl_integration.download(url, output_dir, threads, limit)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "下载失败"))
    return result


@router.post("/tdl/download-by-message")
async def tdl_download_by_message(
    chat_id: int,
    message_id: int,
    output_dir: str = "/downloads",
    current_user: User = Depends(get_current_user)
):
    """通过消息 ID 使用 TDL 下载"""
    result = await tdl_integration.download_by_message(chat_id, message_id, output_dir)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "下载失败"))
    return result





@router.post("/tdl/download-from-task")
async def tdl_download_from_task(
    task_id: str,
    item_ids: List[str],
    output_dir: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """从导出任务中选择文件使用 TDL 下载"""
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 从下载队列中找到对应的项并生成链接
    urls = []
    for item in task.download_queue:
        if item.id in item_ids:
            url = tdl_integration.generate_telegram_link(item.chat_id, item.message_id)
            urls.append(url)
    
    if not urls:
        raise HTTPException(status_code=400, detail="未找到指定的下载项")
    
    # 使用任务的导出路径
    target_dir = output_dir or task.options.export_path
    
    result = await tdl_integration.batch_download(urls, target_dir)
    return {
        "success": result.get("success"),
        "requested": len(item_ids),
        "found": len(urls),
        "output": result.get("output"),
        "error": result.get("error")
    }


@router.post("/export/{task_id}/tdl-mode")
async def set_tdl_mode(
    task_id: str,
    enabled: bool,
    current_user: User = Depends(get_current_user)
):
    """设置任务的 TDL 下载模式
    
    开启后，该任务的所有下载将使用 TDL 进行
    """
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 检查 TDL 是否可用
    if enabled:
        status = tdl_integration.get_status()
        if not status.get("container_running"):
            raise HTTPException(status_code=400, detail="TDL 容器未运行")
    
    # 保存 TDL 模式状态到任务 (可扩展到 ExportOptions)
    # 目前仅作为前端状态使用
    return {
        "status": "ok",
        "task_id": task_id,
        "tdl_mode": enabled,
        "message": f"TDL 模式已{'启用' if enabled else '禁用'}"
    }


@router.post("/export/{task_id}/tdl-start")
async def start_tdl_download(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """启动 TDL 批量下载任务
    
    将任务中所有待下载的文件交给 TDL 处理
    """
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 获取待下载的项
    pending_items = [
        {
            "id": item.id,
            "url": tdl_integration.generate_telegram_link(item.chat_id, item.message_id),
            "file_name": item.file_name,
            "file_size": item.file_size
        }
        for item in task.download_queue
        if item.status.value in ["waiting", "failed"]
    ]
    
    if not pending_items:
        return {"success": False, "message": "没有待下载的文件"}
    
    # 逐个下载（TDL 仅作为下载器）
    results = []
    for item in pending_items:
        result = await tdl_integration.download(
            url=item["url"],
            output_dir=task.options.export_path,
            threads=task.options.download_threads,
            limit=task.options.max_concurrent_downloads
        )
        results.append({
            "id": item["id"],
            "file_name": item["file_name"],
            "success": result.get("success"),
            "error": result.get("error")
        })
    
    success_count = sum(1 for r in results if r["success"])
    return {
        "success": True,
        "message": f"TDL 下载完成: {success_count}/{len(results)} 成功",
        "results": results
    }


@router.post("/export/{task_id}/tdl-download-item")
async def tdl_download_single_item(
    task_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user)
):
    """使用 TDL 下载单个文件
    
    TDL 仅作为下载器，下载选择由 tg-export 控制
    """
    task = export_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 查找下载项
    item = next((i for i in task.download_queue if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="下载项不存在")
    
    # 生成链接并下载
    url = tdl_integration.generate_telegram_link(item.chat_id, item.message_id)
    
    result = await tdl_integration.download(
        url=url,
        output_dir=task.options.export_path,
        threads=task.options.download_threads,
        limit=task.options.max_concurrent_downloads
    )
    
    return {
        "success": result.get("success"),
        "item_id": item_id,
        "file_name": item.file_name,
        "url": url,
        "output": result.get("output"),
        "error": result.get("error")
    }
