# Line Notification Bot

[English](README.md) | **中文**

一個**通用、可擴充的通知機器人**，基於 **LINE Messaging API**。接收來自*任何*來源的 webhook payload 並推播到 LINE，支援選配的**雙向互動**（在 LINE 聊天中查詢資訊）。

**主打輕量化**：整個 bot 是單一小型 Flask 容器，閒置時記憶體約 **~60 MB**、映像檔僅數 MB — 輕到可以跑在記憶體有限的 Raspberry Pi 3 上。沒有資料庫、沒有背景 worker；整合模組只是純 Python 檔案，新增一個來源只需約 20 行程式碼加上重新 build。

**Grafana / Prometheus 整合只是其中一個整合模組**（`monitoring`）— bot 核心不依賴任何特定平台。撰寫約 20 行程式碼即可接入任何其他來源。

由於 LINE Notify 已於 2025 年 3 月終止服務，本專案改用 **LINE Messaging API**（透過 LINE Official Account）來發送訊息。

## 功能特色

- 🪶 **輕量化** — 單一 Flask + gunicorn 容器，約 60 MB RAM，無資料庫／佇列／worker；可跑在 Raspberry Pi 3 這類小型裝置上
- 🔔 **通用 webhook 橋接** — 任何 JSON 來源 → LINE 訊息
- 🧩 **可插拔整合** — 在 `line_notification_bot/integrations/` 放入模組，啟動時自動載入
- 📡 **內建整合**:
  - `monitoring` — Grafana 告警 → LINE，附 `status` / `alerts` 聊天指令
  - `generic` — 通用 `/notify` 端點，接受任意 JSON
- 💬 **雙向互動** — 可擴充的聊天指令框架（`help`、`ping`、`status`、`alerts`…）
- 👥 **多推播目標** — 一則訊息推播給多個 User/Group ID
- 🔒 **安全性** — LINE callback 使用 HMAC-SHA256 簽章驗證；`/notify` 支援選配的 bearer token
- 🐳 **Docker 就緒** — 單一容器，附 docker-compose 設定
- 🏥 **健康檢查端點** — 方便監控 bot 本身運作狀態

## 架構圖

```
  任何來源 ──► Integrations ──► Line Notification Bot ──► LINE
               （可插拔）        （Flask + gunicorn）

  Grafana      ─► POST /webhook/monitoring ─┐
  CI/CD        ─► POST /webhook/<custom>  ──┼─► format_payload() ─► LINE Push API
  排程/腳本     ─► POST /notify (generic)  ──┘
  LINE 伺服器   ─► POST /callback ◄─ LINE Reply API（聊天指令）

  整合模組介面:
    name: str
    format_payload(payload) -> IntegrationResult
    register_commands()     # 選配聊天指令
```

## 專案結構

```
line-alert-bot/
├── app.py                          # Flask 應用程式（端點）
├── line_notification_bot/
│   ├── core/
│   │   ├── config.py               # 環境變數驅動的設定
│   │   ├── line_client.py          # LINE Push/Reply 客戶端 + 簽章驗證
│   │   └── commands.py             # 聊天指令註冊表與分派器
│   └── integrations/
│       ├── registry.py             # 整合模組協定與自動載入器
│       ├── monitoring.py           # Grafana/Prometheus 整合
│       └── generic.py              # 通用 /notify 後備整合
├── tests/                          # pytest 測試套件（31 個測試）
│   ├── conftest.py                 # 共用 fixtures
│   ├── test_app.py                 # 端點測試（notify/webhook/callback）
│   ├── test_commands.py            # 聊天指令框架測試
│   └── test_integrations.py        # 格式化 + 註冊表測試
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── README.md / README.zh-TW.md
```

## 前置需求

- Docker & Docker Compose
- （選配，`monitoring` 整合用）Grafana v9 以上，需啟用 Unified Alerting
- 反向代理伺服器（Caddy、Nginx、Traefik 等），用於將 `/callback` 端點公開到網際網路
- 一個已啟用 Messaging API 的 [LINE Official Account](https://manager.line.biz/)

## 快速開始

### 1. 建立 LINE Messaging API Channel

1. 前往 [LINE Developers Console](https://developers.line.biz/console/)
2. 建立 Provider → Messaging API Channel
3. 取得以下憑證：
   - **Channel Access Token**
   - **Channel Secret**
   - **推播目標 ID（可多個）** — 你的 LINE User ID（在 Channel → Basic settings 中找到），或先加 bot 為好友後傳任意訊息，再查看 callback log 取得

### 2. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env 並填入你的 LINE 憑證
```

```env
LINE_CHANNEL_ACCESS_TOKEN=<你的_channel_access_token>
LINE_CHANNEL_SECRET=<你的_channel_secret>

# 推播目標（可多個，逗號分隔）
LINE_TARGET_IDS=<你的_line_user_id>
# （舊版單一目標 LINE_USER_ID 仍然可用）

# 選配：啟用 monitoring 的 alerts 聊天指令
GRAFANA_TOKEN=<grafana_service_account_token>

# 選配：保護通用 /notify 端點
NOTIFY_SECRET=<隨機字串>
```

### 3. 部署

```bash
docker compose up -d --build
```

驗證：
```bash
curl http://localhost:5000/health
curl http://localhost:5000/integrations
```

`line_configured` 應為 `true`，且 `/integrations` 會列出所有已載入模組。

### 4. 設定 LINE Webhook URL

在 LINE Developers Console → Messaging API 分頁 → Webhook settings：

```
https://<你的域名>/callback
```

開啟 **Use webhook**，點擊 **Verify** 確認連通（應回傳 200）。

> 如果使用路徑前綴（例如 `https://grafana.example.com/line-bot/callback`），請在反向代理中設定去除前綴並轉發到 port 5000。

### 5. 接入整合模組

#### 方式 A — Grafana（`monitoring` 整合）

在 Grafana UI → **Alerting** → **Contact points** → **+ Add contact point**：

| 欄位 | 值 |
|------|-----|
| Name | `LINE Bot` |
| Integration | Webhook |
| URL | `http://line-notification-bot:5000/webhook/monitoring`（同 Docker 網路）或 `https://<你的域名>/webhook/monitoring`（遠端） |
| HTTP Method | `POST` |

點擊 **Test** 確認 LINE 收到測試訊息，然後 **Save**。

若要啟用 `alerts` 聊天指令，請建立 Grafana service account token（Administration → Service Accounts，Role `Viewer` 以上）並設定 `GRAFANA_TOKEN`。

#### 方式 B — 任何其他來源（`generic`）

```bash
curl -X POST http://localhost:5000/notify \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${NOTIFY_SECRET}" \
  -d '{"text": "部署完成 ✅"}'
```

或使用結構化 payload（會以 key/value 摘要呈現）：

```bash
curl -X POST http://localhost:5000/notify \
  -H 'Content-Type: application/json' \
  -d '{"title": "夜間備份", "host": "db-01", "status": "ok"}'
```

#### 方式 C — 撰寫自己的整合

建立 `line_notification_bot/integrations/my_thing.py`：

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

重新建置（`docker compose up -d --build`）— 模組會被自動載入並暴露在 `POST /webhook/my_thing`。

## LINE 聊天指令

Webhook 連接後，在 LINE 中傳送以下文字訊息給 bot：

| 指令 | 來源 | 說明 |
|------|------|------|
| `help` | 核心 | 顯示可用指令 |
| `ping` | generic | 測試 bot 是否存活 |
| `status` | monitoring | 查詢 Grafana & Prometheus 健康狀態 |
| `alerts` | monitoring | 列出目前觸發中的告警（需設定 `GRAFANA_TOKEN`） |

## API 端點

| 端點 | 方法 | 用途 |
|------|------|------|
| `/health` | GET | 健康檢查 / 設定狀態 |
| `/integrations` | GET | 列出已載入的整合模組 |
| `/notify` | POST | 通用推播：任意 JSON → LINE（可選 bearer token） |
| `/webhook/<name>` | POST | 指定整合模組的進入 webhook |
| `/callback` | POST | 接收 LINE webhook 回呼（對外） |

### 測試 monitoring 整合

```bash
curl -X POST http://localhost:5000/webhook/monitoring \
  -H 'Content-Type: application/json' \
  -d '{
    "status": "firing",
    "alerts": [{
      "status": "firing",
      "labels": {"alertname": "ManualTest", "severity": "info"},
      "annotations": {"summary": "手動測試告警"}
    }],
    "commonLabels": {"alertname": "ManualTest", "severity": "info"}
  }'
```

預期回應：
```json
{"status": "sent", "targets": 1}
```

## 環境變數參考

所有設定皆透過環境變數：

| 變數 | 必填 | 預設值 | 說明 |
|------|------|--------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | — | LINE Messaging API channel access token |
| `LINE_CHANNEL_SECRET` | ✅ | — | LINE Messaging API channel secret |
| `LINE_TARGET_IDS` | ✅* | — | 推播目標（可多個，逗號分隔的 User/Group ID） |
| `LINE_USER_ID` | ❌ | — | 舊版單一推播目標（`LINE_TARGET_IDS` 未設定時使用） |
| `ENABLED_INTEGRATIONS` | ❌ | （全部） | 逗號分隔的允許清單，例如 `monitoring,generic` |
| `NOTIFY_SECRET` | ❌ | — | `POST /notify` 需帶的 bearer token |
| `GRAFANA_URL` | ❌ | `http://grafana:3000` | Grafana URL（monitoring 整合用） |
| `GRAFANA_TOKEN` | ❌ | — | Grafana service account token（`alerts` 指令用） |
| `PROMETHEUS_URLS` | ❌ | `http://prometheus:9090` | 逗號分隔的多個 Prometheus URL（健康檢查用） |
| `ALERT_SOURCES` | ❌ | — | 逗號分隔的 `needle=標籤` 配對，標示告警來自哪個 Grafana（比對 receiver 名稱 / externalURL host） |
| `ALERT_URL_REWRITES` | ❌ | — | 逗號分隔的 `內部URL=公開URL` 配對，把訊息中的內網連結改寫成公開網址 |
| `LOG_LEVEL` | ❌ | `INFO` | Python logging 等級 |
| `PORT` | ❌ | `5000` | Flask 監聽 port |
| `TZ` | ❌ | `UTC` | 容器時區 |
| `LINE_MAX_TEXT_LENGTH` | ❌ | `4800` | 長訊息自動分割的門檻 |
| `HTTP_TIMEOUT` | ❌ | `10` | 對外 HTTP 請求逾時（秒） |

\* `LINE_TARGET_IDS` 與 `LINE_USER_ID` 至少需設定一個。

## 自動化測試

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -v
```

測試涵蓋端點行為（`/notify`、`/webhook/<name>`、`/callback`）、聊天指令分派、
整合模組 payload 格式化、LINE 簽章驗證、註冊表自動載入 — 全程不產生真實網路請求
（LINE push/reply 已 stub）。

## 反向代理設定範例

### Caddy（路徑前綴）

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

LINE webhook URL：`https://grafana.example.com/line-bot/callback`

### Caddy（獨立子域名）

```Caddyfile
line-bot.example.com {
    reverse_proxy localhost:5000
}
```

LINE webhook URL：`https://line-bot.example.com/callback`

### Nginx（路徑前綴）

```nginx
location /line-bot/ {
    proxy_pass http://localhost:5000/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

## Docker 網路設定

如果監控堆疊與 bot 在**同一個 Docker 網路**中，webhook URL 可直接使用容器名稱：

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
    name: net_prometheus  # 改成你的 Grafana Docker 網路名稱
```

Grafana contact point URL：`http://line-notification-bot:5000/webhook/monitoring`

如果 Grafana 在**遠端伺服器**上，請使用公網 URL：`https://<你的域名>/webhook/monitoring`

## 管理指令

```bash
# 查看日誌
docker logs line-notification-bot -f

# 重啟
docker compose restart

# 修改程式碼後重新建置
docker compose up -d --build

# 健康檢查
curl http://localhost:5000/health

# 公網健康檢查
curl https://<你的域名>/health
```

## 專案結構

請參考上方[專案結構](#專案結構)說明。

## 技術棧

- **Python 3.12** + **Flask 3.0** + **Gunicorn**
- **LINE Messaging API**（Push + Reply 端點）
- **Docker** / **Docker Compose**

## 授權條款

MIT