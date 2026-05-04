#!/bin/bash
set -e

sysctl -w net.ipv4.ip_forward=1 -q

exec python /app/cli.py start --config "${CONFIG_PATH:-/app/configs/server.toml}"
