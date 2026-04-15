#!/usr/bin/env bash
set -euo pipefail

CLIENT="$1"

if [[ -z "${CLIENT:-}" ]]; then
  echo "Uso: $0 <nome-do-cliente>"
  exit 1
fi

EASYRSA_DIR="/etc/openvpn/easy-rsa"
OUTPUT_DIR="/etc/openvpn/client-configs/files"
BASE_CONFIG="/etc/openvpn/client-configs/base.conf"

CA_CERT="${EASYRSA_DIR}/pki/ca.crt"
CLIENT_CERT="${EASYRSA_DIR}/pki/issued/${CLIENT}.crt"
CLIENT_KEY="${EASYRSA_DIR}/pki/private/${CLIENT}.key"
TC_KEY="/etc/openvpn/tc.key"

if [[ ! -f "$CLIENT_CERT" || ! -f "$CLIENT_KEY" ]]; then
  echo "Erro: certificado ou chave do cliente não encontrados."
  exit 1
fi

OVPN_FILE="${OUTPUT_DIR}/${CLIENT}.ovpn"

cat "$BASE_CONFIG" > "$OVPN_FILE"
echo "" >> "$OVPN_FILE"

echo "<ca>" >> "$OVPN_FILE"
cat "$CA_CERT" >> "$OVPN_FILE"
echo "</ca>" >> "$OVPN_FILE"

echo "<cert>" >> "$OVPN_FILE"
sed -n '/BEGIN CERTIFICATE/,$p' "$CLIENT_CERT" >> "$OVPN_FILE"
echo "</cert>" >> "$OVPN_FILE"

echo "<key>" >> "$OVPN_FILE"
cat "$CLIENT_KEY" >> "$OVPN_FILE"
echo "</key>" >> "$OVPN_FILE"

echo "<tls-crypt>" >> "$OVPN_FILE"
cat "$TC_KEY" >> "$OVPN_FILE"
echo "</tls-crypt>" >> "$OVPN_FILE"

chmod 600 "$OVPN_FILE"

echo "Perfil gerado com sucesso:"
echo "  $OVPN_FILE"
