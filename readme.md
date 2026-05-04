# 0xVPN

A simple self-hosted VPN over UDP with AES-256-GCM encryption.

---

## Server setup (Linux VPS)

```bash
curl -fsSL https://raw.githubusercontent.com/H6NG/0xVPN/main/setup/install-linux.sh | bash
```

Then start the server:

```bash
cd /opt/0xvpn
./venv/bin/python3 setup/cli.py start --config configs/server.toml
```

Get your shared key:

```bash
grep shared_key /opt/0xvpn/configs/server.toml
```

---

## Client setup

### macOS

```bash
curl -fsSL https://raw.githubusercontent.com/H6NG/0xVPN/main/setup/install-macos.sh | bash
```

Then connect:

```bash
0xvpn connect
```

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/H6NG/0xVPN/main/setup/install-linux.sh | bash
```

Then connect:

```bash
sudo ./venv/bin/python3 cli.py connect
```

### Windows

Run as Administrator in PowerShell:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\install-windows.ps1
```

Then connect:

```powershell
python cli.py connect
```

> **Note:** Windows requires the [Wintun driver](https://www.wintun.net) and `pip install wintun`.

---

## Commands

```bash
0xvpn connect      # connect to VPN
0xvpn disconnect   # disconnect
0xvpn status       # check status
```

---

## Check your current IP address

```bash
curl ifconfig.me
```

---

## Notes

- Requires sudo/admin (TUN interface needs root)
- DNS is set automatically on connect and restored on disconnect
- Hit Ctrl+C to disconnect