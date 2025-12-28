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

### 容器化一键部署 (推荐)
```bash
bash <(curl -sL https://raw.githubusercontent.com/zfonlyone/tg-export/main/tg-export.sh)
```

### 手动构建部署
```bash
git clone https://github.com/zfonlyone/tg-export.git
cd tg-export
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
