# LINE Alert Bot

[English](README.md) | **中文**

一個輕量級的 Webhook 橋接服務，將 **Grafana 告警通知**轉發到 **LINE Messaging API**，並支援選配的**雙向互動**功能（在 LINE 聊天中查詢系統狀態）。

由於 LINE Notify 已於 2025 年 3 月終止服務，本專案改用 **LINE Messaging API**（透過 LINE Official Account）來發送告警訊息。

## 功能特色

- 🔔 **單向告警推播** — Grafana webhook → LINE 訊息
- 💬 **雙向互動** — 在 LINE 中回覆 `status`、`alerts` 或 `help` 查詢監控狀態
- 🔒 **簽章驗證** — 使用 HMAC-SHA256 驗證 LINE webhook 回呼
- 🐳 **Docker 就緒** — 單一容器，附 docker-compose 設定
- 🏥 **健康檢查端點** — 方便監控 bot 本身運作狀態

## 架構圖

```
┌─────────────────────────────────────────────────────────────┐
│  Grafana Alerting                                           │
│    └─ Contact Point (Webhook)                               │
│         └─ POST /push  ──────────────┐                      │
└──────────────────────────────────────│──────────────────────┘
                                       ▼
                              ┌─────────────────┐
                              │  line-alert-bot  │
                              │  (Flask+gunicorn) │
                              │                  │
                              │  /push    ◄── Grafana webhook
                              │  /callback ◄── LINE webhook
                              │  /health  ◄── 監控用
                              └───────┬──────────┘
                                      │
                          ┌───────────┴───────────┐
                          ▼                       ▼
                   LINE Push API           LINE Reply API
                   (發送告警)             (回覆使用者)
                          │                       ▲
                          ▼                       │
                    ┌──────────┐          ┌──────────────┐
                    │ 你的 LINE │          │ LINE 伺服器   │
                    │  手機     │ ────────►│ (webhook      │
                    └──────────┘  訊息     │  callback)    │
                                          └──────────────┘
```

## 前置需求

- Docker & Docker Compose
- Grafana（v9 以上，需啟用 Unified Alerting）
- 反向代理伺服器（Caddy、Nginx、Traefik 等），用於將 `/callback` 端點公開到網際網路
- 一個已啟用 Messaging API 的 [LINE Official Account](https://manager.line.biz/)

## 快速開始

### 1. 建立 LINE Messaging API Channel

1. 前往 [LINE Developers Console](https://developers.line.biz/console/)
2. 建立 Provider → Messaging API Channel
3. 取得以下憑證：
   - **Channel Access Token**
   - **Channel Secret**
   - **你的 LINE User ID**（在 Channel → Basic settings 中找到，或先加 bot 為好友後傳任意訊息，再查看 callback log 取得）

### 2. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env 並填入你的 LINE 憑證
```

```env
LINE_CHANNEL_ACCESS_TOKEN=<你的_channel_access_token>
LINE_CHANNEL_SECRET=<你的_channel_secret>
LINE_USER_ID=<你的_line_user_id>

# 選配：用於雙向互動的 alerts 指令
GRAFANA_TOKEN=<grafana_service_account_token>

# 選配：覆寫預設值
GRAFANA_URL=http://grafana:3000
PROMETHEUS_URLS=http://prometheus:9090
```

### 3. 部署

```bash
docker compose up -d --build
```

驗證：
```bash
curl http://localhost:5000/health
```

所有 `*_configured` 欄位應為 `true`。

### 4. 設定 LINE Webhook URL

在 LINE Developers Console → Messaging API 分頁 → Webhook settings：

```
https://<你的域名>/callback
```

開啟 **Use webhook**，點擊 **Verify** 確認連通（應回傳 200）。

> 如果使用路徑前綴（例如 `https://grafana.example.com/line-bot/callback`），請在反向代理中設定去除前綴並轉發到 port 5000。

### 5. 設定 Grafana Contact Point

在 Grafana UI → **Alerting** → **Contact points** → **+ Add contact point**：

| 欄位 | 值 |
|------|-----|
| Name | `LINE Bot` |
| Integration | Webhook |
| URL | `http://line-alert-bot:5000/push`（同 Docker 網路）或 `https://<你的域名>/push`（遠端） |
| HTTP Method | `POST` |

點擊 **Test** 確認 LINE 收到測試訊息，然後 **Save**。

### 6.（選配）設定 Grafana Service Account Token

若要啟用 `alerts` 雙向互動指令：

1. Grafana → **Administration** → **Service Accounts** → **+ Add**
   - Role：`Viewer`（最低權限）
2. 產生 token 並加入 `.env` 中的 `GRAFANA_TOKEN`
3. 重啟：`docker compose restart`

## LINE 聊天指令

Webhook 連接後，在 LINE 中傳送以下文字訊息給 bot：

| 指令 | 說明 |
|------|------|
| `status` | 查詢 Grafana & Prometheus 健康狀態 |
| `alerts` | 列出目前觸發中的告警（需設定 `GRAFANA_TOKEN`） |
| `help` | 顯示可用指令 |

## API 端點

| 端點 | 方法 | 用途 |
|------|------|------|
| `/health` | GET | 健康檢查 / 設定狀態 |
| `/push` | POST | 接收 Grafana webhook 告警（內部） |
| `/callback` | POST | 接收 LINE webhook 回呼（對外） |

### 手動測試推播

```bash
curl -X POST http://localhost:5000/push \
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
{"status": "sent"}
```

## 環境變數參考

所有設定皆透過環境變數：

| 變數 | 必填 | 預設值 | 說明 |
|------|------|--------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | — | LINE Messaging API channel access token |
| `LINE_CHANNEL_SECRET` | ✅ | — | LINE Messaging API channel secret |
| `LINE_USER_ID` | ✅ | — | 推播目標的 LINE User ID |
| `GRAFANA_URL` | ❌ | `http://grafana:3000` | Grafana URL（雙向查詢用） |
| `GRAFANA_TOKEN` | ❌ | — | Grafana service account token（`alerts` 指令用） |
| `PROMETHEUS_URLS` | ❌ | `http://prometheus:9090` | 逗號分隔的多個 Prometheus URL（健康檢查用） |
| `LOG_LEVEL` | ❌ | `INFO` | Python logging 等級 |
| `PORT` | ❌ | `5000` | Flask 監聽 port |

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

如果 Grafana 和 line-alert-bot 在**同一個 Docker 網路**中，webhook URL 可直接使用容器名稱：

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
    name: net_prometheus  # 改成你的 Grafana Docker 網路名稱
```

Grafana contact point URL：`http://line-alert-bot:5000/push`

如果 Grafana 在**遠端伺服器**上，請使用公網 URL：`https://<你的域名>/push`

## 管理指令

```bash
# 查看日誌
docker logs line-alert-bot -f

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

```
line-alert-bot/
├── app.py              # Flask 應用程式
├── Dockerfile          # 容器映像定義
├── docker-compose.yml  # Docker Compose 設定
├── requirements.txt    # Python 依賴套件
├── .env.example        # 環境變數範本
└── README.md           # 英文說明文件
└── README.zh-TW.md     # 本文件
```

## 技術棧

- **Python 3.12** + **Flask 3.0** + **Gunicorn**
- **LINE Messaging API**（Push + Reply 端點）
- **Docker** / **Docker Compose**

## 授權條款

MIT