"""Telegram Bot API: bildirim ve önizleme.

Token URL içinde geçtiği için hata mesajları her zaman scrub() ile temizlenir.
"""
from __future__ import annotations

import requests

from . import settings

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 30


class TelegramError(RuntimeError):
    pass


def _call(method: str, data: dict | None = None, files: dict | None = None) -> dict:
    token = settings.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN boş")
    try:
        resp = requests.post(API.format(token=token, method=method), data=data, files=files, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise TelegramError(settings.scrub(f"bağlantı hatası: {type(exc).__name__}")) from None
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code != 200 or not body.get("ok"):
        desc = body.get("description", "")
        raise TelegramError(settings.scrub(f"{resp.status_code} {desc}".strip()))
    return body["result"]


def get_me() -> dict:
    return _call("getMe")


def send_message(text: str, disable_preview: bool = True) -> dict:
    chat_id = settings.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise TelegramError("TELEGRAM_CHAT_ID boş")
    return _call(
        "sendMessage",
        {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": disable_preview},
    )


def notify(text: str) -> bool:
    """Bildirim gönderir; başarısız olursa programı durdurmaz."""
    try:
        send_message(text)
        return True
    except TelegramError:
        return False
