#!/usr/bin/env python3
import csv
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_file, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("OVPN_WEB_SECRET", "change-this-secret")

EASYRSA_DIR = Path("/etc/openvpn/easy-rsa")
CLIENT_CFG_DIR = Path("/etc/openvpn/client-configs")
MAKE_OVPN = CLIENT_CFG_DIR / "make-ovpn.sh"
OVPN_OUT_DIR = CLIENT_CFG_DIR / "files"

REGISTRY = OVPN_OUT_DIR / "registry.csv"
SERVER_UNIT = "openvpn@server"
CRL_DST = Path("/etc/openvpn/crl.pem")
SERVER_CONF = Path("/etc/openvpn/server.conf")
STATUS_LOG = Path("/var/log/openvpn/status.log")
ENV_FILE = Path("/root/.config/ovpn-menu.env")

NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
ID_RE = re.compile(r"^[0-9]+$")

if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or not line.startswith("export "):
            continue
        try:
            key, value = line.replace("export ", "", 1).split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        except ValueError:
            pass


def parse_connected_clients():
    if not STATUS_LOG.exists():
        return []

    clients = []
    for raw_line in STATUS_LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("CLIENT_LIST,"):
            parts = line.split(",")
        elif line.startswith("CLIENT_LIST\t"):
            parts = line.split("\t")
        else:
            continue

        clients.append(
            {
                "common_name": parts[1] if len(parts) > 1 else "",
                "real_address": parts[2] if len(parts) > 2 else "",
                "virtual_address": parts[3] if len(parts) > 3 else "",
                "bytes_received": parts[5] if len(parts) > 5 else "",
                "bytes_sent": parts[6] if len(parts) > 6 else "",
                "connected_since": parts[7] if len(parts) > 7 else "",
                "cipher": parts[12] if len(parts) > 12 else "",
            }
        )

    return clients


def get_connected_names():
    return {c["common_name"] for c in parse_connected_clients() if c.get("common_name")}


def format_bytes(value):
    try:
        num = int(value)
    except Exception:
        return value

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024


def render_page(template_name: str, *, active_page: str = "", **context):
    return render_template(template_name, active_page=active_page, **context)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_hours_utc(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.fullmatch(name):
        raise ValueError("Invalid name. Use only [a-zA-Z0-9_.-].")
    return name


def sanitize_id(raw: str) -> int:
    raw = (raw or "").strip()
    if not ID_RE.fullmatch(raw):
        raise ValueError("Invalid ID.")
    return int(raw)


def run_cmd(cmd, cwd=None, env=None, check=True):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=merged,
        text=True,
        capture_output=True,
        check=check,
    )


def require_paths():
    if not EASYRSA_DIR.is_dir():
        raise RuntimeError(f"Easy-RSA not found at: {EASYRSA_DIR}")
    if not (EASYRSA_DIR / "easyrsa").exists():
        raise RuntimeError(f"easyrsa not found at: {EASYRSA_DIR / 'easyrsa'}")
    OVPN_OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not REGISTRY.exists():
        REGISTRY.write_text("id,cn,created_at,expires_at,status\n", encoding="utf-8")


def client_crt(name: str) -> Path:
    return EASYRSA_DIR / "pki" / "issued" / f"{name}.crt"


def client_key(name: str) -> Path:
    return EASYRSA_DIR / "pki" / "private" / f"{name}.key"


def client_exists(name: str) -> bool:
    return client_crt(name).exists() and client_key(name).exists()


def ovpn_path(name: str) -> Path:
    return OVPN_OUT_DIR / f"{name}.ovpn"


def list_issued_clients():
    issued_dir = EASYRSA_DIR / "pki" / "issued"
    if not issued_dir.exists():
        return []
    return sorted(p.stem for p in issued_dir.glob("*.crt"))


def list_revoked_clients_raw():
    idx = EASYRSA_DIR / "pki" / "index.txt"
    if not idx.exists():
        return "index.txt not found."
    lines = [line for line in idx.read_text(encoding="utf-8", errors="ignore").splitlines() if line.startswith("R")]
    return "\n".join(lines) if lines else "No revoked clients found."


def show_connected_raw():
    if not STATUS_LOG.exists():
        return "status.log not found. Add this to server.conf:\nstatus /var/log/openvpn/status.log\nstatus-version 2"
    return STATUS_LOG.read_text(encoding="utf-8", errors="ignore")


def server_health():
    commands = [
        ["systemctl", "status", SERVER_UNIT, "--no-pager"],
        ["ss", "-lunp"],
        ["ip", "-br", "a"],
        ["sysctl", "net.ipv4.ip_forward"],
        ["ls", "-l", str(MAKE_OVPN)],
        ["ls", "-ld", str(OVPN_OUT_DIR)],
    ]
    blocks = []
    for cmd in commands:
        res = run_cmd(cmd, check=False)
        blocks.append(f"$ {' '.join(cmd)}\n{res.stdout}{res.stderr}")
    if SERVER_CONF.exists():
        relevant = []
        for i, line in enumerate(SERVER_CONF.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            if re.match(r'^(port|proto|dev|server |push "route|tls-crypt|tls-auth|crl-verify|status )', line):
                relevant.append(f"{i}:{line}")
        blocks.append("$ server.conf\n" + ("\n".join(relevant) if relevant else "No relevant lines found."))
    return "\n\n".join(blocks)


def read_registry_rows():
    require_paths()
    rows = []
    with REGISTRY.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append(row)
    return rows


def append_registry(id_value: int, cn: str, ttl_hours: int):
    with REGISTRY.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([id_value, cn, now_utc(), add_hours_utc(ttl_hours), "active"])


def registry_last_record(id_value: int):
    found = None
    for row in read_registry_rows():
        if row["id"] == str(id_value):
            found = row
    return found


def registry_last_active_cn(id_value: int):
    rows = read_registry_rows()
    for row in reversed(rows):
        if row["id"] == str(id_value) and row["status"] == "active":
            return row["cn"]
    return None


def mark_revoked_id_last_active(id_value: int):
    rows = read_registry_rows()
    changed = False
    for i in range(len(rows) - 1, -1, -1):
        if rows[i]["id"] == str(id_value) and rows[i]["status"] == "active":
            rows[i]["status"] = "revoked"
            changed = True
            break
    if not changed:
        return False
    with REGISTRY.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "cn", "created_at", "expires_at", "status"])
        writer.writeheader()
        writer.writerows(rows)
    return True


def create_client_only(name: str):
    name = sanitize_name(name)
    if client_exists(name):
        return f"Client '{name}' already exists."
    env = {"EASYRSA_BATCH": "1"}
    r1 = run_cmd(
        ["./easyrsa", "--batch", f"--req-cn={name}", "gen-req", name, "nopass"],
        cwd=EASYRSA_DIR,
        env=env,
        check=False,
    )
    if r1.returncode != 0:
        raise RuntimeError(f"Failed to generate request/key for {name}\n\nSTDOUT:\n{r1.stdout}\nSTDERR:\n{r1.stderr}")

    r2 = run_cmd(
        ["./easyrsa", "--batch", "sign-req", "client", name],
        cwd=EASYRSA_DIR,
        env=env,
        check=False,
    )
    if r2.returncode != 0:
        raise RuntimeError(f"Failed to sign certificate for {name}\n\nSTDOUT:\n{r2.stdout}\nSTDERR:\n{r2.stderr}")

    return f"Client created: {name}"


def generate_ovpn_only(name: str):
    name = sanitize_name(name)
    if not MAKE_OVPN.exists():
        raise RuntimeError(f"Script not found: {MAKE_OVPN}")
    if not os.access(MAKE_OVPN, os.X_OK):
        raise RuntimeError(f"Script is not executable: {MAKE_OVPN}")
    if not client_crt(name).exists():
        raise RuntimeError(f"Certificate not found: {client_crt(name)}")
    if not client_key(name).exists():
        raise RuntimeError(f"Private key not found: {client_key(name)}")

    r = run_cmd([str(MAKE_OVPN), name], check=False)
    if r.returncode != 0:
        raise RuntimeError(
            f"Failed to generate .ovpn for {name}\n\nCommand: {MAKE_OVPN} {name}\n\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        )
    out = ovpn_path(name)
    if not out.exists():
        raise RuntimeError(
            f"make-ovpn.sh finished, but the file did not appear at:\n{out}\n\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        )
    return out


def export_telegram(name: str):
    name = sanitize_name(name)
    src = ovpn_path(name)
    if not src.exists():
        raise RuntimeError(f".ovpn file not found: {src}")
    token = os.environ.get("OVPN_TG_BOT_TOKEN", "")
    chat = os.environ.get("OVPN_TG_CHAT_ID", "")
    if not token or not chat:
        raise RuntimeError("OVPN_TG_BOT_TOKEN / OVPN_TG_CHAT_ID not configured in /root/.config/ovpn-menu.env")
    r = run_cmd(
        [
            "curl",
            "-sS",
            "-X",
            "POST",
            f"https://api.telegram.org/bot{token}/sendDocument",
            "-F",
            f"chat_id={chat}",
            "-F",
            f"caption=OpenVPN profile: {name}.ovpn",
            "-F",
            f"document=@{src}",
        ],
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Failed to send to Telegram.\n\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")
    return f"{name}.ovpn sent to Telegram."


def ensure_crl_enabled_hint():
    if SERVER_CONF.exists() and re.search(r"^\s*crl-verify\s+", SERVER_CONF.read_text(encoding="utf-8", errors="ignore"), re.M):
        return "crl-verify is configured in server.conf."
    return "crl-verify is NOT configured in server.conf. Recommended: crl-verify /etc/openvpn/crl.pem"


def update_crl_and_restart_drop_sessions():
    src_crl = EASYRSA_DIR / "pki" / "crl.pem"
    if src_crl.exists():
        shutil.copy2(src_crl, CRL_DST)
        os.chmod(CRL_DST, 0o644)
    run_cmd(["systemctl", "restart", SERVER_UNIT], check=False)
    return ensure_crl_enabled_hint()


def revoke_client_by_cn(name: str):
    name = sanitize_name(name)
    env = {"EASYRSA_BATCH": "1"}
    r1 = run_cmd(["./easyrsa", "--batch", "revoke", name], cwd=EASYRSA_DIR, env=env, check=False)
    if r1.returncode != 0:
        raise RuntimeError(f"Failed to revoke {name}\n\nSTDOUT:\n{r1.stdout}\nSTDERR:\n{r1.stderr}")

    r2 = run_cmd(["./easyrsa", "--batch", "gen-crl"], cwd=EASYRSA_DIR, env=env, check=False)
    if r2.returncode != 0:
        raise RuntimeError(f"Failed to generate CRL\n\nSTDOUT:\n{r2.stdout}\nSTDERR:\n{r2.stderr}")

    try:
        ovpn_path(name).unlink(missing_ok=True)
    except TypeError:
        if ovpn_path(name).exists():
            ovpn_path(name).unlink()

    return update_crl_and_restart_drop_sessions()


def revoke_by_id(id_value: int):
    cn = registry_last_active_cn(id_value)
    if not cn:
        raise RuntimeError(f"ID {id_value} not found as active in the registry.")
    hint = revoke_client_by_cn(cn)
    mark_revoked_id_last_active(id_value)
    return cn, hint


def revoke_id_range(start: int, end: int):
    env = {"EASYRSA_BATCH": "1"}
    revoked = []
    skipped = []
    for id_value in range(start, end + 1):
        cn = registry_last_active_cn(id_value)
        if not cn:
            skipped.append(str(id_value))
            continue
        r = run_cmd(["./easyrsa", "--batch", "revoke", cn], cwd=EASYRSA_DIR, env=env, check=False)
        if r.returncode != 0:
            skipped.append(f"{id_value}:{cn}")
            continue
        mark_revoked_id_last_active(id_value)
        try:
            ovpn_path(cn).unlink(missing_ok=True)
        except TypeError:
            if ovpn_path(cn).exists():
                ovpn_path(cn).unlink()
        revoked.append(f"{id_value}:{cn}")

    r2 = run_cmd(["./easyrsa", "--batch", "gen-crl"], cwd=EASYRSA_DIR, env=env, check=False)
    if r2.returncode != 0:
        raise RuntimeError(f"Failed to generate CRL\n\nSTDOUT:\n{r2.stdout}\nSTDERR:\n{r2.stderr}")

    hint = update_crl_and_restart_drop_sessions()
    return revoked, skipped, hint


@app.before_request
def startup_check():
    require_paths()


@app.route("/")
def index():
    clients = list_issued_clients()
    registry_rows = read_registry_rows()
    active_reg = sum(1 for r in registry_rows if r["status"] == "active")
    revoked_reg = sum(1 for r in registry_rows if r["status"] == "revoked")
    ovpn_count = len(list(OVPN_OUT_DIR.glob("*.ovpn")))
    revoked_lines = list_revoked_clients_raw().splitlines()
    revoked_count = 0 if revoked_lines == ["No revoked clients found."] else len(revoked_lines)

    connected_clients = parse_connected_clients()
    connected_names = {c["common_name"] for c in connected_clients if c.get("common_name")}
    connected_now = len(connected_clients)

    client_rows = []
    for c in clients:
        client_rows.append(
            {
                "name": c,
                "crt": "ok" if client_crt(c).exists() else "missing",
                "key": "ok" if client_key(c).exists() else "missing",
                "ovpn": "ok" if ovpn_path(c).exists() else "missing",
                "online": c in connected_names,
            }
        )

    kpis = [
        {"label": "Issued clients", "value": len(clients)},
        {"label": "Generated profiles", "value": ovpn_count},
        {"label": "Connected", "value": connected_now},
        {"label": "Active registry entries", "value": active_reg},
        {"label": "Revoked registry entries", "value": revoked_reg},
        {"label": "Revoked in CA", "value": revoked_count},
    ]

    return render_page(
        "index.html",
        active_page="index",
        kpis=kpis,
        client_rows=client_rows,
    )


@app.route("/create-client", methods=["POST"])
def create_client_route():
    try:
        name = sanitize_name(request.form.get("name", ""))
        msg = create_client_only(name)
        flash(msg, "ok")
    except Exception as e:
        flash(str(e), "err")
    return redirect(url_for("index"))


@app.route("/generate-ovpn", methods=["POST"])
def generate_ovpn_route():
    try:
        name = sanitize_name(request.form.get("name", ""))
        out = generate_ovpn_only(name)
        return send_file(out, as_attachment=True, download_name=out.name)
    except Exception as e:
        flash(str(e), "err")
        return redirect(url_for("index"))


@app.route("/create-generate-ttl", methods=["POST"])
def create_generate_ttl_route():
    try:
        name = sanitize_name(request.form.get("name", ""))
        ttl = int(request.form.get("ttl", "0"))
        if ttl <= 0:
            raise RuntimeError("Invalid validity period.")
        create_client_only(name)
        out = generate_ovpn_only(name)
        append_registry(0, name, ttl)
        flash(f"Client {name} created, .ovpn generated, and validity recorded until {add_hours_utc(ttl)}", "ok")
        return send_file(out, as_attachment=True, download_name=out.name)
    except Exception as e:
        flash(str(e), "err")
        return redirect(url_for("index"))


@app.route("/revoke-cn", methods=["POST"])
def revoke_cn_route():
    try:
        name = sanitize_name(request.form.get("name", ""))
        hint = revoke_client_by_cn(name)
        flash(f"Client {name} revoked. {hint}", "warn")
    except Exception as e:
        flash(str(e), "err")
    return redirect(url_for("index"))


@app.route("/revoked")
def revoked_page():
    data = list_revoked_clients_raw()
    return render_page("revoked.html", active_page="revoked", data=data)


@app.route("/connected")
def connected_page():
    clients = parse_connected_clients()
    rows = []
    for c in clients:
        rows.append(
            {
                "common_name": c.get("common_name", "-") or "-",
                "real_address": c.get("real_address", "-") or "-",
                "virtual_address": c.get("virtual_address", "-") or "-",
                "rx": format_bytes(c.get("bytes_received", "0")),
                "tx": format_bytes(c.get("bytes_sent", "0")),
                "connected_since": c.get("connected_since", "-") or "-",
                "cipher": c.get("cipher", "-") or "-",
            }
        )
    return render_page("connected.html", active_page="connected", clients=rows)


@app.route("/send-telegram", methods=["POST"])
def send_telegram_route():
    try:
        name = sanitize_name(request.form.get("name", ""))
        msg = export_telegram(name)
        flash(msg, "ok")
    except Exception as e:
        flash(str(e), "err")
    return redirect(url_for("index"))


@app.route("/download-form")
def download_ovpn_by_form():
    try:
        name = sanitize_name(request.args.get("name", ""))
        return redirect(url_for("download_ovpn", name=name))
    except Exception as e:
        flash(str(e), "err")
        return redirect(url_for("index"))


@app.route("/download/<name>")
def download_ovpn(name):
    try:
        name = sanitize_name(name)
        path = ovpn_path(name)
        if not path.exists():
            raise RuntimeError(f"File not found: {path}")
        return send_file(path, as_attachment=True, download_name=path.name)
    except Exception as e:
        flash(str(e), "err")
        return redirect(url_for("index"))


@app.route("/logs")
def logs_page():
    res = run_cmd(["journalctl", "-u", SERVER_UNIT, "-n", "150", "--no-pager"], check=False)
    data = res.stdout or res.stderr or "No output."
    return render_page("logs.html", active_page="logs", data=data)


@app.route("/health")
def health_page():
    data = server_health()
    return render_page("health.html", active_page="health", data=data)


@app.route("/batch-create", methods=["POST"])
def batch_create_route():
    try:
        start = int(request.form.get("start", "0"))
        end = int(request.form.get("end", "0"))
        ttl = int(request.form.get("ttl", "0"))
        if start <= 0 or end < start or ttl <= 0:
            raise RuntimeError("Invalid range or validity period.")

        results = []
        for i in range(start, end + 1):
            cn = f"vpn-{i:03d}"
            last = registry_last_record(i)
            if last:
                results.append(f"ID {i} already exists in the registry -> skip ({cn})")
                continue
            create_client_only(cn)
            generate_ovpn_only(cn)
            append_registry(i, cn, ttl)
            results.append(f"OK: ID={i} CN={cn} TTL={ttl}h")

        flash("Batch completed:\n" + "\n".join(results[-40:]), "ok")
    except Exception as e:
        flash(str(e), "err")
    return redirect(url_for("index"))


@app.route("/registry")
def registry_page():
    rows = list(reversed(read_registry_rows()))
    return render_page("registry.html", active_page="registry", rows=rows)


@app.route("/registry/download")
def download_registry():
    return send_file(REGISTRY, as_attachment=True, download_name="registry.csv")


@app.route("/revoke-id", methods=["POST"])
def revoke_id_route():
    try:
        id_value = sanitize_id(request.form.get("id", ""))
        cn, hint = revoke_by_id(id_value)
        flash(f"ID {id_value} / CN {cn} revoked. {hint}", "warn")
    except Exception as e:
        flash(str(e), "err")
    return redirect(url_for("index"))


@app.route("/revoke-range", methods=["POST"])
def revoke_range_route():
    try:
        start = int(request.form.get("start", "0"))
        end = int(request.form.get("end", "0"))
        if start <= 0 or end < start:
            raise RuntimeError("Invalid range.")
        revoked, skipped, hint = revoke_id_range(start, end)
        flash(
            "Range processed.\n"
            f"Revoked: {', '.join(revoked) if revoked else 'none'}\n"
            f"Skipped/failures: {', '.join(skipped) if skipped else 'none'}\n"
            f"{hint}",
            "warn",
        )
    except Exception as e:
        flash(str(e), "err")
    return redirect(url_for("index"))


if __name__ == "__main__":
    require_paths()
    app.run(host="127.0.0.1", port=8080, debug=False)
