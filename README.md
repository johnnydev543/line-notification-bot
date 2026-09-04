# Line Notification Bot

**English** | [中文](README.zh-TW.md)

A **generic, extensible notification bot** built on the **LINE Messaging API**. It accepts webhook payloads from *any* source and pushes messages to LINE, with optional **bidirectional interaction** (query things from LINE chat).

**Designed to be lightweight**: the whole bot is a single small Flask container that idles at roughly **~60 MB RAM** and a few MB of image — light enough for a Raspberry Pi 3 with limited memory. No database, no background workers; integrations are just plain Python modules, so adding a new source is a ~20-line file plus a rebuild.

**Grafana / Prometheus integration is just one of the available integrations** (`monitoring`) — the bot core does not depend on any specific platform. Write your own integration in ~20 lines to connect anything else.

Since LINE Notify was deprecated in March 2025, this project uses the **LINE Messaging API** (via LINE Official Account) to deliver messages.

## Features

- 🪶 **Lightweight** — single Flask + gunicorn container, ~60 MB RAM, no DB/queue/worker; fits small boards like a Raspberry Pi 3
- 🔔 **Generic webhook bridge** — any JSON source → LINE message
- 🧩 **Pluggable integrations** — drop a module in `line_notification_bot/integrations/`, auto-discovered at startup
- 📡 **Built-in integrations**:
  - `monitoring` — Grafana alerts → LINE, plus `status` / `alerts` chat commands
  - `generic` — universal `/notify` endpoint for arbitrary JSON
- 💬 **Two-way interaction** — extensible chat command framework (`help`, `ping`, `status`, `alerts`, …)
- 👥 **Multiple push targets** — one message to many User/Group IDs
- 🔒 **Security** — HMAC-SHA256 signature verification for LINE callbacks; optional bearer-token on `/notify`
- 🐳 **Docker-ready** — single container, docker-compose included
- 🏥 **Health check endpoint** — for monitoring the bot itself

## Architecture

```
  any source ──► Integrations ──► Line Notification Bot ──► LINE
                 (pluggable)       (Flask + gunicorn)

  Grafana      ─► POST /webhook/monitoring ─┐
  CI/CD        ─► POST /webhook/<custom>  ──┼─► format_payload() ─► LINE Push API
  Cron/scripts ─► POST /notify (generic)  ──┘
  LINE server  ─► POST /callback ◄─ LINE Reply API (chat commands)

  Integration contract:
    name: str
    format_payload(payload) -> IntegrationResult
    register_commands()     # optional chat commands
```

## Project Layout

```
line-alert-bot/
├── app.py                          # Flask application (endpoints)
├── line_notification_bot/
│   ├── core/
│   │   ├── config.py               # Env-driven configuration
│   │   ├── line_client.py          # LINE Push/Reply client + signature verify
│   │   └── commands.py             # Chat command registry & dispatcher
│   └── integrations/
│       ├── registry.py             # Integration protocol & auto-loader
│       ├── monitoring.py           # Grafana/Prometheus integration
│       └── generic.py              # Universal /notify fallback integration
├── tests/                          # pytest suite (31 tests)
│   ├── conftest.py                 # Shared fixtures
│   ├── test_app.py                 # Endpoint tests (notify/webhook/callback)
│   ├── test_commands.py            # Chat command framework tests
│   └── test_integrations.py        # Formatting + registry tests
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── README.md / README.zh-TW.md
```

## Prerequisites

- Docker & Docker Compose
- (Optional, for `monitoring` integration) Grafana v9+ with Unified Alerting
- A reverse proxy (Caddy, Nginx, Traefik, etc.) to expose `/callback` publicly
- A [LINE Official Account](https://manager.line.biz/) with Messaging API enabled

## Quick Start

### 1. Create a LINE Messaging API Channel

1. Go to [LINE Developers Console](https://developers.line.biz/console/)
2. Create a Provider → Messaging API Channel
3. Obtain:
   - **Channel Access Token**
   - **Channel Secret**
   - **Push target ID(s)** — your LINE User ID (Channel → Basic settings), or add the bot as a friend and send it a message, then check the callback logs for your `userId`

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env and fill in your LINE credentials
```

```env
LINE_CHANNEL_ACCESS_TOKEN=<your_channel_access_token>
LINE_CHANNEL_SECRET=<your_channel_secret>

# One or more targets, comma-separated
LINE_TARGET_IDS=<your_line_user_id>
# (legacy single-target LINE_USER_ID also works)

# Optional: enable the monitoring "alerts" chat command
GRAFANA_TOKEN=<grafana_service_account_token>

# Optional: protect the generic /notify endpoint
NOTIFY_SECRET=<random_string>
```

### 3. Deploy

```bash
docker compose up -d --build
```

Verify:
```bash
curl http://localhost:5000/health
curl http://localhost:5000/integrations
```

`line_configured` should be `true`, and `/integrations` lists all loaded modules.

### 4. Set Up LINE Webhook URL

In LINE Developers Console → Messaging API tab → Webhook settings:

```
https://<your-domain>/callback
```

Enable **Use webhook** and click **Verify** (should return 200).

> If using a path prefix (e.g., `https://grafana.example.com/line-bot/callback`), configure your reverse proxy to strip the prefix and forward to port 5000.

### 5. Connect an Integration

#### Option A — Grafana (`monitoring` integration)

In Grafana UI → **Alerting** → **Contact points** → **+ Add contact point**:

| Field | Value |
|-------|-------|
| Name | `LINE Bot` |
| Integration | Webhook |
| URL | `http://line-notification-bot:5000/webhook/monitoring` (same Docker network) or `https://<your-domain>/webhook/monitoring` (remote) |
| HTTP Method | `POST` |

Click **Test** to verify your LINE receives a test message, then **Save**.

For the `alerts` chat command, create a Grafana service account token (Administration → Service Accounts, Role `Viewer`+) and set `GRAFANA_TOKEN`.

#### Option B — Any other source (`generic`)

```bash
curl -X POST http://localhost:5000/notify \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${NOTIFY_SECRET}" \
  -d '{"text": "Deploy finished ✅"}'
```

Or a structured payload (rendered as a key/value summary):

```bash
curl -X POST http://localhost:5000/notify \
  -H 'Content-Type: application/json' \
  -d '{"title": "Nightly Backup", "host": "db-01", "status": "ok"}'
```

#### Option C — Write your own integration

Create `line_notification_bot/integrations/my_thing.py`:

```python
from ..core.commands import register_command
from .registry import IntegrationResult


class MyThingIntegration:
    name = "my_thing"

    def format_payload(self, payload: dict) -> IntegrationResult:
        text = f"🚀 {payload.get('event', 'Event')} — {payload.get('detail', '')}"
        return IntegrationResult(ok=True, messages=[{"type": "text", "text": text}])

    def register_commands(self) -> None:
        register_command("mything", "查詢 my_thing 狀態", lambda a, t: "OK")


integration = MyThingIntegration()
```

Rebuild (`docker compose up -d --build`) — it is auto-discovered and exposed at `POST /webhook/my_thing`.

## LINE Chat Commands

Once the webhook is connected, send these text messages to your bot in LINE:

| Command | Source | Description |
|---------|--------|-------------|
| `help` | core | Show available commands |
| `ping` | generic | Check the bot is alive |
| `status` | monitoring | Query Grafana & Prometheus health status |
| `alerts` | monitoring | List currently firing alerts (requires `GRAFANA_TOKEN`) |

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check / config status |
| `/integrations` | GET | List loaded integrations |
| `/notify` | POST | Generic push: any JSON → LINE (bearer-token optional) |
| `/webhook/<name>` | POST | Inbound webhook for a named integration |
| `/callback` | POST | Receive LINE webhook callbacks (public) |

### Example: Monitoring Integration Test

```bash
curl -X POST http://localhost:5000/webhook/monitoring \
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
{"status": "sent", "targets": 1}
```

## Configuration Reference

All configuration is via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | — | LINE Messaging API channel access token |
| `LINE_CHANNEL_SECRET` | ✅ | — | LINE Messaging API channel secret |
| `LINE_TARGET_IDS` | ✅* | — | Push target(s), comma-separated User/Group IDs |
| `LINE_USER_ID` | ❌ | — | Legacy single push target (used if `LINE_TARGET_IDS` empty) |
| `ENABLED_INTEGRATIONS` | ❌ | *(all)* | Comma-separated allowlist, e.g. `monitoring,generic` |
| `NOTIFY_SECRET` | ❌ | — | Bearer token required on `POST /notify` |
| `GRAFANA_URL` | ❌ | `http://grafana:3000` | Grafana URL (monitoring integration) |
| `GRAFANA_TOKEN` | ❌ | — | Grafana service account token (for `alerts` command) |
| `PROMETHEUS_URLS` | ❌ | `http://prometheus:9090` | Comma-separated Prometheus URLs for health check |
| `LOG_LEVEL` | ❌ | `INFO` | Python logging level |
| `PORT` | ❌ | `5000` | Flask listen port |
| `TZ` | ❌ | `UTC` | Container timezone |
| `LINE_MAX_TEXT_LENGTH` | ❌ | `4800` | Auto-split threshold for long messages |
| `HTTP_TIMEOUT` | ❌ | `10` | Outbound HTTP timeout (seconds) |

\* At least one of `LINE_TARGET_IDS` / `LINE_USER_ID` must be set.

## Testing

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -v
```

The suite covers endpoint behaviour (`/notify`, `/webhook/<name>`, `/callback`),
chat command dispatch, integration payload formatting, LINE signature
verification, and registry auto-discovery — all without real network calls
(LINE push/reply is stubbed).

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

If your monitoring stack and the bot are on the **same Docker network**, use the container name as the webhook URL:

```yaml
# docker-compose.yml
services:
  line-notification-bot:
    # ...
    networks:
      - monitoring

networks:
  monitoring:
    external: true
    name: net_prometheus  # or your Grafana network name
```

Grafana contact point URL: `http://line-notification-bot:5000/webhook/monitoring`

If Grafana is on a **remote server**, use the public URL: `https://<your-domain>/webhook/monitoring`

## Management

```bash
# View logs
docker logs line-notification-bot -f

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

See [Project Layout](#project-layout) above.

## Tech Stack

- **Python 3.12** + **Flask 3.0** + **Gunicorn**
- **LINE Messaging API** (Push + Reply endpoints)
- **Docker** / **Docker Compose**

## License

MIT