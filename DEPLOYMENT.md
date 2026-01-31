# VPS Deployment Guide

## Prerequisites

- Ubuntu 20.04+ or similar Linux distribution
- Python 3.10+
- curl or wget
- sudo access

## Quick Start (Manual Deployment)

### 1. SSH into your VPS

```bash
ssh user@your-vps-ip
```

### 2. Clone or upload project

```bash
git clone <your-repo-url> forex_bot
cd forex_bot
```

### 3. Create virtual environment and install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
nano .env  # Edit with your n8n webhook URL
```

### 5. Test the bot

```bash
cd app
python main.py
```

Visit `http://your-vps-ip:8000/health` to verify it's running.

---

## Production Deployment with systemd

### 1. Create service user

```bash
sudo useradd -r -s /bin/bash trading
sudo mkdir -p /opt/forex_bot
sudo chown trading:trading /opt/forex_bot
```

### 2. Copy project to /opt

```bash
sudo cp -r forex_bot/* /opt/forex_bot/
sudo chown -R trading:trading /opt/forex_bot
```

### 3. Create systemd service file

```bash
sudo tee /etc/systemd/system/forex-bot.service > /dev/null << EOF
[Unit]
Description=Forex Trading Bot
After=network.target

[Service]
Type=simple
User=trading
WorkingDirectory=/opt/forex_bot
Environment="PATH=/opt/forex_bot/venv/bin"
EnvironmentFile=/opt/forex_bot/.env
ExecStart=/opt/forex_bot/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

### 4. Enable and start service

```bash
sudo systemctl daemon-reload
sudo systemctl enable forex-bot
sudo systemctl start forex-bot
```

### 5. Verify it's running

```bash
sudo systemctl status forex-bot
sudo journalctl -u forex-bot -f  # Follow logs
```

---

## Docker Deployment (Recommended)

### 1. Install Docker and Docker Compose

```bash
# Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.1/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### 2. Prepare project

```bash
mkdir -p /opt/forex_bot
cd /opt/forex_bot
git clone <your-repo-url> .
cp .env.example .env
nano .env  # Edit configuration
```

### 3. Run with Docker Compose

```bash
docker-compose up -d
docker-compose logs -f  # Follow logs
```

### 4. Manage container

```bash
# Stop
docker-compose down

# Rebuild
docker-compose build --no-cache
docker-compose up -d

# View logs
docker-compose logs -f forex-bot
```

---

## Nginx Reverse Proxy (Optional)

Add a reverse proxy in front for better security and SSL:

```bash
sudo apt install nginx
```

Create `/etc/nginx/sites-available/forex-bot`:

```nginx
upstream forex_bot {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://forex_bot;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/forex-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

Add SSL with Let's Encrypt:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## Monitoring and Maintenance

### Check status

```bash
# systemd
sudo systemctl status forex-bot

# Docker
docker-compose ps
docker-compose stats
```

### View logs

```bash
# systemd (last 100 lines, follow)
sudo journalctl -u forex-bot -n 100 -f

# Docker
docker-compose logs -f --tail=100
```

### Restart bot

```bash
# systemd
sudo systemctl restart forex-bot

# Docker
docker-compose restart
```

### Health check

```bash
curl http://localhost:8000/health
curl http://localhost:8000/status
```

---

## Troubleshooting

### Bot won't start

1. Check configuration: `cat /opt/forex_bot/.env`
2. Check logs: `sudo journalctl -u forex-bot -n 50`
3. Verify N8N_WEBHOOK_URL is accessible: `curl -X POST <N8N_WEBHOOK_URL>`
4. Check Python version: `python3 --version` (needs 3.10+)

### High memory usage

- Check number of trades/positions
- Monitor with: `docker stats` or `top`
- Adjust HEARTBEAT_INTERVAL in .env

### Webhook failures

- Bot continues running (graceful degradation)
- Check n8n webhook is accessible from VPS
- Check firewall rules: `sudo ufw allow 8000`

### Port already in use

```bash
# Find and kill process using port 8000
sudo lsof -i :8000
sudo kill -9 <PID>

# Or change port in docker-compose.yml or systemd service
```

---

## Scaling Considerations

For multiple bot instances:

1. **Separate credentials** - Use different .env files
2. **Different ports** - 8001, 8002, etc with nginx routing
3. **Load balancing** - Route requests via n8n or external service
4. **Monitoring** - Centralize logs with ELK or similar

---

## Security Checklist

- [ ] `.env` file locked down (600 permissions)
- [ ] Firewall configured (only port 80/443/SSH open)
- [ ] SSH key-based auth (no passwords)
- [ ] Regular backups of trade logs
- [ ] Monitor n8n webhook for suspicious activity
- [ ] Keep Python/packages updated
- [ ] Use reverse proxy with SSL/TLS
- [ ] Run as non-root user

---

## Backup and Recovery

Backup daily:

```bash
# Backup script
#!/bin/bash
BACKUP_DIR="/backups"
DATE=$(date +%Y%m%d_%H%M%S)
tar -czf "$BACKUP_DIR/forex_bot_$DATE.tar.gz" /opt/forex_bot
# Send to cloud storage (S3, etc)
```

Restore:

```bash
tar -xzf forex_bot_backup.tar.gz -C /opt
sudo systemctl restart forex-bot
```
