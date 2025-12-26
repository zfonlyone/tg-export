# TG Export - Telegram 全功能导出工具 v2.3.1

📥 一键导出 Telegram 私密频道、群组、私聊的全部内容，支持 HTML + JSON 格式输出。

## ✨ v2.3.1 核心更新

### 📦 配置管理现代化 (YAML Migration)
- **全面弃用 .env**：配置文件统一迁移至 `config/config.yml`，结构更清晰，支持注释。
- **环境直连**：变量直接通过 Compose 注入，彻底解决容器重启导致的配置丢失或回退。
- **自动迁移**：部署脚本支持旧版配置自动识别并合并至 YAML。

### ⏳ 正序消息扫描 (Chronological Scan)
- **旧到新扫描**：底层逻辑从“瀑布流倒序”重构为“时间轴正序”，完美匹配导出逻辑。
- **起步 ID 精准化**：修复了“从第 N 条开始”时可能遗漏起始消息的致命 Bug。
- **增量同步增强**：增量扫描现按 ID 递增顺序推进，导出进度更符合直觉。

### 🛡️ 系统稳定性与防爆炸
- **任务重入锁定**：后端引入严格状态锁，杜绝由于前端连击或 API 并发导致的 Worker 池爆炸。
- **状态同步乐观锁**：前端引入 5s 乐观锁，彻底消除 TDL/代理切换时的按钮回跳（Flicker）现象。
- **实时进度解析**：优化了 TDL 日志解析模块，进度反馈更实时、准确。

### 🌐 全局代理支持
- **链路透传**：现在代理设置能正确应用于所有下载场景（含非 TDL 模式）。
- **动态更新**：支持任务运行中实时修改代理地址。

---

## 🛠️ 安装与部署

### 容器化一键部署 (推荐)
```bash
# 下载一键部署脚本
bash <(curl -sL https://raw.githubusercontent.com/zfonlyone/tg-export/main/tg-export.sh)
```

### 手动构建部署
```bash
# 克隆仓库
git clone https://github.com/zfonlyone/tg-export.git
cd tg-export

# 构建并启动
docker-compose build
docker-compose up -d
```

---

## 📁 辅助工具
- **TDL 文件名转换脚本**: `convert_tdl.sh`
  - 如果您单独使用了 TDL 并没有使用本项目管理，可以使用该脚本将 TDL 默认格式转换为本项目的 `消息ID-群组ID-文件名` 格式。

---

## 📜 许可证
MIT License
