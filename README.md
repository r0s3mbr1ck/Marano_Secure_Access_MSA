# OpenVPN Community Full Setup
## Proxmox + LXC + CLI/Web Management Panel

## Overview

This project documents a full self-hosted OpenVPN Community deployment running inside a dedicated LXC container on Proxmox VE, with both CLI and Web Panel management.

The main goal is to provide a scalable and fully controlled VPN solution based on OpenVPN Community Edition, avoiding the connection limits of the free Access Server tier and keeping the whole stack self-hosted and customizable.

## Why this project exists

This project was built to create a practical alternative to limited self-hosted VPN offerings by using OpenVPN Community Edition with:

- full infrastructure ownership
- certificate-based authentication
- self-hosted PKI lifecycle control
- unlimited simultaneous connections at the OpenVPN Community layer
- web and CLI operational management
- Telegram-based `.ovpn` profile delivery
- easy integration with Proxmox, internal DNS, DDNS, and LAN routing

In short:

**build a fully self-hosted VPN platform with no artificial concurrent-user limits, while keeping administration lightweight and under your own control.**

## Key Features

- OpenVPN Community Edition server
- Dedicated LXC container on Proxmox VE
- Certificate-based client authentication
- Easy-RSA based PKI
- Manual and batch client provisioning
- Client revocation with CRL regeneration
- Connected clients monitoring
- `.ovpn` profile generation
- Telegram bot integration for profile delivery
- Web dashboard for daily operations
- CLI management menu for maintenance and automation
- LAN access through VPN
- NAT and forwarding support
- Internal-use friendly and fully self-hosted

## Screenshots

### CLI version

Add your screenshot here:

```md
![CLI Version](docs/images/cli-version.webp)
```

### Web version

Add your screenshot here:

```md
![Web Version](docs/images/web-version.webp)
```

## Tested Environment

This setup was tested on:

- Proxmox VE
- Ubuntu 22 LXC container
- OpenVPN Community Edition
- Easy-RSA
- Python 3 + Flask
- Nginx reverse proxy
- systemd
- iptables / netfilter

> It can also be deployed in a VM on Proxmox, VMware, VirtualBox, KVM, or any other hypervisor with appropriate network adjustments.

## Important Notes

- Search for `CHANGE`, `XX`, and placeholder values in this documentation and replace them with your own settings.
- This project assumes a routed LAN behind the VPN server.
- The Telegram bot integration is already supported by the management scripts and web panel through environment variables.
- Never publish private keys, issued certificates, `.ovpn` files, tokens, or internal infrastructure details in a public repository.

## Architecture

```text
Internet
   |
[ ISP Router ]
  - Port Forward UDP 1194 -> 192.168.XX.XX
  - DDNS: CHANGE_FOR_YOU.example.com
   |
[ Proxmox Host ]
   |
[ OpenVPN Community LXC ]
  - eth0: 192.168.XX.XX
  - tun0: 10.8.XX.1
```

## Installed Components

- OpenVPN Community Edition
- Easy-RSA
- Python 3
- Flask
- curl
- systemd
- iptables / netfilter
- OpenVPN client configuration tools
- Nginx for reverse proxying the web panel

## Proxmox Host Preparation

### Enable `/dev/net/tun` for the LXC container (create LXC container before)

```bash
pct stop ID_CT
pct set ID_CT -mp0 /dev/net/tun,mp=/dev/net/tun
pct start ID_CT
```

## Package Installation (inside the LXC)

```bash
apt update
apt install -y openvpn easy-rsa iptables-persistent python3 python3-pip nginx curl
```

If you plan to run the web panel inside a Python virtual environment:

```bash
apt install -y python3-venv
```

## PKI Setup with Easy-RSA

This project uses Easy-RSA as the certificate authority and certificate lifecycle manager.

### 1. Create the Easy-RSA working directory

```bash
make-cadir /etc/openvpn/easy-rsa
cd /etc/openvpn/easy-rsa
```

### 2. Optional: adjust Easy-RSA defaults before initialization

```bash
nano vars
```

Example values:

```bash
set_var EASYRSA_KEY_SIZE    4096
set_var EASYRSA_CA_EXPIRE   3650
set_var EASYRSA_CERT_EXPIRE 825
```

### 3. Initialize the PKI

```bash
./easyrsa init-pki
```

### 4. Build the CA

Interactive mode:

```bash
./easyrsa build-ca
```

Non-interactive or lab-friendly mode:

```bash
./easyrsa build-ca nopass
```

### 5. Generate the server private key and certificate request

```bash
./easyrsa gen-req server nopass
```

### 6. Sign the server certificate

```bash
./easyrsa sign-req server server
```

### 7. Generate Diffie-Hellman parameters

```bash
./easyrsa gen-dh
```

### 8. Generate a TLS-Crypt key

```bash
openvpn --genkey tls-crypt /etc/openvpn/tc.key
```

### 9. Generate the initial CRL

This is required if `crl-verify` is enabled in `server.conf`.

```bash
./easyrsa gen-crl
cp pki/crl.pem /etc/openvpn/
chmod 644 /etc/openvpn/crl.pem
```

### 10. Copy server-side PKI material

```bash
cp pki/ca.crt /etc/openvpn/
cp pki/issued/server.crt /etc/openvpn/
cp pki/private/server.key /etc/openvpn/
cp pki/dh.pem /etc/openvpn/
```

## OpenVPN Server Configuration

File:

```text
/etc/openvpn/server.conf
```

Example:

```conf
port 1194
proto udp
dev tun

topology subnet
server 10.8.XX.0 255.255.255.0
ifconfig-pool-persist /var/log/openvpn/ipp.txt

ca /etc/openvpn/ca.crt
cert /etc/openvpn/server.crt
key /etc/openvpn/server.key
dh /etc/openvpn/dh.pem

tls-crypt /etc/openvpn/tc.key

cipher AES-256-GCM
auth SHA256
remote-cert-tls client

keepalive 10 120
persist-key
persist-tun

user nobody
group nogroup

status /var/log/openvpn/status.log
status-version 2

crl-verify /etc/openvpn/crl.pem

push "dhcp-option DNS 192.168.XX.XX"
push "dhcp-option DOMAIN CHANGE_ME"
push "route 192.168.XX.0 255.255.255.0"

# Optional: route all internet traffic through the VPN
push "redirect-gateway def1 bypass-dhcp"

verb 3
```

## IP Forwarding and NAT

Enable IPv4 forwarding:

```bash
sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
```

Add NAT and forwarding rules:

```bash
iptables -t nat -A POSTROUTING -s 10.8.XX.0/24 -o eth0 -j MASQUERADE
iptables -A FORWARD -s 10.8.XX.0/24 -d 192.168.XX.0/24 -j ACCEPT
iptables -A FORWARD -s 192.168.XX.0/24 -d 10.8.XX.0/24 -j ACCEPT

netfilter-persistent save
```

## OpenVPN Service Management

```bash
systemctl enable openvpn@server
systemctl start openvpn@server
systemctl status openvpn@server
```

## Client Certificates

Create one certificate per device.

Examples:

```bash
cd /etc/openvpn/easy-rsa

./easyrsa gen-req client-phone nopass
./easyrsa sign-req client client-phone

./easyrsa gen-req client-notebook nopass
./easyrsa sign-req client client-notebook
```

## Client Profile Structure

```text
/etc/openvpn/client-configs/
├── base.conf
├── make-ovpn.sh
└── files/
```

### Example `base.conf`

```conf
client
dev tun
proto udp
remote CHANGE_HERE.example.com 1194

resolv-retry infinite
nobind
persist-key
persist-tun

remote-cert-tls server
cipher AES-256-GCM
auth SHA256

verb 3
```

### Generate a client profile

```bash
/etc/openvpn/client-configs/make-ovpn.sh client-phone
```

## Android and Desktop Clients

This setup is intended to use a single embedded `.ovpn` file per device.

### Recommended client workflow

- Generate the client certificate
- Build the final `.ovpn`
- Import it directly into the VPN client
- No external certificate files required

## Monitoring Connected Clients

```bash
cat /var/log/openvpn/status.log
```

Real-time view:

```bash
watch -n 2 cat /var/log/openvpn/status.log
```

## Revoking a Client Certificate

```bash
cd /etc/openvpn/easy-rsa
./easyrsa revoke client-phone
./easyrsa gen-crl
cp pki/crl.pem /etc/openvpn/
chmod 644 /etc/openvpn/crl.pem
systemctl restart openvpn@server
```

## CLI Management Version

The repository also includes a CLI menu for operational tasks such as:

- creating clients
- generating `.ovpn` files
- exporting profiles
- revoking certificates
- showing connected clients
- checking server health
- batch issuing clients with TTL-based registry entries
- Telegram export of VPN profiles

### Main CLI capabilities

- Easy-RSA client management
- profile generation through `make-ovpn.sh`
- registry-based tracking (`id -> cn -> expires_at -> status`)
- batch creation for numbered clients
- revoke by CN, ID, or ID range
- export via Telegram or local copy
- health checks and log inspection

If you want to keep the README shorter, place the full CLI script in:

```text
scripts/ovpn-menu.sh
```

and reference it from the README instead of embedding the entire script.

## Web Panel Version

The web panel was created to make OpenVPN Community operationally easier to manage in internal environments, especially when the goal is to keep the entire solution self-hosted while still having a modern interface for day-to-day tasks.

### Current web panel features

- dashboard with operational statistics
- connected clients view
- issued clients table
- profile generation
- revocation actions
- registry download
- OpenVPN log access
- health check view
- Telegram profile delivery
- responsive layout with collapsible sidebar

## Web Panel Project Layout

```text
ovpn-web-panel/
├── app.py
├── requirements.txt
├── README.md
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── connected.html
│   ├── revoked.html
│   ├── logs.html
│   ├── health.html
│   └── registry.html
└── static/
    ├── css/
    │   └── style.css
    └── js/
        └── app.js
```

## Web Panel Setup

### 1. Create the application directory

```bash
mkdir -p /opt/ovpn-web-panel
cd /opt/ovpn-web-panel
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv /opt/ovpn-web-panel/venv
source /opt/ovpn-web-panel/venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install --upgrade pip
pip install flask
```

### 4. Copy the project files

Example:

```bash
cp -r ovpn_web_panel/* /opt/ovpn-web-panel/
```

Or clone your GitHub repository directly.

### 5. Configure environment variables

Create:

```text
/root/.config/ovpn-menu.env
```

Example:

```bash
export OVPN_WEB_SECRET='CHANGE_ME'
export OVPN_TG_BOT_TOKEN='CHANGE_ME'
export OVPN_TG_CHAT_ID='CHANGE_ME'
```

> The Telegram bot integration is already supported by the scripts and web panel.
> Just set the environment variables and keep the token out of the repository.

### 6. Test manually

```bash
cd /opt/ovpn-web-panel
source venv/bin/activate
python3 app.py
```

By default, Flask should listen on:

```text
127.0.0.1:8080
```

### 7. Create a systemd service

Example:

```ini
[Unit]
Description=OpenVPN Web Panel
After=network.target

[Service]
User=root
WorkingDirectory=/opt/ovpn-web-panel
Environment="PATH=/opt/ovpn-web-panel/venv/bin"
ExecStart=/opt/ovpn-web-panel/venv/bin/python3 /opt/ovpn-web-panel/app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Save as:

```text
/etc/systemd/system/ovpn-web-service.service
```

Then enable it:

```bash
systemctl daemon-reload
systemctl enable --now ovpn-web-service
systemctl status ovpn-web-service
```

### 8. Put Nginx in front of Flask

Example server block:

```nginx
server {
    listen 80;
    server_name CHANGE_ME;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and test:

```bash
nginx -t
systemctl reload nginx
```

### 9. Optional: redirect IP-based access to the internal DNS name

If users still open the panel through the raw IP address, redirect it to the preferred hostname:

```nginx
server {
    listen 80;
    server_name 192.168.XX.XX;
    return 301 http://CHANGE_ME$request_uri;
}
```

## Security Notes

- Do not commit private keys, client certificates, `.ovpn` files, or Telegram tokens.
- Restrict panel access to your internal network or VPN whenever possible.
- Use HTTPS if the web panel is exposed beyond a trusted internal environment.
- Prefer one certificate per device.
- Revoke certificates immediately when a device is lost or retired.
- Keep `crl-verify` enabled.
- Keep the Easy-RSA CA offline or minimally exposed if you move from lab to production.

## Repository Suggestions

A clean public repository layout could look like this:

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
└── examples/
    ├── server.conf.example
    ├── base.conf.example
    └── ovpn-web-service.service.example
```

## Final Notes

This project is meant for operators who want:

- a self-hosted OpenVPN platform
- certificate-driven access control
- predictable operations
- simple web-based day-to-day administration
- no dependency on a limited free connection tier
- full ownership of the VPN stack

It is especially useful for homelabs, internal infrastructure, training labs, and controlled organizational environments.
