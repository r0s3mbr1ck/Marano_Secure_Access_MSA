!/bin/bash

set -e

echo "=== Marano Secure Access Bootstrap ==="

# -------------------------
# 1. Install dependencies
# -------------------------
echo "[+] Installing dependencies..."
apt update
apt install -y python3 python3-pip python3-venv easy-rsa nginx git qrencode

# -------------------------
# 2. Clone repo (optional)
# -------------------------
if [ ! -d "Marano_Secure_Access_MSA" ]; then
  echo "[+] Cloning repository..."
  git clone https://github.com/r0s3mbr1ck/Marano_Secure_Access_MSA.git
fi

cd Marano_Secure_Access_MSA

# -------------------------
# 3. Python env
# -------------------------
echo "[+] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# -------------------------
# 4. Fix Easy-RSA path
# -------------------------
echo "[+] Fixing Easy-RSA path..."
mkdir -p /etc/openvpn

if [ ! -e /etc/openvpn/easy-rsa ]; then
  ln -s /usr/share/easy-rsa /etc/openvpn/easy-rsa
fi

# -------------------------
# 5. Initialize PKI (if needed)
# -------------------------
EASYRSA_DIR="/etc/openvpn/easy-rsa"

if [ ! -d "$EASYRSA_DIR/pki" ]; then
  echo "[+] Initializing PKI..."

  cd $EASYRSA_DIR

  ./easyrsa init-pki
  echo "MSA-CA" | ./easyrsa build-ca nopass

  ./easyrsa gen-req server nopass
  echo "yes" | ./easyrsa sign-req server server

  ./easyrsa gen-dh
  ./easyrsa gen-crl

  mkdir -p /etc/openvpn

  cp pki/ca.crt /etc/openvpn/
  cp pki/private/server.key /etc/openvpn/
  cp pki/issued/server.crt /etc/openvpn/
  cp pki/dh.pem /etc/openvpn/
  cp pki/crl.pem /etc/openvpn/
  chmod 644 /etc/openvpn/crl.pem
fi

cd ~/Marano_Secure_Access_MSA

# -------------------------
# 6. Admin setup
# -------------------------
ENV_FILE="/root/.config/ovpn-menu.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "[+] Creating admin setup..."

  mkdir -p /root/.config

  ADMIN_USER="admin"
  ADMIN_PASS=$(openssl rand -base64 12)

  TOTP_SECRET=$(python3 - <<EOF
import pyotp
print(pyotp.random_base32())
EOF
)

  cat > $ENV_FILE <<EOF
export OVPN_ADMIN_USER=$ADMIN_USER
export OVPN_ADMIN_PASS=$ADMIN_PASS
export OVPN_ADMIN_TOTP_SECRET=$TOTP_SECRET
EOF

  echo ""
  echo "====================================="
  echo " ADMIN CREDENTIALS"
  echo "====================================="
  echo "User: $ADMIN_USER"
  echo "Pass: $ADMIN_PASS"
  echo "TOTP Secret: $TOTP_SECRET"
  echo "====================================="

  echo ""
  echo "Add this secret to Google Authenticator or other Authenticator App  manually."
fi

# -------------------------
# 7. Done
# -------------------------
echo ""
echo "✅ Setup complete!"
echo ""
echo "Run the app with:"
echo "source venv/bin/activate && python3 app.py"
echo ""
echo "Access:"
echo "http://<SERVER_IP>:8080"
