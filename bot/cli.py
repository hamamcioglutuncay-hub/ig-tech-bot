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


def _slides(day_dir: Path) -> list[Path]:
    return sorted((day_dir / "slides").glob("*.jpg"))


def cmd_test_url(args: argparse.Namespace) -> int:
    """Yayınlamadan Instagram'ın repo'daki görseli çekebildiğini doğrular."""
    from . import hosting, instagram

    day_dir = config.OUTPUT_DIR / args.date if args.date else today_dir()
    slides = _slides(day_dir)
    if not slides:
        console.print("[red]❌ Slayt yok. Önce: python -m bot render[/]")
        return 1
    if hosting.push_paths(slides, f"Slaytlar: {day_dir.name}"):
        console.print("[dim]Slaytlar GitHub'a gönderildi.[/]")
    url = hosting.raw_url(slides[0])
    ok, info = hosting.check_url(url)
    console.print(f"{'✅' if ok else '❌'} Herkese açık URL: {info} · {url}")
    if not ok:
        return 1
    try:
        with console.status("Instagram görseli çekmeyi deniyor (yayın YOK)…"):
            instagram.test_fetch(url)
    except instagram.InstagramError as exc:
        console.print(f"[red]❌ Instagram görseli çekemedi: {exc}[/]")
        return 1
    console.print("✅ Instagram görseli GitHub raw adresinden çekebildi (kap oluşturuldu, yayınlanmadı; 24 saatte silinir).")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    from . import hosting, instagram, settings, telegram

    if settings.mode() == "dry-run" and not args.ignore_mode:
        console.print("[yellow]⏭️  MODE=dry-run: yayın yapılmaz. (Elle denemek için --ignore-mode)[/]")
        return 1

    day_dir = config.OUTPUT_DIR / args.date if args.date else today_dir()
    content = day_dir / "content.json"
    slides = _slides(day_dir)
    if not content.exists() or not slides:
        console.print("[red]❌ İçerik ya da slayt yok. Önce: python -m bot write && python -m bot render[/]")
        return 1
    post = json.loads(content.read_text(encoding="utf-8"))
    pub_file = config.STATE_DIR / "published.json"
    published = json.loads(pub_file.read_text(encoding="utf-8")) if pub_file.exists() else {}
    if day_dir.name in published and not args.force:
        console.print(f"[yellow]⚠️  {day_dir.name} zaten yayınlandı: {published[day_dir.name].get('permalink')}[/]")
        return 1
    if len(slides) != len(post["items"]) + 2:
        console.print("[red]❌ Slayt sayısı içerikle uyuşmuyor; önce yeniden render edin.[/]")
        return 1

    if hosting.push_paths(slides, f"Slaytlar: {day_dir.name}"):
        console.print("[dim]Slaytlar GitHub'a gönderildi.[/]")
    urls = [hosting.raw_url(s) for s in slides]
    for u in urls:
        ok, info = hosting.check_url(u)
        if not ok:
            console.print(f"[red]❌ Görsel herkese açık değil ({info}): {u}[/]")
            return 1

    alts = [f"Kapak: Günün teknoloji ve oyun haberleri. "
            + " ".join(f"{n}. {it['slide_title']}." for n, it in enumerate(post["items"], 1))]
    alts += [it.get("alt_text", "") for it in post["items"]]
    alts += ["Kapanış: Takip et @singleplayer_tr — her gün güncel teknoloji ve oyun haberleri."]

    if not args.yes:
        console.print(f"{len(urls)} slayt, caption {len(post['caption'])} karakter. Yayınlansın mı? [e/H] ", end="")
        if input().strip().lower() not in ("e", "evet", "y", "yes"):
            console.print("İptal edildi.")
            return 1
    try:
        with console.status("Instagram'a yükleniyor…"):
            res = instagram.publish_carousel(urls, alts, post["caption"])
    except instagram.InstagramError as exc:
        console.print(f"[red]❌ Yayın başarısız: {exc}[/]")
        telegram.notify(f"❌ ig-tech-bot: Instagram yayını başarısız ({day_dir.name}).\n{exc}")
        return 1

    published[day_dir.name] = {"media_id": res.media_id, "permalink": res.permalink,
                               "slides": res.children, "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    pub_file.write_text(json.dumps(published, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    seen = SeenStore()
    for it in post["items"]:
        for s in it["all_sources"]:
            seen.add(s["url"])
    seen.prune()
    seen.save()
    console.print(f"✅ Yayınlandı: {res.permalink}")
    telegram.notify(f"✅ Instagram'da yayınlandı ({res.children} slayt):\n{res.permalink}")
    return 0


def cmd_refresh_token(args: argparse.Namespace) -> int:
    from . import settings, telegram, token_refresh

    try:
        if args.exchange:
            st = token_refresh.upgrade_if_short_lived()
            if st is None:
                console.print("[yellow]Token zaten uzun ömürlü görünüyor ya da IG_APP_SECRET boş; değişiklik yok.[/]")
                return 0
        else:
            st = token_refresh.refresh_and_store()
        if args.ci:
            token_refresh.push_secret("IG_ACCESS_TOKEN", settings.get("IG_ACCESS_TOKEN"))
    except token_refresh.TokenRefreshError as exc:
        console.print(f"[red]❌ Token yenilenemedi: {exc}[/]")
        telegram.notify(f"⚠️ ig-tech-bot: Instagram token yenilenemedi.\n{exc}")
        return 1
    where = "GitHub Secret'a" if args.ci else ".env'ye"
    console.print(f"✅ Token yenilendi ve {where} yazıldı (değer gösterilmez). Geçerlilik: {st['expires_at']}")
    return 0


MODE_NOTES = {
    "dry-run": "🧪 Mod: dry-run — bu içerik yayınlanmayacak (yalnızca önizleme).",
    "approve": "✅ Mod: approve — yayınlamak için GitHub uygulaması → ig-tech-bot → Actions → "
               "'Instagram'da yayınla' → Run workflow.",
    "auto": "⏰ Mod: auto — bugün 12:30'da (İstanbul) otomatik yayınlanacak.",
}


def cmd_run(args: argparse.Namespace) -> int:
    """Günlük akış: topla → yaz → görselle → slayt → Telegram önizleme. Kota dolarsa tur atlanır (çıkış 0)."""
    from . import settings, telegram

    day = today_dir()
    if (day / "content.json").exists() and not args.force:
        console.print(f"[dim]{day.name} içeriği zaten var; yazım adımı atlanıyor (--force ile yeniden üret).[/]")
    else:
        rc = cmd_write(argparse.Namespace(hours=24, no_mark=args.no_mark, images_only=False))
        if rc:
            return 0 if rc == 2 else rc
    rc = cmd_render(argparse.Namespace(date=None, design=None, no_telegram=args.no_telegram, no_open=True))
    if rc:
        return 0 if rc == 2 else rc
    if not args.no_telegram:
        telegram.notify(MODE_NOTES[settings.mode()])
    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    """output/ altında N günden eski gün klasörlerini siler."""
    import shutil
    from datetime import date as _date, timedelta

    cutoff = datetime.now(IST).date() - timedelta(days=args.days)
    removed = []
    for d in sorted(config.OUTPUT_DIR.iterdir()) if config.OUTPUT_DIR.exists() else []:
        try:
            day = _date.fromisoformat(d.name)
        except ValueError:
            continue
        if d.is_dir() and day < cutoff:
            shutil.rmtree(d)
            removed.append(d.name)
    console.print(f"🧹 {len(removed)} eski gün silindi" + (f": {', '.join(removed)}" if removed else ""))
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

    r = sub.add_parser("render", help="Arka planları üret ve carousel slaytlarını oluştur")
    r.add_argument("--date", help="output/ altındaki gün (YYYY-AA-GG), varsayılan bugün")
    r.add_argument("--design", nargs="*", help="designs/*.yaml varyasyon(lar)ı; verilmezse design.yaml")
    r.add_argument("--no-telegram", action="store_true", help="Telegram'a önizleme gönderme")
    r.add_argument("--no-open", action="store_true", help="Klasörü Finder'da açma")
    r.set_defaults(func=cmd_render)

    u = sub.add_parser("test-url", help="Instagram'ın slaytları GitHub'dan çekebildiğini YAYINLAMADAN doğrula")
    u.add_argument("--date", help="output/ altındaki gün (YYYY-AA-GG)")
    u.set_defaults(func=cmd_test_url)

    pb = sub.add_parser("publish", help="Günün carousel'ini Instagram'da yayınla")
    pb.add_argument("--date", help="output/ altındaki gün (YYYY-AA-GG)")
    pb.add_argument("--yes", action="store_true", help="onay sormadan yayınla")
    pb.add_argument("--force", action="store_true", help="o gün zaten yayınlandıysa yine de yayınla")
    pb.add_argument("--ignore-mode", action="store_true", help="MODE=dry-run olsa bile yayınla (elle test)")
    pb.set_defaults(func=cmd_publish)

    tk = sub.add_parser("refresh-token", help="Instagram token'ını yenile (60 gün) ve .env'ye yaz")
    tk.add_argument("--exchange", action="store_true", help="kısa ömürlü token'ı uzun ömürlüye çevir (IG_APP_SECRET gerekir)")
    tk.add_argument("--ci", action="store_true", help="GitHub Actions: yeni token'ı repo Secret'ına yaz (GH_PAT gerekir)")
    tk.set_defaults(func=cmd_refresh_token)

    rn = sub.add_parser("run", help="Günlük akış: topla, yaz, görselle, Telegram önizleme")
    rn.add_argument("--force", action="store_true", help="bugünün içeriği varsa bile yeniden yaz")
    rn.add_argument("--no-mark", action="store_true", help="seçilen haberleri seen.json'a yazma")
    rn.add_argument("--no-telegram", action="store_true", help="Telegram'a gönderme")
    rn.set_defaults(func=cmd_run)

    cl = sub.add_parser("cleanup", help="Eski çıktıları sil")
    cl.add_argument("--days", type=int, default=30, help="bu günden eski klasörler silinir (varsayılan 30)")
    cl.set_defaults(func=cmd_cleanup)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "limit", None) == 0:
        args.limit = None
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
