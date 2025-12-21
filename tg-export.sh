#!/bin/bash

# ==========================================================
# TG Export 一键部署脚本 v1.1
# 功能: 安装/卸载 TG Export + Nginx + SSL证书管理 + UFW端口
# 新增: 下载重试机制 + 暂停/恢复 + 失败记录 + AList 风格 UI
# ==========================================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
PLAIN='\033[0m'

# ===== 统一配置 =====
APP_NAME="TG Export"
APP_DIR="/opt/tg-export"
CONFIG_FILE=".tge_config"
DOCKER_IMAGE="zfonlyone/tg-export:latest"
WEB_PORT=9528
HTTP_PORT=8443      # Nginx HTTP 监听端口
HTTPS_PORT=9443     # Nginx HTTPS 监听端口
UNIFIED_CERT_DIR="/etc/ssl/wildcard"
NGINX_CONF="/etc/nginx/conf.d/tg-export.conf"
CRON_FILE="/etc/cron.d/wildcard-cert-renewal"
ACME_SH="$HOME/.acme.sh/acme.sh"

# 日志函数
log() { echo -e "${GREEN}[✓]${PLAIN} $1"; }
warn() { echo -e "${YELLOW}[!]${PLAIN} $1"; }
error() { echo -e "${RED}[✗]${PLAIN} $1"; }

# ===== 显示菜单 =====
show_menu() {
    echo -e "${CYAN}${BOLD}=============================================${PLAIN}"
    echo -e "${CYAN}${BOLD}      TG Export - Telegram 全功能导出工具    ${PLAIN}"
    echo -e "${CYAN}${BOLD}=============================================${PLAIN}"
    echo -e " ${GREEN}1.${PLAIN} 安装 TG Export"
    echo -e " ${GREEN}2.${PLAIN} 卸载 TG Export"
    echo -e " ${GREEN}3.${PLAIN} 更新 TG Export"
    echo -e " ${GREEN}4.${PLAIN} 查看状态"
    echo -e " ${GREEN}5.${PLAIN} 查看日志"
    echo -e " ${GREEN}6.${PLAIN} 配置 Nginx 反代"
    echo -e " ${GREEN}7.${PLAIN} 管理 SSL 证书"
    echo -e " ${GREEN}8.${PLAIN} 管理防火墙 (UFW)"
    echo -e " ${GREEN}0.${PLAIN} 退出"
    echo -e "${CYAN}---------------------------------------------${PLAIN}"
}

# ===== 权限检查 =====
check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "请使用 root 用户运行此脚本！"
        exit 1
    fi
}

# ===== 读取配置 =====
load_config() {
    if [ -f "$APP_DIR/$CONFIG_FILE" ]; then
        source "$APP_DIR/$CONFIG_FILE"
        return 0
    fi
    return 1
}

# ===== 保存配置 =====
save_config() {
    mkdir -p "$APP_DIR"
    cat > "$APP_DIR/$CONFIG_FILE" <<EOF
# TG Export 配置文件 - 自动生成
# 修改后重新运行安装即可生效

# ===== Telegram API =====
API_ID="$API_ID"
API_HASH="$API_HASH"
BOT_TOKEN="$BOT_TOKEN"

# ===== Web 面板 =====
ADMIN_PASSWORD="$ADMIN_PASSWORD"
WEB_PORT="${WEB_PORT:-9528}"

# ===== 域名配置 =====
DOMAIN="$DOMAIN"
MAIN_DOMAIN="$MAIN_DOMAIN"

# ===== 可选组件 =====
ENABLE_NGINX="${ENABLE_NGINX:-n}"
NGINX_TYPE="${NGINX_TYPE:-3}"     # 1=HTTP, 2=HTTPS, 3=HTTPS+跳转
ENABLE_SSL="${ENABLE_SSL:-n}"
SSL_PROVIDER="${SSL_PROVIDER:-1}" # 1=HTTP, 2=CF, 3=阿里, 4=DNSPod

# ===== 下载目录 =====
DOWNLOAD_DIR="${DOWNLOAD_DIR:-/storage/downloads}"

# ===== Docker 镜像 =====
DOCKER_IMAGE="${DOCKER_IMAGE:-ghcr.io/your-username/tg-export:latest}"
EOF
    chmod 600 "$APP_DIR/$CONFIG_FILE"
    log "配置已保存到 $APP_DIR/$CONFIG_FILE"
}

# ===== 显示当前配置 =====
show_config() {
    echo -e "${CYAN}当前配置:${PLAIN}"
    echo -e "  API_ID: ${GREEN}${API_ID:-未设置}${PLAIN}"
    echo -e "  API_HASH: ${GREEN}${API_HASH:+已设置}${API_HASH:-未设置}${PLAIN}"
    echo -e "  Bot Token: ${GREEN}${BOT_TOKEN:+已设置}${BOT_TOKEN:-未设置}${PLAIN}"
    echo -e "  管理员密码: ${GREEN}${ADMIN_PASSWORD:+已设置}${ADMIN_PASSWORD:-未设置}${PLAIN}"
    echo -e "  Web 端口: ${GREEN}${WEB_PORT:-9528}${PLAIN}"
    echo -e "  域名: ${GREEN}${DOMAIN:-未设置}${PLAIN}"
    echo -e "  Nginx: ${GREEN}${ENABLE_NGINX:-n}${PLAIN}"
    echo -e "  SSL: ${GREEN}${ENABLE_SSL:-n}${PLAIN}"
    echo -e "  下载目录: ${GREEN}${DOWNLOAD_DIR:-/storage/downloads}${PLAIN}"
}

# ===== UFW 防火墙管理 =====
check_ufw_status() {
    if command -v ufw &> /dev/null; then
        UFW_STATUS=$(ufw status 2>/dev/null | head -n 1)
        if [[ "$UFW_STATUS" == *"active"* ]]; then
            return 0  # UFW 已启用
        fi
    fi
    return 1  # UFW 未安装或未启用
}

check_port_open() {
    local PORT=$1
    if check_ufw_status; then
        if ufw status | grep -q "$PORT"; then
            return 0  # 端口已开放
        fi
        return 1  # 端口未开放
    fi
    return 0  # UFW 未启用，视为端口已开放
}

open_ufw_port() {
    local PORT=$1
    if check_ufw_status; then
        if ! check_port_open $PORT; then
            log "正在开放端口 $PORT..."
            ufw allow $PORT/tcp
            ufw reload
            log "端口 $PORT 已开放"
        else
            log "端口 $PORT 已开放"
        fi
    else
        warn "UFW 未启用，跳过端口配置"
    fi
}

manage_ufw() {
    echo -e "${CYAN}${BOLD}===== 防火墙 (UFW) 管理 =====${PLAIN}"
    echo
    
    if ! command -v ufw &> /dev/null; then
        warn "UFW 未安装"
        read -p "是否安装 UFW? [y/N]: " INSTALL_UFW
        if [[ "$INSTALL_UFW" =~ ^[Yy]$ ]]; then
            apt-get update && apt-get install -y ufw
        else
            return
        fi
    fi
    
    echo -e "UFW 状态: $(ufw status | head -n 1)"
    echo
    echo -e "TG Export 需要的端口:"
    echo -e "  - ${CYAN}$WEB_PORT${PLAIN} (Web 面板)"
    echo -e "  - ${CYAN}80${PLAIN} (HTTP 验证/重定向)"
    echo -e "  - ${CYAN}443${PLAIN} (HTTPS)"
    echo
    
    if check_port_open $WEB_PORT; then
        echo -e "  ${GREEN}✓${PLAIN} 端口 $WEB_PORT 已开放"
    else
        echo -e "  ${RED}✗${PLAIN} 端口 $WEB_PORT 未开放"
    fi
    
    if check_port_open 80; then
        echo -e "  ${GREEN}✓${PLAIN} 端口 80 已开放"
    else
        echo -e "  ${RED}✗${PLAIN} 端口 80 未开放"
    fi
    
    if check_port_open 443; then
        echo -e "  ${GREEN}✓${PLAIN} 端口 443 已开放"
    else
        echo -e "  ${RED}✗${PLAIN} 端口 443 未开放"
    fi
    
    echo
    echo "1. 开放所有必需端口"
    echo "2. 查看 UFW 规则"
    echo "3. 启用 UFW"
    echo "4. 禁用 UFW"
    echo "0. 返回"
    read -p "请选择: " UFW_CHOICE
    
    case $UFW_CHOICE in
        1)
            open_ufw_port $WEB_PORT
            open_ufw_port 80
            open_ufw_port 443
            ;;
        2)
            ufw status numbered
            ;;
        3)
            ufw --force enable
            log "UFW 已启用"
            ;;
        4)
            ufw disable
            log "UFW 已禁用"
            ;;
    esac
}

# ===== 安装 acme.sh =====
install_acme() {
    if [ ! -f "$ACME_SH" ]; then
        log "正在安装 acme.sh..."
        curl https://get.acme.sh | sh -s email=admin@example.com
        source ~/.bashrc 2>/dev/null || true
        "$ACME_SH" --set-default-ca --server letsencrypt 2>/dev/null || true
    fi
}

# ===== 设置证书自动续期 =====
setup_cert_cron() {
    local domain=$1
    
    log "正在设置证书自动续期..."
    
    mkdir -p "$UNIFIED_CERT_DIR"
    cat > "$UNIFIED_CERT_DIR/renew.sh" <<'SCRIPT'
#!/bin/bash
ACME_SH="$HOME/.acme.sh/acme.sh"
if [ -f "$ACME_SH" ]; then
    "$ACME_SH" --cron --home "$HOME/.acme.sh" > /var/log/acme-renew.log 2>&1
    nginx -s reload 2>/dev/null || true
fi
SCRIPT
    chmod +x "$UNIFIED_CERT_DIR/renew.sh"
    
    cat > "$CRON_FILE" <<CRON
# TG Export 证书自动续期
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
0 3 1,15 * * root $UNIFIED_CERT_DIR/renew.sh
CRON
    
    log "证书自动续期已配置 (每月 1 号和 15 号凌晨 3 点)"
}

# ===== 申请证书 =====
issue_certificate() {
    local MAIN_DOMAIN=$1
    local SUBDOMAIN="tge.$MAIN_DOMAIN"
    
    mkdir -p "$UNIFIED_CERT_DIR"
    
    # 检查现有证书
    if [ -f "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt" ] && [ -f "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.key" ]; then
        if openssl x509 -checkend 86400 -noout -in "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt" 2>/dev/null; then
            CERT_CN=$(openssl x509 -noout -subject -in "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt" 2>/dev/null | grep -oP 'CN\s*=\s*\K[^,]+')
            if [[ "$CERT_CN" == "*.$MAIN_DOMAIN" ]] || [[ "$CERT_CN" == "$MAIN_DOMAIN" ]]; then
                log "已存在有效证书 (CN=$CERT_CN)"
                return 0
            fi
        fi
    fi
    
    # 检查 v2ray-agent 证书
    if [ -f "/etc/v2ray-agent/tls/$MAIN_DOMAIN.crt" ]; then
        log "发现 v2ray-agent 证书，创建软链接..."
        ln -sf "/etc/v2ray-agent/tls/$MAIN_DOMAIN.crt" "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt"
        ln -sf "/etc/v2ray-agent/tls/$MAIN_DOMAIN.key" "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.key"
        setup_cert_cron "$MAIN_DOMAIN"
        return 0
    fi
    
    # 申请新证书
    install_acme
    
    echo -e "${CYAN}请选择证书申请方式:${PLAIN}"
    echo -e "  ${GREEN}1)${PLAIN} HTTP 验证 (推荐)"
    echo -e "  ${GREEN}2)${PLAIN} 通配符证书 - Cloudflare DNS"
    echo -e "  ${GREEN}3)${PLAIN} 通配符证书 - 阿里云 DNS"
    echo -e "  ${GREEN}4)${PLAIN} 通配符证书 - DNSPod DNS"
    echo -e "  ${GREEN}5)${PLAIN} 跳过"
    read -p "请选择 [1-5]: " DNS_PROVIDER
    
    case $DNS_PROVIDER in
        1)
            echo -e "${YELLOW}使用 HTTP 验证...${PLAIN}"
            systemctl stop nginx 2>/dev/null || true
            "$ACME_SH" --issue -d "$SUBDOMAIN" --standalone --force --server letsencrypt
            if [ $? -eq 0 ]; then
                "$ACME_SH" --install-cert -d "$SUBDOMAIN" \
                    --key-file "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.key" \
                    --fullchain-file "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt" \
                    --reloadcmd "nginx -s reload 2>/dev/null || true"
                log "证书申请成功！"
                setup_cert_cron "$MAIN_DOMAIN"
                systemctl start nginx 2>/dev/null || true
                return 0
            else
                error "证书申请失败"
                systemctl start nginx 2>/dev/null || true
                return 1
            fi
            ;;
        2)
            read -p "请输入 Cloudflare API Token: " CF_Token
            export CF_Token
            "$ACME_SH" --issue -d "$MAIN_DOMAIN" -d "*.$MAIN_DOMAIN" --dns dns_cf --server letsencrypt
            ;;
        3)
            read -p "请输入阿里云 AccessKey ID: " Ali_Key
            read -p "请输入阿里云 AccessKey Secret: " Ali_Secret
            export Ali_Key Ali_Secret
            "$ACME_SH" --issue -d "$MAIN_DOMAIN" -d "*.$MAIN_DOMAIN" --dns dns_ali --server letsencrypt
            ;;
        4)
            read -p "请输入 DNSPod ID: " DP_Id
            read -p "请输入 DNSPod Key: " DP_Key
            export DP_Id DP_Key
            "$ACME_SH" --issue -d "$MAIN_DOMAIN" -d "*.$MAIN_DOMAIN" --dns dns_dp --server letsencrypt
            ;;
        5)
            warn "跳过证书申请"
            return 1
            ;;
    esac
    
    if [ $? -eq 0 ]; then
        "$ACME_SH" --install-cert -d "$MAIN_DOMAIN" \
            --key-file "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.key" \
            --fullchain-file "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt" \
            --reloadcmd "nginx -s reload 2>/dev/null || true"
        log "通配符证书申请成功！"
        setup_cert_cron "$MAIN_DOMAIN"
        return 0
    fi
    
    error "证书申请失败"
    return 1
}

# ===== 证书管理菜单 =====
manage_certs() {
    echo -e "${CYAN}${BOLD}===== SSL 证书管理 =====${PLAIN}"
    echo -e "统一证书目录: ${CYAN}$UNIFIED_CERT_DIR${PLAIN}"
    echo
    
    if ls "$UNIFIED_CERT_DIR"/*.crt 1>/dev/null 2>&1; then
        for cert in "$UNIFIED_CERT_DIR"/*.crt; do
            CERT_NAME=$(basename "$cert" .crt)
            CERT_CN=$(openssl x509 -noout -subject -in "$cert" 2>/dev/null | grep -oP 'CN\s*=\s*\K[^,]+')
            EXPIRY=$(openssl x509 -enddate -noout -in "$cert" 2>/dev/null | cut -d= -f2)
            
            if [[ "$CERT_CN" == "*.$CERT_NAME" ]]; then
                echo -e "${GREEN}✓ $CERT_NAME${PLAIN}: CN=$CERT_CN (通配符)"
            else
                echo -e "${YELLOW}○ $CERT_NAME${PLAIN}: CN=$CERT_CN"
            fi
            echo -e "  过期: $EXPIRY"
            
            if [ -L "$cert" ]; then
                echo -e "  ${YELLOW}-> $(readlink -f "$cert")${PLAIN}"
            fi
        done
    else
        warn "无证书"
    fi
    
    echo
    echo "1. 申请/更新证书"
    echo "2. 查看证书详情"
    echo "3. 删除证书"
    echo "4. 手动续期"
    echo "0. 返回"
    read -p "请选择: " CERT_CHOICE
    
    case $CERT_CHOICE in
        1)
            read -p "请输入主域名 (例如 example.com): " NEW_DOMAIN
            if [ -n "$NEW_DOMAIN" ]; then
                issue_certificate "$NEW_DOMAIN"
            fi
            ;;
        2)
            for cert in "$UNIFIED_CERT_DIR"/*.crt; do
                [ -f "$cert" ] && openssl x509 -noout -text -in "$cert" | head -30
            done
            ;;
        3)
            read -p "确认删除所有证书? (yes/N): " CONFIRM_DEL
            if [[ "$CONFIRM_DEL" == "yes" ]]; then
                rm -f "$UNIFIED_CERT_DIR"/*.crt "$UNIFIED_CERT_DIR"/*.key
                log "证书已删除"
            fi
            ;;
        4)
            if [ -f "$ACME_SH" ]; then
                "$ACME_SH" --cron --home "$HOME/.acme.sh"
                nginx -s reload 2>/dev/null || true
                log "续期检查完成"
            else
                error "acme.sh 未安装"
            fi
            ;;
    esac
}

# ===== 配置 Nginx =====
setup_nginx() {
    echo -e "${CYAN}${BOLD}===== 配置 Nginx 反向代理 =====${PLAIN}"
    
    # 安装 Nginx
    if ! command -v nginx &> /dev/null; then
        log "正在安装 Nginx..."
        apt-get update && apt-get install -y nginx
        systemctl enable nginx
        systemctl start nginx
    fi
    
    load_config
    
    if [ -z "$DOMAIN" ]; then
        read -p "请输入域名 (例如 tge.example.com): " DOMAIN
    fi
    
    MAIN_DOMAIN=$(echo "$DOMAIN" | sed 's/^[^.]*\.//')
    
    echo -e "${CYAN}请选择配置类型:${PLAIN}"
    echo -e "  ${GREEN}1)${PLAIN} 仅 HTTP (端口 $HTTP_PORT)"
    echo -e "  ${GREEN}2)${PLAIN} HTTPS (端口 $HTTPS_PORT)"
    echo -e "  ${GREEN}3)${PLAIN} HTTPS + HTTP 自动跳转"
    read -p "请选择 [1-3]: " NGINX_TYPE
    
    case $NGINX_TYPE in
        1)
            cat > "$NGINX_CONF" <<NGINX
# TG Export - HTTP
server {
    listen $HTTP_PORT;
    server_name $DOMAIN;
    
    location / {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX
            ;;
        2|3)
            # 检查/申请证书
            if [ ! -f "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt" ]; then
                issue_certificate "$MAIN_DOMAIN"
            fi
            
            # 确定证书路径
            if [ -f "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt" ]; then
                CERT_PATH="$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt"
                KEY_PATH="$UNIFIED_CERT_DIR/$MAIN_DOMAIN.key"
            else
                error "未找到证书"
                return 1
            fi
            
            if [[ "$NGINX_TYPE" == "3" ]]; then
                # HTTPS + HTTP 跳转
                cat > "$NGINX_CONF" <<NGINX
# TG Export - HTTPS with HTTP redirect
server {
    listen $HTTP_PORT;
    server_name $DOMAIN;
    return 301 https://\$host:$HTTPS_PORT\$request_uri;
}

server {
    listen $HTTPS_PORT ssl http2;
    server_name $DOMAIN;
    
    ssl_certificate $CERT_PATH;
    ssl_certificate_key $KEY_PATH;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;
    
    location / {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    
    # WebSocket 支持
    location /ws {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX
            else
                # 仅 HTTPS
                cat > "$NGINX_CONF" <<NGINX
# TG Export - HTTPS
server {
    listen $HTTPS_PORT ssl http2;
    server_name $DOMAIN;
    
    ssl_certificate $CERT_PATH;
    ssl_certificate_key $KEY_PATH;
    ssl_protocols TLSv1.2 TLSv1.3;
    
    location / {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINX
            fi
            ;;
    esac
    
    # 测试并重载 Nginx
    nginx -t
    if [ $? -eq 0 ]; then
        nginx -s reload
        log "Nginx 配置成功！"
        
        # 开放端口
        open_ufw_port $HTTP_PORT
        open_ufw_port $HTTPS_PORT
        
        echo -e "访问地址: ${CYAN}https://$DOMAIN${PLAIN}"
    else
        error "Nginx 配置有误"
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
    echo -e "${YELLOW}获取 API ID 和 API Hash:${PLAIN}"
    echo "  1. 访问 https://my.telegram.org"
    echo "  2. 登录后进入 API development tools"
    echo "  3. 创建应用获取 API ID 和 API Hash"
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
    
    # 生成 .env
    cat > .env <<EOF
API_ID=$API_ID
API_HASH=$API_HASH
BOT_TOKEN=$BOT_TOKEN
ADMIN_PASSWORD=$ADMIN_PASSWORD
SECRET_KEY=$(openssl rand -hex 32)
WEB_PORT=${WEB_PORT:-9528}
EOF
    
    # 使用配置的镜像
    DOCKER_IMAGE=${DOCKER_IMAGE:-ghcr.io/your-username/tg-export:latest}
    WEB_PORT=${WEB_PORT:-9528}
    
    # 生成 docker-compose.yml
    cat > docker-compose.yml <<YAML
services:
  tg-export:
    image: $DOCKER_IMAGE
    container_name: tg-export
    restart: unless-stopped
    ports:
      - "$WEB_PORT:$WEB_PORT"
    volumes:
      - ./data:/app/data:shared
      - $DOWNLOAD_DIR:/downloads:shared
    env_file:
      - .env
    environment:
      - TZ=Asia/Shanghai
      - WEB_PORT=$WEB_PORT
YAML
    
    log "拉取镜像..."
    docker-compose pull 2>/dev/null || docker compose pull
    
    log "启动服务..."
    docker-compose up -d 2>/dev/null || docker compose up -d
    
    sleep 3
    if docker ps | grep -q tg-export; then
        log "TG Export 启动成功！"
    else
        error "启动失败，请检查: docker logs tg-export"
        return 1
    fi
    
    # 开放端口
    open_ufw_port $WEB_PORT
    
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
}

# ===== 自动配置 Nginx (使用保存的配置) =====
setup_nginx_auto() {
    # 安装 Nginx
    if ! command -v nginx &> /dev/null; then
        log "正在安装 Nginx..."
        apt-get update && apt-get install -y nginx
        systemctl enable nginx
        systemctl start nginx
    fi
    
    MAIN_DOMAIN=${MAIN_DOMAIN:-$(echo "$DOMAIN" | sed 's/^[^.]*\.//')}
    WEB_PORT=${WEB_PORT:-9528}
    
    case $NGINX_TYPE in
        1)
            # 仅 HTTP
            cat > "$NGINX_CONF" <<NGINX
# TG Export - HTTP
server {
    listen $HTTP_PORT;
    server_name $DOMAIN;
    
    location / {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINX
            ;;
        2|3)
            # 检查/申请证书
            if [ ! -f "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt" ]; then
                issue_certificate "$MAIN_DOMAIN"
            fi
            
            if [ -f "$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt" ]; then
                CERT_PATH="$UNIFIED_CERT_DIR/$MAIN_DOMAIN.crt"
                KEY_PATH="$UNIFIED_CERT_DIR/$MAIN_DOMAIN.key"
            else
                warn "未找到证书，使用 HTTP 模式"
                NGINX_TYPE=1
                setup_nginx_auto
                return
            fi
            
            if [[ "$NGINX_TYPE" == "3" ]]; then
                # HTTPS + 跳转
                cat > "$NGINX_CONF" <<NGINX
# TG Export - HTTPS with redirect
server {
    listen $HTTP_PORT;
    server_name $DOMAIN;
    return 301 https://\$host:$HTTPS_PORT\$request_uri;
}

server {
    listen $HTTPS_PORT ssl http2;
    server_name $DOMAIN;
    
    ssl_certificate $CERT_PATH;
    ssl_certificate_key $KEY_PATH;
    ssl_protocols TLSv1.2 TLSv1.3;
    
    location / {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    
    location /ws {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX
            else
                # 仅 HTTPS
                cat > "$NGINX_CONF" <<NGINX
# TG Export - HTTPS
server {
    listen $HTTPS_PORT ssl http2;
    server_name $DOMAIN;
    
    ssl_certificate $CERT_PATH;
    ssl_certificate_key $KEY_PATH;
    ssl_protocols TLSv1.2 TLSv1.3;
    
    location / {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
    }
}
NGINX
            fi
            ;;
    esac
    
    nginx -t && nginx -s reload
    if [ $? -eq 0 ]; then
        log "Nginx 配置成功！"
        open_ufw_port $HTTP_PORT
        open_ufw_port $HTTPS_PORT
    else
        error "Nginx 配置有误"
    fi
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

APP_DIR="/opt/tg-export"
UNIFIED_CERT_DIR="/etc/ssl/wildcard"

function show_menu() {
    clear
    echo -e "${GREEN}=== TG Export 管理工具 (tge) ===${NC}"
    echo "1. 启动服务"
    echo "2. 停止服务"
    echo "3. 重启服务"
    echo "4. 查看状态"
    echo "5. 查看日志"
    echo "6. 更新镜像"
    echo "7. 证书管理"
    echo "8. 密码管理"
    echo "0. 退出"
    echo
    read -p "请选择 [0-8]: " choice
    handle_choice "$choice"
}

function handle_choice() {
    case $1 in
        1) cd "$APP_DIR" && docker-compose up -d; read -p "按回车继续..."; show_menu ;;
        2) cd "$APP_DIR" && docker-compose down; read -p "按回车继续..."; show_menu ;;
        3) cd "$APP_DIR" && docker-compose restart; read -p "按回车继续..."; show_menu ;;
        4) 
            docker ps | grep -E "CONTAINER|tg-export"
            echo
            if [ -f /etc/nginx/conf.d/tg-export.conf ]; then
                DOMAIN=$(grep "server_name" /etc/nginx/conf.d/tg-export.conf | head -1 | awk '{print $2}' | tr -d ';')
                echo -e "域名: ${GREEN}$DOMAIN${NC}"
            fi
            read -p "按回车继续..."
            show_menu
            ;;
        5) docker logs -f --tail=100 tg-export ;;
        6) cd "$APP_DIR" && docker-compose pull && docker-compose up -d; read -p "按回车继续..."; show_menu ;;
        7) manage_certs; show_menu ;;
        8) manage_password; show_menu ;;
        0) exit 0 ;;
        *) show_menu ;;
    esac
}

function manage_password() {
    echo -e "${CYAN}=== 密码管理 ===${NC}"
    echo
    if [ -f "$APP_DIR/.env" ]; then
        CURRENT_PWD=$(grep ADMIN_PASSWORD "$APP_DIR/.env" | cut -d= -f2)
        echo -e "当前密码: ${YELLOW}$CURRENT_PWD${NC}"
    else
        echo -e "${RED}未找到配置文件${NC}"
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
    
    # 更新 .env 文件
    if [ -f "$APP_DIR/.env" ]; then
        sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$NEW_PWD/" "$APP_DIR/.env"
    fi
    
    # 更新配置文件
    if [ -f "$APP_DIR/.tge_config" ]; then
        sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=\"$NEW_PWD\"/" "$APP_DIR/.tge_config"
    fi
    
    # 删除用户数据，让系统重新创建
    rm -f "$APP_DIR/data/users.json"
    
    # 重启容器
    cd "$APP_DIR" && docker-compose restart
    
    echo
    echo -e "${GREEN}密码已更新！${NC}"
    echo -e "新密码: ${YELLOW}$NEW_PWD${NC}"
}

function manage_certs() {
    echo -e "${CYAN}=== 证书管理 ===${NC}"
    if ls "$UNIFIED_CERT_DIR"/*.crt 1>/dev/null 2>&1; then
        for cert in "$UNIFIED_CERT_DIR"/*.crt; do
            DOMAIN=$(basename "$cert" .crt)
            EXPIRY=$(openssl x509 -enddate -noout -in "$cert" 2>/dev/null | cut -d= -f2)
            echo -e "${GREEN}✓ $DOMAIN${NC}: 过期 $EXPIRY"
        done
    else
        echo -e "${YELLOW}无证书${NC}"
    fi
    read -p "按回车继续..."
}

# 直接命令支持
case "$1" in
    start) cd "$APP_DIR" && docker-compose up -d ;;
    stop) cd "$APP_DIR" && docker-compose down ;;
    restart) cd "$APP_DIR" && docker-compose restart ;;
    logs) docker logs -f --tail=100 tg-export ;;
    update) cd "$APP_DIR" && docker-compose pull && docker-compose up -d ;;
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
    read -p "是否删除数据? (y/N): " DELETE_DATA
    read -p "是否删除 Nginx 配置? (y/N): " DELETE_NGINX  
    read -p "确认卸载? (y/N): " CONFIRM
    
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        log "取消卸载"
        return
    fi
    
    cd "$APP_DIR" 2>/dev/null
    docker-compose down 2>/dev/null || docker compose down
    docker stop tg-export 2>/dev/null
    docker rm tg-export 2>/dev/null
    
    if [[ "$DELETE_DATA" =~ ^[Yy]$ ]]; then
        rm -rf "$APP_DIR"
    fi
    
    if [[ "$DELETE_NGINX" =~ ^[Yy]$ ]]; then
        rm -f "$NGINX_CONF"
        nginx -s reload 2>/dev/null || true
    fi
    
    rm -f /usr/bin/tge
    log "TG Export 卸载完成！"
}

# ===== 更新 =====
update_app() {
    log "正在更新 TG Export..."
    cd "$APP_DIR" || exit
    docker-compose pull 2>/dev/null || docker compose pull
    docker-compose up -d 2>/dev/null || docker compose up -d
    log "更新完成！"
}

# ===== 查看状态 =====
show_status() {
    echo -e "${CYAN}${BOLD}===== TG Export 状态 =====${PLAIN}"
    echo
    
    if docker ps | grep -q tg-export; then
        echo -e "容器状态: ${GREEN}运行中${PLAIN}"
        docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep tg-export
    else
        echo -e "容器状态: ${RED}未运行${PLAIN}"
    fi
    
    echo
    if [ -f "$NGINX_CONF" ]; then
        DOMAIN=$(grep "server_name" "$NGINX_CONF" | head -1 | awk '{print $2}' | tr -d ';')
        echo -e "Nginx: ${GREEN}已配置${PLAIN} ($DOMAIN)"
    else
        echo -e "Nginx: ${YELLOW}未配置${PLAIN}"
    fi
    
    echo
    if ls "$UNIFIED_CERT_DIR"/*.crt 1>/dev/null 2>&1; then
        echo -e "SSL 证书: ${GREEN}已配置${PLAIN}"
    else
        echo -e "SSL 证书: ${YELLOW}未配置${PLAIN}"
    fi
    
    echo
    if load_config; then
        echo -e "API ID: ${GREEN}${API_ID}${PLAIN}"
        if [[ -n "$BOT_TOKEN" ]]; then
            echo -e "Bot: ${GREEN}已配置${PLAIN}"
        fi
    fi
}

# ===== 主程序 =====
main() {
    check_root
    
    case "$1" in
        install) install_app ;;
        uninstall) uninstall_app ;;
        update) update_app ;;
        status) show_status ;;
        nginx) setup_nginx ;;
        cert) manage_certs ;;
        ufw) manage_ufw ;;
        *) 
            while true; do
                show_menu
                read -p "请选择 [0-8]: " CHOICE
                echo
                case $CHOICE in
                    1) install_app ;;
                    2) uninstall_app ;;
                    3) update_app ;;
                    4) show_status ;;
                    5) docker logs -f --tail=100 tg-export ;;
                    6) setup_nginx ;;
                    7) manage_certs ;;
                    8) manage_ufw ;;
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
