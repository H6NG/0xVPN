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

---

## Client setup (macOS)

```bash
cd your-project-folder
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Connect:

```bash
sudo ./venv/bin/python3 cli.py connect
```

First time it will ask for your VPS IP, port, and shared key.  
Get the shared key from your server:

```bash
grep shared_key /opt/0xvpn/configs/server.toml
```

---

## Commands

```bash
sudo ./venv/bin/python3 cli.py connect      # connect
sudo ./venv/bin/python3 cli.py disconnect   # disconnect
sudo ./venv/bin/python3 cli.py status       # check status
```

---

## Notes

- Requires sudo (TUN interface needs root)
- DNS is set automatically on connect and restored on disconnect
- Hit Ctrl+C to disconnect

--- 

## Check your current IP address

`curl ifconfig.me`