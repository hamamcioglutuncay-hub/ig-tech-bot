"""Resmi Instagram API with Instagram Login — carousel yayınlama.

Akış: her slayt için görsel kabı (is_carousel_item, alt_text) → hepsi FINISHED olana dek bekle →
CAROUSEL kabı (children + caption) → media_publish → permalink.
Token hiçbir zaman loglanmaz; tüm hata mesajları settings.scrub() ile temizlenir.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from . import settings

GRAPH = "https://graph.instagram.com"
DEFAULT_VERSION = "v24.0"
TIMEOUT = 60
POLL_S = 3
WAIT_MAX_S = 180
RATE_LIMIT_CODES = {4, 17, 32, 613}


class InstagramError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, subcode: int | None = None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode


class TokenError(InstagramError):
    """Token geçersiz/süresi dolmuş (kod 190)."""


class RateLimitError(InstagramError):
    """API çağrı ya da günlük paylaşım sınırı."""


def _base() -> str:
    return f"{GRAPH}/{settings.get('IG_API_VERSION', DEFAULT_VERSION)}"


def _token() -> str:
    tok = settings.get("IG_ACCESS_TOKEN")
    if not tok:
        raise TokenError("IG_ACCESS_TOKEN boş")
    return tok


def _req(method: str, path: str, params: dict | None = None, session=requests) -> dict:
    params = dict(params or {})
    params["access_token"] = _token()
    url = f"{_base()}/{path.lstrip('/')}"
    try:
        if method == "GET":
            r = session.get(url, params=params, timeout=TIMEOUT)
        else:
            r = session.post(url, data=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise InstagramError(settings.scrub(f"bağlantı hatası: {type(exc).__name__}")) from None
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400 or "error" in body:
        err = body.get("error") or {}
        code, sub = err.get("code"), err.get("error_subcode")
        msg = settings.scrub(f"{r.status_code} kod={code} alt={sub} {err.get('error_user_msg') or err.get('message', '')}")[:400]
        if code == 190:
            raise TokenError(msg, code, sub)
        if code in RATE_LIMIT_CODES or sub == 2207042:
            raise RateLimitError(msg, code, sub)
        raise InstagramError(msg, code, sub)
    return body


# --------------------------------------------------------------------------- hesap

def me(session=requests) -> dict:
    return _req("GET", "me", {"fields": "user_id,username,account_type,media_count"}, session)


def user_id(session=requests) -> str:
    """IG_USER_ID sayısal ise onu, değilse (ör. kullanıcı adı yazılmışsa) /me'den gelen kimliği kullanır."""
    raw = settings.get("IG_USER_ID")
    if raw.isdigit():
        return raw
    info = me(session)
    return str(info.get("user_id") or info.get("id"))


def publishing_limit(uid: str, session=requests) -> dict:
    data = _req("GET", f"{uid}/content_publishing_limit", {"fields": "config,quota_usage"}, session)
    row = (data.get("data") or [{}])[0]
    return {"used": row.get("quota_usage", 0), "total": (row.get("config") or {}).get("quota_total", 100)}


# --------------------------------------------------------------------------- yayın

def create_image_container(uid: str, image_url: str, alt_text: str = "", carousel_item: bool = True,
                           session=requests) -> str:
    params = {"image_url": image_url}
    if carousel_item:
        params["is_carousel_item"] = "true"
    if alt_text:
        params["alt_text"] = alt_text[:1000]
    try:
        return _req("POST", f"{uid}/media", params, session)["id"]
    except InstagramError as exc:
        if alt_text and "alt_text" in str(exc) and not isinstance(exc, (TokenError, RateLimitError)):
            params.pop("alt_text")  # bu API sürümü alt_text'i kabul etmiyorsa onsuz dene
            return _req("POST", f"{uid}/media", params, session)["id"]
        raise


def container_status(cid: str, session=requests) -> str:
    return _req("GET", cid, {"fields": "status_code,status"}, session).get("status_code", "")


def wait_ready(cids: list[str], session=requests, sleep=time.sleep, max_s: int = WAIT_MAX_S) -> None:
    pending = list(cids)
    waited = 0
    while pending:
        still = []
        for cid in pending:
            st = container_status(cid, session)
            if st in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Kap {cid} durumu {st} — görsel çekilemedi ya da reddedildi")
            if st != "FINISHED":
                still.append(cid)
        pending = still
        if pending:
            if waited >= max_s:
                raise InstagramError(f"{len(pending)} kap {max_s} sn içinde hazır olmadı")
            sleep(POLL_S)
            waited += POLL_S


def create_carousel(uid: str, children: list[str], caption: str, session=requests) -> str:
    return _req("POST", f"{uid}/media",
                {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption}, session)["id"]


def publish_container(uid: str, creation_id: str, session=requests) -> str:
    return _req("POST", f"{uid}/media_publish", {"creation_id": creation_id}, session)["id"]


def permalink(media_id: str, session=requests) -> str:
    return _req("GET", media_id, {"fields": "permalink"}, session).get("permalink", "")


@dataclass
class PublishResult:
    media_id: str
    permalink: str
    children: int


def publish_carousel(image_urls: list[str], alt_texts: list[str], caption: str,
                     session=requests, sleep=time.sleep) -> PublishResult:
    if not 2 <= len(image_urls) <= 10:
        raise InstagramError(f"Carousel 2–10 görsel olmalı (şu an {len(image_urls)})")
    if len(caption) > 2200:
        raise InstagramError("Caption 2.200 karakteri aşıyor")
    uid = user_id(session)
    lim = publishing_limit(uid, session)
    if lim["used"] >= lim["total"]:
        raise RateLimitError(f"Günlük paylaşım sınırı dolu ({lim['used']}/{lim['total']})")
    children = [
        create_image_container(uid, url, alt, True, session)
        for url, alt in zip(image_urls, alt_texts + [""] * (len(image_urls) - len(alt_texts)))
    ]
    wait_ready(children, session, sleep)
    parent = create_carousel(uid, children, caption, session)
    wait_ready([parent], session, sleep)
    media_id = publish_container(uid, parent, session)
    return PublishResult(media_id, permalink(media_id, session), len(children))


def test_fetch(image_url: str, session=requests, sleep=time.sleep) -> str:
    """Yayınlamadan, Instagram'ın görseli çekebildiğini doğrular (kap 24 saatte kendiliğinden silinir)."""
    uid = user_id(session)
    cid = create_image_container(uid, image_url, "", True, session)
    wait_ready([cid], session, sleep)
    return cid
