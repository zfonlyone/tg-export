# TG Export 项目架构与部署规范

## 1. 核心架构
本项目遵循 `源码构建、物理隔离、纯净运行` 的改造模式。

- 源码目录：`/root/code/tg-export`
  - 负责代码修改、前端构建、Docker 镜像构建。
  - 所有 Python / Vue / Dockerfile / Compose 变更都必须在这里完成。
- 运行目录：`/etc/tg-export`
  - 负责容器启动、持久化配置、持久化数据。
  - 这里只保留 `.env`、`config/`、`data/`、`docker-compose.yml`。
  - 部署脚本会清理运行目录中的源码文件，禁止在这里改代码。

## 2. 配置规范
- 统一环境变量文件：`/etc/tg-export/.env`
- 可写运行时配置：`/etc/tg-export/config/runtime.env`
- 持久化数据目录：`/etc/tg-export/data`
- 下载目录通过 `/etc/tg-export/.env` 中的 `DOWNLOAD_DIR` 指定，并挂载到容器内 `/downloads`

## 3. 部署流程
代码修改完成后，必须在源码目录执行：

```bash
cd /root/code/tg-export
sudo ./scripts/deploy.sh
```

部署脚本会执行以下动作：
1. 初始化 `/etc/tg-export/config` 与 `/etc/tg-export/data`
2. 迁移旧版 `data/.env` 到 `config/runtime.env`
3. 在源码目录构建 `tg-export:latest`
4. 将运行目录的 `docker-compose.yml` 链接到源码版本
5. 清理 `/etc/tg-export` 中残留的源码文件
6. 在 `/etc/tg-export` 启动容器

## 4. AI 助手操作约束
- 改逻辑：只允许改 `/root/code/tg-export`
- 改运行时配置：只允许改 `/etc/tg-export/.env` 或 `/etc/tg-export/config/runtime.env`
- 发布代码：必须运行 `scripts/deploy.sh`
- 严禁在 `/etc/tg-export` 及其子目录创建或修改源码文件
