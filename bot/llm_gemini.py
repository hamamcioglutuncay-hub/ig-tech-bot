"""Gemini ile haber seçimi ve Türkçe carousel metni üretimi.

Akış:
  1) prefilter  — yüzlerce haberden ~150 aday (kod ile, ücretsiz)
  2) select     — Gemini: aynı olayları birleştir, kategoriyi düzelt, en önemli 12 hikâyeyi puanla
  3) pick_stories — kod: önem eşiği + denge kuralı ile 3–8 hikâye
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
TEXT_MAX = 260          # slayt gövde metni
WHY_MAX = 120           # "Neden önemli?" satırı
PARA_MIN, PARA_MAX = 80, 330   # caption'daki haber paragrafı (haber sayısına göre daraltılır: para_limits)
INTRO_MAX = 220
CAPTION_MAX = 2150      # Instagram sınırı 2200; güvenlik payı
HASHTAG_MIN, HASHTAG_MAX = 5, 10
AI_NOTE = "Görseller yapay zekâ ile üretilmiştir."
MIN_ITEMS, MAX_ITEMS = 3, 8     # Instagram API carousel sınırı 10 = kapak + en fazla 8 haber + kapanış
IMPORTANCE_THRESHOLD = 6        # 1–10; bu puanın altındaki hikâyeler yalnızca minimumu doldurmak için alınır
N_SELECT = 12                   # Gemini'nin sıralayacağı en fazla hikâye
CATEGORY_EMOJI = {"teknoloji": "💻", "oyun": "🎮"}

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
                    "importance": {"type": "INTEGER"},
                    "headline_tr": {"type": "STRING"},
                },
                "required": ["ids", "category", "importance", "headline_tr"],
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
    importance: int = 5


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
        f"3. Türk okur için en önemli en fazla {N_SELECT} hikâyeyi önem sırasına göre döndür; "
        "içlerinde en az 3 oyun ve en az 3 teknoloji olsun.\n"
        "4. importance: 1–10 önem puanı. 9–10 = günün manşeti, herkesin konuşacağı gelişme; "
        "7–8 = önemli ve ilgi çekici; 6 = paylaşmaya değer; 5 ve altı = sıradan. Puanları cömert verme.\n"
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
        imp = s.get("importance")
        imp = max(1, min(10, int(imp))) if isinstance(imp, (int, float)) else 5
        stories.append(Story([cands[i] for i in ids], s["category"], str(s.get("headline_tr", "")), imp))
    return stories


def min_per_category(n: int) -> int:
    return 1 if n <= 3 else 2


def pick_stories(stories: list[Story], min_n: int = MIN_ITEMS, max_n: int = MAX_ITEMS,
                 threshold: int = IMPORTANCE_THRESHOLD) -> list[Story]:
    """Önem eşiğini geçen hikâyeleri (en az min_n, en fazla max_n) Gemini'nin sırasını koruyarak seçer.

    Denge: 3 haberde her kategoriden en az 1, 4+ haberde en az 2.
    Eksik kategori varsa en zayıf fazlalık, eksik kategorinin en iyisiyle değiştirilir.
    """
    order = {id(s): i for i, s in enumerate(stories)}
    picked = [s for s in stories if s.importance >= threshold][:max_n]
    if len(picked) < min_n:
        picked = stories[:min_n]

    def count(cat):
        return sum(s.category == cat for s in picked)

    for _ in range(4):  # ekleme 3→4 geçişinde gereksinimi artırabilir; kararlı olana dek tekrarla
        changed = False
        for cat, other in (("oyun", "teknoloji"), ("teknoloji", "oyun")):
            while count(cat) < min_per_category(len(picked)):
                pool = [s for s in stories if s.category == cat and all(s is not p for p in picked)]
                if not pool:
                    raise LLMError(f"Denge kuralı için yeterli '{cat}' hikâyesi yok")
                strong = pool[0].importance >= threshold or len(picked) < min_n
                if len(picked) < max_n and strong:
                    picked.append(pool[0])                      # güçlü hikâye: listeyi büyüt
                elif count(other) > min_per_category(len(picked)):
                    weakest = max((s for s in picked if s.category == other), key=lambda s: order[id(s)])
                    picked = [s for s in picked if s is not weakest] + [pool[0]]  # zayıfsa takas et
                elif len(picked) < max_n:
                    picked.append(pool[0])
                else:
                    raise LLMError("Denge kuralına uyan seçim yapılamadı")
                changed = True
        if not changed:
            break
    if len(picked) < min_n:
        raise LLMError("Yeterli hikâye seçilemedi")
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
                    "why_it_matters": {"type": "STRING"},
                    "caption_paragraph": {"type": "STRING"},
                    "source_url": {"type": "STRING"},
                    "category": {"type": "STRING", "enum": ["teknoloji", "oyun"]},
                    "image_prompt": {"type": "STRING"},
                },
                "required": ["slide_title", "slide_text", "why_it_matters", "caption_paragraph",
                             "source_url", "category", "image_prompt"],
            },
        },
        "caption_intro": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["items", "caption_intro", "hashtags"],
}


def _stories_text(stories: list[Story]) -> str:
    out = []
    for n, s in enumerate(stories, 1):
        out.append(f"### Hikâye {n} — kategori: {s.category}")
        for a in s.articles:
            out.append(f"- Kaynak: {a.source} | Link: {a.url}\n  Başlık: {a.title}\n  Özet: {a.summary}")
    return "\n".join(out)


def _write_prompt(stories: list[Story], errors: list[str] | None) -> str:
    n = len(stories)
    pmin, pmax = para_limits(n)
    p = (
        f"Aşağıdaki {n} hikâye için, AYNI SIRAYLA, {n} öğe yaz (karakter sınırlarına boşluklar dahildir):\n"
        f"- slide_title ≤ {TITLE_MAX}: çarpıcı ve bilgi veren başlık.\n"
        f"- slide_text ≤ {TEXT_MAX}: 2–3 cümle; ne oldu, kim, ne zaman, temel ayrıntı.\n"
        f"- why_it_matters ≤ {WHY_MAX}: tek cümle; okur için neden önemli (etkisi, bağlamı).\n"
        f"- caption_paragraph {pmin}–{pmax}: Instagram açıklaması için bu habere özel {'1–2' if pmax < 200 else '2–3'} cümlelik paragraf; "
        "slayttakini kelimesi kelimesine tekrar etme, ek bağlam ver. Başlık, numara, emoji, kaynak adı EKLEME.\n"
        "- source_url: o hikâyenin listesindeki linklerden biri, aynen (tercihen en bilgilendirici olan).\n"
        "- category: hikâyenin kategorisi.\n"
        "- image_prompt: İngilizce, tamamen soyut arka plan (ışık, şekil, parçacık, doku); marka/logo/ürün/"
        "karakter/kişi/yazı yok; tabela, ekran, vitrin, poster, şehir sokağı yok.\n"
        f"- caption_intro ≤ {INTRO_MAX}: GÜNÜN öne çıkanlarını anan 1–2 cümlelik giriş ('haftanın' deme). Haber SAYISI YAZMA.\n"
        f"- hashtags: {HASHTAG_MIN}-{HASHTAG_MAX} adet, '#' ile başlayan, boşluksuz.\n"
        "Kaynak listesi, hashtag ve YZ notunu caption alanlarına EKLEME (sistem ekleyecek).\n"
        "DOĞRULUK: Bütün alanlarda YALNIZCA aşağıdaki başlık ve özetlerde açıkça yazan bilgileri kullan. "
        "Özetlerde olmayan ayrıntı, sonuç, tepki ya da rakam EKLEME; ek bağlam gerekiyorsa diğer kaynakların "
        "özetlerinden al. Emin değilsen daha genel yaz.\n\n"
        + _stories_text(stories)
    )
    if errors:
        p += "\n\nÖNCEKİ YANITINDA ŞU HATALAR VARDI, DÜZELT:\n" + "\n".join(f"- {e}" for e in errors)
    return p


def para_limits(n: int) -> tuple[int, int]:
    """Caption 2.200 sınırına sığması için haber başına paragraf aralığı.
    Sabit kısımlar (giriş, hashtag, YZ notu) ≈400, haber başına başlık+kaynak ≈95 karakter."""
    hi = max(110, min(PARA_MAX, (CAPTION_MAX - 400 - 95 * n) // max(1, n)))
    return min(PARA_MIN, hi - 40), hi


def _shorten_to_sentence(text: str, limit: int) -> str:
    limit = max(40, limit)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > limit * 0.5 else cut[: limit - 1].rstrip() + "…"


def build_caption(intro: str, items: list[dict], hashtags: list[str]) -> str:
    """Giriş + her haber için başlık/paragraf/kaynak + hashtag + YZ notu (≤ CAPTION_MAX)."""
    tail = "\n\n" + " ".join(hashtags) + "\n\n" + AI_NOTE
    paras = [it["caption_paragraph"].strip() for it in items]

    def assemble(ps):
        blocks = [intro.strip()]
        for it, para in zip(items, ps):
            blocks.append(f"{CATEGORY_EMOJI.get(it['category'], '•')} {it['slide_title']}\n{para}\n"
                          f"Kaynak: {it['source_name']}")
        return "\n\n".join(blocks) + tail

    cap = assemble(paras)
    if len(cap) > CAPTION_MAX:
        # Taşma varsa her paragrafa eşit bütçe ver ve cümle sınırında kısalt
        fixed = len(assemble([""] * len(paras)))
        budget = max(60, (CAPTION_MAX - fixed) // max(1, len(paras)))
        paras = [_shorten_to_sentence(pa, budget) for pa in paras]
        cap = assemble(paras)
    return cap if len(cap) <= CAPTION_MAX else cap[: CAPTION_MAX - 1] + "…"


def build_alt_text(item: dict) -> str:
    label = "Teknoloji" if item["category"] == "teknoloji" else "Oyun"
    return (f"{label} haberi: {item['slide_title']}. {item['slide_text']} "
            f"Neden önemli: {item['why_it_matters']} Kaynak: {item['source_name']}.")[:1000]


def validate(data: dict, stories: list[Story]) -> list[str]:
    """Hata listesi döndürür; boş liste = geçerli."""
    errs: list[str] = []
    items = data.get("items")
    if not isinstance(items, list) or len(items) != len(stories):
        return [f"items tam olarak {len(stories)} öğe olmalı"]
    limits = {"slide_title": (1, TITLE_MAX), "slide_text": (1, TEXT_MAX),
              "why_it_matters": (1, WHY_MAX), "caption_paragraph": para_limits(len(items))}
    for n, (it, st) in enumerate(zip(items, stories), 1):
        for field, (lo, hi) in limits.items():
            v = str(it.get(field, "")).strip()
            if len(v) < lo:
                errs.append(f"{n}. {field} boş ya da çok kısa (en az {lo})")
            elif len(v) > hi:
                errs.append(f"{n}. {field} {len(v)} karakter (en fazla {hi})")
        if it.get("source_url") not in {a.url for a in st.articles}:
            errs.append(f"{n}. source_url hikâyenin linklerinden biri değil")
        if it.get("category") not in ("teknoloji", "oyun"):
            errs.append(f"{n}. category geçersiz")
        ip = str(it.get("image_prompt", ""))
        if not ip.strip() or len(ip) > 500 or not ip.isascii():
            errs.append(f"{n}. image_prompt boş, çok uzun ya da İngilizce değil")
    need = min_per_category(len(items))
    cats = Counter(it.get("category") for it in items)
    if cats["oyun"] < need or cats["teknoloji"] < need:
        errs.append(f"her kategoriden en az {need} haber olmalı")
    tags = data.get("hashtags") or []
    if not (HASHTAG_MIN <= len(tags) <= HASHTAG_MAX) or any(
        not str(h).startswith("#") or " " in str(h) for h in tags
    ):
        errs.append(f"hashtags {HASHTAG_MIN}-{HASHTAG_MAX} adet, '#' ile başlayan ve boşluksuz olmalı")
    intro = str(data.get("caption_intro", "")).strip()
    if not intro or len(intro) > INTRO_MAX:
        errs.append(f"caption_intro boş ya da {INTRO_MAX} karakterden uzun")
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
    """Tekilleştirilmiş haberlerden günün carousel içeriğini üretir (3–8 haber, önemine göre)."""
    model = model or model_name()
    system = load_system_prompt()
    cands = prefilter(articles)
    if len(cands) < MIN_ITEMS:
        raise LLMError(f"Yeterli aday haber yok ({len(cands)})")

    chosen: list[Story] | None = None
    for _ in range(2):  # seçim de bozuksa 1 kez tekrar
        try:
            chosen = pick_stories(select_stories(cands, generate, model, system))
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
        item = {
            "slide_title": it["slide_title"].strip(),
            "slide_text": it["slide_text"].strip(),
            "why_it_matters": it["why_it_matters"].strip(),
            "caption_paragraph": it["caption_paragraph"].strip(),
            "source_name": url_source[it["source_url"]],
            "source_url": it["source_url"],
            "category": it["category"],
            "image_prompt": it["image_prompt"].strip(),
            "importance": st.importance,
            "all_sources": [{"name": a.source, "url": a.url} for a in st.articles],
            "headline": st.headline,
        }
        item["alt_text"] = build_alt_text(item)
        items.append(item)
    caption = build_caption(data["caption_intro"], items, data["hashtags"])
    return {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "model": last_model_used or model,
        "candidates": len(cands),
        "items": items,
        "caption": caption,
    }
