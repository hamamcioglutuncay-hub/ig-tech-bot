"""Telegram Bot API: bildirim ve önizleme.

Token URL içinde geçtiği için hata mesajları her zaman scrub() ile temizlenir.
"""
from __future__ import annotations

import requests

from . import settings

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 120


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


def send_media_group(paths: list, caption: str | None = None) -> list:
    """En fazla 10 görseli albüm olarak gönderir. Albüm açıklaması 1024 karakterle sınırlı."""
    import json
    from pathlib import Path

    chat_id = settings.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise TelegramError("TELEGRAM_CHAT_ID boş")
    media, files = [], {}
    handles = []
    try:
        for i, p in enumerate(paths[:10]):
            key = f"photo{i}"
            fh = open(Path(p), "rb")
            handles.append(fh)
            files[key] = (Path(p).name, fh, "image/jpeg")
            entry = {"type": "photo", "media": f"attach://{key}"}
            if i == 0 and caption:
                entry["caption"] = caption[:1024]
            media.append(entry)
        return _call("sendMediaGroup", {"chat_id": chat_id, "media": json.dumps(media)}, files)
    finally:
        for fh in handles:
            fh.close()
