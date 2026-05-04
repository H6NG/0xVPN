#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="$HOME/.0xvpn"
REPO_URL="https://github.com/H6NG/0xVPN.git"

log() {
    echo -e "${GREEN}$1${NC}"
}
warn() {
    echo -e "${YELLOW}$1${NC}"
}
error() {
    echo -e "${RED}$1${NC}"
    exit 1
}
section() {
    echo -e "\n${BLUE}==> $1${NC}\n"
}

print_banner() {
    echo -e "${BLUE}  Welcome to 0xVPN!${NC}"
}

check_macos() {
    section "Checking OS"
    if [[ "$OSTYPE" != "darwin"* ]]; then
        error "This script is for macOS only."
    fi
    MACOS_VERSION=$(sw_vers -productVersion)
    log "Detected macOS $MACOS_VERSION"

    MAJOR=$(echo "$MACOS_VERSION" | cut -d. -f1)
    if [ "$MAJOR" -lt 12 ]; then
        warn "macOS 12+ recommended. You have $MACOS_VERSION."
    fi
}

check_homebrew() {
    section "Checking Homebrew"
    if ! command -v brew &> /dev/null; then
        warn "Homebrew not found. Installing..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        log "Homebrew installed"
    else
        log "Homebrew found"
    fi
}

check_python() {
    section "Checking Python"
    if ! command -v python3 &> /dev/null; then
        warn "Python3 not found. Installing via Homebrew..."
        brew install python3 -q
        log "Python3 installed"
    else
        PYTHON_VERSION=$(python3 --version)
        log "$PYTHON_VERSION found"
    fi
}

install_0xvpn() {
    section "Installing 0xVPN"

    if [ -d "$INSTALL_DIR" ]; then
        warn "0xVPN already installed at $INSTALL_DIR. Updating..."
        cd "$INSTALL_DIR" && git pull -q
    else
        git clone -q "$REPO_URL" "$INSTALL_DIR"
    fi

    cd "$INSTALL_DIR"
    python3 -m venv venv
    ./venv/bin/pip install -r setup/requirements.txt -q

    log "0xVPN installed at $INSTALL_DIR"
}

install_alias() {
    section "Setting up CLI"

    ALIAS_CMD="alias 0xvpn='sudo $INSTALL_DIR/venv/bin/python $INSTALL_DIR/cli.py'"

    if [ -f "$HOME/.zshrc" ]; then
        if ! grep -q "alias 0xvpn=" "$HOME/.zshrc"; then
            echo "" >> "$HOME/.zshrc"
            echo "# 0xVPN" >> "$HOME/.zshrc"
            echo "$ALIAS_CMD" >> "$HOME/.zshrc"
            log "Alias added to ~/.zshrc"
        else
            log "Alias already in ~/.zshrc"
        fi
    elif [ -f "$HOME/.bashrc" ]; then
        if ! grep -q "alias 0xvpn=" "$HOME/.bashrc"; then
            echo "" >> "$HOME/.bashrc"
            echo "# 0xVPN" >> "$HOME/.bashrc"
            echo "$ALIAS_CMD" >> "$HOME/.bashrc"
            log "Alias added to ~/.bashrc"
        else
            log "Alias already in ~/.bashrc"
        fi
    else
        warn "Could not detect shell config. Add this manually:"
        echo "  $ALIAS_CMD"
    fi
}

configure_client() {
    section "Client configuration"

    mkdir -p "$INSTALL_DIR/configs"

    echo ""
    read -p "Do you have a client.toml from your server? (y/n): " HAS_CONFIG

    if [[ "$HAS_CONFIG" == "y" || "$HAS_CONFIG" == "Y" ]]; then
        read -p "Path to your client.toml: " CONFIG_PATH
        CONFIG_PATH="${CONFIG_PATH/#\~/$HOME}"

        if [ -f "$CONFIG_PATH" ]; then
            cp "$CONFIG_PATH" "$INSTALL_DIR/configs/client.toml"
            chmod 600 "$INSTALL_DIR/configs/client.toml"
            log "Config imported to $INSTALL_DIR/configs/client.toml"
        else
            error "File not found: $CONFIG_PATH"
        fi
    else
        warn "No config imported. Copy client.toml from your server:"
        echo "  scp root@YOUR_SERVER_IP:/opt/0xvpn/configs/client.toml ."
        echo "  Then re-run: bash install-macos.sh"
    fi
}

install_launch_agent() {
    section "Auto-start (optional)"

    read -p "Auto-connect at login? (y/n) [n]: " AUTO_START
    AUTO_START=${AUTO_START:-n}

    if [[ "$AUTO_START" == "y" || "$AUTO_START" == "Y" ]]; then
        PLIST_PATH="$HOME/Library/LaunchAgents/com.0xvpn.client.plist"

        cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.0xvpn.client</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/sudo</string>
        <string>$INSTALL_DIR/venv/bin/python</string>
        <string>$INSTALL_DIR/cli.py</string>
        <string>connect</string>
        <string>$INSTALL_DIR/configs/client.toml</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/.0xvpn/0xvpn.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.0xvpn/0xvpn-error.log</string>
</dict>
</plist>
EOF
        launchctl load "$PLIST_PATH"
        log "Launch agent installed"
    else
        log "Skipped auto-start"
    fi
}

print_success() {
    echo ""
    echo -e "${GREEN}  0xVPN client installed!${NC}"
    echo ""
    echo " Install dir : $INSTALL_DIR"
    echo " Config      : $INSTALL_DIR/configs/client.toml"
    echo ""
    echo -e "${YELLOW} Usage (restart your terminal first):${NC}"
    echo "   0xvpn connect              # connect"
    echo "   0xvpn disconnect           # disconnect"
    echo "   0xvpn status               # show status"
    echo ""
    echo -e "${YELLOW} Note:${NC} VPN requires sudo (TUN interface needs root)"
    echo ""
}

main() {
    print_banner
    check_macos
    check_homebrew
    check_python
    install_0xvpn
    install_alias
    configure_client
    install_launch_agent
    print_success
}

main