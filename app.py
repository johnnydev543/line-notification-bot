#!/usr/bin/env python3
"""
Line Notification Bot — a generic webhook-to-LINE bridge.

Endpoints:
  POST /notify              — 通用通知 API（任意 JSON → LINE）
  POST /webhook/<name>      — 整合模組專用 webhook（如 /webhook/monitoring）
  POST /callback            — LINE Messaging API Webhook（雙向互動）
  GET  /health              — 健康檢查
  GET  /integrations        — 列出已載入的整合模組

Grafana / Prometheus 只是其中一個整合（monitoring），
bot 本身不依賴任何特定平台。
"""

import json
import logging

from flask import Flask, abort, jsonify, request

from line_notification_bot.core import commands
from line_notification_bot.core.config import config
from line_notification_bot.core.line_client import line_client
from line_notification_bot.integrations import registry

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=config.log_level,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("line_notification_bot")

# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
app = Flask(__name__)


# ---------------------------------------------------------------------------
# Startup: load integrations + default commands
# ---------------------------------------------------------------------------
def _initialize() -> None:
    commands.init_default_commands()
    loaded = registry.load_integrations()
    for name in loaded:
        if not registry.is_enabled(name):
            logger.info(
                "Integration %r loaded but disabled by ENABLED_INTEGRATIONS", name
            )


_initialize()


# ---------------------------------------------------------------------------
# Routes: health & info
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    """Health check + config status."""
    return jsonify(
        {
            "status": "ok",
            "line_configured": config.line_configured,
            **config.summary(),
        }
    )


@app.route("/integrations", methods=["GET"])
def list_integrations():
    """List loaded integrations (discovery / debugging)."""
    return jsonify(
        {
            "integrations": [
                {"name": name, "webhook": f"/webhook/{name}"}
                for name in registry.all_integrations()
                if registry.is_enabled(name)
            ]
        }
    )


# ---------------------------------------------------------------------------
# Route: generic notify API
# ---------------------------------------------------------------------------
@app.route("/notify", methods=["POST"])
def notify():
    """通用通知 API — 接受任意 JSON，轉發為 LINE 訊息給所有目標。

    Security: 若設定 NOTIFY_SECRET，請求需帶
    ``Authorization: Bearer <NOTIFY_SECRET>``。
    """
    if config.notify_secret:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {config.notify_secret}":
            abort(401)

    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "invalid JSON"}), 400

    return _dispatch_to_integration("generic", payload)


# ---------------------------------------------------------------------------
# Route: integration webhooks
# ---------------------------------------------------------------------------
@app.route("/webhook/<name>", methods=["POST"])
def integration_webhook(name: str):
    """Inbound webhook for a named integration (e.g. /webhook/monitoring)."""
    if registry.get(name) is None or not registry.is_enabled(name):
        return jsonify({"error": f"unknown integration: {name}"}), 404

    payload = request.get_json(silent=True)
    if payload is None:
        logger.warning("Invalid JSON on /webhook/%s", name)
        return jsonify({"error": "invalid JSON"}), 400

    return _dispatch_to_integration(name, payload)


@app.route("/push", methods=["POST"])
def push_legacy():
    """Deprecated alias for /webhook/monitoring (backwards compatibility).

    Kept so existing Grafana contact points pointing at ``/push`` keep
    working after the rename. Prefer ``/webhook/monitoring`` in new setups.
    """
    logger.info("Deprecated /push called — use /webhook/monitoring instead")
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "invalid JSON"}), 400
    return _dispatch_to_integration("monitoring", payload)


def _dispatch_to_integration(name: str, payload: dict):
    """Format an inbound payload and push it to LINE targets."""
    integration = registry.get(name)
    if integration is None:
        return jsonify({"error": f"unknown integration: {name}"}), 404

    try:
        result = integration.format_payload(payload)
    except Exception:  # noqa: BLE001
        logger.exception("Integration %r failed to format payload", name)
        return jsonify({"error": "integration formatting error"}), 500

    if not result.ok:
        return jsonify({"error": result.error or "formatting failed"}), 400

    if not config.line_configured:
        logger.error("LINE not fully configured; cannot push message")
        return jsonify({"error": "LINE not configured"}), 500

    targets = result.target_ids or config.target_ids
    results = {}
    for target in targets:
        results[target] = line_client.push(target, result.messages)

    if all(results.values()):
        return jsonify({"status": "sent", "targets": len(results)}), 200
    failed = [t for t, ok in results.items() if not ok]
    logger.error("Failed to push to targets: %s", failed)
    return jsonify({"status": "partial", "failed": failed}), 500


# ---------------------------------------------------------------------------
# Route: LINE callback (bidirectional chat)
# ---------------------------------------------------------------------------
@app.route("/callback", methods=["POST"])
def callback():
    """接收 LINE Messaging API webhook callback（雙向互動）."""
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()

    if not line_client.verify_signature(body, signature):
        logger.warning("Invalid LINE signature, rejecting request")
        abort(401)

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in LINE callback")
        abort(400)

    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        if msg.get("type") != "text":
            continue

        text = msg.get("text", "")
        reply_token = event.get("replyToken", "")
        user_id = event.get("source", {}).get("userId")

        logger.info("LINE message from %s: %s", user_id, text)
        if reply_token:
            commands.dispatch_and_reply(text, reply_token, fallback_user_id=user_id)
        elif user_id:
            response = commands.handle_user_message(text)
            line_client.push_text(user_id, response)

    return "OK", 200


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = config.port
    logger.info("Starting Line Notification Bot on port %d", port)
    for key, value in config.summary().items():
        logger.info("  %s: %s", key, value)
    app.run(host="0.0.0.0", port=port)