"""Ortam değişkenleri (.env) ve gizli değerlerin maskelenmesi.

Kural: gizli değerler hiçbir zaman ekrana/loglara tam olarak yazılmaz.
Dışarıya giden her mesaj `scrub()` ile temizlenir.
"""
from __future__ import annotations

import os
import re

from dotenv import load_dotenv

from .config import ROOT

ENV_FILE = ROOT / ".env"
SECRET_KEYS = (
    "GEMINI_API_KEY",
    "CF_API_TOKEN",
    "CF_ACCOUNT_ID",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "IG_ACCESS_TOKEN",
    "IG_USER_ID",
)
DEFAULT_MODE = "dry-run"
MODES = ("dry-run", "approve", "auto")

_loaded = False


def load_env() -> None:
    """Proje kökündeki .env'yi yükler. Ortamda zaten olan değerler (GitHub Actions) ezilmez."""
    global _loaded
    if not _loaded:
        if ENV_FILE.exists():
            load_dotenv(ENV_FILE, override=False)
        _loaded = True


def get(name: str, default: str = "") -> str:
    load_env()
    return (os.environ.get(name) or default).strip()


def mode() -> str:
    m = get("MODE", DEFAULT_MODE).lower()
    return m if m in MODES else DEFAULT_MODE


def mask(value: str) -> str:
    """En fazla son 4 karakteri gösterir; kısa değerlerde hiç göstermez."""
    value = value or ""
    if len(value) <= 8:
        return "••••"
    return "••••" + value[-4:]


def scrub(text: str) -> str:
    """Metindeki bilinen gizli değerleri maskeler (hata mesajları, URL'ler vb.)."""
    load_env()
    text = str(text)
    for key in SECRET_KEYS:
        val = (os.environ.get(key) or "").strip()
        if len(val) >= 4:
            text = text.replace(val, mask(val))
    # Telegram token'ı URL içinde başka biçimde geçerse
    text = re.sub(r"bot\d{6,}:[A-Za-z0-9_-]{20,}", "bot••••", text)
    return text
