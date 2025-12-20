"""
TG Export - WebSocket 实时通信
用于推送任务进度
"""
import asyncio
import json
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect

from ..models import ExportTask
from ..telegram import export_manager


class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.task_subscribers: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket):
        """接受连接"""
        await websocket.accept()
        self.active_connections.add(websocket)
    
    def disconnect(self, websocket: WebSocket):
        """断开连接"""
        self.active_connections.discard(websocket)
        # 从所有订阅中移除
        for subscribers in self.task_subscribers.values():
            subscribers.discard(websocket)
    
    def subscribe_task(self, websocket: WebSocket, task_id: str):
        """订阅任务进度"""
        if task_id not in self.task_subscribers:
            self.task_subscribers[task_id] = set()
        self.task_subscribers[task_id].add(websocket)
    
    def unsubscribe_task(self, websocket: WebSocket, task_id: str):
        """取消订阅"""
        if task_id in self.task_subscribers:
            self.task_subscribers[task_id].discard(websocket)
    
    async def broadcast_task_progress(self, task: ExportTask):
        """广播任务进度"""
        task_id = task.id
        if task_id not in self.task_subscribers:
            return
        
        message = {
            "type": "task_progress",
            "task_id": task_id,
            "data": {
                "status": task.status.value,
                "progress": task.progress,
                "total_messages": task.total_messages,
                "processed_messages": task.processed_messages,
                "total_media": task.total_media,
                "downloaded_media": task.downloaded_media,
                "total_size": task.total_size,
                "downloaded_size": task.downloaded_size,
                "error": task.error
            }
        }
        
        dead_connections = set()
        for websocket in self.task_subscribers[task_id]:
            try:
                await websocket.send_json(message)
            except Exception:
                dead_connections.add(websocket)
        
        # 清理断开的连接
        for ws in dead_connections:
            self.disconnect(ws)
    
    async def send_notification(self, websocket: WebSocket, message: dict):
        """发送通知"""
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)


# 全局连接管理器
manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 端点处理"""
    await manager.connect(websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            
            action = data.get("action")
            
            if action == "subscribe":
                task_id = data.get("task_id")
                if task_id:
                    manager.subscribe_task(websocket, task_id)
                    # 注册进度回调
                    export_manager.add_progress_callback(
                        task_id,
                        lambda t: manager.broadcast_task_progress(t)
                    )
                    await websocket.send_json({
                        "type": "subscribed",
                        "task_id": task_id
                    })
            
            elif action == "unsubscribe":
                task_id = data.get("task_id")
                if task_id:
                    manager.unsubscribe_task(websocket, task_id)
            
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        manager.disconnect(websocket)
