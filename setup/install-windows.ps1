# ─────────────────────────────────────────────
#  0xVPN — Windows client installer
#  Run as Administrator in PowerShell:
#  Set-ExecutionPolicy Bypass -Scope Process -Force
#  .\install-windows.ps1
# ─────────────────────────────────────────────

param(
    [string]$RepoUrl = "https://github.com/H6NG/0xVPN.git",
    [string]$InstallDir = "$env:LOCALAPPDATA\0xvpn"
)

$ErrorActionPreference = "Stop"

function log     { param($msg) Write-Host $msg -ForegroundColor Green }
function warn    { param($msg) Write-Host $msg -ForegroundColor Yellow }
function error   { param($msg) Write-Host $msg -ForegroundColor Red; exit 1 }
function section { param($msg) Write-Host "`n==> $msg`n" -ForegroundColor Blue }

function print_banner {
    Write-Host "  Welcome to 0xVPN!" -ForegroundColor Blue
}

function check_admin {
    section "Checking permissions"
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        error "Please run as Administrator. Right-click PowerShell -> 'Run as administrator'"
    }
    log "Running as Administrator"
}

function check_windows {
    section "Checking OS"
    $osVersion = [System.Environment]::OSVersion.Version
    $buildNumber = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion").CurrentBuild
    log "Windows $($osVersion.Major).$($osVersion.Minor) (Build $buildNumber)"

    if ($osVersion.Major -lt 10) {
        error "Windows 10 or 11 required."
    }
}

function install_python {
    section "Checking Python"
    try {
        $pythonVersion = python --version 2>&1
        if ($pythonVersion -match "Python 3") {
            log "$pythonVersion found"
            return
        }
    } catch {}

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        warn "Python not found. Installing via winget..."
        winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
        log "Python installed"
    } else {
        warn "Python not found and winget unavailable."
        Write-Host "  Please install Python from: https://python.org/downloads"
        Write-Host "  Make sure to check 'Add Python to PATH' during install"
        Read-Host "Press Enter after Python is installed"
    }
}

function install_git {
    section "Checking Git"
    if (Get-Command git -ErrorAction SilentlyContinue) {
        log "Git found"
        return
    }

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        warn "Git not found. Installing via winget..."
        winget install Git.Git --silent --accept-package-agreements --accept-source-agreements
        log "Git installed"
    } else {
        warn "Git not found."
        Write-Host "  Please install Git from: https://git-scm.com/download/win"
        Read-Host "Press Enter after Git is installed"
    }
}

function install_wintun {
    section "Wintun driver (TUN interface for Windows)"
    warn "Full VPN tunnel support on Windows is coming soon."
    Write-Host "  The VPN tunnel on Windows requires the Wintun driver."
    Write-Host "  Download it manually from: https://www.wintun.net"
    Write-Host "  Place wintun.dll in: $InstallDir"
    Write-Host ""
}

function install_0xvpn {
    section "Installing 0xVPN"

    if (Test-Path $InstallDir) {
        warn "0xVPN already installed at $InstallDir. Updating..."
        Set-Location $InstallDir
        git pull -q
    } else {
        git clone -q $RepoUrl $InstallDir
    }

    Set-Location $InstallDir
    python -m venv venv
    .\venv\Scripts\pip install -r requirements.txt -q

    log "0xVPN installed at $InstallDir"
}

function configure_client {
    section "Client configuration"

    $configDir = "$InstallDir\configs"
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null

    Write-Host ""
    $hasConfig = Read-Host "Do you have a client.toml from your server? (y/n)"

    if ($hasConfig -eq "y") {
        $configPath = Read-Host "Path to your client.toml"
        if (Test-Path $configPath) {
            Copy-Item $configPath "$configDir\client.toml"
            log "Config imported to $configDir\client.toml"
        } else {
            warn "File not found: $configPath"
            Write-Host "  You can import it later and re-run this installer."
        }
    } else {
        warn "No config imported. Copy client.toml from your server:"
        Write-Host "  scp root@YOUR_SERVER_IP:/opt/0xvpn/configs/client.toml ."
        Write-Host "  Then place it at: $configDir\client.toml"
    }
}

function add_to_path {
    section "Adding 0xvpn to PATH"

    $script = "$InstallDir\0xvpn.bat"
    "@echo off`npython `"$InstallDir\cli.py`" %*" | Set-Content $script

    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($userPath -notlike "*$InstallDir*") {
        [Environment]::SetEnvironmentVariable("PATH", "$userPath;$InstallDir", "User")
        log "Added $InstallDir to PATH"
    } else {
        log "Already in PATH"
    }
}

function print_success {
    Write-Host ""
    Write-Host "  0xVPN client installed!" -ForegroundColor Green
    Write-Host ""
    Write-Host " Install dir : $InstallDir"
    Write-Host " Config      : $InstallDir\configs\client.toml"
    Write-Host ""
    Write-Host " Usage (open a new terminal first):" -ForegroundColor Yellow
    Write-Host "   0xvpn connect       # connect"
    Write-Host "   0xvpn disconnect    # disconnect"
    Write-Host "   0xvpn status        # show status"
    Write-Host ""
    Write-Host " Note: Full Windows tunnel support coming soon." -ForegroundColor Yellow
    Write-Host ""
}

print_banner
check_admin
check_windows
install_python
install_git
install_wintun
install_0xvpn
configure_client
add_to_path
print_success