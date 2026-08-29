#!/usr/bin/env python3
"""
Grafana Alert → LINE Messaging API Webhook Bridge

Endpoints:
  POST /push      — Grafana 告警推播（內部，Grafana呼叫）
  POST /callback  — LINE Messaging API Webhook（對外，LINE 伺服器呼叫）
  GET  /health    — 健康檢查

雙向互動指令（在 LINE 中回覆）：
  status   — 查詢 Grafana 與所有 Prometheus 的健康狀態
  alerts   — 查詢 Grafana 目前的告警狀態
  help     — 顯示可用指令
"""

import hashlib
import hmac
import base64
import json
import os
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, request, abort, jsonify

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")  # 推播目標 User ID

# Grafana / Prometheus 設定（用於雙向查詢）
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://grafana:3000")
GRAFANA_TOKEN = os.environ.get("GRAFANA_TOKEN", "")  # Service Account Token
PROMETHEUS_URLS = [
    name.strip()
    for name in os.environ.get(
        "PROMETHEUS_URLS",
        "http://prometheus:9090",
    ).split(",")
    if name.strip()
]

LINE_API_URL = "https://api.line.me/v2/bot/message/push"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("line-alert-bot")

# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
app = Flask(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def verify_signature(channel_secret: str, body: bytes, signature: str) -> bool:
    """驗證 LINE webhook 簽章 (HMAC-SHA256 → Base64)."""
    if not channel_secret or not signature:
        return False
    expected = base64.b64encode(
        hmac.new(
            channel_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def send_line_message(user_id: str, messages: list[dict]) -> bool:
    """透過 LINE Messaging API push message 發送訊息."""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        logger.error("LINE_CHANNEL_ACCESS_TOKEN not set, cannot send message")
        return False
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"to": user_id, "messages": messages}
    try:
        resp = requests.post(LINE_API_URL, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("LINE message sent to %s", user_id)
            return True
        logger.error(
            "LINE API error: %d %s", resp.status_code, resp.text
        )
        return False
    except Exception as exc:
        logger.error("Failed to send LINE message: %s", exc)
        return False


def send_text(user_id: str, text: str) -> bool:
    """發送純文字訊息."""
    return send_line_message(
        user_id,
        [{"type": "text", "text": text}],
    )


def format_grafana_alert(payload: dict) -> str:
    """將 Grafana webhook payload 格式化為 LINE 文字訊息."""
    alerts = payload.get("alerts", [])
    status = payload.get("status", "unknown")
    alert_name = payload.get("commonLabels", {}).get("alertname", "Unknown Alert")
    severity = payload.get("commonLabels", {}).get("severity", "")
    firing = payload.get("alerts", [])
    firing_count = sum(1 for a in firing if a.get("status") == "firing")
    resolved_count = sum(1 for a in firing if a.get("status") == "resolved")

    # 狀態圖示
    icon = "🔥" if status == "firing" else "✅" if status == "resolved" else "⚠️"

    lines = [f"{icon} Grafana Alert: {alert_name}"]
    if severity:
        lines.append(f"Severity: {severity}")
    lines.append(f"Status: {status}")
    lines.append(f"Firing: {firing_count} | Resolved: {resolved_count}")

    # 加入各 alert 的摘要
    for alert in alerts[:5]:  # 最多顯示 5 個
        a_status = alert.get("status", "")
        a_name = alert.get("labels", {}).get("alertname", "")
        a_instance = alert.get("labels", {}).get("instance", "")
        a_icon = "🔥" if a_status == "firing" else "✅"
        detail = f"  {a_icon} {a_name}"
        if a_instance:
            detail += f" ({a_instance})"
        lines.append(detail)

    if len(alerts) > 5:
        lines.append(f"  ... 還有 {len(alerts) - 5} 個")

    # 加入 dashboard 連結
    panel_url = payload.get("panelUrl", "")
    if panel_url:
        lines.append(f"\n🔗 {panel_url}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 雙向互動：查詢功能
# ---------------------------------------------------------------------------
def query_grafana_health() -> str:
    """查詢 Grafana 健康狀態."""
    try:
        resp = requests.get(f"{GRAFANA_URL}/api/health", timeout=5)
        data = resp.json()
        return f"✅ Grafana: {data.get('version', 'unknown')} — {data.get('database', 'unknown')}"
    except Exception as exc:
        return f"❌ Grafana: {exc}"


def query_prometheus_health() -> list[str]:
    """查詢所有 Prometheus 健康狀態."""
    results = []
    for url in PROMETHEUS_URLS:
        try:
            resp = requests.get(f"{url}/-/healthy", timeout=5)
            if resp.status_code == 200:
                results.append(f"✅ Prometheus: {url}")
            else:
                results.append(f"⚠️ Prometheus: {url} (HTTP {resp.status_code})")
        except Exception as exc:
            results.append(f"❌ Prometheus: {url} — {exc}")
    return results


def query_grafana_alerts() -> str:
    """查詢 Grafana 目前的告警."""
    if not GRAFANA_TOKEN:
        return "❌ 未設定 GRAFANA_TOKEN，無法查詢告警"
    try:
        headers = {"Authorization": f"Bearer {GRAFANA_TOKEN}"}
        resp = requests.get(
            f"{GRAFANA_URL}/api/alertmanager/grafana/api/v2/alerts",
            headers=headers,
            params={"active": "true", "silenced": "false"},
            timeout=10,
        )
        if resp.status_code != 200:
            return f"❌ Grafana API 回傳 {resp.status_code}"
        alerts = resp.json()
        if not alerts:
            return "✅ 目前沒有觸發中的告警"
        lines = [f"🔥 {len(alerts)} 個觸發中的告警:"]
        for alert in alerts[:10]:
            name = alert.get("labels", {}).get("alertname", "unknown")
            severity = alert.get("labels", {}).get("severity", "")
            state = alert.get("status", {}).get("state", "")
            icon = "🔥" if state == "firing" else "⚠️"
            lines.append(f"  {icon} {name} [{severity}]")
        if len(alerts) > 10:
            lines.append(f"  ... 還有 {len(alerts) - 10} 個")
        return "\n".join(lines)
    except Exception as exc:
        return f"❌ 查詢告警失敗: {exc}"


def handle_user_message(text: str, user_id: str) -> str:
    """處理使用者從 LINE 傳來的訊息，回覆對應內容."""
    text = text.strip().lower()
    if text == "help":
        return (
            "🤖 Grafana Alert Bot 指令:\n"
            "  status  — 查詢 Grafana & Prometheus 健康狀態\n"
            "  alerts  — 查詢目前觸發中的告警\n"
            "  help    — 顯示此說明"
        )
    elif text == "status":
        lines = ["📊 系統健康狀態", query_grafana_health()]
        lines.extend(query_prometheus_health())
        return "\n".join(lines)
    elif text == "alerts":
        return query_grafana_alerts()
    else:
        return (
            f"收到: 「{text}」\n"
            "輸入 help 查看可用指令"
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    """健康檢查端點."""
    return jsonify(
        {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "line_token_configured": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "line_secret_configured": bool(LINE_CHANNEL_SECRET),
            "user_id_configured": bool(LINE_USER_ID),
        }
    )


@app.route("/push", methods=["POST"])
def push():
    """接收 Grafana 告警 webhook，轉發到 LINE."""
    payload = request.get_json(silent=True)
    if not payload:
        logger.warning("Received empty or invalid JSON on /push")
        return jsonify({"error": "invalid JSON"}), 400

    logger.info(
        "Grafana alert received: status=%s alerts=%d",
        payload.get("status"),
        len(payload.get("alerts", [])),
    )

    if not LINE_USER_ID:
        logger.error("LINE_USER_ID not set, cannot push notification")
        return jsonify({"error": "LINE_USER_ID not configured"}), 500

    message_text = format_grafana_alert(payload)
    success = send_text(LINE_USER_ID, message_text)

    if success:
        return jsonify({"status": "sent"}), 200
    return jsonify({"error": "failed to send"}), 500


@app.route("/callback", methods=["POST"])
def callback():
    """接收 LINE Messaging API 的 webhook callback（雙向互動）."""
    # 取得 LINE 簽章
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()

    # 驗證簽章
    if not verify_signature(LINE_CHANNEL_SECRET, body, signature):
        logger.warning("Invalid LINE signature, rejecting request")
        abort(401)

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in LINE callback")
        abort(400)

    events = data.get("events", [])
    for event in events:
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        if msg.get("type") != "text":
            continue

        text = msg.get("text", "")
        reply_token = event.get("replyToken", "")
        user_id = event.get("source", {}).get("userId", LINE_USER_ID)

        logger.info("LINE message from %s: %s", user_id, text)
        response_text = handle_user_message(text, user_id)

        # 使用 reply API 回覆（比 push 更即時且免費）
        if LINE_CHANNEL_ACCESS_TOKEN and reply_token:
            try:
                requests.post(
                    "https://api.line.me/v2/bot/message/reply",
                    headers={
                        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "replyToken": reply_token,
                        "messages": [{"type": "text", "text": response_text}],
                    },
                    timeout=10,
                )
            except Exception as exc:
                logger.error("Failed to reply: %s", exc)
        else:
            send_text(user_id, response_text)

    return "OK", 200


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    logger.info("Starting LINE Alert Bot on port %d", port)
    logger.info("  LINE_USER_ID: %s", "set" if LINE_USER_ID else "NOT SET")
    logger.info("  LINE_CHANNEL_ACCESS_TOKEN: %s", "set" if LINE_CHANNEL_ACCESS_TOKEN else "NOT SET")
    logger.info("  LINE_CHANNEL_SECRET: %s", "set" if LINE_CHANNEL_SECRET else "NOT SET")
    logger.info("  GRAFANA_URL: %s", GRAFANA_URL)
    logger.info("  PROMETHEUS_URLS: %s", PROMETHEUS_URLS)
    app.run(host="0.0.0.0", port=port)