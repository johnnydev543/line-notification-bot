"""LINE Messaging API client (push + reply) with signature verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging

import requests

from .config import config

logger = logging.getLogger("line_notification_bot")

LINE_API_BASE = "https://api.line.me"


class LineClient:
    """Thin wrapper around the LINE Messaging API.

    Credentials are read lazily from ``config`` so runtime changes (and
    tests) take effect without re-creating the singleton.
    """

    def __init__(
        self,
        channel_access_token: str | None = None,
        channel_secret: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self._token_override = channel_access_token
        self._secret_override = channel_secret
        self._timeout_override = timeout

    # ------------------------------------------------------------------
    # Lazy config-backed attributes
    # ------------------------------------------------------------------
    @property
    def token(self) -> str:
        return self._token_override if self._token_override is not None else config.line_channel_access_token

    @property
    def secret(self) -> str:
        return self._secret_override if self._secret_override is not None else config.line_channel_secret

    @property
    def timeout(self) -> int:
        return self._timeout_override if self._timeout_override is not None else config.request_timeout

    # ------------------------------------------------------------------
    # Signature verification (for /callback)
    # ------------------------------------------------------------------
    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify the X-Line-Signature header (HMAC-SHA256 → Base64)."""
        if not self.secret or not signature:
            return False
        expected = base64.b64encode(
            hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).digest()
        ).decode("utf-8")
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _split_text(text: str, limit: int) -> list[str]:
        """Split long text into chunks within LINE's 5000-char limit."""
        if len(text) <= limit:
            return [text]
        chunks: list[str] = []
        while text:
            chunks.append(text[:limit])
            text = text[limit:]
        return chunks

    def push(self, to: str, messages: list[dict]) -> bool:
        """Send messages via the Push API. Returns True on success."""
        if not self.token:
            logger.error("LINE_CHANNEL_ACCESS_TOKEN not set, cannot send message")
            return False
        payload = {"to": to, "messages": messages}
        try:
            resp = requests.post(
                f"{LINE_API_BASE}/v2/bot/message/push",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                logger.info("LINE push sent to %s", to)
                return True
            logger.error(
                "LINE push error: %d %s", resp.status_code, resp.text[:500]
            )
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to push LINE message: %s", exc)
            return False

    def reply(self, reply_token: str, messages: list[dict]) -> bool:
        """Send messages via the Reply API (free, must respond within 30s)."""
        if not self.token or not reply_token:
            return False
        try:
            resp = requests.post(
                f"{LINE_API_BASE}/v2/bot/message/reply",
                headers=self._headers(),
                json={"replyToken": reply_token, "messages": messages},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                logger.info("LINE reply sent")
                return True
            logger.error(
                "LINE reply error: %d %s", resp.status_code, resp.text[:500]
            )
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to reply LINE message: %s", exc)
            return False

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------
    def push_text(self, to: str, text: str) -> bool:
        """Push a text message, auto-splitting if it exceeds the length limit."""
        limit = config.max_text_length
        messages = [{"type": "text", "text": chunk} for chunk in self._split_text(text, limit)]
        return self.push(to, messages)

    def broadcast_text(self, text: str) -> dict[str, bool]:
        """Push text to every configured target. Returns per-target results."""
        results: dict[str, bool] = {}
        for target in config.target_ids:
            results[target] = self.push_text(target, text)
        return results

    def reply_text(self, reply_token: str, text: str) -> bool:
        limit = config.max_text_length
        messages = [{"type": "text", "text": chunk} for chunk in self._split_text(text, limit)]
        return self.reply(reply_token, messages)


# Module-level singleton.
line_client = LineClient()