"""python -m bot check — her servise gerçek bir test isteği atar, sonucu maskeli gösterir.

Hiçbir gizli değer tam olarak yazdırılmaz; tüm mesajlar settings.scrub() ile temizlenir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import requests

from . import settings, telegram
from .llm_gemini import DEFAULT_MODEL, model_name

CF_API = "https://api.cloudflare.com/client/v4"
TIMEOUT = 20


@dataclass
class Result:
    service: str
    ok: bool | None  # None = atlandı
    message: str


def _safe(fn):
    """Beklenmeyen hataları yakalar ve maskeler."""
    def wrapper(*a, **k) -> Result:
        try:
            return fn(*a, **k)
        except Exception as exc:  # noqa: BLE001
            name = fn.__name__.removeprefix("check_").capitalize()
            return Result(name, False, settings.scrub(f"{type(exc).__name__}: {exc}")[:200])
    wrapper.__name__ = fn.__name__
    return wrapper


def _flash_rank(name: str) -> tuple:
    """Model adından (sürüm, lite değil mi) sıralama anahtarı çıkarır."""
    m = re.search(r"gemini-(\d+(?:\.\d+)?)-flash", name)
    ver = float(m.group(1)) if m else 0.0
    return (ver, "lite" not in name, "preview" not in name and "exp" not in name)


@_safe
def check_gemini() -> Result:
    key = settings.get("GEMINI_API_KEY")
    if not key:
        return Result("Gemini", False, "GEMINI_API_KEY boş")
    from google import genai
    from google.genai import errors

    client = genai.Client(api_key=key)
    try:
        names = []
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions:
                names.append(m.name.removeprefix("models/"))
        flash = sorted(
            (n for n in names if "flash" in n and not re.search(r"(image|tts|audio|live|thinking)", n)),
            key=_flash_rank,
            reverse=True,
        )
        model = model_name()
        resp = client.models.generate_content(model=model, contents="Sadece 'tamam' yaz.")
    except errors.APIError as exc:
        hint = " (kota doldu)" if exc.code == 429 else (" (anahtar geçersiz)" if exc.code in (400, 401, 403) else "")
        return Result("Gemini", False, settings.scrub(f"{exc.code}{hint}"))
    stable = [n for n in flash if _flash_rank(n)[2] and "latest" not in n]
    suggestion = stable[0] if stable else (flash[0] if flash else DEFAULT_MODEL)
    note = "" if settings.get("LLM_MODEL") else f" (LLM_MODEL boş → varsayılan {DEFAULT_MODEL})"
    msg = (
        f"bağlantı başarılı, anahtar {settings.mask(key)} · model: {model}{note} · yanıt: "
        f"{(resp.text or '').strip()[:20]!r}\n"
        f"     Erişilebilen Flash modelleri: {', '.join(flash[:8]) or '-'}\n"
        f"     Önerilen sabit model: {suggestion}"
    )
    return Result("Gemini", True, msg)


@_safe
def check_cloudflare() -> Result:
    acc, tok = settings.get("CF_ACCOUNT_ID"), settings.get("CF_API_TOKEN")
    if not acc or not tok:
        return Result("Cloudflare", False, "CF_ACCOUNT_ID veya CF_API_TOKEN boş")
    h = {"Authorization": f"Bearer {tok}"}
    # Kullanıcı token'ı ya da hesap token'ı olabilir; ikisini de dene.
    r = requests.get(f"{CF_API}/user/tokens/verify", headers=h, timeout=TIMEOUT)
    if r.status_code != 200:
        r = requests.get(f"{CF_API}/accounts/{acc}/tokens/verify", headers=h, timeout=TIMEOUT)
    if r.status_code != 200:
        return Result("Cloudflare", False, f"{r.status_code} token doğrulanamadı (yetkisiz ya da geçersiz)")
    status = (r.json().get("result") or {}).get("status", "?")
    # Workers AI erişimi: model listesini sorgula (neuron harcamaz)
    r2 = requests.get(
        f"{CF_API}/accounts/{acc}/ai/models/search",
        headers=h, params={"search": "flux-1-schnell", "per_page": 5}, timeout=TIMEOUT,
    )
    if r2.status_code != 200:
        return Result("Cloudflare", False, f"token {status}, ama Workers AI erişimi yok ({r2.status_code}) — Account ID ya da token izni hatalı olabilir")
    found = any("flux-1-schnell" in (m.get("name") or "") for m in r2.json().get("result") or [])
    flux = "FLUX-1-schnell erişilebilir" if found else "FLUX-1-schnell listede yok!"
    return Result("Cloudflare", found, f"token {status} {settings.mask(tok)}, hesap {settings.mask(acc)} · {flux}")


@_safe
def check_telegram(send_test: bool = True) -> Result:
    if not settings.get("TELEGRAM_BOT_TOKEN"):
        return Result("Telegram", False, "TELEGRAM_BOT_TOKEN boş")
    try:
        me = telegram.get_me()
        detail = f"bot @{me.get('username')}"
        if send_test:
            telegram.send_message("✅ ig-tech-bot bağlantı testi")
            detail += f" · test mesajı gönderildi (chat {settings.mask(settings.get('TELEGRAM_CHAT_ID'))})"
    except telegram.TelegramError as exc:
        return Result("Telegram", False, str(exc))
    return Result("Telegram", True, detail)


def check_instagram() -> Result:
    if not settings.get("IG_ACCESS_TOKEN") or not settings.get("IG_USER_ID"):
        return Result("Instagram", None, "Faz 4'te yapılandırılacak (IG_* boş)")
    return Result("Instagram", None, "Instagram kontrolü Faz 4'te eklenecek")


def run_all(send_test: bool = True) -> list[Result]:
    return [check_gemini(), check_cloudflare(), check_telegram(send_test), check_instagram()]
