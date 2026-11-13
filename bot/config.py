"""Proje yolları ve ayar dosyalarının yüklenmesi.

Mutlak yol sabitlenmez; proje kökü bu dosyanın konumundan bulunur.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "feeds.yaml"
STATE_DIR = ROOT / "state"
SEEN_FILE = STATE_DIR / "seen.json"
OUTPUT_DIR = ROOT / "output"
LOGS_DIR = ROOT / "logs"

CATEGORIES = ("teknoloji", "oyun")


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    category: str
    lang: str = "en"
    enabled: bool = True
    topic: str | None = None  # ör. "ai" — yapay zekâ odaklı kaynak
    tz: str | None = None  # tarihleri saat dilimsiz veren kaynaklar için (ör. Europe/Istanbul)


def load_feeds(path: Path = FEEDS_FILE) -> list[Feed]:
    """feeds.yaml'ı okur, hatalı kayıtları açık bir mesajla reddeder."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    feeds: list[Feed] = []
    for i, raw in enumerate(data.get("feeds") or [], start=1):
        missing = [k for k in ("name", "url", "category") if not raw.get(k)]
        if missing:
            raise ValueError(f"feeds.yaml {i}. kayıt: eksik alan(lar): {', '.join(missing)}")
        if raw["category"] not in CATEGORIES:
            raise ValueError(f"feeds.yaml '{raw['name']}': category {CATEGORIES} içinden olmalı")
        feed = Feed(
            name=str(raw["name"]),
            url=str(raw["url"]),
            category=raw["category"],
            lang=str(raw.get("lang", "en")),
            enabled=bool(raw.get("enabled", True)),
            topic=raw.get("topic"),
            tz=raw.get("tz"),
        )
        if feed.enabled:
            feeds.append(feed)
    return feeds
