#!/usr/bin/env python3
from functools import wraps
import pyotp
from functools import wraps
import csv
import os
import re
import shutil
import string
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import smtplib
from email.message import EmailMessage
import secrets
import csv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import io
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, session, flash, redirect, render_template, request, send_file, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("OVPN_WEB_SECRET", "change-this-secret")
app.permanent_session_lifetime = timedelta(minutes=10)
EASYRSA_DIR = Path("/etc/openvpn/easy-rsa")
CLIENT_CFG_DIR = Path("/etc/openvpn/client-configs")
MAKE_OVPN = CLIENT_CFG_DIR / "make-ovpn.sh"
OVPN_OUT_DIR = CLIENT_CFG_DIR / "files"
AUTH_DB = Path("/etc/openvpn/auth/users.db")
AUTH_CLIENT_CFG_DIR = Path("/etc/openvpn/client-configs-auth")
MAKE_OVPN_AUTH = AUTH_CLIENT_CFG_DIR / "make-ovpn-auth.sh"
OVPN_AUTH_OUT_DIR = AUTH_CLIENT_CFG_DIR / "files"
REGISTRY = OVPN_OUT_DIR / "registry.csv"
SERVER_UNIT = "openvpn@server"
CRL_DST = Path("/etc/openvpn/crl.pem")
SERVER_CONF = Path("/etc/openvpn/server.conf")
STATUS_LOG = Path("/var/log/openvpn/status.log")
ENV_FILE = Path("/root/.config/ovpn-menu.env")
NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
ID_RE = re.compile(r"^[0-9]+$")
SMTP_HOST = os.environ.get("OVPN_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("OVPN_SMTP_PORT", "465"))
SMTP_USER = os.environ.get("OVPN_SMTP_USER", "")
SMTP_PASS = os.environ.get("OVPN_SMTP_PASS", "")
SMTP_FROM = os.environ.get("OVPN_SMTP_FROM", SMTP_USER)
REGISTRY_FIELDS = ["id", "cn", "type", "email", "status", "created_at", "revoked_at"]
PROTECTED_CNS = {"server", "ca"}

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
def rebuild_registry():
    from datetime import datetime

    registry = []
    next_id = 1

    index_file = Path("/etc/openvpn/easy-rsa/pki/index.txt")
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 6:
                    continue

                status_code = parts[0]
                cn_field = parts[5]

                if "CN=" not in cn_field:
                    continue

                cn = cn_field.split("CN=")[1].strip()

                if cn in {"server", "ca"}:
                    continue

                status = "active" if status_code == "V" else "revoked"

                registry.append({
                    "id": str(next_id),
                    "cn": cn,
                    "type": "Certificate",
                    "email": "",
                    "status": status,
                    "created_at": "",
                    "revoked_at": "",
                })
                next_id += 1

    ovpn_dir = OVPN_OUT_DIR
    if ovpn_dir.exists():
        for f in ovpn_dir.glob("*.ovpn"):
            cn = f.stem.strip()
            if not cn or cn in {"server", "ca"}:
                continue

            if any(r["cn"] == cn for r in registry):
                continue

            access_type = "Certificate"
            email = ""

            try:
                auth_user = get_auth_user(cn)
                if auth_user is not None:
                    access_type = "Certificate + Credentials"
                    email = (auth_user.get("email") or "").strip()
            except Exception:
                pass

            registry.append({
                "id": str(next_id),
                "cn": cn,
                "type": access_type,
                "email": email,
                "status": "active",
                "created_at": "",
                "revoked_at": "",
            })
            next_id += 1

    wg_dir = Path("/etc/wireguard/clients")
    if wg_dir.exists():
        for f in wg_dir.glob("*.conf"):
            cn = f.stem.strip()
            if not cn or cn in {"server", "ca"}:
                continue

            if any(r["cn"] == cn for r in registry):
                continue

            registry.append({
                "id": str(next_id),
                "cn": cn,
                "type": "WireGuard",
                "email": "",
                "status": "active",
                "created_at": "",
                "revoked_at": "",
            })
            next_id += 1

    write_registry_rows(registry)
    return f"{len(registry)} entries rebuilt successfully"
def revoke_wireguard_client(name: str):
    name = sanitize_name(name)

    client_conf = Path(f"/etc/wireguard/clients/{name}.conf")
    client_pub = Path(f"/etc/wireguard/clients/{name}.pub")
    wg_server_conf = Path("/etc/wireguard/wg0.conf")

    if not client_pub.exists():
        raise RuntimeError(f"WireGuard public key not found for {name}.")

    public_key = client_pub.read_text(encoding="utf-8").strip()
    if not public_key:
        raise RuntimeError(f"WireGuard public key is empty for {name}.")

    # Remove peer live from kernel
    run_cmd(["wg", "set", "wg0", "peer", public_key, "remove"])

    # Remove peer block from wg0.conf
    if wg_server_conf.exists():
        lines = wg_server_conf.read_text(encoding="utf-8").splitlines()
        new_lines = []
        i = 0

        while i < len(lines):
            line = lines[i]
            block = [line]

            if line.strip() == "[Peer]":
                j = i + 1
                while j < len(lines) and lines[j].strip() != "[Peer]":
                    block.append(lines[j])
                    j += 1

                block_text = "\n".join(block)
                if public_key in block_text:
                    i = j
                    continue
                else:
                    new_lines.extend(block)
                    i = j
                    continue

            new_lines.append(line)
            i += 1

        wg_server_conf.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")

    # Opcional: remover arquivos do cliente
    for path in [
        Path(f"/etc/wireguard/clients/{name}.conf"),
        Path(f"/etc/wireguard/clients/{name}.key"),
        Path(f"/etc/wireguard/clients/{name}.pub"),
        Path(f"/etc/wireguard/clients/{name}.png"),
    ]:
        if path.exists():
            path.unlink()

    return f"WireGuard client {name} removed."

def is_protected_cn(name: str) -> bool:
    return sanitize_name(name) in PROTECTED_CNS

def rebuild_registry_from_existing_openvpn():
    rows = read_registry_rows()
    existing_cns = {r["cn"] for r in rows}

    imported = 0

    for ovpn_file in OVPN_OUT_DIR.glob("*.ovpn"):
        cn = ovpn_file.stem.strip()

        if not cn or cn in existing_cns:
            continue

        access_type = "Certificate"
        email = ""

        try:
            auth_user = get_auth_user(cn)
            if auth_user is not None:
                access_type = "Certificate + Credentials"
                email = (auth_user.get("email") or "").strip()
        except Exception:
            pass

        add_registry_entry(cn, access_type, email=email)
        imported += 1

    return imported

def ensure_registry_exists():
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)

    if not REGISTRY.exists():
        with REGISTRY.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS)
            writer.writeheader()


def read_registry_rows():
    ensure_registry_exists()

    with REGISTRY.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    normalized = []
    for row in rows:
        normalized.append({
            "id": (row.get("id") or "").strip(),
            "cn": (row.get("cn") or "").strip(),
            "type": (row.get("type") or "").strip(),
            "email": (row.get("email") or "").strip(),
            "status": (row.get("status") or "").strip() or "active",
            "created_at": (row.get("created_at") or "").strip(),
            "revoked_at": (row.get("revoked_at") or "").strip(),
        })

    return normalized


def write_registry_rows(rows):
    ensure_registry_exists()

    with REGISTRY.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def next_registry_id(rows=None):
    if rows is None:
        rows = read_registry_rows()

    ids = []
    for row in rows:
        try:
            ids.append(int(row["id"]))
        except Exception:
            pass

    return str(max(ids, default=0) + 1)


def add_registry_entry(cn: str, access_type: str, email: str = ""):
    cn = sanitize_name(cn)
    rows = read_registry_rows()

    for row in rows:
        if row["cn"] == cn and row["status"] == "active":
            return row

    new_row = {
        "id": next_registry_id(rows),
        "cn": cn,
        "type": access_type,
        "email": (email or "").strip(),
        "status": "active",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "revoked_at": "",
    }

    rows.append(new_row)
    write_registry_rows(rows)
    return new_row


def mark_registry_revoked_by_cn(cn: str):
    cn = sanitize_name(cn)
    rows = read_registry_rows()
    changed = False

    for row in rows:
        if row["cn"] == cn and row["status"] == "active":
            row["status"] = "revoked"
            row["revoked_at"] = datetime.now().isoformat(timespec="seconds")
            changed = True

    if changed:
        write_registry_rows(rows)

    return changed


def mark_registry_revoked_by_id(reg_id):
    reg_id = str(reg_id).strip()
    rows = read_registry_rows()
    changed = False

    for row in rows:
        if row["id"] == reg_id and row["status"] == "active":
            row["status"] = "revoked"
            row["revoked_at"] = datetime.now().isoformat(timespec="seconds")
            changed = True

    if changed:
        write_registry_rows(rows)

    return changed


def get_registry_row_by_id(reg_id):
    reg_id = str(reg_id).strip()
    for row in read_registry_rows():
        if row["id"] == reg_id:
            return row
    return None


def get_latest_active_registry_row_by_cn(cn: str):
    cn = sanitize_name(cn)
    rows = read_registry_rows()
    matches = [r for r in rows if r["cn"] == cn and r["status"] == "active"]

    if not matches:
        return None

    matches.sort(key=lambda r: int(r["id"]) if r["id"].isdigit() else 0, reverse=True)
    return matches[0]


def count_registry_status(status: str):
    return sum(1 for row in read_registry_rows() if row["status"] == status)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.before_request
def refresh_session_timeout():
    public_endpoints = {"login", "static"}

    if request.endpoint in public_endpoints:
        return

    if session.get("logged_in"):
        session.permanent = True
        session.modified = True

def get_client_access_type(name: str) -> str:
    wg_conf = Path(f"/etc/wireguard/clients/{name}.conf")
    if wg_conf.exists():
        return "WireGuard"

    try:
        user = get_auth_user(name)
        if user is not None:
            return "Certificate + Credentials"
    except Exception:
        pass

    return "Certificate"

def reset_auth_user_temporary_password(username: str):
    username = sanitize_name(username)
    user = get_auth_user(username)

    if user is None:
        raise RuntimeError("Auth user not found.")

    if int(user["is_active"]) != 1:
        raise RuntimeError("User is inactive.")

    new_temp_password = generate_temporary_password()

    changed = set_user_password(username, new_temp_password, must_change_password=1)
    if not changed:
        raise RuntimeError("Could not reset temporary password.")

    return new_temp_password

def restart_vpn_and_nginx():
    run_cmd(["systemctl", "restart", SERVER_UNIT], check=False)
    run_cmd(["systemctl", "restart", "nginx"], check=False)
    return f"{SERVER_UNIT} and nginx restarted."

def restart_nginx_service():
    run_cmd(["systemctl", "restart", "nginx"], check=False)
    return "nginx restarted."

def restart_openvpn_service():
    run_cmd(["systemctl", "restart", SERVER_UNIT], check=False)
    return f"{SERVER_UNIT} restarted."

def revoke_client_by_cn_no_restart(name: str):
    name = sanitize_name(name)
    env = {"EASYRSA_BATCH": "1"}

    r1 = run_cmd(["./easyrsa", "--batch", "revoke", name], cwd=EASYRSA_DIR, env=env, check=False)
    if r1.returncode != 0:
        raise RuntimeError(f"Failed to revoke {name}\n\nSTDOUT:\n{r1.stdout}\nSTDERR:\n{r1.stderr}")

    r2 = run_cmd(["./easyrsa", "--batch", "gen-crl"], cwd=EASYRSA_DIR, env=env, check=False)
    if r2.returncode != 0:
        raise RuntimeError(f"Failed to generate CRL\n\nSTDOUT:\n{r2.stdout}\nSTDERR:\n{r2.stderr}")

    src_crl = EASYRSA_DIR / "pki" / "crl.pem"
    if src_crl.exists():
        shutil.copy2(src_crl, CRL_DST)
        os.chmod(CRL_DST, 0o644)

    try:
        ovpn_path(name).unlink(missing_ok=True)
    except TypeError:
        if ovpn_path(name).exists():
            ovpn_path(name).unlink()

    return ensure_crl_enabled_hint()

def send_wireguard_email(to_email: str, username: str, conf_path: Path):
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SMTP is not configured.")

    subject = f"WireGuard VPN Profile - {username}"

    body = f"""
Hello,

Your WireGuard VPN profile has been created.

Username: {username}

Instructions:
- Import the attached .conf file into your WireGuard client
- Activate the tunnel

Server: vpn.marano
"""

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    with open(conf_path, "rb") as f:
        part = MIMEApplication(f.read(), Name=conf_path.name)
        part["Content-Disposition"] = f'attachment; filename="{conf_path.name}"'
        msg.attach(part)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

def create_wireguard_profile(name: str):
    name = sanitize_name(name)

    cmd = ["/usr/local/bin/wg-create-client.sh", name]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())

    conf_path = Path(f"/etc/wireguard/clients/{name}.conf")

    if not conf_path.exists():
        raise RuntimeError("WireGuard config not generated.")

    return {
        "username": name,
        "profile_path": str(conf_path),
    }

def create_auth_profiles_from_csv(file_storage, auto_send_email: bool = True):
    if not file_storage:
        raise RuntimeError("CSV file is required.")

    content = file_storage.read().decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))

    required_columns = {"username", "email"}
    if not reader.fieldnames or not required_columns.issubset(set(reader.fieldnames)):
        raise RuntimeError("CSV must contain: username,email")

    results = []

    for row in reader:
        username = (row.get("username", "") or "").strip()
        email = (row.get("email", "") or "").strip()

        if not username:
            results.append({
                "username": "",
                "email": email,
                "temporary_password": "",
                "profile_path": "",
                "status": "error: missing username",
            })
            continue

        try:
            username = sanitize_name(username)

            if not client_exists(username):
                create_client_only(username)

            temporary_password = create_auth_user(username, email=email)
            out = generate_auth_ovpn_only(username)

            email_status = "not sent"
            if auto_send_email:
                send_profile_email(email, username, temporary_password, out)
                email_status = "sent"

            results.append({
                "username": username,
                "email": email,
                "temporary_password": temporary_password,
                "profile_path": str(out),
                "status": f"created / email {email_status}",
            })

        except Exception as e:
            results.append({
                "username": username,
                "email": email,
                "temporary_password": "",
                "profile_path": "",
                "status": f"error: {e}",
            })

    return results

def create_auth_profiles_batch(prefix: str, start: int, end: int, email_domain: str = ""):
    if start <= 0 or end < start:
        raise RuntimeError("Invalid range.")

    results = []

    for i in range(start, end + 1):
        name = f"{prefix}{i}"
        email = f"{name}@{email_domain}" if email_domain else ""

        try:
            if not client_exists(name):
                create_client_only(name)

            temporary_password = create_auth_user(name, email=email)
            out = generate_auth_ovpn_only(name)
            add_registry_entry(name, "Certificate", email="")
            results.append({
                "username": name,
                "email": email,
                "temporary_password": temporary_password,
                "profile_path": str(out),
                "status": "created",
            })

        except Exception as e:
            results.append({
                "username": name,
                "email": email,
                "temporary_password": "",
                "profile_path": "",
                "status": f"error: {e}",
            })

    return results

def send_auth_profiles_batch_email(results: list[dict]):
    sent = []
    failed = []

    for item in results:
        if item.get("status") != "created":
            failed.append(f"{item['username']} ({item['status']})")
            continue

        email = item.get("email", "").strip()
        if not email:
            failed.append(f"{item['username']} (missing email)")
            continue

        try:
            send_profile_email(
                email,
                item["username"],
                item["temporary_password"],
                Path(item["profile_path"])
            )
            sent.append(item["username"])
        except Exception as e:
            failed.append(f"{item['username']} ({e})")

    return sent, failed

@app.route("/rebuild-registry", methods=["POST"])
@login_required
def rebuild_registry_route():
    try:
        msg = rebuild_registry()
        flash(msg, "ok")
    except Exception as e:
        flash(str(e), "err")
    return redirect(url_for("registry_export_page"))

@app.route("/send-wireguard-email", methods=["POST"])
@login_required
def send_wireguard_email_route():
    try:
        name = sanitize_name(request.form.get("name", ""))
        email = (request.form.get("email") or "").strip()

        if not email:
            raise RuntimeError("Email required.")

        conf_path = Path(f"/etc/wireguard/clients/{name}.conf")
        if not conf_path.exists():
            raise RuntimeError(f"WireGuard config not found for {name}.")

        send_wireguard_email(email, name, conf_path)
        flash(f"WireGuard profile sent by email to {email}.", "ok")

    except Exception as e:
        flash(str(e), "err")

    return redirect(url_for("index"))

@app.route("/create-auth-profile", methods=["GET", "POST"])
@login_required
def create_auth_profile_page():
    if request.method == "GET":
        return render_page(
            "create_auth_profile.html",
            active_page="create_auth_profile",
            created=None
        )

    try:
        name = sanitize_name(request.form.get("name", ""))
        email = (request.form.get("email", "") or "").strip()

        if not client_exists(name):
            create_client_only(name)

        temporary_password = create_auth_user(name, email=email)
        out = generate_auth_ovpn_only(name)
        add_registry_entry(name, "Certificate + Credentials", email=email)

        return render_page(
            "create_auth_profile.html",
            active_page="create_auth_profile",
            created={
                "username": name,
                "temporary_password": temporary_password,
                "profile_path": str(out),
                "email": email,
            }
        )

    except Exception as e:
        flash(str(e), "err")
        return redirect(url_for("create_auth_profile_page"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        otp_code = (request.form.get("otp_code") or "").strip()

        admin_user = os.environ.get("OVPN_ADMIN_USER", "admin")
        admin_pass = os.environ.get("OVPN_ADMIN_PASS", "admin123")
        totp_secret = os.environ.get("OVPN_ADMIN_TOTP_SECRET", "")

        if username != admin_user or password != admin_pass:
            flash("Invalid credentials")
            return render_template("login.html")

        if not totp_secret:
            flash("MFA is not configured.")
            return render_template("login.html")

        totp = pyotp.TOTP(totp_secret)
        if not totp.verify(otp_code, valid_window=1):
            flash("Invalid authentication code")
            return render_template("login.html")

        session.clear()
        session.permanent = True
        session["logged_in"] = True
        session["admin_user"] = username
        return redirect(url_for("index"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/reset-password-resend-telegram", methods=["POST"])
def reset_password_resend_telegram_route():
    try:
        name = sanitize_name(request.form.get("name", ""))

        access_type = get_client_access_type(name)
        if access_type != "Certificate + Credentials":
            raise RuntimeError("This action is only available for Certificate + Credentials clients.")

        temp_password = reset_auth_user_temporary_password(name)
        profile = ovpn_auth_path(name)

        if not profile.exists():
            raise RuntimeError(f"Auth profile not found: {profile}")

        msg = export_telegram_auth(name)
        flash(
            f"Temporary password reset for {name}. {msg} "
            f"Temporary password: {temp_password}",
            "ok"
        )

    except Exception as e:
        flash(str(e), "err")

    return redirect(url_for("index"))

@app.route("/reset-password-resend-email", methods=["POST"])
def reset_password_resend_email_route():
    try:
        name = sanitize_name(request.form.get("name", ""))
        email = (request.form.get("email", "") or "").strip()

        if not email:
            raise RuntimeError("Email address is required.")

        access_type = get_client_access_type(name)
        if access_type != "Certificate + Credentials":
            raise RuntimeError("This action is only available for Certificate + Credentials clients.")

        temp_password = reset_auth_user_temporary_password(name)
        profile = ovpn_auth_path(name)

        if not profile.exists():
            raise RuntimeError(f"Auth profile not found: {profile}")

        send_profile_email(email, name, temp_password, profile)
        flash(f"Temporary password reset and auth profile sent by email to {email}.", "ok")

    except Exception as e:
        flash(str(e), "err")

    return redirect(url_for("index"))

@app.route("/send-email", methods=["POST"])
def send_email_route():
    try:
        name = sanitize_name(request.form.get("name", ""))
        email = (request.form.get("email", "") or "").strip()

        if not email:
            raise RuntimeError("Email address is required.")

        access_type = get_client_access_type(name)

        if access_type == "WireGuard":
            profile = Path(f"/etc/wireguard/clients/{name}.conf")
            send_wireguard_email(email, name, profile)
            flash(f"WireGuard profile sent by email to {email}.", "ok")

        elif access_type == "Certificate + Credentials":
            user = get_auth_user(name)
            if user is None:
                raise RuntimeError("Auth user not found.")

            profile = ovpn_auth_path(name)

            raise RuntimeError(
                "Temporary password is not available for already-issued auth clients from this page. "
                "Use Create VPN Profile for first delivery, or implement a resend flow with reset password."
            )

        else:
            profile = ovpn_path(name)
            send_profile_email(email, name, "", profile)
            flash(f"OpenVPN profile sent by email to {email}.", "ok")

    except Exception as e:
        flash(str(e), "err")

    return redirect(url_for("index"))

@app.route("/restart-openvpn", methods=["POST"])
def restart_openvpn_route():
    try:
        msg = restart_openvpn_service()
        flash(msg, "ok")
    except Exception as e:
        flash(str(e), "err")
    return redirect(request.referrer or url_for("index"))


@app.route("/restart-nginx", methods=["POST"])
def restart_nginx_route():
    try:
        msg = restart_nginx_service()
        flash(msg, "ok")
    except Exception as e:
        flash(str(e), "err")
    return redirect(request.referrer or url_for("index"))


@app.route("/restart-vpn-and-nginx", methods=["POST"])
def restart_vpn_and_nginx_route():
    try:
        msg = restart_vpn_and_nginx()
        flash(msg, "ok")
    except Exception as e:
        flash(str(e), "err")
    return redirect(request.referrer or url_for("index"))

@app.route("/registry-export")
def registry_export_page():
    rows = list(reversed(read_registry_rows()))
    return render_page(
        "registry_export.html",
        active_page="registry_export",
        rows=rows
    )

@app.route("/revoke-access")
def revoke_access_page():
    return render_page("revoke_access.html", active_page="revoke_access")

@app.route("/create-vpn-profile", methods=["GET", "POST"])
def create_vpn_profile_page():
    if request.method == "GET":
        return render_page(
            "create_vpn_profile.html",
            active_page="create_vpn_profile",
            created=None
        )

    try:
        vpn_type = (request.form.get("vpn_type", "") or "").strip()
        name = sanitize_name(request.form.get("name", ""))
        email = (request.form.get("email", "") or "").strip()
        send_email_flag = request.form.get("send_email") == "on"
        send_telegram_flag = request.form.get("send_telegram") == "on"

        created = {
            "vpn_type": vpn_type,
            "username": name,
            "profile_path": "",
            "temporary_password": "",
        }

        if vpn_type == "openvpn_cert":
            if not client_exists(name):
                create_client_only(name)
            out = generate_ovpn_only(name)
            created["profile_path"] = str(out)
            add_registry_entry(name,"Certificate", email=email)
            if send_email_flag:
                if not email:
                    raise RuntimeError("Email is required when 'Send via email' is enabled.")
                send_profile_email(email, name, "", out)

            if send_telegram_flag:
                msg = export_telegram(name)
                flash(msg, "ok")

        elif vpn_type == "openvpn_auth":
            if not client_exists(name):
                create_client_only(name)
            temporary_password = create_auth_user(name, email=email)
            out = generate_auth_ovpn_only(name)

            created["profile_path"] = str(out)
            created["temporary_password"] = temporary_password
            add_registry_entry(name,"Certificate + Credentials", email=email)

            if send_email_flag:
                if not email:
                    raise RuntimeError("Email is required when 'Send via email' is enabled.")
                send_profile_email(email, name, temporary_password, out)

            if send_telegram_flag:
                msg = export_telegram_auth(name)
                flash(msg, "ok")

        elif vpn_type == "wireguard":
            wg_created = create_wireguard_profile(name)
            created["profile_path"] = wg_created["profile_path"]
            add_registry_entry(name, "WireGuard", email=email)
            if send_email_flag:
                if not email:
                    raise RuntimeError("Email is required when 'Send via email' is enabled.")
                send_wireguard_email(email, name, Path(wg_created["profile_path"]))

        else:
            raise RuntimeError("Invalid VPN type.")

        if send_email_flag and email:
            flash(f"Profile sent by email to {email}.", "ok")

        return render_page(
            "create_vpn_profile.html",
            active_page="create_vpn_profile",
            created=created
        )

    except Exception as e:
        flash(str(e) or "Unexpected error while creating VPN profile.", "err")
        return redirect(url_for("create_vpn_profile_page"))

@app.route("/download-wireguard/<name>")
def download_wireguard(name):
    path = Path(f"/etc/wireguard/clients/{name}.conf")

    if not path.exists():
        abort(404)

    return send_file(path, as_attachment=True)

@app.route("/wireguard-qr/<name>")
def wireguard_qr(name):
    try:
        name = sanitize_name(name)
        conf_path = Path(f"/etc/wireguard/clients/{name}.conf")
        png_path = Path(f"/etc/wireguard/clients/{name}.png")

        if not conf_path.exists():
            raise RuntimeError(f"WireGuard config not found: {conf_path}")

        # gera corretamente o PNG
        subprocess.run(
            f"qrencode -o '{png_path}' -t png < '{conf_path}'",
            shell=True,
            check=True
        )

        return send_file(png_path, mimetype="image/png")

    except Exception as e:
        flash(str(e), "err")
        return redirect(url_for("create_wireguard_profile_page"))

@app.route("/create-wireguard-profile", methods=["GET", "POST"])
def create_wireguard_profile_page():
    if request.method == "GET":
        return render_page(
            "create_wireguard_profile.html",
            active_page="wireguard",
            created=None,
        )

    try:
        name = (request.form.get("name", "") or "").strip()
        auto_send_email = request.form.get("auto_send_email") == "on"

        if not name:
            raise RuntimeError("Name is required.")

        created = create_wireguard_profile(name)

        if auto_send_email:
            email = request.form.get("email", "").strip()
            if email:
                send_wireguard_email(email, name, Path(created["profile_path"]))

        return render_page(
            "create_wireguard_profile.html",
            active_page="wireguard",
            created=created,
        )

    except Exception as e:
        flash(str(e), "err")
        return redirect(url_for("create_wireguard_profile_page"))

@app.route("/batch-auth-profiles-csv", methods=["GET", "POST"])
def batch_auth_profiles_csv_page():
    if request.method == "GET":
        return render_page(
            "batch_auth_profiles_csv.html",
            active_page="batch_auth_profiles_csv",
            results=None,
        )

    try:
        csv_file = request.files.get("csv_file")
        auto_send_email = request.form.get("auto_send_email") == "on"

        results = create_auth_profiles_from_csv(csv_file, auto_send_email=auto_send_email)

        return render_page(
            "batch_auth_profiles_csv.html",
            active_page="batch_auth_profiles_csv",
            results=results,
        )

    except Exception as e:
        flash(str(e), "err")
        return redirect(url_for("batch_auth_profiles_csv_page"))

@app.route("/batch-auth-profiles", methods=["GET", "POST"])
def batch_auth_profiles_page():
    if request.method == "GET":
        return render_page(
            "batch_auth_profiles.html",
            active_page="batch_auth_profiles",
            results=None,
            sent=None,
            failed=None,
        )

    try:
        prefix = (request.form.get("prefix", "") or "").strip()
        start = int(request.form.get("start", "0"))
        end = int(request.form.get("end", "0"))
        email_domain = (request.form.get("email_domain", "") or "").strip()
        auto_send_email = request.form.get("auto_send_email") == "on"

        if not prefix:
            raise RuntimeError("Prefix is required.")

        results = create_auth_profiles_batch(prefix, start, end, email_domain=email_domain)

        sent = []
        failed = []

        if auto_send_email:
            sent, failed = send_auth_profiles_batch_email(results)

        return render_page(
            "batch_auth_profiles.html",
            active_page="batch_auth_profiles",
            results=results,
            sent=sent,
            failed=failed,
        )

    except Exception as e:
        flash(str(e), "err")
        return redirect(url_for("batch_auth_profiles_page"))

def send_profile_email(to_email: str, username: str, temporary_password: str, ovpn_file: Path):
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SMTP is not configured. Set OVPN_SMTP_USER and OVPN_SMTP_PASS.")

    if not ovpn_file.exists():
        raise RuntimeError(f"Profile not found: {ovpn_file}")

    msg = EmailMessage()
    msg["Subject"] = f"VPN profile for {username}"
    msg["From"] = SMTP_FROM
    msg["To"] = to_email

    password_block = ""
    if temporary_password:
        password_block = f"""
Temporary password: {temporary_password}

Important:
- This is a temporary password
- Change it before using the certificate + password VPN mode
"""

    msg.set_content(
        f"""Hello,

Your VPN access profile has been created.

Username: {username}
{password_block}
Regards,
VPN Admin
"""
    )

    with ovpn_file.open("rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="octet-stream",
            filename=ovpn_file.name
        )

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)

def export_telegram_auth(name: str):
    name = sanitize_name(name)
    src = ovpn_auth_path(name)

    if not src.exists():
        raise RuntimeError(f"Auth .ovpn file not found: {src}")

    token = os.environ.get("OVPN_TG_BOT_TOKEN", "")
    chat = os.environ.get("OVPN_TG_CHAT_ID", "")

    if not token or not chat:
        raise RuntimeError("OVPN_TG_BOT_TOKEN / OVPN_TG_CHAT_ID not configured.")

    r = run_cmd([
        "curl", "-sS", "-X", "POST", f"https://api.telegram.org/bot{token}/sendDocument",
        "-F", f"chat_id={chat}",
        "-F", f"caption=OpenVPN auth profile: {name}.ovpn",
        "-F", f"document=@{src}",
    ], check=False)

    if r.returncode != 0:
        raise RuntimeError(f"Failed to send auth profile via Telegram.\n\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")

    return f"{name}.ovpn sent via Telegram."

def generate_temp_password(length=12):
    alphabet = string.ascii_letters + string.digits + "!@#$%*-_"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def create_auth_profile(username):
    password = generate_temp_password()

    # 1. criar usuário
    from app import create_auth_user
    create_auth_user(username, password)

    # 2. gerar certificado + ovpn
    subprocess.run(
        ["/etc/openvpn/client-configs-auth/make-ovpn-auth.sh", username],
        check=True
    )

    ovpn_path = f"/etc/openvpn/client-configs-auth/files/{username}.ovpn"

    return {
        "username": username,
        "password": password,
        "ovpn_path": ovpn_path
    }

def create_auth_user(username: str, email: str = "", temporary_password: str | None = None):
    username = sanitize_name(username)
    temporary_password = temporary_password or generate_temporary_password()

    if get_auth_user(username) is not None:
        raise RuntimeError(f"Auth user '{username}' already exists.")

    conn = auth_db_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cur.execute("""
        INSERT INTO users (username, password_hash, email, must_change_password, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        username,
        generate_password_hash(temporary_password),
        email,
        1,
        1,
        now,
        now
    ))
    conn.commit()
    conn.close()

    return temporary_password

def ovpn_auth_path(name: str) -> Path:
    return OVPN_AUTH_OUT_DIR / f"{name}.ovpn"

def generate_auth_ovpn_only(name: str):
    name = sanitize_name(name)

    if not MAKE_OVPN_AUTH.exists():
        raise RuntimeError(f"Script not found: {MAKE_OVPN_AUTH}")
    if not os.access(MAKE_OVPN_AUTH, os.X_OK):
        raise RuntimeError(f"Script is not executable: {MAKE_OVPN_AUTH}")
    if not client_crt(name).exists():
        raise RuntimeError(f"Client certificate not found: {client_crt(name)}")
    if not client_key(name).exists():
        raise RuntimeError(f"Client private key not found: {client_key(name)}")

    r = run_cmd([str(MAKE_OVPN_AUTH), name], check=False)
    if r.returncode != 0:
        raise RuntimeError(
            f"Failed to generate auth .ovpn for {name}\n\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        )

    out = ovpn_auth_path(name)
    if not out.exists():
        raise RuntimeError(f"Generated file not found: {out}")

    return out

def generate_temporary_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%*-_"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in "!@#$%*-_" for c in password)
        ):
            return password
def auth_db_conn():
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    return conn

def get_auth_user(username: str):
    conn = auth_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, username, email, must_change_password, is_active, created_at, updated_at
        FROM users
        WHERE username = ?
    """, (username,))
    row = cur.fetchone()
    conn.close()
    return row

def verify_auth_user_password(username: str, password: str) -> bool:
    conn = auth_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT password_hash, is_active
        FROM users
        WHERE username = ?
    """, (username,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return False

    if int(row["is_active"]) != 1:
        return False

    return check_password_hash(row["password_hash"], password)

def set_user_password(username: str, new_password: str, must_change_password: int = 0):
    conn = auth_db_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute("""
        UPDATE users
        SET password_hash = ?, must_change_password = ?, updated_at = ?
        WHERE username = ?
    """, (generate_password_hash(new_password), must_change_password, now, username))
    conn.commit()
    changed = cur.rowcount
    conn.close()
    return changed > 0

@app.route("/download-auth/<name>")
def download_auth_ovpn(name):
    try:
        name = sanitize_name(name)
        path = ovpn_auth_path(name)
        if not path.exists():
            raise RuntimeError(f"Auth profile not found: {path}")
        return send_file(path, as_attachment=True, download_name=path.name)
    except Exception as e:
        flash(str(e), "err")
        return redirect(url_for("create_auth_profile_page"))

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
@login_required
def index():
    registry_rows = read_registry_rows()
    active_rows = [r for r in registry_rows if (r.get("status") or "").strip() == "active"]

    active_reg = count_registry_status("active")
    revoked_reg = count_registry_status("revoked")
    ovpn_count = len(list(OVPN_OUT_DIR.glob("*.ovpn")))

    revoked_lines = list_revoked_clients_raw().splitlines()
    revoked_count = 0 if revoked_lines == ["No revoked clients found."] else len(revoked_lines)

    connected_clients = parse_connected_clients()
    connected_names = {c["common_name"] for c in connected_clients if c.get("common_name")}
    connected_now = len(connected_clients)

    client_rows = []

    for row in active_rows:
        c = (row.get("cn") or "").strip()
        access_type = (row.get("type") or "").strip() or get_client_access_type(c)
        row_email = (row.get("email") or "").strip()

        if access_type == "WireGuard":
            crt = "missing"
            key = "missing"
            ovpn = "ok" if Path(f"/etc/wireguard/clients/{c}.conf").exists() else "missing"
            online = False
        else:
            crt = "ok" if client_crt(c).exists() else "missing"
            key = "ok" if client_key(c).exists() else "missing"
            ovpn = "ok" if ovpn_path(c).exists() else "missing"
            online = c in connected_names

            if not row_email:
                try:
                    auth_user = get_auth_user(c)
                    if auth_user is not None and auth_user["email"]:
                        row_email = auth_user["email"]
                except Exception:
                    pass

        client_rows.append({
            "name": c,
            "crt": crt,
            "key": key,
            "ovpn": ovpn,
            "online": online,
            "email": row_email,
            "access_type": access_type,
            "registry_id": (row.get("id") or "").strip(),
        })

    kpis = [
        {"label": "Issued clients", "value": len(active_rows)},
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
        add_registry_entry(name, "Certificate", email="")
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
@login_required
def revoke_cn_route():
    try:
        name = sanitize_name(request.form.get("name", ""))
        restart_now = (request.form.get("restart_now", "no") or "no").strip().lower()

        access_type = get_client_access_type(name)

        if access_type == "WireGuard":
            msg = revoke_wireguard_client(name)
            mark_registry_revoked_by_cn(name)
            flash(msg, "warn")
            return redirect(url_for("index"))

        hint = revoke_client_by_cn_no_restart(name)
        mark_registry_revoked_by_cn(name)

        if restart_now == "yes":
            restart_msg = restart_openvpn_service()
            flash(f"Client {name} revoked. {hint} {restart_msg}", "warn")
        else:
            flash(
                f"Client {name} revoked. CRL updated, but OpenVPN was NOT restarted yet. {hint}",
                "warn"
            )

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

@app.route("/send-auth-telegram", methods=["POST"])
def send_auth_telegram_route():
    try:
        name = sanitize_name(request.form.get("name", ""))
        msg = export_telegram_auth(name)
        flash(msg, "ok")
    except Exception as e:
        flash(str(e), "err")
    return redirect(url_for("create_auth_profile_page"))

@app.route("/send-auth-email", methods=["POST"])
def send_auth_email_route():
    try:
        name = sanitize_name(request.form.get("name", ""))
        email = (request.form.get("email", "") or "").strip()
        temporary_password = request.form.get("temporary_password", "")

        if not email:
            raise RuntimeError("Email address is required.")

        profile = ovpn_auth_path(name)
        send_profile_email(email, name, temporary_password, profile)
        flash(f"Auth profile sent by email to {email}.", "ok")

    except Exception as e:
        flash(str(e), "err")

    return redirect(url_for("create_auth_profile_page"))

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
        mark_registry_revoked_by_id(reg_id)
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

@app.route("/change-password", methods=["GET", "POST"])
def change_password_page():
    if request.method == "GET":
        return render_page("change_password.html", active_page="change_password")

    try:
        username = (request.form.get("username", "") or "").strip()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not current_password or not new_password or not confirm_password:
            raise RuntimeError("All fields are required.")

        if new_password != confirm_password:
            raise RuntimeError("New password and confirmation do not match.")

        if len(new_password) < 10:
            raise RuntimeError("New password must have at least 10 characters.")

        user = get_auth_user(username)
        if user is None:
            raise RuntimeError("User not found.")

        if int(user["is_active"]) != 1:
            raise RuntimeError("User is inactive.")

        if not verify_auth_user_password(username, current_password):
            raise RuntimeError("Invalid temporary password.")

        changed = set_user_password(username, new_password, must_change_password=0)
        if not changed:
            raise RuntimeError("Password could not be updated.")

        flash("Password changed successfully. You may now use the certificate + password VPN profile.", "ok")
        return redirect(url_for("change_password_page"))

    except Exception as e:
        flash(str(e), "err")
        return redirect(url_for("change_password_page"))
if __name__ == "__main__":
    require_paths()
    app.run(host="127.0.0.1", port=8080, debug=False)
