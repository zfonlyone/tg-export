#!/bin/bash

# ═══════════════════════════════════════════════════════════
# TG Export 一键部署脚本 v2.4.5
# 功能: 安装/卸载 TG Export + Nginx 反向代理
# 证书管理: 使用 nginx-acme 模块自动管理
# 更新日志: 任务独立存储、TDL单项下载、文件命名统一
# ═══════════════════════════════════════════════════════════

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
PLAIN='\033[0m'

# ===== 统一配置 =====
APP_NAME="TG Export"
APP_VERSION="2.4.5"
APP_DIR="/opt/tg-export"
CONFIG_DIR="$APP_DIR/config"
CONFIG_FILE="$CONFIG_DIR/config.yml"
DOCKER_IMAGE="zfonlyone/tg-export:latest"
WEB_PORT=9528
NGINX_HTTPS_PORT=443
NGINX_SITES_DIR="/etc/nginx/sites-available"
NGINX_ENABLED_DIR="/etc/nginx/sites-enabled"
CERT_DIR="/etc/nginx/acme/letsencrypt"

# 旧配置文件路径
OLD_CONFIG_FILE="$APP_DIR/.tge_config"
OLD_ENV_FILE="$APP_DIR/.env"

# 日志函数
log() { echo -e "${GREEN}[✓]${PLAIN} $1"; }
warn() { echo -e "${YELLOW}[!]${PLAIN} $1"; }
error() { echo -e "${RED}[✗]${PLAIN} $1"; }
info() { echo -e "${CYAN}[i]${PLAIN} $1"; }

# Docker Compose 兼容封装
docker_compose() {
    # 如果安装目录已存在，尝试切换过去
    if [[ -d "$APP_DIR" ]]; then
        cd "$APP_DIR" || exit
    fi
    
    if command -v docker-compose &> /dev/null; then
        docker-compose "$@"
    elif docker compose version &> /dev/null; then
        docker compose "$@"
    else
        error "未检测到 docker-compose 或 docker compose"
        return 1
    fi
}

# ===== 显示菜单 =====
show_menu() {
    clear
    echo -e ""
    echo -e "${CYAN}${BOLD}  ╔══════════════════════════════════════════════════════╗${PLAIN}"
    echo -e "${CYAN}${BOLD}  ║     📦 TG Export - Telegram 全功能导出工具           ║${PLAIN}"
    echo -e "${CYAN}${BOLD}  ║                    Version ${APP_VERSION}                     ║${PLAIN}"
    echo -e "${CYAN}${BOLD}  ╚══════════════════════════════════════════════════════╝${PLAIN}"
    echo -e ""
    echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━ 📋 主菜单 ━━━━━━━━━━━━━━━━━━${PLAIN}"
    echo -e ""
    echo -e "    ${GREEN}1)${PLAIN} 🚀 安装 TG Export"
    echo -e "    ${GREEN}2)${PLAIN} 🗑️  卸载 TG Export"
    echo -e "    ${GREEN}3)${PLAIN} ⬆️  更新 TG Export"
    echo -e "    ${GREEN}4)${PLAIN} 📊 查看运行状态"
    echo -e "    ${GREEN}5)${PLAIN} 📜 查看实时日志"
    echo -e "    ${GREEN}6)${PLAIN} 🔒 配置 Nginx 反代"
    echo -e ""
    echo -e "    ${RED}0)${PLAIN} ❌ 退出"
    echo -e ""
    echo -e "  ${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${PLAIN}"
    echo -e ""
}

# ===== 环境检查 =====
check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "请使用 root 用户运行此脚本！"
        exit 1
    fi
}

check_disk() {
    local FREE_GB=$(df -m / | awk 'NR==2 {print $4}')
    if [[ $FREE_GB -lt 1024 ]]; then
        warn "系统盘剩余空间较少 (${FREE_GB}MB)，请确保有足够的空间下载 Telegram 媒体。"
    fi
}

# ===== 迁移并删除旧配置 =====
migrate_config() {
    local need_save=false
    
    # 迁移旧 .tge_config
    if [ -f "$OLD_CONFIG_FILE" ]; then
        log "检测到旧配置文件: $OLD_CONFIG_FILE"
        source "$OLD_CONFIG_FILE"
        rm -f "$OLD_CONFIG_FILE"
        log "已读取并删除旧配置"
        need_save=true
    fi
    
    # 迁移并删除旧 .env (v2.3.1 彻底迁移至 config.yml)
    if [ -f "$OLD_ENV_FILE" ]; then
        log "检测到旧环境变量文件: $OLD_ENV_FILE"
        # 尝试提取 SECRET_KEY 等残留字段
        local OLD_SECRET=$(grep "^SECRET_KEY=" "$OLD_ENV_FILE" | cut -d'=' -f2-)
        local OLD_IPV6=$(grep "^USE_IPV6=" "$OLD_ENV_FILE" | cut -d'=' -f2-)
        local OLD_TDL=$(grep "^TDL_CONTAINER_NAME=" "$OLD_ENV_FILE" | cut -d'=' -f2-)
        
        [ -n "$OLD_SECRET" ] && SECRET_KEY="$OLD_SECRET"
        [ -n "$OLD_IPV6" ] && USE_IPV6="$OLD_IPV6"
        [ -n "$OLD_TDL" ] && TDL_CONTAINER_NAME="$OLD_TDL"
        
        rm -f "$OLD_ENV_FILE"
        log "已迁移残留字段并删除旧 .env"
        need_save=true
    fi
    
    # 如果有迁移，保存为新格式
    if $need_save; then
        save_config
        log "配置已合并至: $CONFIG_FILE"
    fi
}

# ===== 读取配置 (YAML 格式) =====
load_config() {
    migrate_config
    
    if [ -f "$CONFIG_FILE" ]; then
        # 简单解析 YAML (v2.3.1 支持更多字段)
        API_ID=$(grep -E "^\s*api_id:" "$CONFIG_FILE" | awk '{print $2}' | tr -d '"' | head -1)
        API_HASH=$(grep -E "^\s*api_hash:" "$CONFIG_FILE" | awk '{print $2}' | tr -d '"' | head -1)
        BOT_TOKEN=$(grep -E "^\s*bot_token:" "$CONFIG_FILE" | awk '{print $2}' | tr -d '"' | head -1)
        ADMIN_PASSWORD=$(grep -E "^\s*password:" "$CONFIG_FILE" | awk '{print $2}' | tr -d '"' | head -1)
        WEB_PORT=$(grep -E "^\s*web_port:" "$CONFIG_FILE" | awk '{print $2}' | head -1)
        NGINX_HTTPS_PORT=$(grep -E "^\s*nginx_https_port:" "$CONFIG_FILE" | awk '{print $2}' | head -1)
        DOMAIN=$(grep -E "^\s*domain:" "$CONFIG_FILE" | awk '{print $2}' | tr -d '"' | head -1)
        DOWNLOAD_DIR=$(grep -E "^\s*download_dir:" "$CONFIG_FILE" | awk '{print $2}' | tr -d '"' | head -1)
        LOG_LEVEL=$(grep -E "^\s*level:" "$CONFIG_FILE" | awk '{print $2}' | tr -d '"' | head -1)
        DOCKER_IMAGE=$(grep -E "^\s*image:" "$CONFIG_FILE" | awk '{print $2}' | tr -d '"' | head -1)
        SECRET_KEY=$(grep -E "^\s*secret_key:" "$CONFIG_FILE" | awk '{print $2}' | tr -d '"' | head -1)
        TDL_CONTAINER_NAME=$(grep -E "^\s*tdl_container:" "$CONFIG_FILE" | awk '{print $2}' | tr -d '"' | head -1)
        USE_IPV6=$(grep -E "^\s*use_ipv6:" "$CONFIG_FILE" | awk '{print $2}' | head -1)
        return 0
    fi
    return 1
}

# ===== 保存配置 (YAML 格式) =====
save_config() {
    mkdir -p "$CONFIG_DIR"
    # 如果 SECRET_KEY 为空，生成一个
    [ -z "$SECRET_KEY" ] && SECRET_KEY=$(openssl rand -hex 32)
    
    cat > "$CONFIG_FILE" <<EOF
# TG Export 配置文件 (由 tg-export.sh 自动生成)
# 生成时间: $(date '+%Y-%m-%d %H:%M:%S')

# Telegram API 配置
telegram:
  api_id: "${API_ID}"
  api_hash: "${API_HASH}"
  bot_token: "${BOT_TOKEN}"

# 服务配置
server:
  web_port: ${WEB_PORT:-9528}
  nginx_https_port: ${NGINX_HTTPS_PORT:-443}
  domain: "${DOMAIN}"
  secret_key: "${SECRET_KEY}"

# 管理员配置
admin:
  password: "${ADMIN_PASSWORD}"

# 存储配置
storage:
  download_dir: "${DOWNLOAD_DIR:-/storage/downloads}"

# Docker 配置
docker:
  image: "${DOCKER_IMAGE:-zfonlyone/tg-export:latest}"
  tdl_container: "${TDL_CONTAINER_NAME:-tdl}"
  use_ipv6: ${USE_IPV6:-true}

# 日志配置
logging:
  level: ${LOG_LEVEL:-DEBUG}
EOF
    chmod 600 "$CONFIG_FILE"
    log "配置已保存到 $CONFIG_FILE"
}

# ===== 显示当前配置 =====
show_config() {
    echo -e "${CYAN}当前配置:${PLAIN}"
    echo -e "  API_ID: ${GREEN}${API_ID:-未设置}${PLAIN}"
    echo -e "  API_HASH: ${GREEN}${API_HASH:+已设置}${API_HASH:-未设置}${PLAIN}"
    echo -e "  Bot Token: ${GREEN}${BOT_TOKEN:+已设置}${BOT_TOKEN:-未设置}${PLAIN}"
    echo -e "  管理员密码: ${GREEN}${ADMIN_PASSWORD:+已设置}${ADMIN_PASSWORD:-未设置}${PLAIN}"
    echo -e "  Docker 服务端口: ${GREEN}${WEB_PORT:-9528}${PLAIN}"
    echo -e "  Nginx HTTPS 端口: ${GREEN}${NGINX_HTTPS_PORT:-443}${PLAIN}"
    echo -e "  域名: ${GREEN}${DOMAIN:-未设置}${PLAIN}"
    echo -e "  Nginx: ${GREEN}${ENABLE_NGINX:-n}${PLAIN}"
    echo -e "  下载目录: ${GREEN}${DOWNLOAD_DIR:-/storage/downloads}${PLAIN}"
    echo -e "  日志级别: ${GREEN}${LOG_LEVEL:-DEBUG}${PLAIN}"
}

# ===== 配置 Nginx (使用 nginx-acme 模块) =====
setup_nginx() {
    echo -e "${CYAN}${BOLD}===== 配置 Nginx 反向代理 (nginx-acme) =====${PLAIN}"
    
    # 检查 nginx-acme 模块
    if ! nginx -V 2>&1 | grep -q "nginx-acme"; then
        warn "未检测到 nginx-acme 模块"
        echo -e "${YELLOW}请先运行 nginx-acme.sh 安装带 ACME 模块的 Nginx${PLAIN}"
        return 1
    fi
    
    load_config
    
    # 域名配置
    read -p "请输入完整域名 (例如 tg-export.example.com): " DOMAIN
    if [ -z "$DOMAIN" ]; then
        error "域名不能为空"
        return 1
    fi
    
    # HTTPS 端口配置
    read -p "Nginx HTTPS 端口 [默认 443]: " INPUT_HTTPS_PORT
    NGINX_HTTPS_PORT=${INPUT_HTTPS_PORT:-443}
    
    # Docker 服务端口
    if [ -z "$WEB_PORT" ]; then
        read -p "Docker 服务端口 [默认 9528]: " INPUT_WEB_PORT
        WEB_PORT=${INPUT_WEB_PORT:-9528}
    else
        info "使用已配置的服务端口: $WEB_PORT"
    fi
    
    # Nginx 配置文件路径 (以完整域名命名)
    NGINX_CONF="$NGINX_SITES_DIR/$DOMAIN"
    
    # 生成 Nginx 配置
    cat > "$NGINX_CONF" <<NGINX
# TG Export - nginx-acme HTTPS 配置
# 由 tg-export.sh v2.3 自动生成
# 域名: ${DOMAIN}

map \$http_upgrade \$connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen ${NGINX_HTTPS_PORT} ssl;
    listen [::]:${NGINX_HTTPS_PORT} ssl;
    http2 on;
    server_name ${DOMAIN};
    
    access_log /var/log/nginx/${DOMAIN}-access.log;
    error_log /var/log/nginx/${DOMAIN}-error.log;
    
    # nginx-acme 自动证书
    acme_certificate letsencrypt;
    ssl_certificate \$acme_certificate;
    ssl_certificate_key \$acme_certificate_key;
    ssl_certificate_cache max=2;
    
    location / {
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_pass http://127.0.0.1:${WEB_PORT};
    }
}
NGINX
    
    # 启用站点
    ln -sf "$NGINX_CONF" "$NGINX_ENABLED_DIR/$DOMAIN"
    
    if nginx -t; then
        nginx -s reload
        log "Nginx 配置成功！"
        echo
        info "配置文件: $NGINX_CONF"
        info "证书目录: $CERT_DIR (由 nginx-acme 自动管理)"
        echo
        echo -e "${YELLOW}请确保防火墙已开放端口:${PLAIN}"
        echo -e "  ufw allow 80/tcp && ufw allow ${NGINX_HTTPS_PORT}/tcp"
        echo
        if [ "$NGINX_HTTPS_PORT" == "443" ]; then
            echo -e "访问地址: ${CYAN}https://${DOMAIN}${PLAIN}"
        else
            echo -e "访问地址: ${CYAN}https://${DOMAIN}:${NGINX_HTTPS_PORT}${PLAIN}"
        fi
        save_config
    else
        error "Nginx 配置有误"
        rm -f "$NGINX_CONF"
    fi
}

# ===== 获取用户输入 =====
get_input_info() {
    local QUICK_MODE=false
    
    if load_config; then
        echo -e "${CYAN}${BOLD}===== 检测到已保存的配置 =====${PLAIN}"
        show_config
        echo
        echo -e "  ${GREEN}1)${PLAIN} 使用已保存的配置 (默认)"
        echo -e "  ${GREEN}2)${PLAIN} 修改配置"
        echo -e "  ${GREEN}3)${PLAIN} 全新配置"
        read -p "请选择 [1]: " CONFIG_CHOICE
        CONFIG_CHOICE=${CONFIG_CHOICE:-1}
        
        case $CONFIG_CHOICE in
            1)
                log "使用已保存的配置"
                return
                ;;
            2)
                # 修改模式 - 显示当前值作为默认
                QUICK_MODE=true
                ;;
            3)
                # 全新配置 - 清空现有值
                API_ID=""
                API_HASH=""
                BOT_TOKEN=""
                ADMIN_PASSWORD=""
                DOMAIN=""
                ;;
        esac
    fi

    echo -e "${CYAN}${BOLD}===== 配置向导 =====${PLAIN}"
    echo
    echo -e "${YELLOW}Telegram API 配置 (用于连接 Telegram):${PLAIN}"
    echo "  1. 访问 https://my.telegram.org"
    echo "  2. 登录后进入 API development tools"
    echo "  3. 创建应用获取 API ID 和 API Hash"
    echo -e "  ${CYAN}注: 这只是 API 配置，账号登录在 Web 面板完成${PLAIN}"
    echo
    
    # API ID
    if [ -n "$API_ID" ]; then
        read -p "请输入 API ID [$API_ID]: " NEW_API_ID
        API_ID=${NEW_API_ID:-$API_ID}
    else
        read -p "请输入 API ID: " API_ID
    fi
    
    # API Hash
    if [ -n "$API_HASH" ]; then
        read -p "请输入 API Hash [已保存]: " NEW_API_HASH
        API_HASH=${NEW_API_HASH:-$API_HASH}
    else
        read -p "请输入 API Hash: " API_HASH
    fi
    
    echo
    echo -e "${YELLOW}Bot Token (可选，用于 Bot 控制):${PLAIN}"
    if [ -n "$BOT_TOKEN" ]; then
        read -p "请输入 Bot Token [已保存]: " NEW_BOT_TOKEN
        BOT_TOKEN=${NEW_BOT_TOKEN:-$BOT_TOKEN}
    else
        read -p "请输入 Bot Token (留空跳过): " BOT_TOKEN
    fi
    
    echo
    # 管理员密码
    if [ -n "$ADMIN_PASSWORD" ]; then
        read -p "管理员密码 [已保存]: " NEW_ADMIN_PASSWORD
        ADMIN_PASSWORD=${NEW_ADMIN_PASSWORD:-$ADMIN_PASSWORD}
    else
        read -p "管理员密码 (留空自动生成): " ADMIN_PASSWORD
        if [ -z "$ADMIN_PASSWORD" ]; then
            ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -dc 'a-zA-Z0-9' | head -c 12)
            echo -e "${GREEN}自动生成密码: ${YELLOW}${ADMIN_PASSWORD}${PLAIN}"
        fi
    fi
    
    echo
    # 域名
    if [ -n "$DOMAIN" ]; then
        read -p "域名 [$DOMAIN]: " NEW_DOMAIN
        DOMAIN=${NEW_DOMAIN:-$DOMAIN}
    else
        read -p "域名 (留空使用 IP): " DOMAIN
    fi
    
    # 提取主域名
    if [ -n "$DOMAIN" ]; then
        MAIN_DOMAIN=$(echo "$DOMAIN" | sed 's/^[^.]*\.//')
    fi
    
    echo
    # 下载目录
    DOWNLOAD_DIR=${DOWNLOAD_DIR:-/storage/downloads}
    read -p "下载目录 [$DOWNLOAD_DIR]: " NEW_DOWNLOAD_DIR
    DOWNLOAD_DIR=${NEW_DOWNLOAD_DIR:-$DOWNLOAD_DIR}
    
    echo
    # 可选组件
    echo -e "${CYAN}可选组件:${PLAIN}"
    
    # Nginx
    ENABLE_NGINX=${ENABLE_NGINX:-n}
    read -p "配置 Nginx 反向代理? [y/N] [$ENABLE_NGINX]: " NEW_ENABLE_NGINX
    ENABLE_NGINX=${NEW_ENABLE_NGINX:-$ENABLE_NGINX}
    
    if [[ "$ENABLE_NGINX" =~ ^[Yy]$ ]]; then
        echo -e "  1) 仅 HTTP"
        echo -e "  2) 仅 HTTPS"
        echo -e "  3) HTTPS + HTTP 跳转 (默认)"
        NGINX_TYPE=${NGINX_TYPE:-3}
        read -p "  Nginx 类型 [$NGINX_TYPE]: " NEW_NGINX_TYPE
        NGINX_TYPE=${NEW_NGINX_TYPE:-$NGINX_TYPE}
        
        if [[ "$NGINX_TYPE" != "1" ]]; then
            ENABLE_SSL="y"
        fi
    fi
}

# ===== 安装 =====
install_app() {
    log "开始安装 $APP_NAME..."
    
    # 安装 Docker
    if ! command -v docker &> /dev/null; then
        log "正在安装 Docker..."
        curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun
        systemctl enable --now docker
    else
        log "Docker 已安装"
    fi
    
    # 安装 Docker Compose
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null 2>&1; then
        log "正在安装 Docker Compose..."
        curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        chmod +x /usr/local/bin/docker-compose
    fi
    
    get_input_info
    
    # 使用配置的下载目录
    DOWNLOAD_DIR=${DOWNLOAD_DIR:-/storage/downloads}
    
    mkdir -p "$APP_DIR/data"
    mkdir -p "$DOWNLOAD_DIR"
    cd "$APP_DIR" || exit
    
    save_config
    
    save_config
    
    # 彻底弃用 .env，所有变量直接注入 environment (v2.3.1)
    # 不再生成 .env 文件
    
    # 使用配置的镜像
    DOCKER_IMAGE=${DOCKER_IMAGE:-ghcr.io/your-username/tg-export:latest}
    WEB_PORT=${WEB_PORT:-9528}
    
    # 生成 docker-compose.yml
    cat > docker-compose.yml <<YAML
services:
  tg-export:
    image: ${DOCKER_IMAGE:-zfonlyone/tg-export:latest}
    container_name: tg-export
    restart: unless-stopped
    ports:
      - "${WEB_PORT:-9528}:${WEB_PORT:-9528}"
    volumes:
      - ./data:/app/data:shared
      - $DOWNLOAD_DIR:/downloads:shared
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config:/app/config:ro
    environment:
      - TZ=Asia/Shanghai
      - WEB_PORT=${WEB_PORT:-9528}
      - DATA_DIR=/app/data
      - EXPORT_DIR=/downloads
      - TEMP_DIR=/app/data/temp
      - CONFIG_PATH=/app/config/config.yml
      # 显式注入关键变量以便后端回退兼容或直接使用
      - API_ID=$API_ID
      - API_HASH=$API_HASH
      - BOT_TOKEN=$BOT_TOKEN
      - ADMIN_PASSWORD=$ADMIN_PASSWORD
      - SECRET_KEY=$SECRET_KEY
      - TDL_CONTAINER_NAME=${TDL_CONTAINER_NAME:-tdl}
      - USE_IPV6=${USE_IPV6:-true}
      - LOG_LEVEL=${LOG_LEVEL:-DEBUG}
YAML
    
    log "拉取镜像..."
    docker_compose pull
    
    log "启动服务..."
    docker_compose up --build -d
    
    sleep 3
    if docker ps | grep -q tg-export; then
        log "TG Export 启动成功！"
    else
        error "启动失败，请检查: docker logs tg-export"
        return 1
    fi
    
    # 安装快捷命令
    install_shortcut
    
    # 根据配置自动配置 Nginx
    if [[ "$ENABLE_NGINX" =~ ^[Yy]$ ]]; then
        log "根据配置自动配置 Nginx..."
        setup_nginx_auto
    else
        echo
        read -p "是否配置 Nginx 反向代理? [y/N]: " SETUP_NGINX
        if [[ "$SETUP_NGINX" =~ ^[Yy]$ ]]; then
            setup_nginx
        fi
    fi
    
    # 输出结果
    IPV4=$(curl -s 4.ipw.cn 2>/dev/null || curl -s ifconfig.me)
    echo
    echo -e "${GREEN}=============================================${PLAIN}"
    echo -e "${GREEN}✅ TG Export 安装完成！${PLAIN}"
    echo -e "${GREEN}=============================================${PLAIN}"
    echo -e "配置文件: ${CYAN}$APP_DIR/$CONFIG_FILE${PLAIN}"
    if [[ -n "$DOMAIN" ]]; then
        if [[ "$ENABLE_NGINX" =~ ^[Yy]$ ]] && [[ "$NGINX_TYPE" != "1" ]]; then
            echo -e "访问地址: ${CYAN}https://${DOMAIN}${PLAIN}"
        else
            echo -e "访问地址: ${CYAN}http://${DOMAIN}${PLAIN}"
        fi
    else
        echo -e "访问地址: ${CYAN}http://${IPV4}:${WEB_PORT}${PLAIN}"
    fi
    echo -e "管理员: ${CYAN}admin${PLAIN}"
    echo -e "密码: ${YELLOW}${ADMIN_PASSWORD}${PLAIN}"
    echo -e "下载目录: ${CYAN}${DOWNLOAD_DIR}${PLAIN}"
    echo -e "管理命令: ${CYAN}tge${PLAIN}"
    echo -e "${GREEN}=============================================${PLAIN}"
    echo
    echo -e "${YELLOW}📱 下一步: 打开 Web 面板 -> 设置${PLAIN}"
    echo -e "  ${CYAN}App API 配置:${PLAIN} 输入 API ID 和 API Hash (首次需要)"
    echo -e "  ${CYAN}账号登录:${PLAIN}"
    echo -e "    1. 输入手机号 (含国际区号)"
    echo -e "    2. 输入 Telegram 收到的验证码"
    echo -e "    3. 如有两步验证，输入密码"
    echo
}

# ===== 自动配置 Nginx (使用 nginx-acme) =====
setup_nginx_auto() {
    if ! nginx -V 2>&1 | grep -q "nginx-acme"; then
        warn "未检测到 nginx-acme 模块，跳过 Nginx 配置"
        return 1
    fi
    
    [ -z "$DOMAIN" ] && return 1
    
    WEB_PORT=${WEB_PORT:-9528}
    NGINX_CONF="$NGINX_SITES_DIR/$DOMAIN"
    
    cat > "$NGINX_CONF" <<NGINX
# TG Export - nginx-acme HTTPS
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name ${DOMAIN};
    
    access_log /var/log/nginx/${DOMAIN}-access.log;
    error_log /var/log/nginx/${DOMAIN}-error.log;
    
    acme_certificate letsencrypt;
    ssl_certificate \$acme_certificate;
    ssl_certificate_key \$acme_certificate_key;
    ssl_certificate_cache max=2;
    
    location / {
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_pass http://127.0.0.1:${WEB_PORT};
    }
}
NGINX
    
    ln -sf "$NGINX_CONF" "$NGINX_ENABLED_DIR/$DOMAIN"
    nginx -t && nginx -s reload && log "Nginx 配置成功！"
}

# ===== 安装快捷命令 =====
install_shortcut() {
    log "正在安装 'tge' 管理工具..."
    
    cat > /usr/bin/tge <<'SCRIPT'
#!/bin/bash
# TG Export 快捷管理命令

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'
APP_VERSION="2.4.5"

APP_DIR="/opt/tg-export"

# Docker Compose 封装 (含目录切换)
function docker_compose() {
    cd "$APP_DIR" || exit
    if command -v docker-compose &> /dev/null; then
        docker-compose "$@"
    else
        docker compose "$@"
    fi
}

function show_menu() {
    clear
    echo -e ""
    echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║    📦 TG Export 管理工具 v${APP_VERSION}      ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
    echo -e ""
    echo -e "  ${GREEN}1)${NC} ▶️  启动服务"
    echo -e "  ${GREEN}2)${NC} ⏹️  停止服务"
    echo -e "  ${GREEN}3)${NC} 🔄 重启服务"
    echo -e "  ${GREEN}4)${NC} 📊 查看状态"
    echo -e "  ${GREEN}5)${NC} 📜 查看日志"
    echo -e "  ${GREEN}6)${NC} ⬆️  更新镜像"
    echo -e "  ${GREEN}7)${NC} 🔑 密码管理"
    echo -e "  ${GREEN}8)${NC} 🚀 安装/更新"
    echo -e "  ${GREEN}9)${NC} 🗑️  卸载工具"
    echo -e "  ${RED}0)${NC} ❌ 退出"
    echo -e ""
    read -p "请选择 [0-9]: " choice
    handle_choice "$choice"
}

function handle_choice() {
    case $1 in
        1) cd "$APP_DIR" && docker_compose up -d; read -p "按回车继续..."; show_menu ;;
        2) cd "$APP_DIR" && docker_compose down; read -p "按回车继续..."; show_menu ;;
        3) cd "$APP_DIR" && docker_compose restart; read -p "按回车继续..."; show_menu ;;
        4) 
            docker ps | grep -E "CONTAINER|tg-export"
            echo
            if [ -f /etc/nginx/sites-available/tg-export ]; then
                DOMAIN=$(grep "server_name" /etc/nginx/sites-available/tg-export | head -1 | awk '{print $2}' | tr -d ';')
                echo -e "域名: ${GREEN}$DOMAIN${NC}"
            fi
            read -p "按回车继续..."
            show_menu
            ;;
        5) docker_compose logs -f --tail=100 tg-export ;;
        6) cd "$APP_DIR" && docker_compose pull && docker_compose up -d; read -p "按回车继续..."; show_menu ;;
        7) manage_password; show_menu ;;
        8) bash "$APP_DIR/tg-export.sh" install; read -p "按回车继续..."; show_menu ;;
        9) bash "$APP_DIR/tg-export.sh" uninstall; exit 0 ;;
        0) exit 0 ;;
        *) show_menu ;;
    esac
}

function manage_password() {
    echo -e "${CYAN}=== 密码管理 ===${NC}"
    echo
    local YAML_FILE="$APP_DIR/config/config.yml"
    if [ -f "$YAML_FILE" ]; then
        CURRENT_PWD=$(grep -E "^\s*password:" "$YAML_FILE" | awk '{print $2}' | tr -d '"' | head -1)
        echo -e "当前密码: ${YELLOW}$CURRENT_PWD${NC}"
    else
        echo -e "${RED}未找到 YAML 配置文件: $YAML_FILE${NC}"
    fi
    echo
    echo "1. 修改密码"
    echo "2. 重置密码 (随机生成)"
    echo "0. 返回"
    read -p "请选择: " pwd_choice
    
    case $pwd_choice in
        1)
            read -p "请输入新密码: " NEW_PWD
            if [ -n "$NEW_PWD" ]; then
                update_password "$NEW_PWD"
            else
                echo -e "${RED}密码不能为空${NC}"
            fi
            ;;
        2)
            NEW_PWD=$(openssl rand -base64 12 | tr -dc 'a-zA-Z0-9' | head -c 12)
            update_password "$NEW_PWD"
            ;;
    esac
    read -p "按回车继续..."
}

function update_password() {
    local NEW_PWD=$1
    local YAML_FILE="$APP_DIR/config/config.yml"
    
    # 1. 更新 config.yml
    if [ -f "$YAML_FILE" ]; then
        sed -i "s/^\(\s*password:\).*/\1 \"$NEW_PWD\"/" "$YAML_FILE"
        echo -e "${GREEN}YAML 配置已更新${NC}"
    fi
    
    # 2. 更新 docker-compose.yml 并重启服务
    if [ -f "$APP_DIR/docker-compose.yml" ]; then
        sed -i "s/- ADMIN_PASSWORD=.*/- ADMIN_PASSWORD=$NEW_PWD/" "$APP_DIR/docker-compose.yml"
        echo -e "${CYAN}正在重启服务以生效新密码...${NC}"
        docker_compose up -d
    fi
    
    echo -e "${GREEN}密码修改成功！${NC}"
}



# 直接命令支持
case "$1" in
    start) cd "$APP_DIR" && docker_compose up -d ;;
    stop) cd "$APP_DIR" && docker_compose down ;;
    restart) cd "$APP_DIR" && docker_compose restart ;;
    logs) docker_compose logs -f --tail=100 tg-export ;;
    update) cd "$APP_DIR" && docker_compose pull && docker_compose up --build -d ;;
    status) docker ps | grep -E "CONTAINER|tg-export" ;;
    "") show_menu ;;
    *) echo "用法: tge {start|stop|restart|logs|update|status}" ;;
esac
SCRIPT
    chmod +x /usr/bin/tge
    log "'tge' 命令已安装"
}

# ===== 卸载 =====
uninstall_app() {
    echo -e "${RED}${BOLD}===== 卸载 TG Export =====${PLAIN}"
    
    load_config
    
    echo
    echo "将执行以下操作:"
    echo "  1. 停止并删除 TG Export 容器"
    echo "  2. 删除快捷命令 tge"
    echo
    
    # 检测 Nginx 配置
    if [ -n "$DOMAIN" ] && [ -f "$NGINX_SITES_DIR/$DOMAIN" ]; then
        echo -e "检测到 Nginx 配置: ${CYAN}$NGINX_SITES_DIR/$DOMAIN${PLAIN}"
    fi
    
    read -p "是否删除数据目录 ($APP_DIR)? (y/N): " DELETE_DATA
    read -p "是否删除 Nginx 配置和相关证书? (y/N): " DELETE_NGINX
    echo
    read -p "确认卸载 TG Export? (y/N): " CONFIRM
    
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        log "取消卸载"
        return
    fi
    
    # 停止容器
    if [ -f "$APP_DIR/docker-compose.yml" ]; then
        log "正在停止 TG Export 服务..."
        cd "$APP_DIR"
        docker_compose down 2>/dev/null || true
    fi
    
    docker stop tg-export 2>/dev/null || true
    docker rm tg-export 2>/dev/null || true
    log "已删除容器"
    
    # 删除 Nginx 配置和证书
    if [[ "$DELETE_NGINX" =~ ^[Yy]$ ]]; then
        if [ -n "$DOMAIN" ]; then
            # 删除 Nginx 配置
            if [ -f "$NGINX_SITES_DIR/$DOMAIN" ]; then
                rm -f "$NGINX_SITES_DIR/$DOMAIN"
                rm -f "$NGINX_ENABLED_DIR/$DOMAIN"
                log "已删除 Nginx 配置: $DOMAIN"
            fi
            
            # 删除对应子域名的证书 (nginx-acme 自动生成的)
            if [ -f "$CERT_DIR/${DOMAIN}.crt" ]; then
                rm -f "$CERT_DIR/${DOMAIN}.crt"
                rm -f "$CERT_DIR/${DOMAIN}.key"
                log "已删除证书: ${DOMAIN}"
            fi
            
            nginx -s reload 2>/dev/null || true
        fi
    fi
    
    # 删除数据目录
    if [[ "$DELETE_DATA" =~ ^[Yy]$ ]]; then
        if [ -d "$APP_DIR" ]; then
            rm -rf "$APP_DIR"
            log "已删除数据目录"
        fi
    else
        log "保留数据目录: $APP_DIR"
    fi
    
    # 删除快捷命令
    rm -f /usr/bin/tge
    log "已删除 tge 命令"
    
    echo
    log "TG Export 卸载完成！"
}

# ===== 更新 =====
update_app() {
    log "正在更新 TG Export..."
    cd "$APP_DIR" || exit
    docker_compose pull
    docker_compose up --build -d
    log "更新完成！"
}

# ===== 查看状态 =====
show_status() {
    echo -e "${CYAN}${BOLD}===== TG Export 状态 =====${PLAIN}"
    echo -e "当前版本: ${GREEN}${APP_VERSION}${PLAIN}"
    echo
    
    load_config
    
    if docker ps | grep -q tg-export; then
        echo -e "容器状态: ${GREEN}运行中${PLAIN}"
        docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep tg-export
    else
        echo -e "容器状态: ${RED}未运行${PLAIN}"
    fi
    
    echo
    
    # Nginx 配置
    if [ -n "$DOMAIN" ] && [ -f "$NGINX_SITES_DIR/$DOMAIN" ]; then
        echo -e "Nginx 配置: ${GREEN}$NGINX_SITES_DIR/$DOMAIN${PLAIN}"
        echo -e "域名: ${CYAN}$DOMAIN${PLAIN}"
        echo -e "SSL: ${CYAN}nginx-acme 模块自动管理${PLAIN}"
    else
        echo -e "Nginx: ${YELLOW}未配置${PLAIN}"
    fi
    
    echo
    
    # 证书状态
    echo -e "${CYAN}证书目录: $CERT_DIR${PLAIN}"
    if [ -n "$DOMAIN" ] && [ -f "$CERT_DIR/${DOMAIN}.crt" ]; then
        EXPIRY=$(openssl x509 -enddate -noout -in "$CERT_DIR/${DOMAIN}.crt" 2>/dev/null | cut -d= -f2)
        echo -e "  ${DOMAIN}: ${GREEN}有效${PLAIN} (过期: $EXPIRY)"
    else
        echo -e "  ${YELLOW}由 nginx-acme 自动管理${PLAIN}"
    fi
    
    echo
    if [ -n "$API_ID" ]; then
        echo -e "API ID: ${GREEN}${API_ID}${PLAIN}"
        if [[ -n "$BOT_TOKEN" ]]; then
            echo -e "Bot: ${GREEN}已配置${PLAIN}"
        fi
    fi
}

# ===== 主程序 =====
main() {
    check_root
    check_disk
    
    case "$1" in
        install) install_app ;;
        uninstall) uninstall_app ;;
        update) update_app ;;
        status) show_status ;;
        nginx) setup_nginx ;;
        logs) docker_compose logs -f --tail=100 tg-export ;;
        *) 
            while true; do
                show_menu
                read -p "请选择 [0-6]: " CHOICE
                echo
                case $CHOICE in
                    1) install_app ;;
                    2) uninstall_app ;;
                    3) update_app ;;
                    4) show_status ;;
                    5) docker_compose logs -f --tail=100 tg-export ;;
                    6) setup_nginx ;;
                    0) exit 0 ;;
                    *) error "无效选择" ;;
                esac
                echo
                read -p "按回车继续..."
            done
            ;;
    esac
}

main "$@"
