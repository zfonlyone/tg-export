# TG Export - Telegram 全功能导出工具 v1.3.1

📥 一键导出 Telegram 私密频道、群组、私聊的全部内容，支持 HTML + JSON 格式输出。

## ✨ 功能特性

### � 导出类型
- **私聊** - 个人对话记录
- **群组** - 私密/公开群组
- **频道** - 私密/公开频道 (包括无法公开访问的私密频道)
- **Bot 对话** - 与机器人的对话记录

### 🎨 媒体支持
- 🖼️ 图片 (无大小限制)
- 🎬 视频 (无大小限制)
- 🎤 语音消息
- 📹 视频消息
- 📎 文件/文档
- � 贴纸
- 🎬 GIF 动态图

### 📄 输出格式
- **HTML** - 人类可读，样式类似 Telegram Desktop 官方导出
- **JSON** - 机器可读，方便程序处理

### ⚙️ 高级功能
- 🎯 **消息范围筛选** - 指定导出第 N 到第 M 条消息 (如 `1-100`)
- 🔄 **断点续传** - 下载中断后继续，未完成文件使用 `.downloading` 后缀
- ⏭️ **跳过已下载** - 第二次运行自动跳过已成功的文件
- 📅 **时间范围筛选** - 按日期筛选消息
- 🔁 **智能重试** - 连接中断/文件引用过期自动重试 (指数退避策略)
- ⏸️ **暂停/恢复** - 随时暂停和恢复下载任务
- 📊 **失败记录** - 自动记录失败的下载，支持手动重试
- 🐢 **速率限制** - 智能控制 API 请求频率，全局 5s 启动间隔 + 30s 冷却，防止账号受限
- 🛡️ **稳健性增强** - 自动识别网络超时并重试，支持 0 字节空文件自动校验与清理

---

## 🚀 一键部署

```bash
# 稳定版安装
bash <(curl -sL https://raw.githubusercontent.com/zfonlyone/tg-export/main/tg-export.sh)
```

### 部署脚本功能
- ✅ 自动安装 Docker/Docker Compose
- ✅ 自动配置 Nginx 反向代理
- ✅ UFW 防火墙端口开放检测
- ✅ SSL 证书申请与自动续期
- ✅ 配置持久化 (第二次安装无需重新输入)

---

## 🎛️ 管理命令

安装后可使用 `tge` 命令管理：

```bash
tge           # 打开管理菜单 (支持启动、停止、更新、安装、卸载等)
tge start     # 启动服务
tge stop      # 停止服务
tge restart   # 重启服务
tge logs      # 查看日志
tge update    # 更新镜像
tge status    # 查看状态
```

---

## 🤖 Telegram Bot 命令

配置 Bot Token 后，可通过 Telegram Bot 控制导出：

### 基础命令
| 命令 | 说明 |
|------|------|
| `/start` | 显示欢迎信息和快捷按钮 |
| `/help` | 显示详细帮助文档 |
| `/status` | 查看 Telegram 账号连接状态 |

### 导出命令
| 命令 | 说明 |
|------|------|
| `/list` | 列出所有可导出的对话 (私聊/群组/频道) |
| `/export` | 打开导出向导菜单 |
| `/export <chat_id>` | 导出指定聊天的全部消息 |
| `/export <chat_id> 1-100` | 导出第 1-100 条消息 |
| `/export <chat_id> 1-0` | 导出全部消息 (0=最新) |

### 任务管理
| 命令 | 说明 |
|------|------|
| `/tasks` | 查看所有导出任务及进度 |
| `/cancel <task_id>` | 取消指定任务 |

### 使用示例
```
/export -1001234567890         # 导出该频道全部内容
/export -1001234567890 1-50    # 导出前 50 条消息
/export -1001234567890 100-0   # 导出第 100 条到最新
```

---

## 🔁 下载重试机制

当下载遇到问题时，系统会自动重试：

| 错误类型 | 处理策略 |
|---------|----------|
| 连接中断 | 指数退避重试 (2s→4s→8s→...，最大60s) |
| 文件引用过期 | 重新获取消息后重试 |
| 限流 (FloodWait) | 等待指定时间后重试 |
| 频道无效 | 标记失败，不重试 |

失败的下载会记录到 `.failed_downloads.json`，可通过 Web 面板手动重试。

---

## 🌐 Web 面板

访问 `http://your-ip:9528` 进入 Web 管理面板：

- **仪表盘** - 统计信息和连接状态
- **导出向导** - 4 步流程，选择聊天类型、媒体类型、高级选项
- **任务管理** - 实时进度追踪，支持暂停/恢复/取消
  - 统计卡片：已完成/未完成/失败任务数
  - 批量操作：暂停所有/恢复所有/移除已完成
  - 失败列表：查看和重试失败的下载
- **设置** - Telegram 登录、Bot 配置

---

## 📁 配置文件

配置文件位于 `/opt/tg-export/.tge_config`：

```bash
# Telegram API
API_ID="12345678"
API_HASH="abc123..."
BOT_TOKEN="123456:ABC..."

# Web 面板
ADMIN_PASSWORD="your-password"
WEB_PORT="9528"

# 域名配置
DOMAIN="tge.example.com"
ENABLE_NGINX="y"
NGINX_TYPE="3"    # 1=HTTP, 2=HTTPS, 3=HTTPS+跳转

# 下载目录
DOWNLOAD_DIR="/storage/downloads"
```

第二次运行安装脚本时，会自动读取配置，直接回车即可使用旧配置。

---

## 🐳 Docker 部署

### docker-compose.yml

```yaml
services:
  tg-export:
    image: zfonlyone/tg-export:latest
    container_name: tg-export
    restart: unless-stopped
    ports:
      - "9528:9528"
    volumes:
      - ./data:/app/data
      - /storage/downloads:/downloads
    environment:
      - API_ID=12345678
      - API_HASH=abc123...
      - ADMIN_PASSWORD=your-password
      - BOT_TOKEN=123456:ABC...
```

---

## 📖 获取 API 凭据

### 获取 API ID 和 API Hash
1. 访问 https://my.telegram.org
2. 使用手机号登录
3. 选择 "API development tools"
4. 创建应用，获取 `api_id` 和 `api_hash`

### 获取 Bot Token (可选)
1. Telegram 搜索 `@BotFather`
2. 发送 `/newbot` 创建机器人
3. 复制获得的 Token

---

## 📜 许可证

MIT License
