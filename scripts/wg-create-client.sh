#!/usr/bin/env bash
set -euo pipefail

WG_DIR="/etc/wireguard"
CLIENT_DIR="${WG_DIR}/clients"
WG_CONF="${WG_DIR}/wg0.conf"
SERVER_PUB="${WG_DIR}/server.pub"
SERVER_ENDPOINT="maranoserver.myvnc.com:51820"
DNS_SERVER="192.168.15.92"
WG_SUBNET_BASE="10.10.0"

CLIENT_NAME="${1:-}"

if [[ -z "$CLIENT_NAME" ]]; then
  echo "Usage: $0 <client-name>"
  exit 1
fi

mkdir -p "$CLIENT_DIR"

CLIENT_KEY="${CLIENT_DIR}/${CLIENT_NAME}.key"
CLIENT_PUB="${CLIENT_DIR}/${CLIENT_NAME}.pub"
CLIENT_CONF="${CLIENT_DIR}/${CLIENT_NAME}.conf"

if [[ -f "$CLIENT_CONF" ]]; then
  echo "Client config already exists: $CLIENT_CONF"
  exit 1
fi

# Find next free IP in 10.10.0.2-254
USED_IPS="$(grep -hoE '10\.10\.0\.[0-9]+' "$WG_CONF" 2>/dev/null || true)"
NEXT_IP=""
for i in $(seq 2 254); do
  CANDIDATE="${WG_SUBNET_BASE}.${i}"
  if ! echo "$USED_IPS" | grep -qx "$CANDIDATE"; then
    NEXT_IP="$CANDIDATE"
    break
  fi
done

if [[ -z "$NEXT_IP" ]]; then
  echo "No free IP available in ${WG_SUBNET_BASE}.0/24"
  exit 1
fi

wg genkey | tee "$CLIENT_KEY" | wg pubkey > "$CLIENT_PUB"
chmod 600 "$CLIENT_KEY"
chmod 644 "$CLIENT_PUB"

CLIENT_PRIVATE_KEY="$(cat "$CLIENT_KEY")"
CLIENT_PUBLIC_KEY="$(cat "$CLIENT_PUB")"
SERVER_PUBLIC_KEY="$(cat "$SERVER_PUB")"

cat > "$CLIENT_CONF" <<EOF
[Interface]
PrivateKey = ${CLIENT_PRIVATE_KEY}
Address = ${NEXT_IP}/24
DNS = ${DNS_SERVER}

[Peer]
PublicKey = ${SERVER_PUBLIC_KEY}
Endpoint = ${SERVER_ENDPOINT}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF

# Add peer to server config
cat >> "$WG_CONF" <<EOF

[Peer]
# ${CLIENT_NAME}
PublicKey = ${CLIENT_PUBLIC_KEY}
AllowedIPs = ${NEXT_IP}/32
EOF

wg syncconf wg0 <(wg-quick strip wg0)

echo "Created client: ${CLIENT_NAME}"
echo "IP: ${NEXT_IP}"
echo "Config: ${CLIENT_CONF}"
