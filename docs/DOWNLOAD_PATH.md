# TG Export - 下载路径配置指南

## 当前配置

### docker-compose.yml
```yaml
volumes:
  - /storage/downloads:/downloads:shared

environment:
  - EXPORT_DIR=/downloads
```

### 路径映射
- **宿主机**: `/storage/downloads/`
- **容器内**: `/downloads/`
- **下载路径**: `/downloads/{task_id}/chats/chat_{chat_id}/{media_type}/`

## 如何验证

### 1. 检查容器内环境变量
```bash
docker exec tg-export env | grep EXPORT_DIR
# 应该输出: EXPORT_DIR=/downloads
```

### 2. 检查挂载目录
```bash
docker inspect tg-export | grep -A 5 "Mounts"
# 应该看到: /storage/downloads -> /downloads
```

### 3. 测试创建文件
```bash
docker exec tg-export touch /downloads/test.txt
ls -la /storage/downloads/test.txt
```

### 4. 查看日志
```bash
docker logs tg-export | grep "目标路径"
# 应该看到类似: → 目标路径: /downloads/{task_id}/chats/...
```

## 常见问题

### 1. 文件不在 /storage/downloads/
**原因**: 容器未重启，旧环境变量仍在使用

**解决**: 
```bash
cd /path/to/tg-export
docker-compose down
docker-compose up -d --build
```

### 2. 权限问题
**症状**: 日志显示路径正确，但文件创建失败

**解决**: 
```bash
sudo chown -R 1000:1000 /storage/downloads
sudo chmod -R 755 /storage/downloads
```

### 3. 路径仍然错误
**检查**: 
```bash
# 查看实际使用的配置
docker exec tg-export python3 -c "from backend.app.config import settings; print(settings.EXPORT_DIR)"
```

## 完整目录结构示例

```
/storage/downloads/
└── {task_id}/                    # 例如: abc123-def456-...
    ├── export_results.html
    ├── css/
    ├── js/
    ├── images/
    ├── lists/
    └── chats/
        └── chat_{chat_id}/       # 例如: chat_1234567890
            ├── messages.html
            ├── photos/
            │   └── photo_001.jpg
            ├── video_files/
            │   └── video_001.mp4
            └── files/
                └── file_001.pdf
```
