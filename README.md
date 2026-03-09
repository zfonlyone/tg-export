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

### 本机开发仓库 vs 生产运行目录（重要）

如果这套服务部署在当前机器上，请注意：

- **开发仓库**：`/root/code/docker/tg-export`
- **实际生产目录**：`/etc/tg-export`
- **线上容器**：`tg-export`

也就是说：

> 只修改 `/root/code/docker/tg-export` 并不代表线上已经更新。

必须把代码同步到 `/etc/tg-export`，然后在那里重新 `docker compose up -d --build`，线上才会真正生效。

### 推荐更新流程（本机部署）

```bash
# 1) 在开发仓库改代码
cd /root/code/docker/tg-export

# 2) 先验证前端能构建
cd frontend && npm run build && cd ..

# 3) 提交代码
git add .
git commit -m "your change"

# 4) 同步到生产目录
rsync -a --delete \
  --exclude '.git/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.env' \
  --exclude 'data/' \
  /root/code/docker/tg-export/ /etc/tg-export/

# 5) 在生产目录重建
cd /etc/tg-export
docker compose up -d --build

# 6) 验证是否真的更新
docker compose ps
docker inspect tg-export --format 'started={{.State.StartedAt}} image={{.Image}}'
docker exec tg-export sh -lc 'sed -n "1,20p" /app/frontend/dist/index.html'
curl -sS http://127.0.0.1:9528/ | sed -n '1,20p'
curl -sS https://tg-export.181028.xyz/ | sed -n '1,20p'
```

### 白屏排查提示

如果页面白屏：

1. 先看公网返回的 `index-*.js` / 页面 chunk 是不是旧 hash
2. 再看容器内 `/app/frontend/dist/index.html` 是不是同一套 hash
3. 如果容器内还是旧 hash：说明根本没重建成功
4. 如果容器内已新、公网仍旧：再怀疑 Cloudflare 缓存或代理缓存

### 标准 Docker Compose 部署（不依赖 `tg-export.sh`）
```bash
git clone https://github.com/zfonlyone/tg-export.git
cd tg-export
cp .env.example .env
# 编辑 .env，填入 API_ID / API_HASH / ADMIN_PASSWORD 等配置
docker compose up -d --build
```

访问地址：
- `http://<你的服务器IP>:${WEB_PORT}`（默认 `9528`）

说明：
- 项目已迁移为 `env` 配置模式，不再依赖 `config.yml`。
- 运行时在面板中修改的关键配置会持久化到 `data/.env`（容器重启后仍可用）。

### 一键脚本部署（可选）
```bash
bash <(curl -sL https://raw.githubusercontent.com/zfonlyone/tg-export/main/tg-export.sh)
```

---

## 📁 辅助工具
- **TDL 文件名转换脚本**: `convert_tdl.sh`
  - 如果您单独使用了 TDL 并没有使用本项目管理，可以使用该脚本将 TDL 默认格式转换为本项目的 `消息ID-群组ID-文件名` 格式。

---

## 📜 许可证
MIT License
