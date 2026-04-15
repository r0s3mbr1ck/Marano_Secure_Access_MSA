#!/bin/bash

set -euo pipefail

echo "======================================"
echo "   Marano Secure Access Installer"
echo "======================================"
echo ""

if [ "$EUID" -ne 0 ]; then
  echo "[!] Run as root"
  exit 1
fi

REPO_URL="https://github.com/r0s3mbr1ck/Marano_Secure_Access_MSA.git"
INSTALL_DIR="/opt/Marano_Secure_Access_MSA"

ENV_FILE="/root/.config/ovpn-menu.env"
WG_ENV_FILE="/etc/wireguard/msa-wg.env"

OPENVPN_DIR="/etc/openvpn"
EASYRSA_DIR="/etc/openvpn/easy-rsa"
CLIENT_CFG_DIR="/etc/openvpn/client-configs"
CLIENT_CFG_AUTH_DIR="/etc/openvpn/client-configs-auth"
WIREGUARD_DIR="/etc/wireguard"
WIREGUARD_CLIENTS_DIR="/etc/wireguard/clients"

AUTH_DB="/etc/openvpn/auth/users.db"
REGISTRY_FILE="/etc/openvpn/client-configs/files/registry.csv"

info() {
  echo "[+] $1"
}

warn() {
  echo "[!] $1"
}

fail() {
  echo "[x] $1"
  exit 1
}

echo "=== Network Configuration ==="

read -rp "VPN public host or IP: " VPN_PUBLIC_HOST
VPN_PUBLIC_HOST="${VPN_PUBLIC_HOST:-}"

read -rp "OpenVPN protocol [udp]: " OVPN_PROTO
OVPN_PROTO="${OVPN_PROTO:-udp}"

read -rp "OpenVPN certificate port [1194]: " OVPN_CERT_PORT
OVPN_CERT_PORT="${OVPN_CERT_PORT:-1194}"

read -rp "OpenVPN auth port [1195]: " OVPN_AUTH_PORT
OVPN_AUTH_PORT="${OVPN_AUTH_PORT:-1195}"

read -rp "OpenVPN server certificate CN [server]: " VPN_SERVER_CN
VPN_SERVER_CN="${VPN_SERVER_CN:-server}"

read -rp "WireGuard interface name [wg0]: " WG_IFACE
WG_IFACE="${WG_IFACE:-wg0}"

read -rp "WireGuard server address (ex: 10.20.30.1) [10.20.30.1]: " WG_SERVER_ADDRESS
WG_SERVER_ADDRESS="${WG_SERVER_ADDRESS:-10.20.30.1}"

read -rp "WireGuard network CIDR (ex: 10.20.30.0/24) [10.20.30.0/24]: " WG_NETWORK_CIDR
WG_NETWORK_CIDR="${WG_NETWORK_CIDR:-10.20.30.0/24}"

read -rp "WireGuard listen port [51820]: " WG_SERVER_PORT
WG_SERVER_PORT="${WG_SERVER_PORT:-51820}"

read -rp "WAN interface for NAT [eth0]: " WAN_IFACE
WAN_IFACE="${WAN_IFACE:-eth0}"

[ -n "$VPN_PUBLIC_HOST" ] || fail "VPN public host or IP is required"
[ -n "$OVPN_PROTO" ] || fail "OpenVPN protocol is required"
[ -n "$OVPN_CERT_PORT" ] || fail "OpenVPN certificate port is required"
[ -n "$OVPN_AUTH_PORT" ] || fail "OpenVPN auth port is required"
[ -n "$VPN_SERVER_CN" ] || fail "OpenVPN server certificate CN is required"
[ -n "$WG_IFACE" ] || fail "WireGuard interface name is required"
[ -n "$WG_SERVER_ADDRESS" ] || fail "WireGuard server address is required"
[ -n "$WG_NETWORK_CIDR" ] || fail "WireGuard network CIDR is required"
[ -n "$WG_SERVER_PORT" ] || fail "WireGuard listen port is required"
[ -n "$WAN_IFACE" ] || fail "WAN interface is required"

echo ""
info "Updating system..."
apt update

info "Installing dependencies..."
apt install -y \
  python3 \
  python3-pip \
  python3-venv \
  easy-rsa \
  nginx \
  git \
  sqlite3 \
  qrencode \
  openssl \
  wireguard-tools \
  openvpn

if [ ! -d "$INSTALL_DIR/.git" ]; then
  info "Cloning repository into $INSTALL_DIR..."
  rm -rf "$INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
else
  info "Repository already exists at $INSTALL_DIR. Pulling latest changes..."
  git -C "$INSTALL_DIR" pull --ff-only || warn "Could not fast-forward pull. Keeping current checkout."
fi

cd "$INSTALL_DIR"

info "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

info "Preparing directories..."
mkdir -p /root/.config
mkdir -p "$OPENVPN_DIR"
mkdir -p /etc/openvpn/auth
mkdir -p "$CLIENT_CFG_DIR/files"
mkdir -p "$CLIENT_CFG_AUTH_DIR/files"
mkdir -p "$WIREGUARD_DIR"
mkdir -p "$WIREGUARD_CLIENTS_DIR"

if [ ! -e "$EASYRSA_DIR" ]; then
  info "Fixing Easy-RSA path..."
  ln -s /usr/share/easy-rsa "$EASYRSA_DIR"
else
  info "Easy-RSA path already exists."
fi

if [ ! -x "$EASYRSA_DIR/easyrsa" ]; then
  chmod +x "$EASYRSA_DIR/easyrsa" || true
fi

info "Ensuring PKI is ready..."
cd "$EASYRSA_DIR"

if [ ! -d "$EASYRSA_DIR/pki" ]; then
  info "Initializing PKI..."
  ./easyrsa init-pki
  echo "MSA-CA" | ./easyrsa build-ca nopass
  ./easyrsa gen-req "$VPN_SERVER_CN" nopass
  echo "yes" | ./easyrsa sign-req server "$VPN_SERVER_CN"
  ./easyrsa gen-dh
else
  info "PKI already exists. Reusing current PKI."
fi

info "Generating CRL..."
./easyrsa gen-crl

[ -f "pki/ca.crt" ] || fail "Missing pki/ca.crt"
[ -f "pki/private/$VPN_SERVER_CN.key" ] || fail "Missing pki/private/$VPN_SERVER_CN.key"
[ -f "pki/issued/$VPN_SERVER_CN.crt" ] || fail "Missing pki/issued/$VPN_SERVER_CN.crt"
[ -f "pki/dh.pem" ] || fail "Missing pki/dh.pem"
[ -f "pki/crl.pem" ] || fail "Missing pki/crl.pem"

cp -f pki/ca.crt /etc/openvpn/
cp -f "pki/private/$VPN_SERVER_CN.key" /etc/openvpn/
cp -f "pki/issued/$VPN_SERVER_CN.crt" /etc/openvpn/
cp -f pki/dh.pem /etc/openvpn/
cp -f pki/crl.pem /etc/openvpn/
chmod 644 /etc/openvpn/crl.pem

cd "$INSTALL_DIR"

info "Ensuring OpenVPN tls-crypt key exists..."
if [ ! -f /etc/openvpn/tc.key ]; then
  openvpn --genkey secret /etc/openvpn/tc.key
fi
chmod 600 /etc/openvpn/tc.key

info "Creating registry file..."
if [ ! -f "$REGISTRY_FILE" ]; then
  cat > "$REGISTRY_FILE" <<'EOF'
id,cn,type,email,status,created_at,revoked_at
EOF
else
  info "Registry file already exists."
fi

info "Creating auth database..."
sqlite3 "$AUTH_DB" <<'EOF'
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT UNIQUE,
    must_change_password INTEGER DEFAULT 1,
    is_active INTEGER DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS user_portal_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    is_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
EOF

chmod 600 "$AUTH_DB"

info "Installing helper scripts and templates..."
[ -f "$INSTALL_DIR/scripts/make-ovpn.sh" ] || fail "Missing scripts/make-ovpn.sh"
[ -f "$INSTALL_DIR/scripts/make-ovpn-auth.sh" ] || fail "Missing scripts/make-ovpn-auth.sh"
[ -f "$INSTALL_DIR/scripts/wg-create-client.sh" ] || fail "Missing scripts/wg-create-client.sh"
[ -f "$INSTALL_DIR/scripts/base.conf" ] || fail "Missing scripts/base.conf"
[ -f "$INSTALL_DIR/scripts/base-auth.conf" ] || fail "Missing scripts/base-auth.conf"
[ -f "$INSTALL_DIR/scripts/wg0.conf.template" ] || fail "Missing scripts/wg0.conf.template"

cp -f "$INSTALL_DIR/scripts/make-ovpn.sh" "$CLIENT_CFG_DIR/make-ovpn.sh"
cp -f "$INSTALL_DIR/scripts/make-ovpn-auth.sh" "$CLIENT_CFG_AUTH_DIR/make-ovpn-auth.sh"
cp -f "$INSTALL_DIR/scripts/wg-create-client.sh" /usr/local/bin/wg-create-client.sh"

chmod +x "$CLIENT_CFG_DIR/make-ovpn.sh"
chmod +x "$CLIENT_CFG_AUTH_DIR/make-ovpn-auth.sh"
chmod +x /usr/local/bin/wg-create-client.sh

info "Rendering OpenVPN base templates..."
sed \
  -e "s|__OVPN_PROTO__|$OVPN_PROTO|g" \
  -e "s|__VPN_PUBLIC_HOST__|$VPN_PUBLIC_HOST|g" \
  -e "s|__OVPN_CERT_PORT__|$OVPN_CERT_PORT|g" \
  "$INSTALL_DIR/scripts/base.conf" > "$CLIENT_CFG_DIR/base.conf"

sed \
  -e "s|__OVPN_PROTO__|$OVPN_PROTO|g" \
  -e "s|__VPN_PUBLIC_HOST__|$VPN_PUBLIC_HOST|g" \
  -e "s|__OVPN_AUTH_PORT__|$OVPN_AUTH_PORT|g" \
  "$INSTALL_DIR/scripts/base-auth.conf" > "$CLIENT_CFG_AUTH_DIR/base.conf"

info "Preparing WireGuard server configuration..."
WG_SERVER_KEY_FILE="$WIREGUARD_DIR/${WG_IFACE}.key"
WG_SERVER_PUB_FILE="$WIREGUARD_DIR/${WG_IFACE}.pub"
WG_CONF_FILE="$WIREGUARD_DIR/${WG_IFACE}.conf"

if [ ! -f "$WG_SERVER_KEY_FILE" ]; then
  info "Generating WireGuard server keys..."
  umask 077
  wg genkey | tee "$WG_SERVER_KEY_FILE" | wg pubkey > "$WG_SERVER_PUB_FILE"
fi

[ -f "$WG_SERVER_KEY_FILE" ] || fail "WireGuard server key was not created"
[ -f "$WG_SERVER_PUB_FILE" ] || fail "WireGuard server public key was not created"

WG_SERVER_PRIVATE_KEY="$(cat "$WG_SERVER_KEY_FILE")"
WG_SERVER_PUBLIC_KEY="$(cat "$WG_SERVER_PUB_FILE")"

info "Preparing WireGuard compatibility paths..."
ln -sf "$WG_SERVER_KEY_FILE" /etc/wireguard/server.key
ln -sf "$WG_SERVER_PUB_FILE" /etc/wireguard/server.pub

sed \
  -e "s|__WG_SERVER_ADDRESS__|$WG_SERVER_ADDRESS|g" \
  -e "s|__WG_SERVER_PORT__|$WG_SERVER_PORT|g" \
  -e "s|__WG_SERVER_PRIVATE_KEY__|$WG_SERVER_PRIVATE_KEY|g" \
  -e "s|__WG_NETWORK_CIDR__|$WG_NETWORK_CIDR|g" \
  -e "s|__WAN_IFACE__|$WAN_IFACE|g" \
  -e "s|__WG_IFACE__|$WG_IFACE|g" \
  "$INSTALL_DIR/scripts/wg0.conf.template" > "$WG_CONF_FILE"

chmod 600 "$WG_CONF_FILE"

info "Creating WireGuard environment file..."
cat > "$WG_ENV_FILE" <<EOF
WG_IFACE=$WG_IFACE
WG_SERVER_ADDRESS=$WG_SERVER_ADDRESS
WG_NETWORK_CIDR=$WG_NETWORK_CIDR
WG_SERVER_PORT=$WG_SERVER_PORT
WG_SERVER_PUBLIC_KEY=$WG_SERVER_PUBLIC_KEY
VPN_PUBLIC_HOST=$VPN_PUBLIC_HOST
EOF

chmod 600 "$WG_ENV_FILE"

if [ ! -f "$ENV_FILE" ]; then
  info "Creating application environment file..."

  ADMIN_USER="admin"
  ADMIN_PASS="$(openssl rand -base64 12)"
  WEB_SECRET="$(openssl rand -hex 32)"

  TOTP_SECRET="$(python3 - <<'PYEOF'
import pyotp
print(pyotp.random_base32())
PYEOF
)"

  cat > "$ENV_FILE" <<EOF
export OVPN_WEB_SECRET=$WEB_SECRET

export OVPN_ADMIN_USER=$ADMIN_USER
export OVPN_ADMIN_PASS=$ADMIN_PASS
export OVPN_ADMIN_TOTP_SECRET=$TOTP_SECRET

export OVPN_SMTP_HOST=
export OVPN_SMTP_PORT=465
export OVPN_SMTP_USER=
export OVPN_SMTP_PASS=
export OVPN_SMTP_FROM=

export OVPN_SUPPORT_EMAIL=vpn.admin@example.com

export OVPN_TG_BOT_TOKEN=
export OVPN_TG_CHAT_ID=
EOF

  echo ""
  echo "======================================"
  echo " ADMIN ACCESS"
  echo "======================================"
  echo "User: $ADMIN_USER"
  echo "Pass: $ADMIN_PASS"
  echo "TOTP Secret: $TOTP_SECRET"
  echo "======================================"
else
  info "Application environment file already exists."
fi

info "Validating installed components..."
[ -x "$CLIENT_CFG_DIR/make-ovpn.sh" ] || fail "OpenVPN script missing or not executable"
[ -x "$CLIENT_CFG_AUTH_DIR/make-ovpn-auth.sh" ] || fail "OpenVPN auth script missing or not executable"
[ -x "/usr/local/bin/wg-create-client.sh" ] || fail "WireGuard script missing or not executable"
[ -f "$CLIENT_CFG_DIR/base.conf" ] || fail "Missing $CLIENT_CFG_DIR/base.conf"
[ -f "$CLIENT_CFG_AUTH_DIR/base.conf" ] || fail "Missing $CLIENT_CFG_AUTH_DIR/base.conf"
[ -f "$AUTH_DB" ] || fail "Database missing"
[ -f "$REGISTRY_FILE" ] || fail "Registry file missing"
[ -x "$EASYRSA_DIR/easyrsa" ] || fail "Easy-RSA not executable"
[ -f "$WIREGUARD_DIR/${WG_IFACE}.conf" ] || fail "WireGuard config missing"
[ -f "$WG_ENV_FILE" ] || fail "WireGuard environment file missing"
[ -f /etc/openvpn/tc.key ] || fail "Missing /etc/openvpn/tc.key"
[ -f /etc/wireguard/server.key ] || fail "Missing /etc/wireguard/server.key"
[ -f /etc/wireguard/server.pub ] || fail "Missing /etc/wireguard/server.pub"

echo ""
echo "✅ INSTALL COMPLETE"
echo ""
echo "Next steps:"
echo "1. Review $ENV_FILE"
echo "2. Review $WG_ENV_FILE"
echo "3. Configure SMTP / Telegram if needed"
echo "4. Start the application:"
echo ""
echo "   cd $INSTALL_DIR"
echo "   source venv/bin/activate"
echo "   python3 app.py"
echo ""
echo "Access:"
echo "   http://<SERVER_IP>:8080"
