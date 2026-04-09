# 🔐 PKI & OpenVPN Setup Guide

This document describes the **manual infrastructure setup required** to run the VPN layer used by Marano Secure Access (MSA).

> ⚠️ This setup is **not automated by the application** and must be performed before using the system in production.

---

## 🧱 Environment Overview

- Host: Proxmox (LXC container)
- VPN: OpenVPN
- PKI: Easy-RSA
- Network: TUN interface + NAT

---

## 🔧 Proxmox Host Configuration

### Enable TUN device for the LXC container

```bash
pct stop 1XX
pct set 1XX -mp0 /dev/net/tun,mp=/dev/net/tun
pct start 1XX
```

---

## 📦 Installation (inside the LXC)
```bash
apt update
apt install -y openvpn easy-rsa iptables-persistent
```

---

## 🔐 PKI Setup – Easy-RSA

1. Initialize PKI directory
```bash
make-cadir /etc/openvpn/easy-rsa
cd /etc/openvpn/easy-rsa
```

---

2. (Optional) Configure variables
```bash
nano vars
```
Example:
```conf
set_var EASYRSA_KEY_SIZE    4096
set_var EASYRSA_CA_EXPIRE   3650
set_var EASYRSA_CERT_EXPIRE 825
```

---

3. Create Certificate Authority (CA)
```bash
./easyrsa init-pki
./easyrsa build-ca
```
> Use build-ca nopass for automated environments

---

4. Generate server certificate and key
```bash
./easyrsa gen-req server nopass
./easyrsa sign-req server server
./easyrsa gen-dh
```
---

5. Generate TLS-Crypt key
```bash
openvpn --genkey tls-crypt /etc/openvpn/tc.key
```

---

6. Generate CRL (required)
```bash
./easyrsa gen-crl
cp pki/crl.pem /etc/openvpn/
```
> ⚠️ The server will not start if crl-verify is enabled and this file is missing

---

7. Copy certificates and keys
```bash
cp pki/ca.crt \
   pki/issued/server.crt \
   pki/private/server.key \
   pki/dh.pem \
   /etc/openvpn/
```

---

## ⚙️ OpenVPN Server Configuration

File: /etc/openvpn/server.conf
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
push "dhcp-option DOMAIN home"

push "route 192.168.XX.0 255.255.255.0"

push "redirect-gateway def1 bypass-dhcp"

verb 3
```

---

## 🔁 IP Forwarding and NAT

Enable forwarding
```bash
sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
```

---

Configure NAT
```bash
iptables -t nat -A POSTROUTING -s 10.8.XX.0/24 -o eth0 -j MASQUERADE
iptables -A FORWARD -s 10.8.XX.0/24 -d 192.168.XX.0/24 -j ACCEPT
iptables -A FORWARD -s 192.168.XX.0/24 -d 10.8.XX.0/24 -j ACCEPT
```
```bash
netfilter-persistent save
```

---

## ▶️ Service Management
```bash
systemctl enable openvpn@server
systemctl start openvpn@server
systemctl status openvpn@server
```

---

## 👤 Client Certificates (one per device)
```bash
cd /etc/openvpn/easy-rsa
```

```bash
./easyrsa gen-req client-phone nopass
./easyrsa sign-req client client-phone
./easyrsa gen-req client-notebook nopass
./easyrsa sign-req client client-notebook
```

---

## ⚠️ Final Notes

Keep private keys secure

Never expose PKI material publicly

Use one certificate per device

Revoke compromised certificates immediately

---

## 🎯 Scope

This guide covers infrastructure and PKI setup only.

The MSA application assumes that:

OpenVPN is already operational

PKI is correctly configured

Certificates are available for integration
