# LINE Alert Bot

A lightweight webhook bridge that forwards **Grafana alert notifications** to **LINE Messaging API**, with optional **bidirectional interaction** (query system status from LINE chat).

Since LINE Notify was deprecated in March 2025, this project uses the **LINE Messaging API** (via LINE Official Account) to deliver alert messages.

## Features

- 🔔 **One-way alert push** — Grafana webhook → LINE message
- 💬 **Two-way interaction** — Reply `status`, `alerts`, or `help` in LINE chat to query your monitoring stack
- 🔒 **Signature verification** — Validates LINE webhook callbacks with HMAC-SHA256
- 🐳 **Docker-ready** — Single container, docker-compose included
- 🏥 **Health check endpoint** — For monitoring the bot itself

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Grafana Alerting                                           │
│    └─ Contact Point (Webhook)                               │
│         └─ POST /push  ──────────────┐                      │
└──────────────────────────────────────│──────────────────────┘
                                       ▼
                              ┌─────────────────┐
                              │  line-alert-bot  │
                              │  (Flask + gunicorn)│
                              │                  │
                              │  /push    ◄── Grafana webhook
                              │  /callback ◄── LINE webhook
                              │  /health  ◄── monitoring
                              └───────┬──────────┘
                                      │
                          ┌───────────┴───────────┐
                          ▼                       ▼
                   LINE Push API           LINE Reply API
                   (send alerts)          (reply to user)
                          │                       ▲
                          ▼                       │
                    ┌──────────┐          ┌──────────────┐
                    │ Your LINE │          │ LINE Server   │
                    │  phone    │ ────────►│ (webhook      │
                    └──────────┘  message  │  callback)    │
                                          └──────────────┘
```

## Prerequisites

- Docker & Docker Compose
- Grafana (v9+ with Unified Alerting)
- A reverse proxy (Caddy, Nginx, Traefik, etc.) to expose `/callback` publicly
- A [LINE Official Account](https://manager.line.biz/) with Messaging API enabled

## Quick Start

### 1. Create a LINE Messaging API Channel

1. Go to [LINE Developers Console](https://developers.line.biz/console/)
2. Create a Provider → Messaging API Channel
3. Obtain:
   - **Channel Access Token**
   - **Channel Secret**
   - **Your LINE User ID** (found in Channel → Basic settings, or send any message to the bot and check the callback logs)

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env and fill in your LINE credentials
```

```env
LINE_CHANNEL_ACCESS_TOKEN=<your_channel_access_token>
LINE_CHANNEL_SECRET=<your_channel_secret>
LINE_USER_ID=<your_line_user_id>

# Optional: for bidirectional "alerts" command
GRAFANA_TOKEN=<grafana_service_account_token>

# Optional: override defaults
GRAFANA_URL=http://grafana:3000
PROMETHEUS_URLS=http://prometheus:9090
```

### 3. Deploy

```bash
docker compose up -d --build
```

Verify:
```bash
curl http://localhost:5000/health
```

All `*_configured` fields should be `true`.

### 4. Set Up LINE Webhook URL

In LINE Developers Console → Messaging API tab → Webhook settings:

```
https://<your-domain>/callback
```

Enable **Use webhook** and click **Verify** (should return 200).

> If using a path prefix (e.g., `https://grafana.example.com/line-bot/callback`), configure your reverse proxy to strip the prefix and forward to port 5000.

### 5. Configure Grafana Contact Point

In Grafana UI → **Alerting** → **Contact points** → **+ Add contact point**:

| Field | Value |
|-------|-------|
| Name | `LINE Bot` |
| Integration | Webhook |
| URL | `http://line-alert-bot:5000/push` (same Docker network) or `https://<your-domain>/push` (remote) |
| HTTP Method | `POST` |

Click **Test** to verify your LINE receives a test message, then **Save**.

### 6. (Optional) Set Up Grafana Service Account Token

To enable the `alerts` bidirectional command:

1. Grafana → **Administration** → **Service Accounts** → **+ Add**
   - Role: `Viewer` (minimum)
2. Generate a token and add it to `.env` as `GRAFANA_TOKEN`
3. Restart: `docker compose restart`

## LINE Chat Commands

Once the webhook is connected, send these text messages to your bot in LINE:

| Command | Description |
|---------|-------------|
| `status` | Query Grafana & Prometheus health status |
| `alerts` | List currently firing alerts (requires `GRAFANA_TOKEN`) |
| `help` | Show available commands |

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check / config status |
| `/push` | POST | Receive Grafana webhook alerts (internal) |
| `/callback` | POST | Receive LINE webhook callbacks (public) |

### Example: Manual Push Test

```bash
curl -X POST http://localhost:5000/push \
  -H 'Content-Type: application/json' \
  -d '{
    "status": "firing",
    "alerts": [{
      "status": "firing",
      "labels": {"alertname": "ManualTest", "severity": "info"},
      "annotations": {"summary": "Manual test alert"}
    }],
    "commonLabels": {"alertname": "ManualTest", "severity": "info"}
  }'
```

Expected response:
```json
{"status": "sent"}
```

## Configuration Reference

All configuration is via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | — | LINE Messaging API channel access token |
| `LINE_CHANNEL_SECRET` | ✅ | — | LINE Messaging API channel secret |
| `LINE_USER_ID` | ✅ | — | Target LINE user ID for push messages |
| `GRAFANA_URL` | ❌ | `http://grafana:3000` | Grafana URL for bidirectional queries |
| `GRAFANA_TOKEN` | ❌ | — | Grafana service account token (for `alerts` command) |
| `PROMETHEUS_URLS` | ❌ | `http://prometheus:9090` | Comma-separated Prometheus URLs for health check |
| `LOG_LEVEL` | ❌ | `INFO` | Python logging level |
| `PORT` | ❌ | `5000` | Flask listen port |

## Reverse Proxy Examples

### Caddy (path-based)

```Caddyfile
grafana.example.com {
    handle_path /line-bot/* {
        reverse_proxy localhost:5000
    }
    handle {
        reverse_proxy localhost:3000
    }
}
```

LINE webhook URL: `https://grafana.example.com/line-bot/callback`

### Caddy (subdomain)

```Caddyfile
line-bot.example.com {
    reverse_proxy localhost:5000
}
```

LINE webhook URL: `https://line-bot.example.com/callback`

### Nginx (path-based)

```nginx
location /line-bot/ {
    proxy_pass http://localhost:5000/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

## Docker Networking

If Grafana and line-alert-bot are on the **same Docker network**, use the container name as the webhook URL:

```yaml
# docker-compose.yml
services:
  line-alert-bot:
    # ...
    networks:
      - monitoring

networks:
  monitoring:
    external: true
    name: net_prometheus  # or your Grafana network name
```

Grafana contact point URL: `http://line-alert-bot:5000/push`

If Grafana is on a **remote server**, use the public URL: `https://<your-domain>/push`

## Management

```bash
# View logs
docker logs line-alert-bot -f

# Restart
docker compose restart

# Rebuild after code changes
docker compose up -d --build

# Health check
curl http://localhost:5000/health

# Public health check
curl https://<your-domain>/health
```

## Project Structure

```
line-alert-bot/
├── app.py              # Flask application
├── Dockerfile          # Container image definition
├── docker-compose.yml  # Docker Compose configuration
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
└── README.md           # This file
```

## Tech Stack

- **Python 3.12** + **Flask 3.0** + **Gunicorn**
- **LINE Messaging API** (Push + Reply endpoints)
- **Docker** / **Docker Compose**

## License

MIT