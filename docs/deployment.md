# 📡 Deployment Guide

Recommended setup:

- Reverse proxy (Nginx)
- TLS (Let's Encrypt or internal CA)
- OpenVPN / WireGuard
- Proxmox or VM-based hosting

Ports:

- UDP 1194 → OpenVPN  
- UDP 51820 → WireGuard  
- TCP 80/443 → Web Panel  

Use DDNS if no static IP is available.
