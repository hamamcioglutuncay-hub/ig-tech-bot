"""RSS/Atom kaynaklarından son N saatin haberlerini toplar."""
from __future__ import annotations

import calendar
import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

import feedparser
import requests
from zoneinfo import ZoneInfo

from .config import Feed

USER_AGENT = "Mozilla/5.0 (compatible; ig-tech-bot/0.1; RSS reader)"
TIMEOUT = 20
SUMMARY_MAX = 600

# fetcher(url) -> ham bayt içerik. Testlerde ağ yerine sahte fetcher verilir.
Fetcher = Callable[[str], bytes]


@dataclass
class Article:
    title: str
    url: str
    source: str
    category: str
    lang: str
    published: datetime
    summary: str = ""
    topic: str | None = None
    related: list[str] = field(default_factory=list)  # aynı olayı veren diğer kaynaklar


@dataclass
class CollectResult:
    articles: list[Article]
    errors: dict[str, str]          # kaynak adı -> hata
    counts: dict[str, int]          # kaynak adı -> zaman penceresindeki haber sayısı


def http_fetch(url: str, retries: int = 1) -> bytes:
    """Kısa bağlantı kopmalarına karşı 1 kez yeniden dener."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.content
        except (requests.ConnectionError, requests.Timeout):
            if attempt == retries:
                raise
            time.sleep(2)
    raise AssertionError("unreachable")


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(text: str, limit: int = SUMMARY_MAX) -> str:
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    text = _WS_RE.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_HAS_TZ = re.compile(r"(Z|[+-]\d{2}:?\d{2}|GMT|UTC|\b[A-Z]{3,4})\s*$")


def _entry_time(entry, feed_tz: str | None = None) -> datetime | None:
    for key in ("published", "updated"):
        t = entry.get(f"{key}_parsed")
        if not t:
            continue
        # feedparser zamanları UTC struct_time olarak verir
        dt = datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
        raw = (entry.get(key) or "").strip()
        if feed_tz and raw and not _HAS_TZ.search(raw):
            # Saat dilimsiz tarih: feedparser UTC sandı, aslında kaynağın yerel saati
            dt = dt.replace(tzinfo=ZoneInfo(feed_tz)).astimezone(timezone.utc)
        return dt
    return None


def parse_feed(feed: Feed, content: bytes, since: datetime, now: datetime) -> list[Article]:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"akış okunamadı: {type(parsed.bozo_exception).__name__}")
    articles = []
    for e in parsed.entries:
        title = clean_text(e.get("title", ""), 300)
        link = (e.get("link") or "").strip()
        published = _entry_time(e, feed.tz)
        # Tarihsiz haberler 24 saat kuralını doğrulayamadığımız için atlanır.
        if not title or not link or published is None:
            continue
        # Geleceğe tarihli (saat dilimi hatalı) haberleri "şimdi" kabul et
        if published > now + timedelta(hours=1):
            published = now
        if published < since:
            continue
        summary = e.get("summary") or ""
        if not summary and e.get("content"):
            summary = e["content"][0].get("value", "")
        articles.append(
            Article(
                title=title,
                url=link,
                source=feed.name,
                category=feed.category,
                lang=feed.lang,
                published=published,
                summary=clean_text(summary),
                topic=feed.topic,
            )
        )
    return articles


def collect(
    feeds: list[Feed],
    hours: float = 24,
    now: datetime | None = None,
    fetcher: Fetcher = http_fetch,
    workers: int = 16,
) -> CollectResult:
    """Tüm kaynakları paralel okur. Bir kaynağın hatası diğerlerini etkilemez."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    def one(feed: Feed):
        try:
            return feed, parse_feed(feed, fetcher(feed.url), since, now), None
        except Exception as exc:  # noqa: BLE001 — her hata raporlanır, akış durmaz
            msg = f"{type(exc).__name__}: {exc}"
            return feed, [], msg[:200]

    articles: list[Article] = []
    errors: dict[str, str] = {}
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for feed, items, err in pool.map(one, feeds):
            counts[feed.name] = len(items)
            if err:
                errors[feed.name] = err
            articles.extend(items)
    articles.sort(key=lambda a: a.published, reverse=True)
    return CollectResult(articles=articles, errors=errors, counts=counts)
