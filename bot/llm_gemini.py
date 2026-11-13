"""Gemini ile haber seçimi ve Türkçe carousel metni üretimi.

Akış:
  1) prefilter  — yüzlerce haberden ~150 aday (kod ile, ücretsiz)
  2) select     — Gemini: aynı olayları birleştir, kategoriyi düzelt, en iyi 8 hikâyeyi sırala
  3) pick_five  — kod: denge kuralına (≥2 oyun, ≥2 teknoloji) uyan 5 hikâye
  4) write      — Gemini: slayt metinleri + caption gövdesi + hashtag'ler
  5) validate   — kod: şema ve sınırlar; bozuksa hatalarla birlikte 1 kez yeniden dene
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from . import settings
from .collector import Article
from .config import ROOT

PROMPTS_DIR = ROOT / "prompts"
# Ücretsiz katmandaki modeller, tercih sırasıyla (2026-11-13'te API'den doğrulandı).
# Bir model yoğun (503), yok (404) ya da kotası dolu (429) ise sıradakine geçilir.
# Hepsi ücretsiz; ücretli bir modele asla geçilmez.
FALLBACK_MODELS = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite")
DEFAULT_MODEL = FALLBACK_MODELS[0]
RETRY_WAIT_S = 20

TITLE_MAX = 60
TEXT_MAX = 180
CAPTION_MAX = 1500
HASHTAG_MIN, HASHTAG_MAX = 5, 10
AI_NOTE = "Görseller yapay zekâ ile üretilmiştir."
N_ITEMS = 5
MIN_PER_CATEGORY = 2

# generate(model, system_instruction, prompt, schema) -> JSON metni.  Testlerde sahtesi verilir.
Generator = Callable[[str, str, str, dict], str]


class LLMError(RuntimeError):
    pass


class QuotaError(LLMError):
    """Ücretsiz kota doldu — tur atlanır, para harcanacak bir yola geçilmez."""


# --------------------------------------------------------------------------- Gemini çağrısı

def model_chain() -> list[str]:
    """LLM_MODEL doluysa önce o, ardından yedek modeller."""
    first = settings.get("LLM_MODEL")
    return list(dict.fromkeys(([first] if first else []) + list(FALLBACK_MODELS)))


def model_name() -> str:
    return ",".join(model_chain())


last_model_used: str | None = None

GEN_TIMEOUT_MS = 120_000   # uzun istem (150 aday) için
CHECK_TIMEOUT_MS = 30_000


def make_client(timeout_ms: int = GEN_TIMEOUT_MS):
    """Zaman aşımlı, SDK içi yeniden denemesi kapalı istemci (yedek zincirini biz yönetiyoruz)."""
    from google import genai
    from google.genai import types

    key = settings.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY boş")
    return genai.Client(
        api_key=key,
        http_options=types.HttpOptions(
            timeout=timeout_ms, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )


def _is_timeout(exc: Exception) -> bool:
    return "timeout" in type(exc).__name__.lower() or "timed out" in str(exc).lower()


def _call_once(client, model: str, system: str, prompt: str, schema: dict):
    from google.genai import types

    return client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.5,
        ),
    )


def gemini_generate(model: str, system: str, prompt: str, schema: dict) -> str:
    """`model` virgülle ayrılmış bir liste olabilir; sırayla denenir.

    Tüm modeller yoğunsa (503) 20 sn bekleyip zinciri bir kez daha dener.
    Tüm modellerin kotası doluysa QuotaError (tur atlanır).
    """
    global last_model_used
    from google.genai import errors

    client = make_client()
    models = [m.strip() for m in model.split(",") if m.strip()]
    problems: dict[str, str] = {}
    resp = None
    for round_ in range(2):
        for m in models:
            try:
                resp = _call_once(client, m, system, prompt, schema)
                last_model_used = m
                break
            except errors.APIError as exc:
                code = exc.code
                problems[m] = str(code)
                if code in (429, 503, 500, 404):
                    continue  # sıradaki ücretsiz modeli dene
                msg = settings.scrub(f"{code} {getattr(exc, 'message', '')}")
                raise LLMError(f"Gemini hatası ({m}): {msg[:300]}") from None
            except Exception as exc:  # noqa: BLE001
                if _is_timeout(exc):
                    problems[m] = "zaman aşımı"
                    continue
                raise LLMError(settings.scrub(f"Gemini bağlantı hatası ({m}): {type(exc).__name__}")) from None
        if resp is not None:
            break
        if any(c in ("503", "500", "zaman aşımı") for c in problems.values()) and round_ == 0:
            time.sleep(RETRY_WAIT_S)
            continue
        break
    if resp is None:
        summary = ", ".join(f"{m}:{c}" for m, c in problems.items())
        if all(c == "429" for c in problems.values()):
            raise QuotaError(f"Gemini ücretsiz kotası tüm modellerde doldu ({summary})")
        raise LLMError(f"Hiçbir Gemini modeli yanıt vermedi ({summary})")
    if not resp.text:
        raise LLMError("Gemini boş yanıt döndü")
    return resp.text


# --------------------------------------------------------------------------- 1) ön eleme

def prefilter(articles: list[Article], limit: int = 150, per_source: int = 6) -> list[Article]:
    """Çok kaynakta geçen ve yeni haberleri öne alır; kaynak ve kategori dengesini korur."""
    if not articles:
        return []
    newest = max(a.published for a in articles)

    def score(a: Article) -> float:
        age_h = (newest - a.published).total_seconds() / 3600
        return len(a.related) * 3 + (2 if a.topic == "ai" else 0) + max(0.0, 24 - age_h) / 12

    ranked = sorted(articles, key=score, reverse=True)
    per_src: Counter[str] = Counter()
    by_cat: dict[str, list[Article]] = {"teknoloji": [], "oyun": []}
    for a in ranked:
        if per_src[a.source] >= per_source:
            continue
        per_src[a.source] += 1
        by_cat.setdefault(a.category, []).append(a)
    half = limit // 2
    tech, game = by_cat["teknoloji"], by_cat["oyun"]
    n_game = min(len(game), max(half, limit - len(tech)))
    n_tech = min(len(tech), limit - n_game)
    chosen = tech[:n_tech] + game[:n_game]
    return sorted(chosen, key=score, reverse=True)


# --------------------------------------------------------------------------- 2) seçim

SELECT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "stories": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "ids": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                    "category": {"type": "STRING", "enum": ["teknoloji", "oyun"]},
                    "headline_tr": {"type": "STRING"},
                },
                "required": ["ids", "category", "headline_tr"],
            },
        }
    },
    "required": ["stories"],
}


@dataclass
class Story:
    articles: list[Article]
    category: str
    headline: str


def _candidates_text(cands: list[Article]) -> str:
    lines = []
    for i, a in enumerate(cands):
        extra = f" (+{len(a.related)} kaynak daha)" if a.related else ""
        lines.append(
            f"[{i}] ({a.source}, {a.lang}, ipucu:{a.category}{'/yz' if a.topic == 'ai' else ''}){extra}\n"
            f"    {a.title}\n    {a.summary[:220]}"
        )
    return "\n".join(lines)


def select_stories(cands: list[Article], generate: Generator, model: str, system: str) -> list[Story]:
    prompt = (
        "Aşağıda son 24 saatin aday haberleri var. Görevin:\n"
        "1. Aynı olayı anlatan adayları (farklı dillerde olsa bile) tek hikâyede birleştir (ids listesi).\n"
        "2. Her hikâyenin kategorisini konuya göre belirle (teknoloji / oyun).\n"
        "3. Türk okur için en önemli 8 hikâyeyi önem sırasına göre döndür; "
        "içlerinde en az 3 oyun ve en az 3 teknoloji olsun.\n"
        "headline_tr: hikâyenin kısa Türkçe özeti (sadece senin takibin için).\n\n"
        + _candidates_text(cands)
    )
    data = _parse_json(generate(model, system, prompt, SELECT_SCHEMA))
    stories, used = [], set()
    for s in data.get("stories", []):
        ids = [i for i in s.get("ids", []) if isinstance(i, int) and 0 <= i < len(cands) and i not in used]
        if not ids or s.get("category") not in ("teknoloji", "oyun"):
            continue
        used.update(ids)
        stories.append(Story([cands[i] for i in ids], s["category"], str(s.get("headline_tr", ""))))
    return stories


def pick_five(stories: list[Story]) -> list[Story]:
    """Sırayı koruyarak ≥2 oyun ve ≥2 teknoloji içeren 5 hikâye seçer."""
    picked: list[Story] = []
    for cat in ("teknoloji", "oyun"):
        picked += [s for s in stories if s.category == cat][:MIN_PER_CATEGORY]
    for s in stories:
        if len(picked) >= N_ITEMS:
            break
        if all(s is not p for p in picked):
            picked.append(s)
    cats = Counter(s.category for s in picked)
    if len(picked) < N_ITEMS or min(cats["oyun"], cats["teknoloji"]) < MIN_PER_CATEGORY:
        raise LLMError("Denge kuralına uyan 5 hikâye seçilemedi")
    order = {id(s): i for i, s in enumerate(stories)}
    return sorted(picked, key=lambda s: order[id(s)])


# --------------------------------------------------------------------------- 4) yazım

WRITE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "slide_title": {"type": "STRING"},
                    "slide_text": {"type": "STRING"},
                    "source_url": {"type": "STRING"},
                    "category": {"type": "STRING", "enum": ["teknoloji", "oyun"]},
                    "image_prompt": {"type": "STRING"},
                },
                "required": ["slide_title", "slide_text", "source_url", "category", "image_prompt"],
            },
        },
        "caption_body": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["items", "caption_body", "hashtags"],
}


def _stories_text(stories: list[Story]) -> str:
    out = []
    for n, s in enumerate(stories, 1):
        out.append(f"### Hikâye {n} — kategori: {s.category}")
        for a in s.articles:
            out.append(f"- Kaynak: {a.source} | Link: {a.url}\n  Başlık: {a.title}\n  Özet: {a.summary}")
    return "\n".join(out)


def _write_prompt(stories: list[Story], errors: list[str] | None) -> str:
    p = (
        f"Aşağıdaki {len(stories)} hikâye için, AYNI SIRAYLA, {len(stories)} slayt yaz.\n"
        f"- slide_title ≤ {TITLE_MAX} karakter, slide_text ≤ {TEXT_MAX} karakter (boşluklar dahil).\n"
        "- source_url: o hikâyenin listesindeki linklerden biri, aynen (tercihen en bilgilendirici olan).\n"
        "- category: hikâyenin kategorisi.\n"
        "- image_prompt: İngilizce, soyut arka plan; marka/logo/ürün/karakter/kişi/yazı yok.\n"
        "- caption_body: kısa giriş + 5 haberin numaralı birer satırlık özeti; her madde AYRI SATIRDA (\\n ile), en fazla 1000 karakter. "
        "Kaynak listesi, hashtag ve YZ notu EKLEME (onları sistem ekleyecek).\n"
        f"- hashtags: {HASHTAG_MIN}-{HASHTAG_MAX} adet, '#' ile başlayan, boşluksuz.\n\n"
        + _stories_text(stories)
    )
    if errors:
        p += "\n\nÖNCEKİ YANITINDA ŞU HATALAR VARDI, DÜZELT:\n" + "\n".join(f"- {e}" for e in errors)
    return p


def _split_numbered(body: str) -> str:
    """'... 1. x 2. y' tek satırda geldiyse maddeleri ayrı satırlara böler."""
    return re.sub(r"\s+(?=(?:[1-9]|10)\.\s)", "\n", body) if "\n1." not in body else body


def build_caption(body: str, hashtags: list[str], sources: list[str]) -> str:
    body = _split_numbered(body)
    uniq_sources = list(dict.fromkeys(sources))
    tail = (
        "\n\nKaynaklar: " + ", ".join(uniq_sources)
        + "\n\n" + " ".join(hashtags)
        + "\n\n" + AI_NOTE
    )
    body = body.strip()
    room = CAPTION_MAX - len(tail)
    if len(body) > room:
        body = body[: room - 1].rstrip() + "…"
    return body + tail


def validate(data: dict, stories: list[Story]) -> list[str]:
    """Hata listesi döndürür; boş liste = geçerli."""
    errs: list[str] = []
    items = data.get("items")
    if not isinstance(items, list) or len(items) != len(stories):
        return [f"items tam olarak {len(stories)} öğe olmalı"]
    for n, (it, st) in enumerate(zip(items, stories), 1):
        t, x = str(it.get("slide_title", "")), str(it.get("slide_text", ""))
        if not t.strip():
            errs.append(f"{n}. slide_title boş")
        if len(t) > TITLE_MAX:
            errs.append(f"{n}. slide_title {len(t)} karakter (en fazla {TITLE_MAX})")
        if not x.strip():
            errs.append(f"{n}. slide_text boş")
        if len(x) > TEXT_MAX:
            errs.append(f"{n}. slide_text {len(x)} karakter (en fazla {TEXT_MAX})")
        if it.get("source_url") not in {a.url for a in st.articles}:
            errs.append(f"{n}. source_url hikâyenin linklerinden biri değil")
        if it.get("category") not in ("teknoloji", "oyun"):
            errs.append(f"{n}. category geçersiz")
        ip = str(it.get("image_prompt", ""))
        if not ip.strip() or len(ip) > 500 or not ip.isascii():
            errs.append(f"{n}. image_prompt boş, çok uzun ya da İngilizce değil")
    cats = Counter(it.get("category") for it in items)
    if cats["oyun"] < MIN_PER_CATEGORY or cats["teknoloji"] < MIN_PER_CATEGORY:
        errs.append("en az 2 oyun ve en az 2 teknoloji haberi olmalı")
    tags = data.get("hashtags") or []
    if not (HASHTAG_MIN <= len(tags) <= HASHTAG_MAX) or any(
        not str(h).startswith("#") or " " in str(h) for h in tags
    ):
        errs.append(f"hashtags {HASHTAG_MIN}-{HASHTAG_MAX} adet, '#' ile başlayan ve boşluksuz olmalı")
    if not str(data.get("caption_body", "")).strip():
        errs.append("caption_body boş")
    return errs


def write_slides(stories: list[Story], generate: Generator, model: str, system: str) -> dict:
    errors: list[str] | None = None
    for attempt in range(2):  # ilk deneme + 1 tekrar
        try:
            data = _parse_json(generate(model, system, _write_prompt(stories, errors), WRITE_SCHEMA))
        except LLMError as exc:
            if isinstance(exc, QuotaError):
                raise
            errors = [str(exc)]
            continue
        errors = validate(data, stories)
        if not errors:
            return data
    raise LLMError("Gemini çıktısı 2 denemede de geçersiz: " + "; ".join(errors or []))


# --------------------------------------------------------------------------- yardımcılar

def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON çözülemedi: {exc.msg}") from None
    if not isinstance(data, dict):
        raise LLMError("JSON nesne değil")
    return data


def load_system_prompt() -> str:
    return (PROMPTS_DIR / "writer_system.md").read_text(encoding="utf-8")


def generate_post(
    articles: list[Article],
    generate: Generator = gemini_generate,
    model: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Tekilleştirilmiş haberlerden günün carousel içeriğini üretir."""
    model = model or model_name()
    system = load_system_prompt()
    cands = prefilter(articles)
    if len(cands) < N_ITEMS:
        raise LLMError(f"Yeterli aday haber yok ({len(cands)})")

    stories: list[Story] = []
    chosen: list[Story] | None = None
    for _ in range(2):  # seçim de bozuksa 1 kez tekrar
        try:
            stories = select_stories(cands, generate, model, system)
            chosen = pick_five(stories)
            break
        except QuotaError:
            raise
        except LLMError:
            chosen = None
    if not chosen:
        raise LLMError("Gemini 2 denemede de geçerli bir haber seçimi yapamadı")

    data = write_slides(chosen, generate, model, system)
    url_source = {a.url: a.source for s in chosen for a in s.articles}
    items = []
    for it, st in zip(data["items"], chosen):
        items.append(
            {
                "slide_title": it["slide_title"].strip(),
                "slide_text": it["slide_text"].strip(),
                "source_name": url_source[it["source_url"]],
                "source_url": it["source_url"],
                "category": it["category"],
                "image_prompt": it["image_prompt"].strip(),
                "all_sources": [{"name": a.source, "url": a.url} for a in st.articles],
                "headline": st.headline,
            }
        )
    caption = build_caption(data["caption_body"], data["hashtags"], [i["source_name"] for i in items])
    return {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "model": last_model_used or model,
        "candidates": len(cands),
        "items": items,
        "caption": caption,
    }
