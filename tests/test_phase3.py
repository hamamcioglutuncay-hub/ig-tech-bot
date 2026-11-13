"""Faz 3 testleri — composer ve imagegen (ağ yok; FLUX yanıtı sahte)."""
import base64
import io
import json
from datetime import date
from pathlib import Path

import pytest
from PIL import Image, ImageFont

from bot import composer as C
from bot import imagegen as G
from bot.config import ROOT

OVERLAY = {"layout": "overlay", "background": {"tint": "none"}, "title": {"upper": False, "highlight": False}}


@pytest.fixture(params=["panel", "overlay"])
def variant(request, tmp_path):
    if request.param == "panel":
        return None  # design.yaml (panel düzeni)
    import yaml
    f = tmp_path / "overlay.yaml"
    f.write_text(yaml.safe_dump(OVERLAY), encoding="utf-8")
    return f
TR = "ğĞşŞıİöÖüÜçÇ"

LONG = {
    "slide_title": "Çok uzun bir başlık: Şirketin İstanbul'daki ğüşıöç yatırımı " * 2,
    "slide_text": "Uzun açıklama metni ğüşıöçİ " * 20,
    "why_it_matters": "Bu gelişme sektörü derinden etkileyebilir çünkü ğüşıöç " * 4,
    "source_name": "DonanımHaber", "category": "oyun", "image_prompt": "x",
}
ITEM = {"slide_title": "Yeni İşlemci Tanıtıldı: Çığır Açan Güç", "slide_text": "Şirket, ğüşıöç İçin yeni çipini duyurdu.",
        "why_it_matters": "Dizüstü pazarında rekabeti artırabilir.",
        "source_name": "Webtekno", "category": "teknoloji", "image_prompt": "x"}


def bg():
    return Image.new("RGB", (1024, 1024), (200, 210, 230))  # açık renk: okunabilirlik katmanını zorlar


@pytest.mark.parametrize("font", ["assets/fonts/ArchivoBlack-Regular.ttf", "assets/fonts/Archivo-Variable.ttf"])
def test_fonts_have_turkish_glyphs(font):
    f = ImageFont.truetype(str(ROOT / font), 60)
    notdef = f.getmask("￿").getbbox()
    assert all(f.getmask(ch).getbbox() not in (None, notdef) for ch in TR)


def test_tr_upper_and_date():
    assert C.tr_upper("istifa ılık") == "İSTİFA ILIK"
    assert C.tr_date(date(2026, 11, 13)) == "13 Kasım 2026 · Cuma"


def test_long_text_stays_in_canvas(variant):
    d = C.load_design(variant)
    comp = C.Composer(d)
    img = comp.news_slide(bg(), LONG, 2, 7)
    assert img.size == (1080, 1350)
    lay = comp.last_layout
    m = d["margin"]
    for key in ("title", "text"):
        ft = lay[key]
        assert len(ft.lines) <= d[key]["max_lines"]
        assert all(ft.font.getlength(l) <= 1080 - 2 * m for l in ft.lines)
    # bloklar üst üste binmemeli ve kaynak etiketinin üstünde bitmeli
    assert lay["y_title"] + lay["title"].height <= lay["y_text"]
    assert lay["y_text"] + lay["text"].height <= lay["y_why"]
    assert lay["y_why"] + lay["why_h"] <= lay["y_source"]
    assert lay["y_title"] >= 150
    assert lay["y_source"] + d["source"]["size"] <= 1350 - m + 10


@pytest.mark.parametrize("n", [3, 5, 8])
def test_render_carousel_variable_count(tmp_path, n):
    post = {"items": [dict(ITEM, category="oyun" if i % 2 else "teknoloji") for i in range(n)]}
    bgs = {"cover": bg(), **{i: bg() for i in range(1, n + 1)}, 2: None}  # 2: marka zemini yedeği
    paths = C.render_carousel(post, bgs, date(2026, 11, 13), tmp_path, C.load_design())
    assert [p.name for p in paths] == [f"{i:02d}.jpg" for i in range(1, n + 3)]
    for p in paths:
        im = Image.open(p)
        assert im.format == "JPEG" and im.size == (1080, 1350)


def test_logo_and_source_label_drawn():
    d = C.load_design()
    comp = C.Composer(d)
    img = comp.news_slide(Image.new("RGB", (1024, 1024), (0, 0, 0)), ITEM, 2, 7)
    m = d["margin"]
    # logo bölgesi siyah zeminde boş olmamalı
    logo_box = img.crop((m, m - 16, m + d["header"]["logo_size"], m - 16 + d["header"]["logo_size"]))
    assert logo_box.convert("L").getextrema()[1] > 100
    y = comp.last_layout["y_source"]
    src_box = img.crop((m, y, m + 300, y + d["source"]["size"] + 6))
    assert src_box.convert("L").getextrema()[1] > 100


def test_template_layer_used_if_present(tmp_path, monkeypatch):
    tdir = tmp_path / "templates"
    tdir.mkdir()
    Image.new("RGBA", (1080, 1350), (255, 0, 0, 255)).save(tdir / "slide.png")
    monkeypatch.setattr(C, "TEMPLATES_DIR", tdir)
    img = C.Composer(C.load_design()).news_slide(bg(), ITEM, 2, 7)
    assert img.getpixel((1070, 700))[0] > 200  # kırmızı şablon katmanı görünüyor


# --------------------------------------------------------------------------- imagegen

class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._p = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        return self._p


def _jpeg_b64():
    buf = io.BytesIO()
    Image.new("RGB", (1024, 1024), (10, 20, 30)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, headers, json, timeout):
        self.calls.append(json)
        return self.responses.pop(0)


@pytest.fixture
def cf_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc0000000000")
    monkeypatch.setenv("CF_API_TOKEN", "tok000000000000")
    monkeypatch.setattr(G, "USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(G, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    return tmp_path


def test_generate_image_saves_and_records_usage(cf_env):
    s = FakeSession([FakeResp(200, {"result": {"image": _jpeg_b64()}, "success": True})])
    out = G.generate_image("neon waves", cf_env / "bg.jpg", session=s)
    assert Image.open(out).size == (1024, 1024)
    assert "no text" in s.calls[0]["prompt"] and s.calls[0]["steps"] == G.STEPS
    assert G.used_today(cf_env / "usage.json") == pytest.approx(G.NEURONS_PER_IMAGE)
    # önbellek: ikinci çağrı API'ye gitmez
    G.generate_image("neon waves", out, session=FakeSession([]))


def test_quota_errors(cf_env):
    s = FakeSession([FakeResp(429, {"errors": [{"code": 4006}]})])
    with pytest.raises(G.ImageQuotaError):
        G.generate_image("x", cf_env / "a.jpg", session=s)
    G.record_usage(G.DAILY_FREE_NEURONS)  # bugünkü kota dolmuş gibi
    with pytest.raises(G.ImageQuotaError):
        G.generate_image("x", cf_env / "b.jpg", session=FakeSession([]))


def test_server_error_retried_once(cf_env):
    s = FakeSession([FakeResp(500, text="boom"), FakeResp(200, {"result": {"image": _jpeg_b64()}})])
    G.generate_image("x", cf_env / "c.jpg", session=s)
    assert len(s.calls) == 2


def test_cover_has_no_fixed_count_and_list_fits():
    d = C.load_design()
    assert not any(ch.isdigit() for ch in d["cover"]["title"] + d["cover"]["kicker"] + d["outro"]["subtitle"])
    comp = C.Composer(d)
    items = [dict(ITEM, category="oyun" if i % 2 else "teknoloji") for i in range(8)]
    comp.cover_slide(bg(), date(2026, 11, 13), items, 10)
    assert comp.last_cover["date_bottom"] <= comp.last_cover["list_top"]
