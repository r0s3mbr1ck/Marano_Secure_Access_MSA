#!/usr/bin/env bash
set -euo pipefail

####################################################
# OpenVPN Community - CLI Menu (v4 - TTL)
# - Easy-RSA client management
# - Generate .ovpn via make-ovpn.sh
# - Registry: ID -> CN + TTL (expires_at)
# - Batch: create+ovpn for ID range (vpn-001..)
# - Revoke by CN / ID / ID range
# - Export: Telegram / local copy
# - Expire job: separate script ovpn-expire-check.sh
####################################################

EASYRSA_DIR="/etc/openvpn/easy-rsa"
CLIENT_CFG_DIR="/etc/openvpn/client-configs"
MAKE_OVPN="${CLIENT_CFG_DIR}/make-ovpn.sh"
OVPN_OUT_DIR="${CLIENT_CFG_DIR}/files"

REGISTRY="${OVPN_OUT_DIR}/registry.csv"
SERVER_UNIT="openvpn@server"
CRL_DST="/etc/openvpn/crl.pem"
SERVER_CONF="/etc/openvpn/server.conf"
STATUS_LOG="/var/log/openvpn/status.log"

[[ -f /root/.config/ovpn-menu.env ]] && source /root/.config/ovpn-menu.env

RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; BLUE=$'\e[36m'; RESET=$'\e[0m'
die() { echo "${RED}[-]${RESET} $*" >&2; exit 1; }
ok()  { echo "${GREEN}[+]${RESET} $*"; }
warn(){ echo "${YELLOW}[!]${RESET} $*"; }
info(){ echo "${BLUE}[*]${RESET} $*"; }

need_root() { [[ "${EUID}" -eq 0 ]] || die "Run as root."; }
pause() { read -r -p "Press ENTER to continue... " _; }

sanitize_name() {
  local name="$1"
  [[ "$name" =~ ^[a-zA-Z0-9_-]+$ ]] || die "Invalid name. Use only [a-zA-Z0-9_-]."
}

client_exists() {
  local name="$1"
  [[ -f "$EASYRSA_DIR/pki/issued/${name}.crt" && -f "$EASYRSA_DIR/pki/private/${name}.key" ]]
}

ovpn_path() {
  local name="$1"
  echo "${OVPN_OUT_DIR}/${name}.ovpn"
}

require_paths() {
  [[ -d "$EASYRSA_DIR" ]] || die "Easy-RSA not found at: $EASYRSA_DIR"
  [[ -f "$EASYRSA_DIR/easyrsa" ]] || die "easyrsa not found at: $EASYRSA_DIR/easyrsa"
  [[ -x "$MAKE_OVPN" ]] || warn "make-ovpn.sh not executable/not found: $MAKE_OVPN (ovpn generation may fail)."
  mkdir -p "$OVPN_OUT_DIR" || true

  # registry format (CSV):
  # id,cn,created_at,expires_at,status
  if [[ ! -f "$REGISTRY" ]]; then
    echo "id,cn,created_at,expires_at,status" > "$REGISTRY"
  fi
}

# ---------- time helpers ----------
now_utc() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
add_hours_utc() {
  local hours="$1"
  date -u -d "+${hours} hours" +"%Y-%m-%dT%H:%M:%SZ"
}

# ---------- Registry helpers (ID -> CN) ----------
# registry format: id,cn,created_at,expires_at,status
# Strategy (Option 2): keep history -> append new lines, never delete old ones.
# Always resolve "current" by looking at the LAST record for that ID.

registry_last_record() {
  local id="$1"
  [[ -f "$REGISTRY" ]] || return 1
  # Get last record for this ID (ignore header)
  awk -F',' -v id="$id" 'NR>1 && $1==id {rec=$0} END{if(rec!="") print rec; else exit 1}' "$REGISTRY"
}

registry_last_status() {
  local id="$1"
  local rec
  rec="$(registry_last_record "$id" 2>/dev/null)" || return 1
  echo "$rec" | awk -F',' '{print $5}'
}

registry_last_cn() {
  local id="$1"
  local rec
  rec="$(registry_last_record "$id" 2>/dev/null)" || return 1
  echo "$rec" | awk -F',' '{print $2}'
}

# Find the most recent ACTIVE CN for an ID (walk from bottom)
registry_last_active_cn() {
  local id="$1"
  tac "$REGISTRY" | awk -F',' -v id="$id" '
    $1==id && $5=="active" {print $2; exit}
  ' 2>/dev/null
}

registry_id_is_active() {
  local id="$1"
  local st
  st="$(registry_last_status "$id" 2>/dev/null || true)"
  [[ "$st" == "active" ]]
}

append_registry() {
  local id="$1" cn="$2" ttl_hours="$3"
  local created expires
  created="$(now_utc)"
  expires="$(add_hours_utc "$ttl_hours")"
  echo "${id},${cn},${created},${expires},active" >> "$REGISTRY"
}

# Mark ONLY the last ACTIVE record for this ID as revoked (keep history)
mark_revoked_id_last_active() {
  local id="$1"
  local tmp="${REGISTRY}.tmp"
  local total line_to_mark

  total="$(wc -l < "$REGISTRY")"
  line_to_mark="$(tac "$REGISTRY" | awk -F',' -v id="$id" '
    NR==1{next}  # (tac reverses; ignore if header ends up here)
    $1==id && $5=="active" {print NR; exit}
  ' 2>/dev/null || true)"

  [[ -n "${line_to_mark:-}" ]] || return 1

  # Convert "tac line number" back to original file line number:
  # original_line = total - tac_line + 1
  local orig_line=$(( total - line_to_mark + 1 ))

  awk -F',' -v OFS=',' -v n="$orig_line" '
    NR==1 {print; next}
    NR==n {$5="revoked"}
    {print}
  ' "$REGISTRY" > "$tmp" && mv "$tmp" "$REGISTRY"
}

# Backward-compatible alias (old code calls mark_revoked_id)
mark_revoked_id() {
  mark_revoked_id_last_active "$1"
}

show_registry() {
  info "Registry: $REGISTRY (history kept; newest entries are at the bottom)"
  column -s, -t "$REGISTRY" | tail -n 120
}

# ---------- Listing ----------
list_issued_clients() {
  info "Issued clients (issued/*.crt):"
  if [[ -d "$EASYRSA_DIR/pki/issued" ]]; then
    ls -1 "$EASYRSA_DIR/pki/issued" 2>/dev/null | sed 's/\.crt$//' | sort
  else
    warn "Issued directory does not exist."
  fi
}

list_revoked_clients() {
  local idx="$EASYRSA_DIR/pki/index.txt"
  info "Revoked clients (index.txt):"
  [[ -f "$idx" ]] || { warn "index.txt not found ($idx)."; return 0; }
  awk '$1 ~ /^R/ {print $0}' "$idx" || true
}

# ---------- Create / Generate ----------

create_client_only() {
  local name="$1"
  sanitize_name "$name"

  if client_exists "$name"; then
    warn "Client '$name' already exists. Skipping creation."
    return 0
  fi

  info "Creating request (nopass) and signing client certificate (batch)..."
  pushd "$EASYRSA_DIR" >/dev/null

  export EASYRSA_BATCH=1

  ./easyrsa --batch --req-cn="$name" gen-req "$name" nopass
  ./easyrsa --batch sign-req client "$name"

  popd >/dev/null
  ok "Client created: $name"
}

generate_ovpn_only() {
  local name="$1"
  sanitize_name "$name"

  [[ -x "$MAKE_OVPN" ]] || die "make-ovpn.sh is not executable: $MAKE_OVPN"
  client_exists "$name" || die "Client '$name' does not exist (missing crt/key). Create it first."

  info "Generating .ovpn profile..."
  "$MAKE_OVPN" "$name"

  local out; out="$(ovpn_path "$name")"
  [[ -f "$out" ]] && ok "Profile generated: $out" || warn "Could not find $out. Check your make-ovpn.sh output path."
}

create_and_generate_ttl() {
  read -r -p "Client name (CN) [e.g., alex-phone]: " name
  sanitize_name "$name"
  read -r -p "TTL (hours) [e.g., 24]: " ttl
  [[ "$ttl" =~ ^[0-9]+$ && "$ttl" -gt 0 ]] || die "Invalid TTL hours."

  create_client_only "$name"
  generate_ovpn_only "$name"

  # CN-based entry uses id=0 (manual CN). Keeps registry uniform.
  echo "0,${name},$(now_utc),$(add_hours_utc "$ttl"),active" >> "$REGISTRY"
  ok "TTL registered: ${name} expires at $(add_hours_utc "$ttl")"

  echo
  read -r -p "Do you want to export/send the .ovpn now? (y/N): " yn
  if [[ "${yn,,}" == "y" ]]; then
    export_menu "$name"
  fi
}

# ---------- Batch create+ovpn (ID range) ----------
batch_create_range_ttl() {
  read -r -p "Start ID (e.g., 1): " start
  read -r -p "End ID   (e.g., 78): " end
  [[ "$start" =~ ^[0-9]+$ && "$end" =~ ^[0-9]+$ && "$start" -le "$end" ]] || die "Invalid range."

  read -r -p "TTL (hours) for ALL generated profiles [e.g., 24]: " ttl
  [[ "$ttl" =~ ^[0-9]+$ && "$ttl" -gt 0 ]] || die "Invalid TTL hours."

  for i in $(seq "$start" "$end"); do
    local cn; cn="$(printf "vpn-%03d" "$i")"

    if registry_has_id "$i"; then
      warn "ID $i already exists in registry -> skipping ($cn)"
      continue
    fi

    create_client_only "$cn" || { warn "Create failed for $cn"; continue; }
    [[ -f "$EASYRSA_DIR/pki/issued/${cn}.crt" ]] || { warn "No issued crt for $cn -> skipping registry"; continue; }

    generate_ovpn_only "$cn" || { warn "OVPN generation failed for $cn"; continue; }
    [[ -f "$(ovpn_path "$cn")" ]] || { warn "No .ovpn output for $cn -> skipping registry"; continue; }

    append_registry "$i" "$cn" "$ttl"
    ok "Batch OK: ID=$i CN=$cn TTL=${ttl}h"
  done

  ok "Batch complete."
}

# ---------- Revoke ----------
ensure_crl_enabled_hint() {
  if grep -qE '^\s*crl-verify\s+' "$SERVER_CONF"; then
    ok "crl-verify is configured in server.conf."
  else
    warn "crl-verify is NOT set in server.conf."
    echo "  Recommended to add:"
    echo "    crl-verify /etc/openvpn/crl.pem"
  fi
}

_update_crl_and_restart_drop_sessions() {
  # Generate + deploy CRL
  if [[ -f "$EASYRSA_DIR/pki/crl.pem" ]]; then
    cp "$EASYRSA_DIR/pki/crl.pem" "$CRL_DST"
    chmod 644 "$CRL_DST"
    ok "CRL updated at: $CRL_DST"
  else
    warn "crl.pem not found under pki/. Something failed."
  fi

  # Restart to DROP current sessions (you requested “derruba sessão”)
  info "Restarting OpenVPN (drops active sessions)..."
  systemctl restart "$SERVER_UNIT"
  ok "OpenVPN restarted."
  ensure_crl_enabled_hint
}

revoke_client_by_cn_strong_confirm() {
  read -r -p "Client name to revoke (CN): " name
  sanitize_name "$name"

  echo
  warn "IRREVERSIBLE ACTION:"
  echo "  - Client '$name' will be revoked"
  echo "  - A new CRL will be generated and OpenVPN will be restarted (drops sessions)"
  echo
  read -r -p "Type exactly: REVOKE ${name}  (or ENTER to cancel): " confirm
  [[ "$confirm" == "REVOKE ${name}" ]] || { warn "Cancelled."; return 0; }

  info "Revoking '$name' and generating CRL..."
  pushd "$EASYRSA_DIR" >/dev/null
  export EASYRSA_BATCH=1
  ./easyrsa --batch revoke "$name"
  ./easyrsa --batch gen-crl
  popd >/dev/null

  rm -f "$(ovpn_path "$name")" 2>/dev/null || true
  _update_crl_and_restart_drop_sessions
  ok "Client revoked: $name"
}

revoke_by_id_strong_confirm() {
  read -r -p "Client ID to revoke: " id
  [[ "$id" =~ ^[0-9]+$ ]] || die "Invalid ID."

  local cn; cn="$(cn_from_id "$id")"
  [[ -n "$cn" ]] || die "ID $id not found in registry."

  echo
  warn "IRREVERSIBLE ACTION:"
  echo "  - ID: $id"
  echo "  - CN: $cn"
  echo "  - Will revoke + gen-crl + restart OpenVPN (drops sessions)"
  echo
  read -r -p "Type exactly: REVOKE ${id}  (or ENTER to cancel): " confirm
  [[ "$confirm" == "REVOKE ${id}" ]] || { warn "Cancelled."; return 0; }

  info "Revoking '$cn'..."
  pushd "$EASYRSA_DIR" >/dev/null
  export EASYRSA_BATCH=1 
  ./easyrsa --batch revoke "$name"
  ./easyrsa --batch gen-crl
  popd >/dev/null

  rm -f "$(ovpn_path "$cn")" 2>/dev/null || true
  mark_revoked_id "$id"
  _update_crl_and_restart_drop_sessions
  ok "Revoked: ID=$id CN=$cn"
}

revoke_id_range() {
  read -r -p "Start ID: " start
  read -r -p "End ID: " end
  [[ "$start" =~ ^[0-9]+$ && "$end" =~ ^[0-9]+$ && "$start" -le "$end" ]] || die "Invalid range."

  echo
  warn "This will revoke ALL IDs from ${start} to ${end} (if present in registry)."
  read -r -p "Type exactly: REVOKE_RANGE ${start}-${end}  (or ENTER to cancel): " confirm
  [[ "$confirm" == "REVOKE_RANGE ${start}-${end}" ]] || { warn "Cancelled."; return 0; }

  pushd "$EASYRSA_DIR" >/dev/null

  # >>> evita prompts ("Type the word 'yes' ...")
  export EASYRSA_BATCH=1

  for i in $(seq "$start" "$end"); do
    local cn
    cn="$(registry_last_active_cn "$i" || true)"
    if [[ -z "${cn:-}" ]]; then
      warn "ID $i not in registry -> skipping"
      continue
    fi

    info "Revoking ID=$i CN=$cn"
      ./easyrsa --batch revoke "$cn" || { warn "Failed to revoke $cn (maybe already revoked). Continuing..."; continue; }
      mark_revoked_id "$i" || true
      rm -f "$(ovpn_path "$cn")" 2>/dev/null || true
  done

  ./easyrsa --batch gen-crl || die "gen-crl failed"
  popd >/dev/null

  _update_crl_and_restart_drop_sessions
  ok "Range revoke done."
}

# ---------- Connected / logs / health ----------
show_connected() {
  if [[ ! -f "$STATUS_LOG" ]]; then
    warn "Status log does not exist: $STATUS_LOG"
    warn "Add to server.conf:"
    echo '  status /var/log/openvpn/status.log'
    echo '  status-version 2'
    return 0
  fi
  info "Connected clients (status.log):"
  cat "$STATUS_LOG"
}

tail_server_log() {
  info "Tailing OpenVPN logs (CTRL+C to exit)..."
  journalctl -u "$SERVER_UNIT" -f
}

server_health() {
  info "Quick server checks:"
  echo
  systemctl status "$SERVER_UNIT" --no-pager || true
  echo
  ss -lunp | grep -E '(:1194\b)' || warn "1194/udp is not listening."
  ip -br a | grep -E '^tun' || warn "No tun* interface found."
  sysctl net.ipv4.ip_forward || true
  echo
  info "server.conf (relevant lines):"
  grep -nE '^(port|proto|dev|server |push "route|tls-crypt|tls-auth|crl-verify|status )' "$SERVER_CONF" || true
}

# ---------- Export (Telegram / local copy) ----------
export_local_copy() {
  local name="$1"
  local src; src="$(ovpn_path "$name")"
  [[ -f "$src" ]] || die ".ovpn file not found: $src"

  read -r -p "Destination path (e.g., /root/${name}.ovpn): " dst
  [[ -z "$dst" ]] && { warn "Cancelled."; return 0; }

  cp -f "$src" "$dst"
  chmod 600 "$dst"
  ok "Copied to: $dst"
}

export_telegram() {
  local name="$1"
  local src; src="$(ovpn_path "$name")"
  [[ -f "$src" ]] || die ".ovpn file not found: $src"

  local token="${OVPN_TG_BOT_TOKEN:-}"
  local chat="${OVPN_TG_CHAT_ID:-}"

  [[ -n "$token" && -n "$chat" ]] || {
    warn "Telegram variables are not configured."
    echo "  Example in /root/.config/ovpn-menu.env:"
    echo "    export OVPN_TG_BOT_TOKEN='123:ABC...'"
    echo "    export OVPN_TG_CHAT_ID='123456789'"
    return 0
  }

  command -v curl >/dev/null 2>&1 || die "curl not found."

  info "Sending via Telegram (bot)..."
  local resp
  resp="$(curl -sS -X POST "https://api.telegram.org/bot${token}/sendDocument" \
    -F "chat_id=${chat}" \
    -F "caption=OpenVPN profile: ${name}.ovpn" \
    -F "document=@${src}")" || die "Failed to call Telegram API."

  if echo "$resp" | grep -q '"ok":true'; then
    ok "Successfully sent to Telegram."
  else
    warn "Telegram responded, but did not confirm ok=true. Response:"
    echo "$resp"
  fi
}

export_menu() {
  local name="$1"
  local src; src="$(ovpn_path "$name")"
  [[ -f "$src" ]] || die ".ovpn file not found: $src"

  while true; do
    echo
    echo "==== Export ${name}.ovpn ===="
    echo "1) Copy to a local path"
    echo "2) Send via Telegram (bot)"
    echo "0) Back"
    echo
    read -r -p "Choice: " c
    case "$c" in
      1) export_local_copy "$name" ;;
      2) export_telegram "$name" ;;
      0) break ;;
      *) warn "Invalid option." ;;
    esac
  done
}

export_existing_ovpn() {
  read -r -p "Client name (CN) to export: " name
  sanitize_name "$name"
  [[ -f "$(ovpn_path "$name")" ]] || die ".ovpn file not found for $name (generate first)."
  export_menu "$name"
}

# ---------- Main menu ----------
menu() {
  clear
  echo "======================================"
  echo " OpenVPN Community - CLI Menu (v4 TTL)"
  echo "======================================"
  echo "1)  List issued clients"
  echo "2)  Create new client (cert/key)"
  echo "3)  Generate .ovpn profile (existing client)"
  echo "4)  Create client + generate .ovpn + TTL (hours)"
  echo "5)  Revoke client by CN + update CRL + restart (drops sessions)"
  echo "6)  List revoked clients (index.txt)"
  echo "7)  Show connected clients (status.log)"
  echo "8)  Export/send .ovpn (Telegram/Local)"
  echo "9)  Tail server logs (journalctl -f)"
  echo "10) Health check"
  echo "11) Batch: create+ovpn+TTL+registry (ID range -> vpn-001..)"
  echo "12) Show registry (ID -> CN -> expires)"
  echo "13) Revoke by ID (registry) + update CRL + restart (drops sessions)"
  echo "14) Revoke by ID range (registry) + update CRL + restart (drops sessions)"
  echo "0)  Exit"
  echo
}

main() {
  need_root
  require_paths

  while true; do
    menu
    read -r -p "Choice: " choice
    echo
    case "$choice" in
      1)  list_issued_clients; pause ;;
      2)  read -r -p "Client name (CN): " n; create_client_only "$n"; pause ;;
      3)  read -r -p "Client name (CN): " n; generate_ovpn_only "$n"; pause ;;
      4)  create_and_generate_ttl; pause ;;
      5)  revoke_client_by_cn_strong_confirm; pause ;;
      6)  list_revoked_clients; pause ;;
      7)  show_connected; pause ;;
      8)  export_existing_ovpn; pause ;;
      9)  tail_server_log ;;
      10) server_health; pause ;;
      11) batch_create_range_ttl; pause ;;
      12) show_registry; pause ;;
      13) revoke_by_id_strong_confirm; pause ;;
      14) revoke_id_range; pause ;;
      0)  exit 0 ;;
      *)  warn "Invalid option."; pause ;;
    esac
  done
}


if [[ $# -eq 0 ]]; then
    main "$@"
    exit 0
fi

case "$1" in
    "api_list") cat "$REGISTRY" ;;
    "api_connected") show_connected ;;
    "api_health") server_health ;;
    "api_list_revoked") list_revoked_clients ;;
    "api_create")
        create_client_only "$2"
        generate_ovpn_only "$2"
        append_registry "0" "$2" "$3"
        echo "SUCCESS" ;;
    "api_revoke")
        pushd "$EASYRSA_DIR" >/dev/null
        export EASYRSA_BATCH=1
        ./easyrsa --batch revoke "$2"
        ./easyrsa --batch gen-crl
        popd >/dev/null
        # Atualiza o status para 'revoked' no CSV
        sed -i "/,$2,.*,active/s/active/revoked/" "$REGISTRY"
        rm -f "$(ovpn_path "$2")" 2>/dev/null || true
        _update_crl_and_restart_drop_sessions
        echo "REVOKED" ;;
    "api_delete")
        # DELETAR: Remove a linha inteira do CSV para sumir da tabela
        sed -i "/,$2,/d" "$REGISTRY"
        rm -f "$(ovpn_path "$2")" 2>/dev/null || true
        echo "DELETED" ;;
    *) exit 1 ;;
esac
exit 0
