"""Komut satırı: python -m bot <komut>"""
from __future__ import annotations

import argparse
import sys

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
        title = art.title + (f" [dim](+{', '.join(art.related)})[/]" if art.related else "")
        table.add_row(when, cat, art.source, title)
    console.print(table)
    if args.limit and len(items) > args.limit:
        console.print(f"[dim]… {len(items) - args.limit} haber daha (--limit 0 ile hepsi)[/]")

    by_cat = {c: sum(1 for a in items if a.category == c) for c in config.CATEGORIES}
    console.print(f"Teknoloji: {by_cat['teknoloji']}  ·  Oyun: {by_cat['oyun']}")
    ok = [n for n in result.counts if n not in result.errors]
    console.print(f"[green]✅ {len(ok)} kaynak çalıştı[/]")
    for name, err in result.errors.items():
        console.print(f"[red]❌ {name}: {err}[/]")
    empty = [n for n in ok if result.counts[n] == 0]
    if empty:
        console.print(f"[yellow]⚠️  Son {args.hours:g} saatte haber yok: {', '.join(empty)}[/]")
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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "limit", None) == 0:
        args.limit = None
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
