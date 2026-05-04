#!/usr/bin/env python3
"""0xVPN — lightweight VPN over UDP with AES-256-GCM."""

import fcntl
import hashlib
import ipaddress
import os
import secrets
import select
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

import click
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        raise RuntimeError("Install tomli: pip install tomli")

# ── TUN / utun constants ──────────────────────────────────────────────────────

TUNSETIFF = 0x400454CA
IFF_TUN   = 0x0001
IFF_NO_PI = 0x1000

AF_SYSTEM        = 32
AF_SYS_CONTROL   = 2
SYSPROTO_CONTROL = 2
UTUN_OPT_IFNAME  = 2
CTLIOCGINFO      = 0xC0644E03

# ── crypto ────────────────────────────────────────────────────────────────────

def _derive_key(hex_key: str) -> bytes:
    return hashlib.sha256(bytes.fromhex(hex_key)).digest()


def encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt(key: bytes, data: bytes) -> Optional[bytes]:
    if len(data) < 13:
        return None
    try:
        return AESGCM(key).decrypt(data[:12], data[12:], None)
    except Exception:
        return None


# ── TUN device abstraction ────────────────────────────────────────────────────

class TunDevice:
    """Wraps a TUN file descriptor, normalising read/write across platforms."""

    _AF_INET_HDR = struct.pack(">I", socket.AF_INET)  # macOS utun prefix

    def __init__(self, fd: int, name: str, *, macos: bool = False):
        self.fd     = fd
        self.name   = name
        self._macos = macos

    def read(self) -> bytes:
        raw = os.read(self.fd, 65536)
        return raw[4:] if self._macos else raw

    def write(self, pkt: bytes) -> None:
        if self._macos:
            pkt = self._AF_INET_HDR + pkt
        os.write(self.fd, pkt)


def _open_tun_linux(name: str = "tun0") -> TunDevice:
    fd  = os.open("/dev/net/tun", os.O_RDWR)
    ifr = struct.pack("16sH", name.encode(), IFF_TUN | IFF_NO_PI)
    fcntl.ioctl(fd, TUNSETIFF, ifr)
    return TunDevice(fd, name)


def _open_tun_macos(index: int = 0) -> TunDevice:
    """Open a utun device on macOS via PF_SYSTEM control socket."""
    sock = socket.socket(AF_SYSTEM, socket.SOCK_DGRAM, SYSPROTO_CONTROL)

    ctl_name = b"com.apple.net.utun_control"
    buf = bytearray(4 + 256)
    buf[4:4 + len(ctl_name)] = ctl_name
    buf = fcntl.ioctl(sock.fileno(), CTLIOCGINFO, bytes(buf))
    ctl_id = struct.unpack_from("I", buf, 0)[0]

    sock.connect((ctl_id, index + 1))

    iface = sock.getsockopt(SYSPROTO_CONTROL, UTUN_OPT_IFNAME, 64)
    iface = iface.rstrip(b"\x00").decode()
    return TunDevice(sock.detach(), iface, macos=True)


def _open_tun_windows(name: str = "0xVPN") -> TunDevice:
    """Open a Wintun TUN device on Windows."""
    try:
        import wintun
    except ImportError:
        raise RuntimeError(
            "Wintun not found. Install it: pip install wintun\n"
            "Also requires the Wintun driver: https://www.wintun.net"
        )
    adapter = wintun.Adapter(name, "0xVPN")
    session = adapter.start_session(0x400000)
    fd = session.fileno()
    return TunDevice(fd, name)


def open_tun(name: str = "tun0") -> TunDevice:
    if sys.platform == "linux":
        return _open_tun_linux(name)
    if sys.platform == "darwin":
        for i in range(8):
            try:
                return _open_tun_macos(i)
            except OSError:
                continue
        raise RuntimeError("No free utun device available")
    if sys.platform == "win32":
        return _open_tun_windows(name)
    raise NotImplementedError(f"TUN not supported on {sys.platform}")


def configure_tun(dev: TunDevice, address: str) -> str:
    """Assign CIDR address to the TUN device and bring it up."""
    net = ipaddress.ip_interface(address)

    if sys.platform == "linux":
        subprocess.run(["ip", "addr", "add", address, "dev", dev.name], check=True)
        subprocess.run(["ip", "link", "set", dev.name, "up", "mtu", "1420"], check=True)

    elif sys.platform == "darwin":
        local_ip = str(net.ip)
        peer_ip  = str(
            net.network.network_address + 1
            if net.ip != net.network.network_address + 1
            else net.network.network_address + 2
        )
        subprocess.run(
            ["ifconfig", dev.name, local_ip, peer_ip, "up", "mtu", "1420"],
            check=True,
        )
        subprocess.run(
            ["route", "-n", "add", "-net", str(net.network), local_ip],
            check=True,
        )

    elif sys.platform == "win32":
        subprocess.run(
            ["netsh", "interface", "ip", "set", "address", dev.name,
             "static", str(net.ip), str(net.netmask)],
            check=True,
        )
        subprocess.run(
            ["netsh", "interface", "ipv4", "set", "subinterface", dev.name,
             "mtu=1420", "store=persistent"],
            check=False,
        )

    return str(net.network)


# ── DNS helpers ───────────────────────────────────────────────────────────────

def _get_default_interface_linux() -> str:
    """Return the default network interface name on Linux."""
    r = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        parts = line.split()
        if "dev" in parts:
            return parts[parts.index("dev") + 1]
    return "eth0"


def save_and_set_dns(dns_servers: list) -> dict:
    """Save current DNS config and set new servers. Returns state for restore."""
    state = {"platform": sys.platform}

    if sys.platform == "darwin":
        r = subprocess.run(
            ["networksetup", "-getdnsservers", "Wi-Fi"],
            capture_output=True, text=True,
        )
        out = r.stdout.strip()
        state["original"] = [] if "There aren't any" in out else out.splitlines()
        subprocess.run(
            ["networksetup", "-setdnsservers", "Wi-Fi"] + dns_servers,
            check=False,
        )

    elif sys.platform == "linux":
        resolv = Path("/etc/resolv.conf")
        state["original"] = resolv.read_text() if resolv.exists() else ""
        lines = [f"nameserver {s}" for s in dns_servers]
        resolv.write_text("\n".join(lines) + "\n")

    elif sys.platform == "win32":
        iface = _get_default_interface_linux()
        r = subprocess.run(
            ["netsh", "interface", "ipv4", "show", "dns", iface],
            capture_output=True, text=True,
        )
        state["original"] = r.stdout
        state["iface"]    = iface
        subprocess.run(
            ["netsh", "interface", "ipv4", "set", "dns", iface,
             "static", dns_servers[0]],
            check=False,
        )
        for s in dns_servers[1:]:
            subprocess.run(
                ["netsh", "interface", "ipv4", "add", "dns", iface, s, "index=2"],
                check=False,
            )

    click.echo(f"[0xVPN] DNS set to {' '.join(dns_servers)}")
    return state


def restore_dns(state: dict) -> None:
    """Restore DNS to original settings."""
    if not state:
        return
    click.echo("[0xVPN] restoring DNS...")

    if state["platform"] == "darwin":
        original = state.get("original", [])
        if original:
            subprocess.run(
                ["networksetup", "-setdnsservers", "Wi-Fi"] + original,
                check=False,
            )
        else:
            subprocess.run(
                ["networksetup", "-setdnsservers", "Wi-Fi", "empty"],
                check=False,
            )

    elif state["platform"] == "linux":
        Path("/etc/resolv.conf").write_text(state.get("original", ""))

    elif state["platform"] == "win32":
        iface = state.get("iface", "")
        subprocess.run(
            ["netsh", "interface", "ipv4", "set", "dns", iface, "dhcp"],
            check=False,
        )


# ── routing helpers ───────────────────────────────────────────────────────────

def setup_routes(gateway: str, host: str) -> dict:
    """Add routes to send all traffic through VPN. Returns state for restore."""
    state = {"platform": sys.platform, "host": host}

    if sys.platform == "linux":
        # Save original default route
        r = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
        state["original_route"] = r.stdout.strip()
        # Add direct route to VPS before changing default
        iface = _get_default_interface_linux()
        gw_r = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
        orig_gw = None
        for part in gw_r.stdout.split():
            if orig_gw is None and "via" in gw_r.stdout:
                parts = gw_r.stdout.split()
                if "via" in parts:
                    orig_gw = parts[parts.index("via") + 1]
                break
        if orig_gw:
            subprocess.run(["ip", "route", "add", host, "via", orig_gw], check=False)
            state["orig_gw"] = orig_gw
        subprocess.run(["ip", "route", "replace", "default", "via", gateway], check=False)
        click.echo(f"[0xVPN] Linux routes configured via {gateway}")

    elif sys.platform == "darwin":
        # Save original gateway
        r = subprocess.run(["route", "-n", "get", "default"], capture_output=True, text=True)
        orig_gw = None
        for line in r.stdout.splitlines():
            if "gateway:" in line:
                orig_gw = line.split("gateway:")[1].strip()
                break
        state["orig_gw"] = orig_gw
        click.echo(f"[0xVPN] original gateway: {orig_gw}")

        subprocess.run(["route", "-n", "add", "-net", "0.0.0.0/1",   gateway], check=False)
        subprocess.run(["route", "-n", "add", "-net", "128.0.0.0/1", gateway], check=False)
        if orig_gw:
            subprocess.run(["route", "-n", "add", "-host", host, orig_gw], check=False)
        click.echo(f"[0xVPN] macOS routes configured via {gateway}")

    elif sys.platform == "win32":
        # Save original default gateway
        r = subprocess.run(["route", "print", "0.0.0.0"], capture_output=True, text=True)
        state["original_route"] = r.stdout
        orig_gw = None
        for line in r.stdout.splitlines():
            if "0.0.0.0" in line and "0.0.0.0" in line:
                parts = line.split()
                if len(parts) >= 3:
                    orig_gw = parts[2]
                    break
        if orig_gw:
            subprocess.run(["route", "add", host, orig_gw], check=False)
            state["orig_gw"] = orig_gw
        subprocess.run(["route", "add", "0.0.0.0", "mask", "0.0.0.0", gateway], check=False)
        click.echo(f"[0xVPN] Windows routes configured via {gateway}")

    return state


def restore_routes(state: dict) -> None:
    """Remove VPN routes and restore originals."""
    if not state:
        return
    click.echo("[0xVPN] restoring routes...")
    host = state.get("host", "")

    if state["platform"] == "linux":
        subprocess.run(["ip", "route", "del", host], check=False)
        orig = state.get("original_route", "")
        if orig:
            subprocess.run(["ip", "route", "replace"] + orig.split()[1:], check=False)

    elif state["platform"] == "darwin":
        subprocess.run(["route", "-n", "delete", "-net", "0.0.0.0/1"],   check=False)
        subprocess.run(["route", "-n", "delete", "-net", "128.0.0.0/1"], check=False)
        orig_gw = state.get("orig_gw")
        if orig_gw:
            subprocess.run(["route", "-n", "delete", "-host", host], check=False)

    elif state["platform"] == "win32":
        subprocess.run(["route", "delete", host], check=False)
        subprocess.run(["route", "delete", "0.0.0.0", "mask", "0.0.0.0"], check=False)
        orig_gw = state.get("orig_gw")
        if orig_gw:
            subprocess.run(["route", "add", "0.0.0.0", "mask", "0.0.0.0", orig_gw], check=False)


# ── forwarding loops ──────────────────────────────────────────────────────────

def _tun_to_udp(
    tun: TunDevice,
    sock: socket.socket,
    key: bytes,
    get_remote,
    stop: threading.Event,
) -> None:
    while not stop.is_set():
        r, _, _ = select.select([tun.fd], [], [], 1.0)
        if not r:
            continue
        try:
            pkt = tun.read()
        except OSError:
            break
        remote = get_remote(pkt)
        if not remote:
            continue
        try:
            sock.sendto(encrypt(key, pkt), remote)
        except OSError:
            break


def _udp_to_tun(
    tun: TunDevice,
    sock: socket.socket,
    key: bytes,
    on_receive,
    stop: threading.Event,
) -> None:
    while not stop.is_set():
        r, _, _ = select.select([sock], [], [], 1.0)
        if not r:
            continue
        try:
            data, src = sock.recvfrom(65536 + 128)
        except OSError:
            break
        pkt = decrypt(key, data)
        if pkt is None:
            continue
        on_receive(src, pkt)
        try:
            tun.write(pkt)
        except OSError:
            break


# ── server ────────────────────────────────────────────────────────────────────

def run_server(cfg: dict) -> None:
    iface = cfg["interface"]
    key   = _derive_key(iface["shared_key"])
    addr  = iface["address"]
    port  = int(iface["listen_port"])

    tun     = open_tun("tun0")
    network = configure_tun(tun, addr)

    out_iface = iface.get("out_iface", "eth0")
    subprocess.run(
        ["iptables", "-t", "nat", "-A", "POSTROUTING",
         "-s", network, "-o", out_iface, "-j", "MASQUERADE"],
        check=False,
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))

    click.echo(f"[0xVPN] server  addr={addr}  port={port}/udp")

    clients: dict = {}
    lock = threading.Lock()
    stop = threading.Event()

    def on_receive(src: tuple, pkt: bytes) -> None:
        if len(pkt) < 20:
            return
        vpn_src = socket.inet_ntoa(pkt[12:16])
        with lock:
            clients[vpn_src] = src

    def get_remote(pkt: bytes):
        if len(pkt) < 20:
            return None
        vpn_dst = socket.inet_ntoa(pkt[16:20])
        with lock:
            return clients.get(vpn_dst)

    t1 = threading.Thread(target=_udp_to_tun, args=(tun, sock, key, on_receive, stop), daemon=True)
    t2 = threading.Thread(target=_tun_to_udp, args=(tun, sock, key, get_remote, stop), daemon=True)
    t1.start()
    t2.start()

    try:
        t1.join()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        click.echo("\n[0xVPN] server stopped")


# ── client ────────────────────────────────────────────────────────────────────

def run_client(cfg: dict) -> None:
    iface     = cfg["interface"]
    peer      = cfg["peer"]
    key       = _derive_key(peer["shared_key"])
    addr      = iface["address"]
    host, raw_port = peer["endpoint"].rsplit(":", 1)

    click.echo(f"[0xVPN] resolving {host}...")
    remote    = (socket.gethostbyname(host), int(raw_port))
    click.echo(f"[0xVPN] resolved to {remote[0]}")

    route_all = peer.get("allowed_ips", "") == "0.0.0.0/0"

    click.echo(f"[0xVPN] opening TUN device...")
    tun = open_tun("tun0")
    click.echo(f"[0xVPN] TUN opened: {tun.name}")

    click.echo(f"[0xVPN] configuring TUN {addr}...")
    configure_tun(tun, addr)
    click.echo(f"[0xVPN] TUN configured")

    gateway = str(ipaddress.ip_interface(addr).network.network_address + 1)
    click.echo(f"[0xVPN] VPN gateway: {gateway}")

    route_state = {}
    dns_state   = {}

    if route_all:
        route_state = setup_routes(gateway, host)
        dns_state   = save_and_set_dns(["1.1.1.1", "8.8.8.8"])

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))

    click.echo(f"[0xVPN] connected  peer={host}:{raw_port}  local={addr}")
    click.echo(f"[0xVPN] threads running — Ctrl+C to disconnect")

    stop = threading.Event()

    t1 = threading.Thread(
        target=_tun_to_udp,
        args=(tun, sock, key, lambda _pkt: remote, stop),
        daemon=True,
    )
    t2 = threading.Thread(
        target=_udp_to_tun,
        args=(tun, sock, key, lambda _src, _pkt: None, stop),
        daemon=True,
    )
    t1.start()
    t2.start()

    try:
        t1.join()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if route_all:
            restore_routes(route_state)
            restore_dns(dns_state)
        click.echo("\n[0xVPN] disconnected")


# ── interactive setup ─────────────────────────────────────────────────────────

def interactive_setup(config_path: Path) -> None:
    """Prompt the user for server details and write a client.toml."""
    click.echo("\n[0xVPN] No config found. Let's set it up!\n")

    server_ip  = click.prompt("  VPS IP address")
    port       = click.prompt("  Port", default="51820")
    shared_key = click.prompt("  Shared key (from your server's server.toml)")
    client_ip  = click.prompt("  Client VPN IP", default="10.0.0.2/24")

    config_path.parent.mkdir(parents=True, exist_ok=True)

    toml_content = f"""[interface]
address = "{client_ip}"
mode    = "client"

[peer]
endpoint    = "{server_ip}:{port}"
shared_key  = "{shared_key}"
allowed_ips = "0.0.0.0/0"
"""

    config_path.write_text(toml_content)
    config_path.chmod(0o600)

    click.echo(f"\n  Config saved to {config_path}")
    click.echo("  Connecting...\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """0xVPN — simple encrypted VPN."""


@cli.command()
@click.option("--config", required=True, type=click.Path(exists=True), help="Path to server.toml")
def start(config: str) -> None:
    """Start the VPN server."""
    with open(config, "rb") as f:
        cfg = tomllib.load(f)
    run_server(cfg)


@cli.command()
@click.argument("config", required=False)
def connect(config: Optional[str]) -> None:
    """Connect as a VPN client."""
    default = Path.home() / ".0xvpn" / "configs" / "client.toml"
    path = Path(config) if config else default

    if not path.exists():
        interactive_setup(path)

    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    run_client(cfg)


@cli.command()
def disconnect() -> None:
    """Tear down the VPN tunnel."""
    if sys.platform == "linux":
        r = subprocess.run(["ip", "link", "del", "tun0"], capture_output=True)
    elif sys.platform == "win32":
        r = subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True)
    else:
        r = subprocess.run(["pkill", "-f", "cli.py connect"], capture_output=True)
    msg = "disconnected" if r.returncode == 0 else "not connected (or already disconnected)"
    click.echo(f"[0xVPN] {msg}")


@cli.command()
def status() -> None:
    """Show VPN connection status."""
    if sys.platform == "linux":
        r = subprocess.run(["ip", "link", "show", "tun0"], capture_output=True, text=True)
        connected = r.returncode == 0 and "UP" in r.stdout
        click.echo(f"[0xVPN] {'connected' if connected else 'not connected'}")
        if connected:
            click.echo(r.stdout.strip())
    elif sys.platform == "darwin":
        r = subprocess.run(["ifconfig"], capture_output=True, text=True)
        utuns = [line for line in r.stdout.splitlines() if line.startswith("utun")]
        if utuns:
            click.echo("[0xVPN] connected")
            for u in utuns:
                click.echo(f"  {u}")
        else:
            click.echo("[0xVPN] not connected")
    elif sys.platform == "win32":
        r = subprocess.run(["netsh", "interface", "show", "interface", "0xVPN"],
                           capture_output=True, text=True)
        connected = "Connected" in r.stdout
        click.echo(f"[0xVPN] {'connected' if connected else 'not connected'}")
    else:
        click.echo(f"[0xVPN] status not supported on {sys.platform}")


if __name__ == "__main__":
    cli()