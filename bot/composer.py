"""Pillow ile carousel slaytları: kapak + 3–8 haber + kapanış (1080×1350 JPEG).

Bütün görsel kararlar design.yaml'dan (ve isteğe bağlı designs/*.yaml üst yazımından) gelir.
assets/templates/{cover,slide,outro}.png varsa, arka planın üstüne katman olarak eklenir.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import ROOT

DESIGN_FILE = ROOT / "design.yaml"
TEMPLATES_DIR = ROOT / "assets" / "templates"

AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
         "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
CATEGORY_LABEL = {"teknoloji": "TEKNOLOJİ", "oyun": "OYUN"}


# --------------------------------------------------------------------------- tasarım dosyası

def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_design(variant: Path | str | None = None, base: Path = DESIGN_FILE) -> dict:
    d = yaml.safe_load(Path(base).read_text(encoding="utf-8"))
    if variant:
        d = _deep_merge(d, yaml.safe_load(Path(variant).read_text(encoding="utf-8")) or {})
    return d


# --------------------------------------------------------------------------- yardımcılar

def tr_upper(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def tr_date(d: date) -> str:
    return f"{d.day} {AYLAR[d.month - 1]} {d.year} · {GUNLER[d.weekday()]}"


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@lru_cache(maxsize=256)
def _font(file: str, size: int, weight: int | None, width: int | None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(ROOT / file), size)
    if weight is not None or width is not None:
        axes = {a["name"]: a["default"] for a in f.get_variation_axes()}
        if weight is not None:
            axes[b"Weight"] = weight
        if width is not None:
            axes[b"Width"] = width
        f.set_variation_by_axes([axes[b"Weight"], axes[b"Width"]])
    return f


def cover_fit(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (w, h), method=Image.LANCZOS, centering=(0.5, 0.5))


def duotone(img: Image.Image, dark: tuple, light: tuple, strength: float) -> Image.Image:
    g = ImageOps.grayscale(img)
    toned = ImageOps.colorize(g, black=dark, white=light, mid=None)
    return Image.blend(img.convert("RGB"), toned, strength)


def vertical_alpha(w: int, h: int, y0: int, y1: int, a0: float, a1: float) -> Image.Image:
    """y0→y1 arasında a0→a1 geçişli alfa maskesi (yumuşak eğri)."""
    col = Image.new("L", (1, h))
    for y in range(h):
        if y <= y0:
            t = 0.0
        elif y >= y1:
            t = 1.0
        else:
            t = (y - y0) / max(1, y1 - y0)
            t = t * t * (3 - 2 * t)  # smoothstep
        col.putpixel((0, y), int(255 * (a0 + (a1 - a0) * t)))
    return col.resize((w, h))


@dataclass
class Fitted:
    font: ImageFont.FreeTypeFont
    lines: list[str]
    size: int
    line_h: int

    @property
    def height(self) -> int:
        return self.line_h * len(self.lines)


def wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Kelime bazlı satır kırma; metindeki elle konmuş satır sonlarına (\\n) uyar."""
    if "\n" in text:
        return [l for part in text.split("\n") for l in wrap(part, font, max_w)]
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if font.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# --------------------------------------------------------------------------- composer

class Composer:
    def __init__(self, design: dict):
        self.d = design
        self.W = design["canvas"]["width"]
        self.H = design["canvas"]["height"]
        self.M = design["margin"]
        c = design["colors"]
        self.c = {k: hex_rgb(v) for k, v in c.items()}
        self.logo = Image.open(ROOT / design["brand"]["logo"]).convert("RGBA")
        bbox = self.logo.getbbox()
        if bbox:
            self.logo = self.logo.crop(bbox)

    # ---- yazı tipleri
    def font(self, key: str, size: int) -> ImageFont.FreeTypeFont:
        spec = self.d["fonts"][key]
        return _font(spec["file"], int(size), spec.get("weight"), spec.get("width"))

    def fit(self, text: str, key: str, max_size: int, min_size: int, max_w: int,
            max_lines: int, spacing: float, scale: float = 1.0) -> Fitted:
        hi = max(min_size, int(max_size * scale))
        for size in range(hi, min_size - 1, -2):
            f = self.font(key, size)
            lines = wrap(text, f, max_w)
            if len(lines) <= max_lines and all(f.getlength(l) <= max_w for l in lines):
                return Fitted(f, lines, size, int(size * spacing))
        # en küçük boyutta da sığmadı: son satırı "…" ile kısalt
        f = self.font(key, min_size)
        lines = wrap(text, f, max_w)[:max_lines]
        last = lines[-1]
        while last and f.getlength(last + "…") > max_w:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
        return Fitted(f, lines, min_size, int(min_size * spacing))

    # ---- katmanlar
    def _logo(self, size: int) -> Image.Image:
        lw, lh = self.logo.size
        s = size / max(lw, lh)
        return self.logo.resize((max(1, int(lw * s)), max(1, int(lh * s))), Image.LANCZOS)

    def _template(self, name: str) -> Image.Image | None:
        p = TEMPLATES_DIR / f"{name}.png"
        if p.exists():
            return Image.open(p).convert("RGBA").resize((self.W, self.H), Image.LANCZOS)
        return None

    def _background(self, bg: Image.Image | None, accent: tuple | None) -> Image.Image:
        if bg is None:
            return self.brand_backdrop()
        img = cover_fit(bg, self.W, self.H)
        b = self.d["background"]
        if b.get("tint") == "duotone" and accent:
            img = duotone(img, self.c["bg"], accent, float(b.get("tint_strength", 0.6)))
        br = float(b.get("brightness", 1.0))
        if br != 1.0:
            img = Image.blend(Image.new("RGB", img.size, (0, 0, 0)), img, br)
        return img.convert("RGBA")

    def brand_backdrop(self) -> Image.Image:
        """Kodla çizilen marka zemini: lacivert + camgöbeği/mor ışık lekeleri (API harcamaz)."""
        base = Image.new("RGBA", (self.W, self.H), self.c["bg"] + (255,))
        glow = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        g = ImageDraw.Draw(glow)
        g.ellipse((-350, -300, 650, 650), fill=self.c["teknoloji"] + (110,))
        g.ellipse((450, 750, 1450, 1700), fill=self.c["oyun"] + (120,))
        glow = glow.filter(ImageFilter.GaussianBlur(220))
        return Image.alpha_composite(base, glow)

    def _shade(self, img: Image.Image, y0: int, y1: int, a0: float, a1: float) -> Image.Image:
        layer = Image.new("RGBA", img.size, self.c["bg"] + (0,))
        layer.putalpha(vertical_alpha(self.W, self.H, y0, y1, a0, a1))
        return Image.alpha_composite(img, layer)

    def _top_shade(self, img: Image.Image) -> Image.Image:
        a = float(self.d.get("top_shade", 0))
        if a <= 0:
            return img
        layer = Image.new("RGBA", img.size, self.c["bg"] + (0,))
        mask = vertical_alpha(self.W, self.H, 0, 300, a, 0.0)
        layer.putalpha(mask)
        return Image.alpha_composite(img, layer)

    def _header(self, img: Image.Image, number: str | None) -> int:
        """Logo + kullanıcı adı + slayt numarası. Header'ın alt y değerini döndürür."""
        h = self.d["header"]
        draw = ImageDraw.Draw(img)
        logo = self._logo(h["logo_size"])
        y = self.M - 16
        img.alpha_composite(logo, (self.M, y))
        f = self.font("label", h["handle_size"])
        ty = y + logo.height // 2 - h["handle_size"] // 2 - 4
        draw.text((self.M + logo.width + 18, ty), self.d["brand"]["handle"], font=f, fill=self.c["text"])
        if number:
            fn = self.font("label", h["number_size"])
            tw = fn.getlength(number)
            draw.text((self.W - self.M - tw, ty), number, font=fn, fill=self.c["text"])
        return y + logo.height

    def _badge(self, draw: ImageDraw.ImageDraw, x: int, y: int, label: str, accent: tuple) -> int:
        b = self.d["badge"]
        f = self.font("label", b["size"])
        if b.get("style") == "line":
            draw.rectangle((x, y + b["size"] // 2, x + 44, y + b["size"] // 2 + 4), fill=accent)
            draw.text((x + 58, y - 3), label, font=f, fill=accent)
            return b["size"] + 6
        tw = f.getlength(label)
        h = b["size"] + 2 * b["pad_y"]
        draw.rounded_rectangle((x, y, x + tw + 2 * b["pad_x"], y + h), radius=h // 2, fill=accent)
        draw.text((x + b["pad_x"], y + b["pad_y"] - 3), label, font=f, fill=self.c["on_accent"])
        return h

    def _draw_title(self, draw: ImageDraw.ImageDraw, x: int, y: int, ft: Fitted, accent: tuple) -> None:
        t = self.d["title"]
        for i, line in enumerate(ft.lines):
            ly = y + i * ft.line_h
            if t.get("highlight"):
                pad = int(ft.size * 0.18)
                l, top, r, bot = draw.textbbox((x, ly), line, font=ft.font)
                draw.rectangle((l - pad, top - pad, r + pad, bot + pad), fill=accent)
                draw.text((x, ly), line, font=ft.font, fill=self.c["on_accent"])
            else:
                draw.text((x, ly), line, font=ft.font, fill=self.c["text"])

    # ---- haber slaytı
    def news_slide(self, bg: Image.Image | None, item: dict, index: int, total: int) -> Image.Image:
        d = self.d
        accent = self.c[item["category"]]
        img = self._background(bg, accent)
        tmpl = self._template("slide")

        title_text = tr_upper(item["slide_title"]) if d["title"].get("upper") else item["slide_title"]
        label = CATEGORY_LABEL[item["category"]]
        text_w = self.W - 2 * self.M - (int(d["title"]["max_size"] * 0.2) if d["title"].get("highlight") else 0)
        g = d["gaps"]
        badge_h = d["badge"]["size"] + 2 * d["badge"]["pad_y"]
        source_h = d["source"]["size"] + 8

        panel = d.get("layout") == "panel"
        pad_top = badge_h // 2 + 34
        if panel:
            area_top = int(self.H * (1 - d["panel_ratio"])) + pad_top
        else:
            area_top = 260
        area_bottom = self.H - self.M
        avail = area_bottom - area_top

        why = (item.get("why_it_matters") or "").strip()
        wy = d.get("why", {})
        why_indent = 24
        why_label_h = wy.get("label_size", 22) + 10

        # Başlık, metin ve "Neden önemli?" bloğunu birlikte küçülterek alana sığdır
        for scale in [1.0, 0.94, 0.88, 0.82, 0.76, 0.7, 0.64]:
            tt, tx = d["title"], d["text"]
            ft = self.fit(title_text, tt.get("font", "heading"), tt["max_size"], tt["min_size"],
                          text_w, tt["max_lines"], tt["line_spacing"], scale)
            fx = self.fit(item["slide_text"], tx.get("font", "body"), tx["max_size"], tx["min_size"],
                          self.W - 2 * self.M, tx["max_lines"], tx["line_spacing"], scale)
            fw = None
            why_h = 0
            if why and wy:
                fw = self.fit(why, wy.get("font", "body"), wy["max_size"], wy["min_size"],
                              self.W - 2 * self.M - why_indent, wy["max_lines"], wy["line_spacing"], scale)
                why_h = why_label_h + fw.height
            total_h = (0 if panel else badge_h + g["badge_title"]) + ft.height + g["title_text"] \
                + fx.height + (g.get("text_why", 30) + why_h if fw else 0) + g["text_source"] + source_h
            if total_h <= avail:
                break

        y_source = area_bottom - source_h
        if panel:
            # Panel yüksekliği içeriğe göre: kısa haberde görsel daha çok yer kaplar
            min_py = int(self.H * (1 - d["panel_ratio"]))
            max_py = int(self.H * (1 - d.get("panel_min_ratio", d["panel_ratio"])))
            py = min(max_py, max(min_py, area_bottom - total_h - pad_top))
            area_top = py + pad_top
            img = self._shade(img, py - 160, py, 0.0, 1.0)
            y_badge = py - badge_h // 2
            y_title = area_top                      # panelde metin yukarıdan akar
            y_text = y_title + ft.height + g["title_text"]
            y_why = y_text + fx.height + g.get("text_why", 30)
        else:                                       # görsel üstünde: alttan yukarı
            y_why = y_source - g["text_source"] - why_h
            y_text = (y_why - g.get("text_why", 30) if fw else y_source - g["text_source"]) - fx.height
            y_title = y_text - g["title_text"] - ft.height
            y_badge = y_title - g["badge_title"] - badge_h
            gy = y_badge - d["gradient"]["extend_above_text"]
            img = self._shade(img, gy, y_badge + 120, 0.0, float(d["gradient"]["max_opacity"]))
        img = self._top_shade(img)
        if tmpl:
            img.alpha_composite(tmpl)

        self._header(img, f"{index}/{total}")
        draw = ImageDraw.Draw(img)
        self._badge(draw, self.M, y_badge, label, accent)
        hl = d["title"].get("highlight")
        self._draw_title(draw, self.M + (int(ft.size * 0.18) if hl else 0), y_title, ft, accent)
        ab = d["accent_bar"]
        if not hl:
            bar_y = y_title + ft.height + g["title_text"] // 2 - ab["height"] // 2
            draw.rectangle((self.M, bar_y, self.M + ab["width"], bar_y + ab["height"]), fill=accent)
        for i, line in enumerate(fx.lines):
            draw.text((self.M, y_text + i * fx.line_h), line, font=fx.font, fill=self.c["text"])

        if fw:
            fl = self.font("label", wy.get("label_size", 22))
            draw.rectangle((self.M, y_why + 4, self.M + 5, y_why + why_h - 6), fill=accent)
            draw.text((self.M + why_indent, y_why - 2), wy.get("label", "NEDEN ÖNEMLİ?"), font=fl, fill=accent)
            for i, line in enumerate(fw.lines):
                draw.text((self.M + why_indent, y_why + why_label_h + i * fw.line_h), line, font=fw.font,
                          fill=self.c["text_muted"])

        fs = self.font("label", d["source"]["size"])
        draw.text((self.M, y_source), d["source"]["prefix"] + item["source_name"], font=fs,
                  fill=self.c["text_muted"])
        hint = d["source"].get("swipe_hint")
        if hint:
            draw.text((self.W - self.M - fs.getlength(hint), y_source), hint, font=fs, fill=accent)
        self.last_layout = {"title": ft, "text": fx, "why": fw, "why_h": why_h, "y_title": y_title,
                            "y_text": y_text, "y_why": y_why, "y_source": y_source, "y_badge": y_badge}
        return img.convert("RGB")

    # ---- kapak
    def cover_slide(self, bg: Image.Image | None, day: date, items: list[dict], total: int) -> Image.Image:
        d, cv = self.d, self.d["cover"]
        img = self._background(bg, None)
        img = self._shade(img, int(self.H * 0.25), int(self.H * 0.7), 0.15, 0.92)
        img = self._top_shade(img)
        tmpl = self._template("cover")
        if tmpl:
            img.alpha_composite(tmpl)
        draw = ImageDraw.Draw(img)

        logo = self._logo(cv["logo_size"])
        y = self.M + 10
        img.alpha_composite(logo, ((self.W - logo.width) // 2, y))
        y += logo.height + 28
        fh = self.font("label", d["header"]["handle_size"] + 2)
        hw = fh.getlength(d["brand"]["handle"])
        draw.text(((self.W - hw) / 2, y), d["brand"]["handle"], font=fh, fill=self.c["text"])

        logo_bottom = y + 60
        # İçerik listesi (alt kısım) — haber sayısına göre boyut
        n_items = len(items)
        list_size = cv["list_size"] if n_items <= 5 else int(cv["list_size"] * 0.88)
        line_h = int(list_size * 1.55)
        list_top = self.H - self.M - 46 - line_h * n_items

        # Başlık bloğu (ortalanmış), listenin üstüne sığacak şekilde
        ft = self.fit(cv["title"], "heading", cv["title_size"], 56, self.W - 2 * self.M,
                      cv["title"].count("\n") + 1, 1.04)
        block_h = 52 + ft.height + 18 + 40
        y = max(logo_bottom, min(int(self.H * 0.40), list_top - block_h - 50))
        fk = self.font("label", 34)
        kick = cv["kicker"]
        draw.text(((self.W - fk.getlength(kick)) / 2, y), kick, font=fk, fill=self.c["teknoloji"])
        y += 52
        for line in ft.lines:
            lw = ft.font.getlength(line)
            draw.text(((self.W - lw) / 2, y), line, font=ft.font, fill=self.c["text"])
            y += ft.line_h
        y += 18
        fd = self.font("body", 32)
        ds = tr_date(day)
        draw.text(((self.W - fd.getlength(ds)) / 2, y), ds, font=fd, fill=self.c["text_muted"])
        date_bottom = y + 40

        fl = self.font("body", list_size)
        fn = self.font("label", list_size)
        y = list_top
        maxw = self.W - 2 * self.M - 70
        for n, it in enumerate(items, 1):
            acc = self.c[it["category"]]
            draw.text((self.M, y), f"{n:02d}", font=fn, fill=acc)
            t = it["slide_title"]
            while fl.getlength(t) > maxw and len(t) > 4:
                t = t[:-2].rstrip() + "…" if not t.endswith("…") else t[:-3].rstrip() + "…"
            draw.text((self.M + 70, y), t, font=fl, fill=self.c["text"])
            y += line_h
        self.last_cover = {"date_bottom": date_bottom, "list_top": list_top}
        fs = self.font("label", d["source"]["size"])
        hint = d["source"].get("swipe_hint", "")
        draw.text((self.W - self.M - fs.getlength(hint), self.H - self.M - 4), hint, font=fs,
                  fill=self.c["teknoloji"])
        draw.text((self.M, self.H - self.M - 4), f"1/{total}", font=fs, fill=self.c["text_muted"])
        return img.convert("RGB")

    # ---- kapanış
    def outro_slide(self, index: int, total: int) -> Image.Image:
        d, o = self.d, self.d["outro"]
        img = self.brand_backdrop()
        tmpl = self._template("outro")
        if tmpl:
            img.alpha_composite(tmpl)
        draw = ImageDraw.Draw(img)
        logo = self._logo(o["logo_size"])
        y = int(self.H * 0.17)
        img.alpha_composite(logo, ((self.W - logo.width) // 2, y))
        y += logo.height + 60

        ft = self.font("heading", 96)
        draw.text(((self.W - ft.getlength(o["title"])) / 2, y), o["title"], font=ft, fill=self.c["text"])
        y += 120
        fh = self.font("label", 46)
        h = d["brand"]["handle"]
        draw.text(((self.W - fh.getlength(h)) / 2, y), h, font=fh, fill=self.c["teknoloji"])
        y += 90
        fs = self.fit(o["subtitle"], "body", 36, 28, self.W - 2 * self.M - 80, 2, 1.3)
        for line in fs.lines:
            draw.text(((self.W - fs.font.getlength(line)) / 2, y), line, font=fs.font, fill=self.c["text_muted"])
            y += fs.line_h
        y += 50
        fc = self.font("label", 32)
        cw = fc.getlength(o["cta"])
        pad = 34
        draw.rounded_rectangle(((self.W - cw) / 2 - pad, y - 18, (self.W + cw) / 2 + pad, y + 50),
                               radius=34, outline=self.c["oyun"], width=3)
        draw.text(((self.W - cw) / 2, y - 4), o["cta"], font=fc, fill=self.c["text"])
        fn = self.font("label", d["source"]["size"])
        draw.text((self.M, self.H - self.M - 4), f"{index}/{total}", font=fn, fill=self.c["text_muted"])
        return img.convert("RGB")


def render_carousel(post: dict, backgrounds: dict, day: date, out_dir: Path,
                    design: dict) -> list[Path]:
    """7 slaytı out_dir/01.jpg … 07.jpg olarak kaydeder."""
    comp = Composer(design)
    items = post["items"]
    total = len(items) + 2
    q = design["canvas"]["jpeg_quality"]
    out_dir.mkdir(parents=True, exist_ok=True)
    slides = [comp.cover_slide(backgrounds.get("cover"), day, items, total)]
    for n, it in enumerate(items, 1):
        slides.append(comp.news_slide(backgrounds.get(n), it, n + 1, total))
    slides.append(comp.outro_slide(total, total))
    paths = []
    for i, s in enumerate(slides, 1):
        p = out_dir / f"{i:02d}.jpg"
        s.save(p, "JPEG", quality=q, optimize=True, progressive=True)
        paths.append(p)
    return paths
