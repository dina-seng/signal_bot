# 🚀 Complete Deployment & Telegram Bot Setup Guide

This guide provides step-by-step instructions to configure your Telegram Bot, configure environment variables, and host the **Forex Market Analysis & Signal Bot** on a server for 24/7 autonomous trading signal delivery and market monitoring.

---

## 📑 Table of Contents

1. [Step 1: Create & Configure Your Telegram Bot](#step-1-create--configure-your-telegram-bot)
2. [Step 2: Environment Configuration (`.env`)](#step-2-environment-configuration-env)
3. [Step 3: Hosting Options](#step-3-hosting-options)
   - [Option A: Linux VPS (Ubuntu/Debian) with Systemd & Nginx (Recommended)](#option-a-linux-vps-ubuntudebian-with-systemd--nginx-recommended)
   - [Option B: Docker & Docker Compose (Fastest Containerized Setup)](#option-b-docker--docker-compose-fastest-containerized-setup)
   - [Option C: Cloud Hosting (Render, Railway, Fly.io)](#option-c-cloud-hosting-render-railway-flyio)
4. [Step 4: Setting Up Telegram Webhook (For Interactive Commands)](#step-4-setting-up-telegram-webhook-for-interactive-commands)
5. [Step 5: Verification, Monitoring & Commands Testing](#step-5-verification-monitoring--commands-testing)
6. [Step 6: Troubleshooting & Common Issues](#step-6-troubleshooting--common-issues)

---

## 🤖 Step 1: Create & Configure Your Telegram Bot

### 1.1 Create Your Bot with @BotFather

1. Open Telegram and search for [`@BotFather`](https://t.me/botfather).
2. Send `/start` to BotFather.
3. Send `/newbot` to create a new bot.
4. Choose a **display name** (e.g., `My Forex Signal Pro`).
5. Choose a **username** ending in `bot` (e.g., `my_forex_signal_pro_bot`).
6. BotFather will output your **HTTP API Token**. It looks like:
   ```text
   <YOUR_BOT_TOKEN>
   ```
   👉 **Copy this token** — this is your `TELEGRAM_BOT_TOKEN`.

### 1.2 Register Bot Commands with BotFather

To enable the quick command autocomplete menu in Telegram:
1. In `@BotFather`, send `/setcommands`.
2. Select your bot.
3. Paste the following command list:
   ```text
   scan - Scan all markets for high-confluence trade setups
   signal - Deep signal score for pair (e.g. /signal EUR/USD)
   news - Today's economic calendar & news blackout status
   account - View virtual paper trading account & margin
   positions - View all open & pending virtual positions
   performance - Strategy win rate, profit factor & stats
   backtest - Run historical backtest on symbol
   help - Show full interactive command guide
   ```

### 1.3 Obtain Your Telegram `Chat ID`

You can send signals to a **Private 1-on-1 Chat**, a **Private Group**, or a **Public/Private Channel**.

#### For a Private 1-on-1 Chat:
1. Search for [`@userinfobot`](https://t.me/userinfobot) or [`@RawDataBot`](https://t.me/RawDataBot) in Telegram and send `/start`.
2. Copy the numeric `Id` (e.g. `123456789`).
3. Send `/start` to your newly created bot to open the chat.

#### For a Telegram Channel or Group:
1. Create a Channel or Group (e.g., `My Forex Signals VIP`).
2. Add your bot as an **Administrator** with permission to **Post Messages**.
3. To get the Channel ID:
   - Forward any message from the channel to [`@userinfobot`](https://t.me/userinfobot) or [`@RawDataBot`](https://t.me/RawDataBot).
   - The Channel ID will start with `-100` (e.g. `-1001987654321`).
4. Set `TELEGRAM_CHAT_ID=-1001987654321` in your `.env`.

---

## ⚙️ Step 2: Environment Configuration (`.env`)

1. Clone or copy your project repository to your target machine:
   ```bash
   git clone <your-repository-url>
   cd trade
   ```

2. Create your `.env` file from `.env.example`:
   ```bash
   cp .env.example .env
   ```

3. Open `.env` in an editor (e.g., `nano .env`) and update the values:

```ini
# ==========================================
# Application Settings
# ==========================================
PROJECT_NAME="Forex Market Analysis & Signal System"
APP_ENV=production
LOG_LEVEL=INFO

# ==========================================
# Database Connection
# ==========================================
DATABASE_URL=sqlite:///./trade.db
# For production PostgreSQL: postgresql+psycopg://user:password@localhost:5432/forex_bot

# ==========================================
# Instruments & Timeframes
# ==========================================
SUPPORTED_SYMBOLS=["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]
SUPPORTED_TIMEFRAMES=["15m", "1h", "4h"]

# ==========================================
# Strategy Confluence Parameters
# ==========================================
SWING_LOOKBACK=2
EMA_FAST=20
EMA_MID=50
EMA_SLOW=200
RSI_PERIOD=14
ATR_PERIOD=14
MIN_SETUP_SCORE=75.0
MIN_RR=2.0
MAX_RISK_PERCENT=0.5

# ==========================================
# Economic News Blackout Window
# ==========================================
NEWS_BLACKOUT_BEFORE_MINUTES=30
NEWS_BLACKOUT_AFTER_MINUTES=15

# ==========================================
# Market Data & News Providers
# ==========================================
MARKET_DATA_PROVIDER=yfinance
# Optional secondary providers:
TWELVE_DATA_API_KEY=
ALPHA_VANTAGE_API_KEY=
NEWS_API_KEY=

# ==========================================
# Telegram Bot Configuration
# ==========================================
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

# ==========================================
# Automated Background Scanner & Paper Trading
# ==========================================
SCANNER_ENABLED=true
SCANNER_INTERVAL_MINUTES=15
SCANNER_TIMEFRAMES=["1h", "15m"]
SCANNER_AUTO_TRADE_PAPER=true
PAPER_TRADING=true
```

---

## 🖥️ Step 3: Hosting Options

Choose the deployment method that fits your infrastructure:

---

### Option A: Linux VPS (Ubuntu/Debian) with Systemd & Nginx (Recommended)

This provides high stability, zero extra cloud costs, auto-restart on crashes/reboots, and free SSL for Telegram Webhooks.

#### A.1 Server Preparation & Dependencies

Connect to your VPS (e.g. Ubuntu 22.04 / 24.04):
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx ufw
```

Configure basic firewall:
```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

#### A.2 Deploy Code & Set Up Virtual Environment

```bash
# Clone to /var/www/forex-bot
sudo mkdir -p /var/www/forex-bot
sudo chown -R $USER:$USER /var/www/forex-bot
git clone <your-repository-url> /var/www/forex-bot
cd /var/www/forex-bot

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create .env configuration
cp .env.example .env
nano .env  # Enter your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
```

#### A.3 Create Systemd Service (Auto-Start & Restart on Boot)

Create `/etc/systemd/system/forex-bot.service`:
```bash
sudo nano /etc/systemd/system/forex-bot.service
```

Paste the following configuration:
```ini
[Unit]
Description=Forex Market Analysis & Telegram Signal Bot
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/var/www/forex-bot
Environment="PATH=/var/www/forex-bot/venv/bin"
ExecStart=/var/www/forex-bot/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2

Restart=always
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```
*(Replace `User=ubuntu` and paths if using a different username).*

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable forex-bot
sudo systemctl start forex-bot
sudo systemctl status forex-bot
```

#### A.4 Configure Nginx Reverse Proxy & SSL with Certbot

Create `/etc/nginx/sites-available/forex-bot`:
```bash
sudo nano /etc/nginx/sites-available/forex-bot
```

Paste:
```nginx
server {
    server_name yourdomain.com; # Replace with your domain or VPS subdomain

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

Enable site and obtain free Let's Encrypt SSL certificate:
```bash
sudo ln -s /etc/nginx/sites-available/forex-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Issue SSL certificate
sudo certbot --nginx -d yourdomain.com
```

---

### Option B: Docker & Docker Compose (Fastest Containerized Setup)

If you prefer Docker containers:

1. **Install Docker & Docker Compose**:
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   ```

2. **Configure `.env`**:
   Ensure `.env` contains your `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

3. **Start the Bot in Background**:
   ```bash
   docker compose up -d --build
   ```

4. **Useful Docker Management Commands**:
   - Check container status:
     ```bash
     docker compose ps
     ```
   - Stream live logs:
     ```bash
     docker compose logs -f
     ```
   - Restart the bot:
     ```bash
     docker compose restart
     ```
   - Stop the bot:
     ```bash
     docker compose down
     ```

---

### Option C: Cloud Hosting (Render, Railway, Fly.io)

You can host the application on managed cloud container platforms:

#### Deploying on Render / Railway:
1. Push your code to GitHub.
2. In [Render](https://render.com) or [Railway](https://railway.app), click **New + -> Web Service** and connect your GitHub repository.
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. In **Environment Variables**, add:
   - `TELEGRAM_BOT_TOKEN` = `your_token_here`
   - `TELEGRAM_CHAT_ID` = `your_chat_id_here`
   - `APP_ENV` = `production`
   - `SCANNER_ENABLED` = `true`
6. Click **Deploy**.

---

## 🔗 Step 4: Setting Up Telegram Webhook (For Interactive Commands)

To allow the bot to respond immediately to user interactive commands (`/scan`, `/signal EUR/USD`, `/account`, `/help`) via Telegram:

Run this command from your terminal or browser (replace `<YOUR_BOT_TOKEN>` and `<YOUR_DOMAIN>`):
```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://yourdomain.com/api/v1/telegram/webhook"
```

You should receive:
```json
{
  "ok": true,
  "result": true,
  "description": "Webhook was set"
}
```

To verify your webhook status anytime:
```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

---

## 🧪 Step 5: Verification, Monitoring & Commands Testing

### 5.1 Test Bot Commands in Telegram

Open your bot in Telegram and try the following interactive commands:

| Command | Expected Output |
| :--- | :--- |
| `/start` or `/help` | Shows the full interactive command guide and menu. |
| `/scan` | Triggers an immediate multi-market scan across EUR/USD, GBP/USD, USD/JPY, Gold. |
| `/signal EUR/USD` | Performs deep multi-pillar analysis (Structure, Sweeps, EMA/RSI, Price Action) and returns confluence score out of 100. |
| `/news` | Shows upcoming high-impact economic calendar events and blackout status. |
| `/account` | Displays virtual paper trading account balance, equity, and margin levels. |
| `/positions` | Lists all active and pending paper positions. |
| `/performance` | Shows strategy win rate %, profit factor, and total realized PnL. |
| `/backtest EUR/USD` | Runs historical backtest and returns key metrics (Sharpe, Max DD %, Win Rate). |

### 5.2 Automated Background Scanner Verification

The automated background scanner runs periodically based on `SCANNER_INTERVAL_MINUTES` (default: every 15 minutes):
1. Downloads fresh candle data.
2. Evaluates 4-pillar setups.
3. Checks economic news blackout.
4. Broadcasts qualified signals to your Telegram channel (with automatic deduplication).
5. Opens paper trading positions (if `SCANNER_AUTO_TRADE_PAPER=true`).
6. Monitors open positions and sends alerts if **TP1**, **TP2**, or **Stop Loss** are hit.

To manually trigger a scan cycle anytime via API:
```bash
curl -X POST "http://localhost:8000/api/v1/telegram/scanner/trigger?timeframe=1h&broadcast=true&auto_trade=true"
```

### 5.3 Real-Time Server Monitoring

- **Live Systemd Logs**:
  ```bash
  journalctl -u forex-bot -f
  ```
- **Health Check API**:
  ```bash
  curl http://localhost:8000/api/v1/health
  ```
- **Telegram Bot API Status**:
  ```bash
  curl http://localhost:8000/api/v1/telegram/status
  ```
- **Interactive Swagger Documentation**:
  Visit `https://yourdomain.com/docs` or `http://localhost:8000/docs` in your browser.

---

## 🔧 Step 6: Troubleshooting & Common Issues

### 1. Bot Is Not Sending Messages
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env`.
- Ensure you have clicked `/start` in your 1-on-1 chat with the bot, or added the bot as an **Administrator** to your channel/group.
- Test connection via API:
  ```bash
  curl -X POST "http://localhost:8000/api/v1/telegram/broadcast" \
       -H "Content-Type: application/json" \
       -d '{"text": "🔔 Test message from server"}'
  ```

### 2. Webhook Returns 404 / Cannot Receive Commands
- Verify your domain has a valid SSL certificate (Telegram requires HTTPS for webhooks).
- Verify Nginx is proxying requests to port 8000:
  ```bash
  sudo nginx -t && sudo systemctl reload nginx
  ```
- Check the webhook status:
  ```bash
  curl "https://api.telegram.org/bot<YOUR_TOKEN>/getWebhookInfo"
  ```

### 3. Yahoo Finance Rate Limiting
- If market candle sync encounters rate limits, set `TWELVE_DATA_API_KEY` or `ALPHA_VANTAGE_API_KEY` in `.env` for dedicated data feeds.

---

## 🏁 Summary Checklist

- [x] Created Bot via `@BotFather` and retrieved token.
- [x] Obtained user / channel `TELEGRAM_CHAT_ID`.
- [x] Configured `.env` file with bot credentials and scanner settings.
- [x] Started server using systemd service or Docker Compose.
- [x] Configured HTTPS / SSL and registered Telegram Webhook URL.
- [x] Sent `/help` and `/scan` in Telegram to verify two-way communication.

Your institutional-grade **Forex Market Analysis & Telegram Signal Bot** is now hosted and operating 24/7!
