"""Komut satırı: python -m bot <komut>"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.table import Table

from . import config
from .collector import collect
from .dedupe import SeenStore, dedupe

IST = ZoneInfo("Europe/Istanbul")
console = Console()


def cmd_collect(args: argparse.Namespace) -> int:
    feeds = config.load_feeds()
    if args.category:
        feeds = [f for f in feeds if f.category == args.category]
    with console.status(f"{len(feeds)} kaynak okunuyor…"):
        result = collect(feeds, hours=args.hours)
    seen = None if args.include_seen else SeenStore()
    items = dedupe(result.articles, seen)

    table = Table(title=f"Son {args.hours:g} saatin haberleri — {len(items)} tekil haber "
                        f"({len(result.articles)} ham)", show_lines=False)
    table.add_column("Saat (TR)", style="dim", no_wrap=True)
    table.add_column("Kategori", no_wrap=True)
    table.add_column("Kaynak", style="cyan", no_wrap=True)
    table.add_column("Başlık")
    for art in items[: args.limit]:
        when = art.published.astimezone(IST).strftime("%d.%m %H:%M")
        cat = "[magenta]oyun[/]" if art.category == "oyun" else "[green]teknoloji[/]"
        if art.topic == "ai":
            cat += " [yellow]YZ[/]"
        title = art.title + (f" [dim](+{', '.join(art.related)})[/]" if art.related else "")
        table.add_row(when, cat, art.source, title)
    console.print(table)
    if args.limit and len(items) > args.limit:
        console.print(f"[dim]… {len(items) - args.limit} haber daha (--limit 0 ile hepsi)[/]")

    by_cat = {c: sum(1 for a in items if a.category == c) for c in config.CATEGORIES}
    ai = sum(1 for a in items if a.topic == "ai")
    console.print(f"Teknoloji: {by_cat['teknoloji']} (YZ kaynaklı: {ai})  ·  Oyun: {by_cat['oyun']}")
    ok = [n for n in result.counts if n not in result.errors]
    console.print(f"[green]✅ {len(ok)} kaynak çalıştı[/]")
    for name, err in result.errors.items():
        console.print(f"[red]❌ {name}: {err}[/]")
    empty = [n for n in ok if result.counts[n] == 0]
    if empty:
        console.print(f"[yellow]⚠️  Son {args.hours:g} saatte haber yok: {', '.join(empty)}[/]")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from .check import run_all
    from .settings import ENV_FILE

    if not ENV_FILE.exists():
        console.print("[red]❌ .env dosyası yok.[/] Önce .env.example'dan oluşturup doldurun.")
        return 1
    icons = {True: "✅", False: "❌", None: "⏭️ "}
    results = run_all(send_test=not args.no_telegram_test)
    for r in results:
        console.print(f"{icons[r.ok]} [bold]{r.service}[/]: {r.message}", highlight=False)
    return 0 if all(r.ok is not False for r in results) else 1


def today_dir(now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    return config.OUTPUT_DIR / now.astimezone(IST).strftime("%Y-%m-%d")


def cmd_write(args: argparse.Namespace) -> int:
    from . import telegram
    from .llm_gemini import LLMError, QuotaError, generate_post, model_name

    if args.images_only:
        from .llm_gemini import refresh_image_prompts

        day_dir = today_dir()
        path = day_dir / "content.json"
        post = json.loads(path.read_text(encoding="utf-8"))
        with console.status("Gemini görsel tariflerini yeniden yazıyor…"):
            refresh_image_prompts(post)
        path.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        removed = 0
        for f in (day_dir / "bg").glob("bg_*.jpg"):
            f.unlink()
            removed += 1
        for n, it in enumerate(post["items"], 1):
            console.print(f"[cyan]{n}.[/] {it['slide_title']}\n   [dim]{it['image_prompt']}[/]")
        console.print(f"[dim]{removed} eski arka plan silindi; 'python -m bot render' yenilerini üretecek.[/]")
        return 0

    feeds = config.load_feeds()
    with console.status(f"{len(feeds)} kaynak okunuyor…"):
        result = collect(feeds, hours=args.hours)
    seen = SeenStore()
    items = dedupe(result.articles, seen)
    console.print(f"{len(items)} tekil haber · model: {model_name()}")
    try:
        with console.status("Gemini haberleri seçiyor ve yazıyor…"):
            post = generate_post(items)
    except QuotaError as exc:
        console.print(f"[yellow]⏭️  {exc} — bu tur atlandı.[/]")
        telegram.notify(f"⏭️ ig-tech-bot: Gemini ücretsiz kotası doldu, bugünkü tur atlandı.\n{exc}")
        return 2
    except LLMError as exc:
        console.print(f"[red]❌ {exc}[/]")
        telegram.notify(f"❌ ig-tech-bot: metin üretilemedi, tur atlandı.\n{exc}")
        return 1

    out = today_dir()
    out.mkdir(parents=True, exist_ok=True)
    path = out / "content.json"
    path.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.no_mark:
        for it in post["items"]:
            for s in it["all_sources"]:
                seen.add(s["url"])
        seen.prune()
        seen.save()

    print_post(post)
    console.print(f"\n[dim]Kaydedildi: {path.relative_to(config.ROOT)}"
                  f"{' · seen.json güncellenmedi (--no-mark)' if args.no_mark else ' · seen.json güncellendi'}[/]")
    return 0


def print_post(post: dict) -> None:
    from rich.panel import Panel

    total = len(post["items"]) + 2
    for n, it in enumerate(post["items"], 1):
        cat = "[magenta]OYUN[/]" if it["category"] == "oyun" else "[green]TEKNOLOJİ[/]"
        others = list(dict.fromkeys(s["name"] for s in it["all_sources"] if s["name"] != it["source_name"]))
        body = (
            f"[bold]{it['slide_title']}[/]  [dim]({len(it['slide_title'])}/60)[/]\n\n"
            f"{it['slide_text']}  [dim]({len(it['slide_text'])}/260)[/]\n\n"
            f"[cyan]Neden önemli?[/] {it.get('why_it_matters', '')}  [dim]({len(it.get('why_it_matters', ''))}/120)[/]\n\n"
            f"[cyan]Kaynak:[/] {it['source_name']}"
            + (f" [dim](+ {', '.join(others)})[/]" if others else "")
            + f"\n[dim]Önem: {it.get('importance', '-')}/10 · Görsel: {it['image_prompt']}[/]"
        )
        console.print(Panel(body, title=f"Slayt {n + 1}/{total} · {cat}", title_align="left", width=100))
    console.print(f"[dim]Model: {post['model']} · {post['candidates']} aday haber arasından "
                  f"{len(post['items'])} haber seçildi[/]")
    console.print(Panel(post["caption"], title=f"Caption ({len(post['caption'])}/2200)",
                        title_align="left", width=100))

def make_backgrounds(post: dict, day_dir: Path, design: dict) -> dict:
    """Kapak + her haber için FLUX arka planlarını üretir (önbellekli: dosya varsa yeniden üretmez)."""
    from PIL import Image

    from .imagegen import ImageGenError, ImageQuotaError, generate_image

    bg_dir = day_dir / "bg"
    jobs = [("cover", design["cover"]["prompt"])] + [
        (n, it["image_prompt"]) for n, it in enumerate(post["items"], 1)
    ]
    out: dict = {}
    for key, prompt in jobs:
        path = bg_dir / f"bg_{key}.jpg"
        try:
            with console.status(f"Arka plan üretiliyor: {key}…"):
                generate_image(prompt, path)
            out[key] = Image.open(path)
        except ImageQuotaError:
            raise
        except ImageGenError as exc:
            console.print(f"[yellow]⚠️  {key} arka planı üretilemedi, marka zemini kullanılacak: {exc}[/]")
            out[key] = None
    return out


def cmd_render(args: argparse.Namespace) -> int:
    import subprocess
    from datetime import date as _date

    from . import telegram
    from .composer import load_design, render_carousel
    from .imagegen import NEURONS_PER_IMAGE, ImageQuotaError, used_today

    day_dir = config.OUTPUT_DIR / args.date if args.date else today_dir()
    content = day_dir / "content.json"
    if not content.exists():
        console.print(f"[red]❌ {content.relative_to(config.ROOT)} yok. Önce: python -m bot write[/]")
        return 1
    post = json.loads(content.read_text(encoding="utf-8"))
    day = _date.fromisoformat(day_dir.name)

    variants = [Path(v) for v in args.design] if args.design else [None]
    base = load_design()
    try:
        backgrounds = make_backgrounds(post, day_dir, base)
    except ImageQuotaError as exc:
        console.print(f"[yellow]⏭️  {exc} — bu tur atlandı.[/]")
        telegram.notify(f"⏭️ ig-tech-bot: Cloudflare ücretsiz görsel kotası doldu, tur atlandı.\n{exc}")
        return 2
    console.print(f"[dim]Cloudflare kullanım tahmini bugün: {used_today():.0f}/10000 neuron "
                  f"(görsel başına ≈{NEURONS_PER_IMAGE:.0f})[/]")

    all_dirs = []
    for v in variants:
        design = load_design(v)
        name = design.get("variant_name") or "design.yaml"
        out = day_dir / "slides" if v is None else day_dir / "variants" / v.stem
        paths = render_carousel(post, backgrounds, day, out, design)
        all_dirs.append(out)
        console.print(f"✅ {name}: {len(paths)} slayt → {out.relative_to(config.ROOT)}")
        if not args.no_telegram:
            try:
                telegram.send_media_group(paths, caption=f"🎨 {name} — {day_dir.name}")
            except telegram.TelegramError as exc:
                console.print(f"[yellow]⚠️  Telegram önizleme gönderilemedi: {exc}[/]")
    if not args.no_telegram and variants == [None]:
        telegram.notify("📝 Caption önizleme:\n\n" + post["caption"])
    if not args.no_open:
        for d in all_dirs:
            subprocess.run(["open", str(d)], check=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m bot", description="ig-tech-bot komutları")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="Son 24 saatin tekil haberlerini tablo olarak göster")
    c.add_argument("--hours", type=float, default=24, help="zaman penceresi (saat), varsayılan 24")
    c.add_argument("--limit", type=int, default=60, help="gösterilecek en fazla satır (0 = hepsi)")
    c.add_argument("--category", choices=config.CATEGORIES, help="yalnızca bu kategori")
    c.add_argument("--include-seen", action="store_true", help="daha önce kullanılanları da göster")
    c.set_defaults(func=cmd_collect)

    k = sub.add_parser("check", help="Anahtarları servislere gerçek istekle doğrula (maskeli)")
    k.add_argument("--no-telegram-test", action="store_true", help="Telegram'a test mesajı gönderme")
    k.set_defaults(func=cmd_check)

    w = sub.add_parser("write", help="Günün haberlerini (3–8) seç ve Türkçe slayt metinlerini üret")
    w.add_argument("--hours", type=float, default=24, help="zaman penceresi (saat)")
    w.add_argument("--no-mark", action="store_true", help="seçilen haberleri seen.json'a yazma (deneme)")
    w.add_argument("--images-only", action="store_true", help="bugünkü içerikte yalnızca görsel tariflerini yenile")
    w.set_defaults(func=cmd_write)

    r = sub.add_parser("render", help="Arka planları üret ve 7 slaytlık carousel'i oluştur")
    r.add_argument("--date", help="output/ altındaki gün (YYYY-AA-GG), varsayılan bugün")
    r.add_argument("--design", nargs="*", help="designs/*.yaml varyasyon(lar)ı; verilmezse design.yaml")
    r.add_argument("--no-telegram", action="store_true", help="Telegram'a önizleme gönderme")
    r.add_argument("--no-open", action="store_true", help="Klasörü Finder'da açma")
    r.set_defaults(func=cmd_render)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "limit", None) == 0:
        args.limit = None
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
