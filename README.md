# 🛡️ OpenVPN Community Full Setup with Proxmox + LXC + CLI/Web Management Panel
<p align="center">
  <img src="docs/images/cover.png" width="900"/>
</p>

## 📌 Overview

This project provides a **fully self-hosted OpenVPN Community deployment** running inside a Proxmox LXC container, with both:

* CLI management (automation + operations)
* Web panel (Flask-based dashboard)

The goal is to deliver a **scalable VPN solution without artificial limitations**, unlike OpenVPN Access Server free tier.

---

## 🎯 Why this project exists

This project was built to create a **real-world, self-hosted VPN platform** with:

* full infrastructure ownership
* certificate-based authentication
* PKI lifecycle control (Easy-RSA)
* unlimited simultaneous connections
* CLI + Web management interface
* Telegram `.ovpn` delivery
* Proxmox + LAN integration

👉 **No artificial user limits. No vendor lock-in. Full control.**

---

## 🌐 Real-world scenario (important)

This setup was built in a **home/lab environment**, where:

* there is **no public static IP**
* a **DDNS service** is used
* router performs:

  * UDP **port forwarding (1194)**
  * NAT

```text
Internet
   |
[ ISP Router ]
  - DDNS → yourdomain.ddns.net
  - Port Forward UDP 1194 → VPN Server
   |
[ Proxmox ]
   |
[ OpenVPN LXC ]
```

⚠️ Adapt this to your environment:

* cloud VM
* public IP
* enterprise firewall
* reverse proxy

---

## 🚀 Features

* OpenVPN Community server
* Easy-RSA PKI
* CLI management script
* Web panel (Flask)
* Telegram integration
* Batch client creation
* Certificate revocation (CRL)
* Connected clients monitoring
* `.ovpn` generation
* LAN routing
* Sidebar-based UI

---

## 📸 Screenshots

### CLI

![CLI](docs/images/cli.png)

### Dashboard

![Dashboard](docs/images/dashboard_webpage.png)

### Connected Clients

![Connected](docs/images/connected_clients.png)

### Sidebar

![Sidebar](docs/images/dashboard_webpage_sidebar.png)

### Logs

![Logs](docs/images/logs.png)

---

## 🧪 Tested Environment

* Proxmox VE
* Ubuntu 22 LXC
* OpenVPN Community
* Easy-RSA
* Python 3 + Flask
* Nginx
* iptables

---

# ⚡ Quick Start (Web Panel)

## 1. Clone repository

```bash
git clone https://github.com/r0s3mbr1ck/OVPN_Self_Hosted.git
cd OVPN_Self_Hosted
```

---

## 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

---

## 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 4. Configure environment variables

```bash
nano /root/.config/ovpn-menu.env
```

```bash
export OVPN_WEB_SECRET='CHANGE_ME'
export OVPN_TG_BOT_TOKEN='CHANGE_ME'
export OVPN_TG_CHAT_ID='CHANGE_ME'
```

---

## 5. Run the web panel

```bash
python3 app.py
```

Access:

```text
http://127.0.0.1:8080
```

---

## ⚠️ Requirements

This project assumes OpenVPN is already installed and configured:

```text
/etc/openvpn/
/etc/openvpn/easy-rsa/
/etc/openvpn/client-configs/
```

---

# 📦 Installation (OpenVPN)

```bash
apt update
apt install -y openvpn easy-rsa iptables-persistent python3 python3-pip nginx curl
```

---

# 🔐 PKI Setup (Easy-RSA)

```bash
make-cadir /etc/openvpn/easy-rsa
cd /etc/openvpn/easy-rsa

./easyrsa init-pki
./easyrsa build-ca nopass

./easyrsa gen-req server nopass
./easyrsa sign-req server server
./easyrsa gen-dh

openvpn --genkey tls-crypt /etc/openvpn/tc.key

./easyrsa gen-crl
cp pki/crl.pem /etc/openvpn/
chmod 644 /etc/openvpn/crl.pem
```

---

# ⚙️ OpenVPN Server Config

File:

```text
/etc/openvpn/server.conf
```

---

# 🔁 NAT & Forwarding

```bash
sysctl -w net.ipv4.ip_forward=1

iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE
netfilter-persistent save
```

---

# ▶️ Service

```bash
systemctl enable openvpn@server
systemctl start openvpn@server
```

---

# 💻 CLI Management

Script:

```text
scripts/ovpn-menu.sh
```

### Features

* client creation
* `.ovpn` generation
* revoke (CN / ID / range)
* registry with TTL
* Telegram export
* logs + health

---

# 🌐 Web Panel

## Features

* Dashboard
* Connected clients
* Client management
* Revocation
* Logs
* Health check
* Telegram export
* Sidebar navigation

---

## ⚙️ Run

```bash
python3 app.py
```

---

# 🌍 Nginx Reverse Proxy

Example:

```nginx
server {
    listen 80;
    server_name vpn.yourdomain.local;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Enable:

```bash
nginx -t
systemctl reload nginx
```

---

## 🔁 Redirect IP → Domain (optional)

```nginx
server {
    listen 80;
    server_name 192.168.XX.XX;
    return 301 http://vpn.yourdomain.local$request_uri;
}
```

---

# 📁 Project Structure

```text
.
├── README.md
├── app.py
├── requirements.txt
├── templates/
├── static/
├── scripts/
│   └── ovpn-menu.sh
├── docs/
│   └── images/
├── examples/
│   ├── server.conf.example
│   ├── base.conf.example
│   ├── ovpn-web-service.service.example
│   └── ovpn-menu.env.example
```

---

# ⚙️ Optional: Run as systemd service

```bash
cp examples/ovpn-web-service.service.example /etc/systemd/system/ovpn-web.service

systemctl daemon-reload
systemctl enable --now ovpn-web.service
```

---

# 🔐 Security Notes

* Use HTTPS if exposed externally
* Restrict access to the panel
* One certificate per device
* Revoke compromised devices immediately
* Never publish `.ovpn` files or private keys

---

# 🧠 Final Notes

This project is ideal for:

* homelabs
* cyber labs
* internal networks
* training environments

👉 Fully self-hosted
👉 Scalable
👉 No vendor lock-in

---

# 🚀 Next Step

👉 Docker version (recommended for portability)
