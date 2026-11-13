"""Tekilleştirme: aynı link, daha önce görülen haber ve benzer başlıklar."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .collector import Article
from .config import SEEN_FILE

SEEN_KEEP_DAYS = 30
TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|ref$|ref_src$|mc_|cmpid$|ftag$|taid$)")

STOPWORDS = {
    # en
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "with",
    "at", "by", "from", "its", "it", "as", "be", "this", "that", "new", "now", "after",
    # tr
    "ve", "ile", "bir", "bu", "da", "de", "için", "mi", "mı", "ne", "o", "çok", "daha",
    "gibi", "olarak", "oldu", "yeni", "geliyor", "açıklandı",
}


def normalize_url(url: str) -> str:
    """Takip parametreleri, #parça, sondaki / ve http/https farkı atılır."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k.lower())]
    path = parts.path.rstrip("/") or "/"
    host = parts.netloc.lower().removeprefix("www.")
    return urlunsplit(("https", host, path, urlencode(query), ""))


def url_key(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def _tr_lower(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower()


def title_tokens(title: str) -> set[str]:
    text = unicodedata.normalize("NFC", _tr_lower(title))
    words = re.findall(r"[0-9a-zçğıöşüâîû]+", text)
    return {w for w in words if len(w) > 1 and w not in STOPWORDS}


def similar_titles(a: str, b: str) -> bool:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    jaccard = len(ta & tb) / len(ta | tb)
    if jaccard >= 0.6 and min(len(ta), len(tb)) >= 3:
        return True
    ratio = SequenceMatcher(None, _tr_lower(a), _tr_lower(b)).ratio()
    return ratio >= 0.85


class SeenStore:
    """state/seen.json: {url_key: ISO tarih}. 30 günden eski kayıtlar budanır."""

    def __init__(self, path: Path = SEEN_FILE):
        self.path = Path(path)
        self.data: dict[str, str] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8")) or {}
            except json.JSONDecodeError:
                self.data = {}

    def __contains__(self, url: str) -> bool:
        return url_key(url) in self.data

    def add(self, url: str, when: datetime | None = None) -> None:
        when = when or datetime.now(timezone.utc)
        self.data[url_key(url)] = when.isoformat(timespec="seconds")

    def prune(self, now: datetime | None = None, keep_days: int = SEEN_KEEP_DAYS) -> None:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=keep_days)
        self.data = {
            k: v for k, v in self.data.items() if datetime.fromisoformat(v) >= cutoff
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def dedupe(articles: list[Article], seen: SeenStore | None = None) -> list[Article]:
    """Görülmüş ve tekrarlanan haberleri atar.

    Benzer başlıklı haberler gruplanır; en erken yayınlanan temsilci olur,
    diğer kaynakların adları `related` alanına eklenir.
    Sonuç yeniden eskiye sıralanır.
    """
    by_url: dict[str, Article] = {}
    for art in sorted(articles, key=lambda a: a.published):
        key = url_key(art.url)
        if seen is not None and art.url in seen:
            continue
        if key not in by_url:
            by_url[key] = art

    groups: list[Article] = []
    for art in by_url.values():  # eskiden yeniye
        for rep in groups:
            if similar_titles(rep.title, art.title):
                if art.source != rep.source and art.source not in rep.related:
                    rep.related.append(art.source)
                break
        else:
            groups.append(art)
    groups.sort(key=lambda a: a.published, reverse=True)
    return groups
