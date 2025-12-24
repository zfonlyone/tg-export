# TG Export - Telegram 全功能导出工具 v1.6.9

📥 一键导出 Telegram 私密频道、群组、私聊的全部内容，支持 HTML + JSON 格式输出。

## ✨ v1.6.9 核心更新

### 🚀 TDL 极速引擎 (Rocket Mode)
- **全新集成 TDL**：Go 语言编写的底层下载引擎，速度提升 3-10 倍。
- **批量下载聚合**：自动按子目录聚合下载项，一次性下发 TDL 命令，利用原生并发。
- **连接稳定性校验**：严格监控 Docker 退出码，崩溃自动判定并记录，杜绝状态误报。
- **自动子目录对齐**：TDL 现在能准确识别并下载到项目指定的 deep 子目录中。

### ⚡ 并行分块下载 (Pyrogram Mode)
- **单文件多连接并发**：对于未启用 TDL 的任务，大文件自动启用多连接并行下载。
- **基于 MTProto raw API**：突破单连接限速，保证基础下载速度。

### 📂 路径命名优化
- **简洁文件夹名**：移除导出目录名中的任务 ID 后缀（如 `_b016b`），路径更直观。
- **同名增量更新**：遇到同名任务时直接重用目录进行覆盖/增量更新，不再重复建文件夹。

### 🎨 UI & 管理进化
- **TDL 一键切换**：前端任务详情页增加 🚀 TDL 开关，按需启用极速模式。
- **队列自适应展示**：优化下载页面分类页签（等待、失败、完成），状态一目了然。
- **信号量并发保护**：全局信号量控制，防止 TDL 会话重复登录导致的账号风险。

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
