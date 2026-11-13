"""Faz 2 testleri — Gemini çağrısı sahte; ağ ve gerçek anahtar kullanılmaz."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from bot import llm_gemini as L
from bot import settings
from bot.collector import Article

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def art(i, cat, source=None, related=()):
    return Article(
        title=f"Haber {i}", url=f"https://s.test/{i}", source=source or f"Kaynak{i % 7}",
        category=cat, lang="tr", published=NOW - timedelta(hours=i % 20),
        summary=f"Özet {i}", related=list(related),
    )


ARTICLES = [art(i, "oyun" if i % 2 else "teknoloji") for i in range(40)]


def good_items(stories_urls, cats):
    return [
        {
            "slide_title": f"Başlık {n}", "slide_text": "Kısa ve öz bir açıklama.",
            "why_it_matters": "Sektörü etkileyebilir.",
            "caption_paragraph": "Bu habere özel, slayttakinden farklı ek bağlam veren iki üç cümlelik bir paragraf burada yer alıyor.",
            "source_url": url, "category": c,
            "image_prompt": "abstract neon waves over deep blue gradient, soft light",
        }
        for n, (url, c) in enumerate(zip(stories_urls, cats), 1)
    ]


class FakeGemini:
    """Sıradaki yanıtları döndürür; seçim yanıtından sonra yazım yanıtlarını üretir."""

    def __init__(self, select=None, writes=None):
        self.select = select
        self.writes = list(writes or [])
        self.calls = []

    def __call__(self, model, system, prompt, schema):
        self.calls.append((schema is L.SELECT_SCHEMA, prompt))
        if schema is L.SELECT_SCHEMA:
            return json.dumps(self.select)
        w = self.writes.pop(0)
        return w(prompt) if callable(w) else w


def default_select(importances=(9, 8, 7, 7, 6, 4)):
    cats = ["teknoloji", "oyun", "teknoloji", "oyun", "teknoloji", "teknoloji"]
    ids = [[0, 1], [2], [3], [4], [5], [6]]
    return {"stories": [
        {"ids": i, "category": c, "importance": imp, "headline_tr": "x"}
        for i, c, imp in zip(ids, cats, importances)
    ]}


def urls_from_prompt(prompt):
    """Yazım istemindeki her hikâyenin ilk linkini sırayla döndürür."""
    out, cur = [], None
    for line in prompt.splitlines():
        if line.startswith("### Hikâye"):
            cur = True
        elif cur and "Link: " in line:
            out.append(line.split("Link: ")[1].strip())
            cur = False
    return out


def cats_from_prompt(prompt):
    return [l.split("kategori: ")[1].strip() for l in prompt.splitlines() if l.startswith("### Hikâye")]


def writer(title_len=20, tags=6):
    def w(prompt):
        urls, cats = urls_from_prompt(prompt), cats_from_prompt(prompt)
        items = good_items(urls, cats)
        for it in items:
            it["slide_title"] = "B" * title_len
        return json.dumps({"items": items, "caption_intro": "Günün öne çıkan gelişmeleri.",
                           "hashtags": [f"#etiket{i}" for i in range(tags)]})
    return w


def test_generate_post_happy_path():
    fake = FakeGemini(default_select(), [writer()])
    post = L.generate_post(ARTICLES, generate=fake, model="test-model", now=NOW)
    assert len(post["items"]) == 5  # önem ≥6 olan 5 hikâye
    cats = [i["category"] for i in post["items"]]
    assert cats.count("oyun") >= 2 and cats.count("teknoloji") >= 2
    for it in post["items"]:
        assert len(it["slide_title"]) <= 60 and len(it["slide_text"]) <= L.TEXT_MAX
        assert it["alt_text"].startswith(("Teknoloji haberi", "Oyun haberi"))
        assert it["source_url"].startswith("https://s.test/")
        assert it["source_name"].startswith("Kaynak")
    assert post["caption"].endswith(L.AI_NOTE)
    assert post["caption"].count("Kaynak: ") == 5 and len(post["caption"]) <= L.CAPTION_MAX
    assert "🎮" in post["caption"] and "💻" in post["caption"]
    assert len(fake.calls) == 2


def test_retry_once_on_invalid_then_success():
    fake = FakeGemini(default_select(), [writer(title_len=80), writer()])
    post = L.generate_post(ARTICLES, generate=fake, model="m", now=NOW)
    assert len(post["items"]) == 5
    retry_prompt = fake.calls[-1][1]
    assert "HATALAR" in retry_prompt and "slide_title 80 karakter" in retry_prompt


def test_fails_after_two_invalid_attempts():
    fake = FakeGemini(default_select(), [writer(title_len=80), writer(title_len=80)])
    with pytest.raises(L.LLMError, match="2 denemede"):
        L.generate_post(ARTICLES, generate=fake, model="m", now=NOW)


def test_broken_json_is_retried():
    fake = FakeGemini(default_select(), ["{bozuk json", writer()])
    assert len(L.generate_post(ARTICLES, generate=fake, model="m", now=NOW)["items"]) == 5


def test_hallucinated_url_rejected():
    def bad(prompt):
        data = json.loads(writer()(prompt))
        data["items"][0]["source_url"] = "https://uydurma.test/x"
        return json.dumps(data)
    fake = FakeGemini(default_select(), [bad, bad])
    with pytest.raises(L.LLMError):
        L.generate_post(ARTICLES, generate=fake, model="m", now=NOW)


def test_pick_stories_variable_count_and_balance():
    S = lambda c, i: L.Story([], c, "", i)
    # sakin gün: yalnızca 2 hikâye eşiği geçiyor → en az 3, dengeli
    calm = L.pick_stories([S("teknoloji", 8), S("teknoloji", 7), S("teknoloji", 5), S("oyun", 4)])
    assert len(calm) == 3 and sum(s.category == "oyun" for s in calm) == 1
    # yoğun gün: 12 güçlü hikâye → en fazla 8
    busy = L.pick_stories([S("oyun" if i % 2 else "teknoloji", 9) for i in range(12)])
    assert len(busy) == 8
    # dengesiz: hepsi teknoloji eşiği geçiyor → 2 oyun eklenir/takas edilir
    tech_heavy = [S("teknoloji", 9) for _ in range(8)] + [S("oyun", 5), S("oyun", 3)]
    pk = L.pick_stories(tech_heavy)
    assert len(pk) == 8 and sum(s.category == "oyun" for s in pk) == 2
    with pytest.raises(L.LLMError):
        L.pick_stories([S("teknoloji", 9) for _ in range(6)])


def test_hashtag_rules():
    fake = FakeGemini(default_select(), [writer(tags=3), writer(tags=3)])
    with pytest.raises(L.LLMError, match="hashtags"):
        L.generate_post(ARTICLES, generate=fake, model="m", now=NOW)


def test_quota_error_not_retried():
    def quota(*a):
        raise L.QuotaError("429")
    with pytest.raises(L.QuotaError):
        L.generate_post(ARTICLES, generate=quota, model="m", now=NOW)


def test_build_caption_trims_paragraphs_to_limit():
    items = [{"category": "oyun", "slide_title": "Başlık", "source_name": "A",
              "caption_paragraph": "Uzun bir cümle burada. " * 40} for _ in range(8)]
    cap = L.build_caption("Giriş.", items, ["#a"] * 5)
    assert len(cap) <= L.CAPTION_MAX and cap.endswith(L.AI_NOTE)
    assert cap.count("Kaynak: A") == 8


def test_prefilter_balance_and_source_cap():
    many = [art(i, "teknoloji", source="Tek") for i in range(50)] + [art(100 + i, "oyun") for i in range(30)]
    out = L.prefilter(many, limit=20, per_source=6)
    assert sum(1 for a in out if a.source == "Tek") <= 6
    assert sum(1 for a in out if a.category == "oyun") >= 10


# --------------------------------------------------------------------------- gizli bilgi

def test_mask_never_reveals_more_than_4():
    assert settings.mask("AIzaSyABCDEFGHIJKLMNOP1234") == "••••1234"
    assert settings.mask("short") == "••••"
    assert settings.mask("") == "••••"


def test_scrub_hides_env_values(monkeypatch):
    secret = "AIzaFAKEVALUE0000000000000000XYZW"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    out = settings.scrub(f"hata: https://x.test/?key={secret}")
    assert secret not in out and "XYZW" in out
    tg = "123456789:" + "AA" + "FAKE" * 7 + "12"  # parçalı: commit taraması sahte değeri yakalamasın
    assert tg not in settings.scrub(f"https://api.telegram.org/bot{tg}/getMe")


def test_check_output_masks_secrets(monkeypatch):
    """check, servis hatası verse bile gizli değeri yazdırmaz."""
    from bot import check

    secret = "cf_FAKE_TOKEN_abcdefghijklmnopqrstuv"
    monkeypatch.setenv("CF_API_TOKEN", secret)
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc_fake_1234567890")

    def boom(url, **k):
        raise ConnectionError(f"failed {url} {k['headers']['Authorization']}")

    monkeypatch.setattr(check.requests, "get", boom)
    res = check.check_cloudflare()
    assert res.ok is False and secret not in res.message


def test_env_file_is_gitignored():
    import subprocess
    from bot.config import ROOT
    r = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT)
    assert r.returncode == 0


def test_model_fallback_chain(monkeypatch):
    """Yoğun (503) ve kotası dolu (429) modeller atlanır, sıradaki ücretsiz modele geçilir."""
    from google.genai import errors

    calls = []

    class Resp:
        text = '{"ok": true}'

    def fake_call(client, model, system, prompt, schema):
        calls.append(model)
        if model == "m1":
            raise errors.APIError(503, {"error": {"message": "busy"}})
        if model == "m2":
            raise errors.APIError(429, {"error": {"message": "quota"}})
        return Resp()

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test-0000")
    monkeypatch.setattr(L, "_call_once", fake_call)
    monkeypatch.setattr(L, "make_client", lambda *a, **k: object())
    assert L.gemini_generate("m1,m2,m3", "s", "p", {}) == '{"ok": true}'
    assert calls == ["m1", "m2", "m3"] and L.last_model_used == "m3"


def test_all_models_quota_raises_quota_error(monkeypatch):
    from google.genai import errors

    def quota(*a):
        raise errors.APIError(429, {"error": {"message": "quota"}})

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test-0000")
    monkeypatch.setattr(L, "_call_once", quota)
    monkeypatch.setattr(L, "make_client", lambda *a, **k: object())
    with pytest.raises(L.QuotaError):
        L.gemini_generate("m1,m2", "s", "p", {})


@pytest.mark.parametrize("n", [3, 5, 8])
def test_caption_fits_when_paragraphs_at_limit(n):
    """Gemini sınırın tamamını kullansa bile caption 2.200'e sığar ve paragraf boşalmaz."""
    lo, hi = L.para_limits(n)
    items = [{"category": "oyun", "slide_title": "B" * 60, "source_name": "Rock Paper Shotgun",
              "caption_paragraph": ("Cümle bir iki üç dört. " * 30)[:hi]} for _ in range(n)]
    cap = L.build_caption("G" * L.INTRO_MAX, items, ["#etiketuzun"] * 10)
    assert len(cap) <= L.CAPTION_MAX
    for block in cap.split("\n\n")[1:n + 1]:
        assert len(block.splitlines()[1]) >= 40  # paragraf satırı boş değil


def test_shorten_never_empties():
    assert len(L._shorten_to_sentence("Bir cümle. " * 50, -300)) >= 30
