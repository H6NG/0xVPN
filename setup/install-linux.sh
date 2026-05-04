#!/bin/bash

set -e # exit on error

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

INSTALL_DIR="/opt/0xvpn"
REPO_URL="https://github.com/H6NG/0xVPN.git"

log() {
    echo -e "${GREEN}$1${NC}"
}
warn() {
    echo -e "${YELLOW}$1${NC}"
}
error() {
    echo -e "${RED}$1${NC}"
}
section() {
    echo -e "\n${BLUE}==> $1${NC}\n"
}

print_banner() {
    echo -e "${BLUE}  Welcome to 0xVPN!${NC}"
}


check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}Please run as root${NC}"
        exit 1
    fi
}

check_os() {
    section "Checking OS"
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" == "ubuntu" || "$ID" == "debian" ]]; then
            log "Detected $PRETTY_NAME"
        else
            warn "Untested OS: $PRETTY_NAME. Continuing anyway..."
        fi
    else
        error "Cannot detect OS. Only Ubuntu/Debian are supported."
    fi
}

check_port_availability() {
    local port=$1
    if ss -ulnp | grep -q ":$port "; then
        warn "Port $port is already in use. Choose a different port."
        read -p "Enter a different port: " PORT
    fi
}

install_dependencies() {
    section "Installing dependencies"
    apt-get update -qq
    apt-get install -y -qq \
        python3 \
        python3-pip \
        python3-venv \
        iproute2 \
        iptables \
        git \
        curl \
        ufw
    log "Dependencies installed"
}

install_0xvpn() {
    section "Installing OxVPN"

    if [ -d "$INSTALL_DIR" ]; then
        warn "0xVPN already installed at $INSTALL_DIR. Updating..."
        cd "$INSTALL_DIR" && git pull -q
    else
        git clone -q "$REPO_URL" "$INSTALL_DIR"
    fi

    cd "$INSTALL_DIR"
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt -q
    log "0xVPN installed at $INSTALL_DIR"
}

configure() {
    section "Configuration"

    DETECTED_IP=$(curl -s ifconfig.me || echo "")
    if [ -n "$DETECTED_IP" ]; then
        read -p "Your VPS public IP [$DETECTED_IP]: " SERVER_IP
        SERVER_IP=${SERVER_IP:-$DETECTED_IP}
    else
        read -p "Your VPS public IP: " SERVER_IP
        [ -z "$SERVER_IP" ] && error "Server IP is required"
    fi

    read -p "Port to listen on [51820]: " PORT
    PORT=${PORT:-51820}
    check_port_availability "$PORT"

    read -p "VPN subnet [10.0.0.0/24]: " SUBNET
    SUBNET=${SUBNET:-10.0.0.0/24}

    SHARED_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

    mkdir -p "$INSTALL_DIR/configs"

    cat > "$INSTALL_DIR/configs/server.toml" << EOF
[interface]
address = "10.0.0.1/24"
listen_port = $PORT
server_ip = "$SERVER_IP"
subnet = "$SUBNET"
shared_key = "$SHARED_KEY"
mode = "server"
EOF

    cat > "$INSTALL_DIR/configs/client.toml" << EOF
[interface]
address = "10.0.0.2/24"
mode = "client"

[peer]
endpoint = "$SERVER_IP:$PORT"
shared_key = "$SHARED_KEY"
allowed_ips = "0.0.0.0/0"
EOF

    chmod 600 "$INSTALL_DIR/configs/server.toml"
    chmod 600 "$INSTALL_DIR/configs/client.toml"

    log "Config written to $INSTALL_DIR/configs/"
}

setup_firewall() {
    section "Configuring firewall"

    echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-0xvpn.conf
    sysctl -p /etc/sysctl.d/99-0xvpn.conf -q

    ufw allow ssh -q
    ufw allow "$PORT"/udp -q
    ufw --force enable -q

    log "Firewall configured (port $PORT/udp open)"
}

install_service() {
    section "Installing systemd service"

    cat > /etc/systemd/system/0xvpn.service <<EOF
[Unit]
Description=0xVPN Server
After=network.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/cli.py start --config $INSTALL_DIR/configs/server.toml
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable 0xvpn -q
    systemctl start 0xvpn

    log "Service installed and started"
}

print_success() {
    echo ""
    echo -e "${GREEN}  0xVPN installed successfully!${NC}"
    echo ""
    echo " Server IP   : $SERVER_IP"
    echo " Port        : $PORT/udp"
    echo " Config      : $INSTALL_DIR/configs/server.toml"
    echo ""
    echo -e "${YELLOW} Next steps:${NC}"
    echo " 1. Copy client config to your machine:"
    echo "    scp root@$SERVER_IP:$INSTALL_DIR/configs/client.toml ."
    echo ""
    echo " 2. Connect from your machine:"
    echo "    sudo python3 cli.py connect client.toml"
    echo ""
    echo " Useful commands:"
    echo "    systemctl status 0xvpn"
    echo "    journalctl -u 0xvpn -f"
    echo "    systemctl restart 0xvpn"
    echo ""
}

main() {
    print_banner
    check_root
    check_os
    install_dependencies
    install_0xvpn
    configure
    setup_firewall
    install_service
    print_success
}

main
