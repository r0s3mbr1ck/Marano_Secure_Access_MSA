Perfeito — já vi tua estrutura (`docs/images/...`) e os nomes dos arquivos.
Vou te devolver o **README pronto**, já corrigido com as imagens reais que você subiu 👇

---

# 🛡️ OpenVPN Community Full Setup

## Proxmox + LXC + CLI/Web Management Panel

---

## 📌 Overview

This project documents a full self-hosted OpenVPN Community deployment running inside a dedicated LXC container on Proxmox VE, with both CLI and Web Panel management.

The main goal is to provide a scalable and fully controlled VPN solution based on OpenVPN Community Edition, avoiding the connection limits of the free Access Server tier and keeping the whole stack self-hosted and customizable.

---

## 🎯 Why this project exists

This project was built to create a practical alternative to limited self-hosted VPN offerings by using OpenVPN Community Edition with:

* full infrastructure ownership
* certificate-based authentication
* self-hosted PKI lifecycle control
* unlimited simultaneous connections
* web and CLI operational management
* Telegram-based `.ovpn` delivery
* easy integration with Proxmox, DNS and LAN

👉 **Goal:**
Build a **fully self-hosted VPN platform** without artificial user limits, keeping everything under your control.

---

## 🚀 Key Features

* OpenVPN Community Edition server
* LXC container on Proxmox
* Easy-RSA PKI lifecycle
* Client creation (manual & batch)
* Certificate revocation + CRL automation
* Connected clients monitoring
* `.ovpn` profile generation
* Telegram bot integration
* Web dashboard (Flask)
* CLI management menu
* LAN routing through VPN
* Fully self-hosted architecture

---

## 📸 Screenshots

### 🖥️ CLI Version

![CLI](docs/images/cli.png)

---

### 🌐 Web Dashboard

![Dashboard](docs/images/dashboard_webpage.png)

---

### 📡 Connected Clients

![Connected Clients](docs/images/connected_clients.png)

---

### 📂 Sidebar Navigation

![Sidebar](docs/images/dashboard_webpage_sidebar.png)

---

### 📜 Logs View

![Logs](docs/images/logs.png)

---

## 🧪 Tested Environment

* Proxmox VE
* Ubuntu 22 LXC
* OpenVPN Community
* Easy-RSA
* Python 3 + Flask
* Nginx
* systemd
* iptables

> Also works on VMs (Proxmox, VMware, VirtualBox, KVM).

---

## ⚠️ Important Notes

* Replace all `CHANGE`, `XX` placeholders
* Do NOT commit:

  * private keys
  * `.ovpn` files
  * Telegram tokens

---

## 🌐 Architecture

```text
Internet
   |
[ ISP Router ]
  - UDP 1194 → 192.168.XX.XX
  - DDNS
   |
[ Proxmox Host ]
   |
[ OpenVPN LXC ]
  - eth0: 192.168.XX.XX
  - tun0: 10.8.XX.1
```

---

## 📦 Installed Components

* OpenVPN Community
* Easy-RSA
* Python 3 + Flask
* curl (Telegram API)
* systemd
* iptables

---

## ⚙️ Proxmox Preparation

```bash
pct stop ID_CT
pct set ID_CT -mp0 /dev/net/tun,mp=/dev/net/tun
pct start ID_CT
```

---

## 📦 Installation

```bash
apt update
apt install -y openvpn easy-rsa iptables-persistent python3 python3-pip nginx curl
```

---

## 🔐 PKI Setup (Easy-RSA)

### Initialize

```bash
make-cadir /etc/openvpn/easy-rsa
cd /etc/openvpn/easy-rsa
./easyrsa init-pki
```

### Create CA

```bash
./easyrsa build-ca nopass
```

### Server cert

```bash
./easyrsa gen-req server nopass
./easyrsa sign-req server server
./easyrsa gen-dh
```

### TLS key

```bash
openvpn --genkey tls-crypt /etc/openvpn/tc.key
```

### CRL

```bash
./easyrsa gen-crl
cp pki/crl.pem /etc/openvpn/
chmod 644 /etc/openvpn/crl.pem
```

---

## ⚙️ OpenVPN Server Config

```conf
port 1194
proto udp
dev tun

server 10.8.XX.0 255.255.255.0

ca /etc/openvpn/ca.crt
cert /etc/openvpn/server.crt
key /etc/openvpn/server.key

tls-crypt /etc/openvpn/tc.key

cipher AES-256-GCM
auth SHA256

status /var/log/openvpn/status.log
crl-verify /etc/openvpn/crl.pem

push "route 192.168.XX.0 255.255.255.0"
```

---

## 🔁 NAT & Forwarding

```bash
sysctl -w net.ipv4.ip_forward=1

iptables -t nat -A POSTROUTING -s 10.8.XX.0/24 -o eth0 -j MASQUERADE
netfilter-persistent save
```

---

## ▶️ Service

```bash
systemctl enable openvpn@server
systemctl start openvpn@server
```

---

## 👤 Client Creation

```bash
./easyrsa gen-req client-phone nopass
./easyrsa sign-req client client-phone
```

---

## 📁 Profiles

```bash
/etc/openvpn/client-configs/make-ovpn.sh client-phone
```

---

## 📊 Monitoring

```bash
cat /var/log/openvpn/status.log
```

---

## ❌ Revoke Client

```bash
./easyrsa revoke client-phone
./easyrsa gen-crl
systemctl restart openvpn@server
```

---

# 🖥️ Web Panel

## Features

* Dashboard (KPIs)
* Connected clients
* Certificate management
* Batch operations
* Telegram export
* Logs
* Health check
* Sidebar navigation

---

## 📂 Project Structure

```text
ovpn-web-panel/
├── app.py
├── requirements.txt
├── templates/
├── static/
├── docs/images/
├── examples/
└── scripts/
```

---

## ⚙️ Setup

```bash
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

✔ Telegram integration já está implementada no projeto

---

## ⚙️ systemd Service

```ini
[Service]
ExecStart=/opt/ovpn-web-panel/venv/bin/python3 app.py
```

---

## 🌍 Nginx

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
}
```

---

## 🔐 Security Notes

* Use HTTPS if the panel is exposed externally  
* Restrict access to the web panel  
* Use one certificate per device  
* Revoke compromised devices immediately  
* Never publish `.ovpn` files or private keys

---

## 📦 Repository Structure

```text
.
├── README.md
├── app.py
├── templates/
├── static/
├── scripts/
├── docs/images/
└── examples/
```

---

## 🧠 Final Notes

This project is ideal for:

* homelabs
* internal infrastructure
* cyber training labs
* controlled environments

👉 It gives you:

* full control
* scalability
* simplicity
* zero vendor lock-in

