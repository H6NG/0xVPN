# ─────────────────────────────────────────────
#  0xVPN — Docker image
#  Usage:
#    docker build -t 0xvpn .
#    docker run -d \
#      --cap-add=NET_ADMIN \
#      --sysctl net.ipv4.ip_forward=1 \
#      -p 51820:51820/udp \
#      -v 0xvpn-configs:/app/configs \
#      -e SERVER_IP=YOUR_VPS_IP \
#      0xvpn
# ─────────────────────────────────────────────

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    iptables \
    procps \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/configs
VOLUME ["/app/configs"]

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 51820/udp

ENTRYPOINT ["/docker-entrypoint.sh"]