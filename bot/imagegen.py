"""Cloudflare Workers AI FLUX-1-schnell ile soyut arka plan üretimi.

- Her istek prompts/style_prompt.txt ile birleştirilir (ortak görsel dil + yasak listesi).
- Üretilen görseller önbelleğe alınır: dosya varsa yeniden üretilmez (kota tasarrufu).
- Neuron kullanımı tahmini olarak state/usage.json ve logs/neurons.log'a yazılır.
  Cloudflare yanıtı kullanım bilgisi döndürmediği için resmî fiyat tablosundan hesaplanır.
"""
from __future__ import annotations

import base64
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image

from . import settings
from .config import LOGS_DIR, ROOT, STATE_DIR

MODEL = "@cf/black-forest-labs/flux-1-schnell"
URL = "https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/" + MODEL
STEPS = 4
TIMEOUT = 90

# Cloudflare fiyat tablosu (flux-1-schnell): 512×512 karo başına 4.80, adım başına 9.60 neuron.
NEURONS_PER_TILE = 4.80
NEURONS_PER_STEP = 9.60
TILES_1024 = 4
NEURONS_PER_IMAGE = TILES_1024 * NEURONS_PER_TILE + STEPS * NEURONS_PER_STEP  # ≈ 57.6
DAILY_FREE_NEURONS = 10_000
SAFETY_MARGIN = 500

USAGE_FILE = STATE_DIR / "usage.json"
STYLE_FILE = ROOT / "prompts" / "style_prompt.txt"


class ImageGenError(RuntimeError):
    pass


class ImageQuotaError(ImageGenError):
    """Günlük ücretsiz neuron kotası doldu — tur atlanır."""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")  # Cloudflare kotası UTC 00:00'da sıfırlanır


def load_usage(path: Path | None = None) -> dict:
    path = path or USAGE_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def record_usage(neurons: float, images: int = 1, path: Path | None = None) -> dict:
    path = path or USAGE_FILE
    data = load_usage(path)
    day = data.setdefault(_today(), {"neurons": 0.0, "images": 0})
    day["neurons"] = round(day["neurons"] + neurons, 1)
    day["images"] += images
    # yalnızca son 60 gün
    for k in sorted(data)[:-60]:
        data.pop(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    LOGS_DIR.mkdir(exist_ok=True)
    with (LOGS_DIR / "neurons.log").open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} +{neurons:.1f} "
                f"(bugün {day['neurons']:.1f}/{DAILY_FREE_NEURONS})\n")
    return day


def used_today(path: Path | None = None) -> float:
    return load_usage(path).get(_today(), {}).get("neurons", 0.0)


def full_prompt(concept: str) -> str:
    style = STYLE_FILE.read_text(encoding="utf-8").strip()
    return f"{concept.strip().rstrip('.')}, {style}"


def generate_image(concept: str, out_path: Path, session=requests) -> Path:
    """Tek arka plan üretir. Dosya zaten varsa dokunmaz."""
    out_path = Path(out_path)
    if out_path.exists():
        return out_path
    if used_today() + NEURONS_PER_IMAGE > DAILY_FREE_NEURONS - SAFETY_MARGIN:
        raise ImageQuotaError(f"Günlük ücretsiz neuron kotası dolmak üzere ({used_today():.0f}/{DAILY_FREE_NEURONS})")
    acc, tok = settings.get("CF_ACCOUNT_ID"), settings.get("CF_API_TOKEN")
    if not acc or not tok:
        raise ImageGenError("CF_ACCOUNT_ID / CF_API_TOKEN boş")

    last = ""
    for attempt in range(3):
        try:
            r = session.post(
                URL.format(acc=acc),
                headers={"Authorization": f"Bearer {tok}"},
                json={"prompt": full_prompt(concept)[:2048], "steps": STEPS},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            last = settings.scrub(type(exc).__name__)
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                raw = base64.b64decode(r.json()["result"]["image"])
                img = Image.open(io.BytesIO(raw)).convert("RGB")
            except Exception as exc:  # noqa: BLE001
                raise ImageGenError(f"Görsel çözülemedi: {type(exc).__name__}") from None
            out_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(out_path, "JPEG", quality=95)
            record_usage(NEURONS_PER_IMAGE)
            return out_path
        body = r.text[:300]
        if r.status_code == 429 or "4006" in body or "allocation" in body.lower():
            raise ImageQuotaError(f"Cloudflare ücretsiz kotası doldu ({r.status_code})")
        last = settings.scrub(f"{r.status_code} {body}")
        if r.status_code in (400, 401, 403) and "8007" not in body:
            break  # yetki/istek hatası: tekrar denemenin anlamı yok
        time.sleep(5 * (attempt + 1))  # geçici hata (5xx, 8007 kapasite vb.)
    raise ImageGenError(f"FLUX isteği başarısız: {last[:200]}")
