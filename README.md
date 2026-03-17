# TG Export - Telegram 全功能导出工具 v2.4.4

📥 一键导出 Telegram 私密频道、群组、私聊的全部内容，支持 HTML + JSON 格式输出。

## ✨ v2.4.4 核心更新

### 🔧 扫描引擎重构
- **Peer 智能预热**: 自动拉取全量对话以填充本地 Session 缓存，彻底解决 `PEER_ID_INVALID` 报错。
- **多格式 ID 自动识别**: 支持 10 位数 ID 自动补全 `-100` 前缀，兼容超级群组、普通群组和个人用户格式。
- **正序扫描优化**: 使用 `min_id` 过滤实现真正的"从旧到新"历史消息扫描。

### 🚀 动态并发控制
- **运行时 Worker 扩容/缩容**: 修改并发数后 Worker 池立即响应，无需重启任务。
- **动态信号量调整**: 并行下载限额根据配置实时变化。

### 📊 增强日志
- **下载完成详细日志**: 记录 DC、群 ID、消息 ID、文件名、大小、耗时。
- **Worker 生命周期日志**: 清晰展示 Worker 启动与退出事件。

### 🛡️ Bug 修复
- **分块下载误触发**: 修复未启用分块时被自动使用的问题。
- **缺失方法补全**: 修复 `resume_export`、`adjust_task_concurrency` 等 API 报错。
- **UI 下拉菜单**: 修复鼠标移动时菜单消失的交互问题。

---

## 🛠️ 安装与部署

### 架构说明

本项目已改造为 `源码构建、物理隔离、纯净运行` 模式：

- **源码目录**：`/root/code/tg-export`
- **运行目录**：`/etc/tg-export`
- **运行时环境变量**：`/etc/tg-export/.env`
- **运行时可写配置**：`/etc/tg-export/config/runtime.env`
- **持久化数据**：`/etc/tg-export/data`

也就是说：

> 只修改 `/root/code/tg-export` 并不代表线上已经更新。

代码变更必须在源码目录构建镜像，再通过部署脚本发布到 `/etc/tg-export`。禁止在源码目录直接 `docker compose up`，也禁止在 `/etc/tg-export` 修改代码文件。

### 首次部署 / 日常发布

```bash
# 1) 在源码目录修改代码
cd /root/code/tg-export

# 2) 先验证前端构建
cd frontend && npm run build && cd ..

# 3) 首次部署前准备运行时环境变量
sudo mkdir -p /etc/tg-export
sudo cp .env.example /etc/tg-export/.env
# 然后手动编辑 /etc/tg-export/.env，填入 API_ID / API_HASH / ADMIN_PASSWORD 等配置

# 4) 执行部署脚本
sudo ./scripts/deploy.sh

# 5) 验证运行状态
cd /etc/tg-export
docker compose --env-file .env ps
docker inspect tg-export --format 'started={{.State.StartedAt}} image={{.Image}}'
docker exec tg-export sh -lc 'sed -n "1,20p" /app/frontend/dist/index.html'
curl -sS http://127.0.0.1:9528/ | sed -n '1,20p'
curl -sS https://tg-export.181028.xyz/ | sed -n '1,20p'
```

### 仅修改运行时配置

如果只是改密钥、管理员密码、下载目录等运行参数，不需要改源码：

```bash
# 主环境变量
sudo editor /etc/tg-export/.env

# 面板写入的运行时配置
sudo editor /etc/tg-export/config/runtime.env

# 重启服务使配置生效
cd /etc/tg-export
docker compose --env-file .env up -d
```

说明：
- Docker Compose 统一从 `/etc/tg-export/.env` 读取环境变量。
- 面板中保存的 API_ID / API_HASH / BOT_TOKEN / 自动生成的管理员密码，会持久化到 `/etc/tg-export/config/runtime.env`。
- 运行目录会被部署脚本自动清理，不再保留 Python / Vue / Dockerfile 等源码文件。

### 白屏排查提示

如果页面白屏：

1. 先看公网返回的 `index-*.js` / 页面 chunk 是不是旧 hash
2. 再看容器内 `/app/frontend/dist/index.html` 是不是同一套 hash
3. 如果容器内还是旧 hash：说明根本没重建成功
4. 如果容器内已新、公网仍旧：再怀疑 Cloudflare 缓存或代理缓存

访问地址：
- `http://<你的服务器IP>:${WEB_PORT}`（默认 `9528`）

---

## 📁 辅助工具
- **TDL 文件名转换脚本**: `convert_tdl.sh`
  - 如果您单独使用了 TDL 并没有使用本项目管理，可以使用该脚本将 TDL 默认格式转换为本项目的 `消息ID-群组ID-文件名` 格式。

---

## 📜 许可证
MIT License
