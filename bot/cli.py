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

    for n, it in enumerate(post["items"], 1):
        cat = "[magenta]OYUN[/]" if it["category"] == "oyun" else "[green]TEKNOLOJİ[/]"
        others = list(dict.fromkeys(s["name"] for s in it["all_sources"] if s["name"] != it["source_name"]))
        body = (
            f"[bold]{it['slide_title']}[/]  [dim]({len(it['slide_title'])}/60)[/]\n\n"
            f"{it['slide_text']}  [dim]({len(it['slide_text'])}/180)[/]\n\n"
            f"[cyan]Kaynak:[/] {it['source_name']}"
            + (f" [dim](+ {', '.join(others)})[/]" if others else "")
            + f"\n[dim]Görsel: {it['image_prompt']}[/]"
        )
        console.print(Panel(body, title=f"Slayt {n + 1}/7 · {cat}", title_align="left", width=100))
    console.print(f"[dim]Model: {post['model']} · {post['candidates']} aday haber arasından seçildi[/]")
    console.print(Panel(post["caption"], title=f"Caption ({len(post['caption'])}/1500)",
                        title_align="left", width=100))


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

    w = sub.add_parser("write", help="Günün 5 haberini seç ve Türkçe slayt metinlerini üret")
    w.add_argument("--hours", type=float, default=24, help="zaman penceresi (saat)")
    w.add_argument("--no-mark", action="store_true", help="seçilen haberleri seen.json'a yazma (deneme)")
    w.set_defaults(func=cmd_write)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "limit", None) == 0:
        args.limit = None
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
