#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BASE_DIR="/etc/tg-export"
CONFIG_DIR="${BASE_DIR}/config"
DATA_DIR="${BASE_DIR}/data"
ENV_FILE="${BASE_DIR}/.env"
RUNTIME_ENV_FILE="${CONFIG_DIR}/runtime.env"
IMAGE_NAME="tg-export:latest"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "$(date '+%H:%M:%S') ${GREEN}[✓]${NC} $1"
}

warn() {
    echo -e "$(date '+%H:%M:%S') ${YELLOW}[!]${NC} $1"
}

error() {
    echo -e "$(date '+%H:%M:%S') ${RED}[x]${NC} $1" >&2
}

merge_env_file() {
    local src="$1"
    local dst="$2"
    local tmp

    tmp="$(mktemp)"
    if [ -f "$dst" ]; then
        cp "$dst" "$tmp"
    else
        : >"$tmp"
    fi

    while IFS= read -r raw_line || [ -n "$raw_line" ]; do
        local line="$raw_line"
        local key

        line="${line%$'\r'}"
        case "$line" in
            ""|\#*) continue ;;
            *=*) ;;
            *) continue ;;
        esac

        key="${line%%=*}"
        awk -v env_key="$key" -F= '$1 != env_key' "$tmp" >"${tmp}.next"
        mv "${tmp}.next" "$tmp"
        printf '%s\n' "$line" >>"$tmp"
    done <"$src"

    mv "$tmp" "$dst"
}

log "初始化隔离后的运行时目录..."
mkdir -p \
    "$CONFIG_DIR" \
    "$DATA_DIR/exports" \
    "$DATA_DIR/logs" \
    "$DATA_DIR/sessions" \
    "$DATA_DIR/tasks"

if [ ! -f "$ENV_FILE" ]; then
    cp "${PROJECT_DIR}/.env.example" "$ENV_FILE"
    warn "已创建 ${ENV_FILE}，请按需补全真实配置后再对外提供服务。"
fi

if [ -f "${DATA_DIR}/.env" ]; then
    log "迁移旧版 data/.env 到 config/runtime.env ..."
    merge_env_file "${DATA_DIR}/.env" "$RUNTIME_ENV_FILE"
    rm -f "${DATA_DIR}/.env"
fi

touch "$RUNTIME_ENV_FILE"
chmod 600 "$RUNTIME_ENV_FILE" || true

log "在源码目录构建本地镜像..."
cd "$PROJECT_DIR"
docker build -t "$IMAGE_NAME" .

log "同步运行时编排入口..."
ln -sf "${PROJECT_DIR}/docker-compose.yml" "${BASE_DIR}/docker-compose.yml"

log "清理运行目录中的源码文件..."
find "$BASE_DIR" -mindepth 1 -maxdepth 1 \
    ! -name '.env' \
    ! -name 'config' \
    ! -name 'data' \
    ! -name 'docker-compose.yml' \
    -exec rm -rf {} +

log "在运行目录启动服务..."
cd "$BASE_DIR"
docker compose --env-file "$ENV_FILE" down || true
docker compose --env-file "$ENV_FILE" up -d --remove-orphans

log "部署完成。运行时代码已清理，配置与数据已隔离。"
