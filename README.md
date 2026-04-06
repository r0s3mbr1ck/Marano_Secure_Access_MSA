# 🛡️ OpenVPN Community Full Setup
## Proxmox + LXC + CLI/Web Management Panel

---

## 📌 Overview

This project documents a full self-hosted OpenVPN Community deployment running inside a dedicated LXC container on Proxmox VE, with both CLI and Web Panel management.

The goal is to provide a scalable, fully controlled VPN solution without the limitations of OpenVPN Access Server free tier.

---

## 🎯 Why this project exists

This project was created to build a **fully self-hosted VPN platform** with:

- full infrastructure ownership  
- certificate-based authentication  
- PKI lifecycle control  
- unlimited simultaneous connections  
- CLI + Web management  
- Telegram `.ovpn` delivery  
- Proxmox + LAN integration  

👉 **No artificial user limits. Full control.**

---

## 🌐 Real-world scenario (important)

This setup was built in a **home/lab environment**, where:

- there is **no public static IP**
- a **DDNS service** is used
- the router performs:
  - UDP **port forwarding (1194)**
  - NAT

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
````

⚠️ Adapt this to your environment:

* cloud VM
* static IP
* reverse proxy
* enterprise firewall

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

## 📦 Installation

```bash
apt update
apt install -y openvpn easy-rsa iptables-persistent python3 python3-pip nginx curl
```

---

## 🔐 PKI Setup (Easy-RSA)

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

## ⚙️ OpenVPN Server Config

File:

```text
/etc/openvpn/server.conf
```

---

## 🔁 NAT & Forwarding

```bash
sysctl -w net.ipv4.ip_forward=1

iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE
netfilter-persistent save
```

---

## ▶️ Service

```bash
systemctl enable openvpn@server
systemctl start openvpn@server
```

---

# 💻 CLI Management

Script location:

```text
scripts/ovpn-menu.sh
```

Features:

* create clients
* generate `.ovpn`
* revoke by CN / ID / range
* registry tracking
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

## ⚙️ Setup

```bash
cd /opt/ovpn-web-panel
python3 -m venv venv
source venv/bin/activate
pip install flask

python3 app.py
```

Access:

```text
http://127.0.0.1:8080
```

---

## 🔐 Environment Variables

```bash
export OVPN_WEB_SECRET='CHANGE_ME'
export OVPN_TG_BOT_TOKEN='CHANGE_ME'
export OVPN_TG_CHAT_ID='CHANGE_ME'
```

---

# 🌍 Nginx (Reverse Proxy)

Example config:

```nginx
server {
    listen 80;
    server_name CHANGE_ME.local;

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
    return 301 http://CHANGE_ME$request_uri;
}
```

---

## 📁 Project Structure

```text
.
├── README.md
├── app.py
├── templates/
├── static/
├── scripts/
│   └── ovpn-menu.sh
├── docs/images/
├── examples/
└── requirements.txt
```

---

## 📁 Example Files

```text
examples/
├── server.conf.example
├── base.conf.example
├── ovpn-web-service.service.example
└── ovpn-menu.env.example
```

---

## 🔐 Security Notes

* Use HTTPS if exposed externally
* Restrict access to the panel
* One certificate per device
* Revoke compromised devices immediately
* Never publish `.ovpn` files or private keys

---

## 🧠 Final Notes

This project is ideal for:

* homelabs
* cyber training labs
* internal networks
* controlled environments

👉 Fully self-hosted
👉 Scalable
👉 No vendor lock-in

````
