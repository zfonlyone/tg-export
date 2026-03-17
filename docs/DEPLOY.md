# GitHub Actions + Docker 部署指南

本指南介绍如何配置 GitHub Actions 自动构建并推送 Docker 镜像到 GitHub Container Registry (GHCR)。

---

## 📋 前置条件

1. GitHub 账号
2. 项目已上传到 GitHub 仓库
3. Dockerfile 已准备好

---

## 🔧 配置步骤

### 步骤 1: 启用 GitHub Container Registry

1. 访问 GitHub 个人设置: `Settings` → `Developer settings` → `Personal access tokens` → `Tokens (classic)`
2. 点击 `Generate new token (classic)`
3. 勾选以下权限:
   - ✅ `write:packages` - 上传包
   - ✅ `read:packages` - 下载包
   - ✅ `delete:packages` - 删除包 (可选)
4. 生成并保存 Token

> ⚠️ **注意**: 使用 GitHub Actions 自动构建时，不需要手动创建 Token。Actions 会自动使用 `GITHUB_TOKEN`。

---

### 步骤 2: 配置仓库权限

1. 进入仓库: `Settings` → `Actions` → `General`
2. 滚动到 `Workflow permissions`
3. 选择 `Read and write permissions`
4. 勾选 `Allow GitHub Actions to create and approve pull requests`
5. 点击 `Save`

---

### 步骤 3: 确认 Actions 工作流

本项目已包含 `.github/workflows/docker-build.yml`:

```yaml
name: Docker Build and Push

on:
  push:
    branches: [ main ]
    tags: [ 'v*' ]
  pull_request:
    branches: [ main ]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Container Registry
        if: github.event_name != 'pull_request'
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract Docker metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=raw,value=latest,enable={{is_default_branch}}

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: ${{ github.event_name != 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

---

### 步骤 4: 设置包可见性 (首次推送后)

首次推送镜像后:

1. 访问 `https://github.com/你的用户名?tab=packages`
2. 点击 `tg-export` 包
3. 点击右侧 `Package settings`
4. 滚动到 `Danger Zone` 
5. 点击 `Change visibility` → 选择 `Public`

---

## 📦 上传项目到 GitHub

### 方法一: 命令行 (推荐)

```bash
# 1. 进入项目目录
cd d:\code\vps\tg-export

# 2. 初始化 Git 仓库
git init

# 3. 添加所有文件
git add .

# 4. 创建首次提交
git commit -m "Initial commit: TG Export - Telegram 全功能导出工具"

# 5. 添加远程仓库 (替换为你的用户名)
git remote add origin https://github.com/你的用户名/tg-export.git

# 6. 推送到 main 分支
git branch -M main
git push -u origin main
```

### 方法二: 使用 SSH (如果已配置)

```bash
cd d:\code\vps\tg-export
git init
git add .
git commit -m "Initial commit: TG Export"
git remote add origin git@github.com:你的用户名/tg-export.git
git branch -M main
git push -u origin main
```

---

## 📝 完整上传流程

### 1. 在 GitHub 创建仓库

1. 访问 https://github.com/new
2. 仓库名: `tg-export`
3. 描述: `Telegram 全功能导出工具 - 支持私密频道/群组导出`
4. 选择 `Public` 或 `Private`
5. **不要** 勾选 "Add a README file"
6. 点击 `Create repository`

### 2. 本地上传

```bash
# 进入项目目录
cd d:\code\vps\tg-export

# 初始化并提交
git init
git add .
git commit -m "feat: TG Export v1.0 - Telegram 全功能导出工具

- 支持私密频道/群组/私聊导出
- HTML + JSON 双格式输出
- 断点续传和消息范围筛选
- Web 面板 + Telegram Bot 控制
- Docker + 一键部署脚本"

# 推送 (替换 YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/tg-export.git
git branch -M main
git push -u origin main
```

### 3. 验证 Actions

1. 访问仓库 → `Actions` 标签
2. 查看 `Docker Build and Push` 工作流
3. 等待构建完成 (约 2-5 分钟)
4. 构建成功后，镜像地址为: `ghcr.io/你的用户名/tg-export:latest`

---

## 🔄 更新部署脚本

构建成功后，需要更新 `tg-export.sh` 中的镜像地址:

```bash
# 找到这行
DOCKER_IMAGE="ghcr.io/your-username/tg-export:latest"

# 替换为
DOCKER_IMAGE="ghcr.io/你的真实用户名/tg-export:latest"
```

---

## ❓ 常见问题

### Q: Actions 构建失败 "permission denied"

确保仓库设置中 `Workflow permissions` 已设为 `Read and write permissions`。

### Q: 镜像拉取失败 "unauthorized"

如果镜像是 Private，需要先登录:
```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

### Q: 如何触发重新构建

- 推送新代码到 main 分支
- 或创建新的 Tag: `git tag v1.0.1 && git push --tags`

---

## 📌 快速参考

| 操作 | 命令 |
|------|------|
| 查看状态 | `git status` |
| 添加文件 | `git add .` |
| 提交 | `git commit -m "message"` |
| 推送 | `git push` |
| 拉取 | `git pull` |
| 创建标签 | `git tag v1.0.0` |
| 推送标签 | `git push --tags` |
