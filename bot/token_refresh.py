"""Instagram token yönetimi (Instagram Login).

- Kısa ömürlü (1 saat) → uzun ömürlü (60 gün): IG_APP_SECRET ile ig_exchange_token.
- Uzun ömürlü token yenileme: ig_refresh_token (token en az 24 saatlik olmalı), yeni 60 gün.
- state/token.json yalnızca tarihleri tutar, token'ı ASLA tutmaz.
- Yerelde yeni token .env'ye yazılır (değer ekrana basılmaz); GitHub Actions'ta Faz 5'te Secret'a yazılır.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import settings
from .config import STATE_DIR

GRAPH = "https://graph.instagram.com"
GRAPH_FB = "https://graph.facebook.com/v24.0"
TIMEOUT = 30
TOKEN_STATE = STATE_DIR / "token.json"


class TokenRefreshError(RuntimeError):
    pass


def _get(path: str, params: dict, base: str = GRAPH) -> dict:
    try:
        r = requests.get(f"{base}/{path}", params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise TokenRefreshError(settings.scrub(f"bağlantı hatası: {type(exc).__name__}")) from None
    body = r.json() if r.headers.get("content-type", "").startswith(("application/json", "text/javascript")) else {}
    if r.status_code != 200 or "access_token" not in body:
        err = body.get("error") or {}
        raise TokenRefreshError(settings.scrub(f"{r.status_code} {err.get('message', '')}")[:300])
    return body


def exchange_short_lived(short_token: str, app_secret: str) -> dict:
    return _get("access_token", {"grant_type": "ig_exchange_token", "client_secret": app_secret,
                                 "access_token": short_token})


def refresh_long_lived(token: str) -> dict:
    if token.startswith("EAA"):
        # Facebook/Unified login token: uygulama kimliği ve gizli anahtarıyla 60 günlük token alınır
        app_id, secret = settings.get("IG_APP_ID"), settings.get("IG_APP_SECRET")
        if not app_id or not secret:
            raise TokenRefreshError("EAA token yenilemek için .env'de IG_APP_ID ve IG_APP_SECRET gerekli")
        return _get("oauth/access_token", {"grant_type": "fb_exchange_token", "client_id": app_id,
                                           "client_secret": secret, "fb_exchange_token": token}, GRAPH_FB)
    return _get("refresh_access_token", {"grant_type": "ig_refresh_token", "access_token": token})


def token_expiry(token: str) -> datetime | None:
    """EAA token'ın bitiş tarihini debug_token ile öğrenir (IG_APP_ID + IG_APP_SECRET gerekir).
    0 = süresiz. Bilinemiyorsa None."""
    app_id, secret = settings.get("IG_APP_ID"), settings.get("IG_APP_SECRET")
    if not token.startswith("EAA") or not app_id or not secret:
        return None
    try:
        r = requests.get(f"{GRAPH_FB}/debug_token", params={"input_token": token,
                         "access_token": f"{app_id}|{secret}"}, timeout=TIMEOUT)
        data = r.json().get("data") or {}
    except (requests.RequestException, ValueError):
        return None
    exp = data.get("data_access_expires_at") if not data.get("expires_at") else data.get("expires_at")
    if exp in (None, 0):
        return None
    return datetime.fromtimestamp(int(exp), tz=timezone.utc)


def save_state(expires_in: int, now: datetime | None = None, path: Path | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    data = {
        "refreshed_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(seconds=int(expires_in))).isoformat(timespec="seconds"),
    }
    path = path or TOKEN_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return data


def load_state(path: Path | None = None) -> dict:
    try:
        return json.loads((path or TOKEN_STATE).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def days_left(now: datetime | None = None, path: Path | None = None) -> float | None:
    st = load_state(path)
    if not st.get("expires_at"):
        return None
    delta = datetime.fromisoformat(st["expires_at"]) - (now or datetime.now(timezone.utc))
    return delta.total_seconds() / 86400


def write_env_value(key: str, value: str, env_file: Path | None = None) -> None:
    """.env içindeki tek bir satırı değiştirir (yoksa ekler). Değer hiçbir yere yazdırılmaz."""
    env_file = env_file or settings.ENV_FILE
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if pat.match(line):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def refresh_and_store(env_file: Path | None = None) -> dict:
    """Mevcut uzun ömürlü token'ı yeniler, .env'ye yazar, tarihleri state/token.json'a kaydeder."""
    token = settings.get("IG_ACCESS_TOKEN")
    if not token:
        raise TokenRefreshError("IG_ACCESS_TOKEN boş")
    body = refresh_long_lived(token)
    write_env_value("IG_ACCESS_TOKEN", body["access_token"], env_file)
    return save_state(body.get("expires_in", 60 * 86400))


def upgrade_if_short_lived(env_file: Path | None = None) -> dict | None:
    """IG_APP_SECRET varsa kısa ömürlü token'ı uzun ömürlüye çevirmeyi dener.
    Token zaten uzun ömürlüyse Meta hata döner; bu durumda None (değişiklik yok)."""
    secret = settings.get("IG_APP_SECRET")
    token = settings.get("IG_ACCESS_TOKEN")
    if not secret or not token:
        return None
    try:
        body = exchange_short_lived(token, secret)
    except TokenRefreshError:
        return None
    write_env_value("IG_ACCESS_TOKEN", body["access_token"], env_file)
    return save_state(body.get("expires_in", 60 * 86400))


def push_secret(name: str, value: str) -> None:
    """GitHub Actions'ta yeni değeri repo Secret'ına yazar. Değer stdin ile verilir, loglara düşmez.
    GITHUB_TOKEN secret yazamaz; GH_PAT (Secrets: write yetkili ince ayarlı token) gerekir."""
    import subprocess

    if not value:
        raise TokenRefreshError(f"{name} boş, Secret'a yazılamaz")
    print(f"::add-mask::{value}")  # GitHub Actions bu değeri loglarda gizler
    pat = os.environ.get("GH_PAT", "")
    if not pat:
        raise TokenRefreshError("GH_PAT secret'ı yok — yenilenen token GitHub'a yazılamadı")
    env = {**os.environ, "GH_TOKEN": pat}
    r = subprocess.run(["gh", "secret", "set", name], input=value, text=True, env=env, capture_output=True)
    if r.returncode != 0:
        raise TokenRefreshError(settings.scrub(f"gh secret set başarısız: {r.stderr.strip()[:200]}"))
