# Marano Secure Access (MSA)

<p align="center">
  <img src="docs/images/cover.png" width="900"/>
</p>

<p align="center">
  <b>Self-hosted secure access platform with OpenVPN, WireGuard, MFA and full lifecycle control</b>
</p>

---

## ⚡ Highlights

- 🔐 MFA (2FA) for administrative access  
- 🌐 OpenVPN + WireGuard support  
- 🧠 Registry-based lifecycle management  
- 📦 Profile delivery (Download / Email / Telegram)  
- ⚙️ CLI + Web automation  
- 🚫 No user limits  
- 🧩 Full PKI ownership  

---

## 🧠 What is MSA?

**Marano Secure Access (MSA)** is a **self-hosted secure access platform** designed to manage VPN access with full control over identity, lifecycle and distribution.

It is not just a VPN installer.

It provides:

- identity-aware access
- certificate lifecycle management
- hybrid authentication (certificate + credentials)
- centralized registry tracking
- operational visibility
- automation-ready workflows

👉 Built for real-world environments (labs, cyber training, internal infrastructure).

---

## 🎬 Features

> Replace with your GIFs later

### 🔐 MFA Login
`docs/gifs/mfa.gif`

### 👤 Client Creation
`docs/gifs/create-client.gif`

### 🔁 Revoke / Remove Peer
`docs/gifs/revoke.gif`

### 📡 WireGuard Profiles
`docs/gifs/wireguard.gif`

### 📊 Dashboard
`docs/gifs/dashboard.gif`

---

## 🧱 Architecture

MSA is composed of:

### 🔹 Access Layer
- OpenVPN
- WireGuard

### 🔹 Identity Layer
- Easy-RSA PKI
- Credential-based authentication (optional)
- MFA (TOTP)

### 🔹 Management Layer
- Flask Web Dashboard
- CLI automation
- Registry engine

### 🔹 Delivery Layer
- Download
- Email
- Telegram

---

## 📦 Installation

### 1. Install dependencies

```bash
apt update
apt install -y openvpn easy-rsa wireguard iptables-persistent python3 python3-pip nginx
```

---

2. Clone project

```bash
git clone https://github.com/YOUR_USER/msa.git
cd msa
```

---

3. Setup environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

4. Configure environment
```bash
nano /root/.config/msa.env
```
Example:
```conf
MSA_WEB_SECRET=CHANGE_ME

MSA_ADMIN_USER=admin
MSA_ADMIN_PASS=CHANGE_ME
MSA_ADMIN_TOTP_SECRET=CHANGE_ME

MSA_TG_BOT_TOKEN=CHANGE_ME
MSA_TG_CHAT_ID=CHANGE_ME

MSA_SMTP_HOST=smtp.example.com
MSA_SMTP_PORT=465
MSA_SMTP_USER=CHANGE_ME
MSA_SMTP_PASS=CHANGE_ME
MSA_SMTP_FROM=CHANGE_ME
```

---

5. Run
```bash
python3 app.py
```

Access:

http://127.0.0.1:8080


---

🌍 Deployment (Example)

Typical home/lab setup:

Internet
   |
[ Router + DDNS ]
   |
[ Proxmox Host ]
   |
[ MSA Container ]
   ├── OpenVPN
   ├── WireGuard
   ├── Web Panel


---

🔐 Authentication Modes

MSA supports:

Certificate only (OpenVPN)

Certificate + Credentials

WireGuard peer-based access

MFA for admin login



---

🗂️ Registry System

MSA includes a registry engine that tracks:

active clients

revoked clients

profile types

lifecycle state


Supported operations:

auto-registration on creation

revoke tracking

rebuild from system state

export



---

🌐 Web Panel

Features:

Dashboard

Issued clients

Connected clients

Profile creation

Revoke / Remove peer

Logs

Server health

Registry management



---

💻 CLI

Script:

scripts/ovpn-menu.sh

Capabilities:

create clients

generate profiles

revoke by CN / ID / range

automation

logs / health



---

🔐 Security Notes

Use HTTPS in production

Protect admin credentials

Enable MFA

Use one profile per device

Revoke compromised clients immediately

Do not expose private keys



---

📁 Project Structure

.
├── app.py
├── requirements.txt
├── templates/
├── static/
├── scripts/
├── docs/
│   ├── images/
│   └── gifs/
├── examples/


---

🚀 Roadmap

Short Term

UI improvements

safer bulk operations

registry enhancements

health dashboard improvements


Mid Term

audit logs

RBAC (roles)

better filtering/search

backup/restore


Future

API REST

multi-admin support

zero-trust model

enterprise integration



---

🤝 Contributing

Contributions are welcome.

Focus areas:

security

UI/UX

automation

documentation



---

📌 Final Notes

MSA provides:

full control

self-hosted architecture

OpenVPN + WireGuard

MFA protection

lifecycle management


👉 Ideal for labs, cyber environments and controlled access infrastructures.
