#!/bin/bash

# setup/connect-vpn.sh

VPS_ADDRESS=$(grep 'endpoint' ~/.0xvpn/configs/client.toml | cut -d'=' -f2 | tr -d ' "' | cut -d':' -f1)

echo "Connecting to $VPS_ADDRESS..."

if sudo python3 ~/.0xvpn/cli.py connect; then
    echo "Connected to $VPS_ADDRESS"
else
    echo "Failed to connect to $VPS_ADDRESS"
fi
