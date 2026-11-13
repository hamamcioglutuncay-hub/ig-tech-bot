"""Faz 1 testleri — ağ kullanmaz, sahte RSS verisiyle çalışır."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from bot.collector import collect, clean_text
from bot.config import Feed, load_feeds
from bot.dedupe import SeenStore, dedupe, normalize_url, similar_titles

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def rss(items):
    body = "".join(
        f"<item><title>{t}</title><link>{l}</link>"
        f"<pubDate>{format_datetime(NOW - timedelta(hours=h))}</pubDate>"
        f"<description>&lt;p&gt;Özet &amp; detay&lt;/p&gt;</description></item>"
        for t, l, h in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'.encode()


TECH = Feed("TechA", "https://a.test/rss", "teknoloji", "en")
GAME = Feed("GameB", "https://b.test/rss", "oyun", "tr")
BROKEN = Feed("Broken", "https://broken.test/rss", "oyun", "en")

FAKE = {
    TECH.url: rss([
        ("Apple unveils new M6 MacBook Pro lineup", "https://a.test/m6?utm_source=rss", 2),
        ("Old news from last week", "https://a.test/old", 30),
    ]),
    GAME.url: rss([
        ("GTA 6 çıkış tarihi resmen açıklandı", "https://b.test/gta6", 5),
        ("Apple unveils new M6 MacBook Pro line-up", "https://b.test/apple-m6", 1),
    ]),
}


def fake_fetch(url):
    if url not in FAKE:
        raise ConnectionError("bağlantı yok")
    return FAKE[url]


def test_24h_window_and_cleaning():
    res = collect([TECH, GAME], hours=24, now=NOW, fetcher=fake_fetch)
    titles = [a.title for a in res.articles]
    assert "Old news from last week" not in titles
    assert len(res.articles) == 3
    assert res.articles[0].published >= res.articles[-1].published  # yeniden eskiye
    assert res.articles[0].summary == "Özet & detay"


def test_broken_feed_does_not_stop_others():
    res = collect([TECH, BROKEN, GAME], hours=24, now=NOW, fetcher=fake_fetch)
    assert "Broken" in res.errors
    assert res.counts["TechA"] == 1 and res.counts["GameB"] == 2


def test_dedupe_merges_similar_titles_across_sources():
    res = collect([TECH, GAME], hours=24, now=NOW, fetcher=fake_fetch)
    items = dedupe(res.articles)
    assert len(items) == 2
    apple = next(a for a in items if "M6" in a.title)
    assert apple.source == "TechA"          # önce yayınlanan temsilci olur
    assert apple.related == ["GameB"]


def test_dedupe_same_url_different_tracking():
    res = collect([TECH], hours=24, now=NOW, fetcher=fake_fetch)
    doubled = res.articles + collect([TECH], hours=24, now=NOW, fetcher=fake_fetch).articles
    assert len(dedupe(doubled)) == 1


def test_seen_store_roundtrip_and_filter(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore(path)
    store.add("https://www.a.test/m6/?utm_campaign=x", when=NOW)
    store.add("https://a.test/very-old", when=NOW - timedelta(days=40))
    store.prune(now=NOW)
    store.save()

    reloaded = SeenStore(path)
    assert "https://a.test/m6" in reloaded
    assert "https://a.test/very-old" not in reloaded
    res = collect([TECH, GAME], hours=24, now=NOW, fetcher=fake_fetch)
    items = dedupe(res.articles, reloaded)
    assert all("a.test/m6" not in a.url for a in items)


def test_corrupt_seen_file_is_tolerated(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("{bozuk", encoding="utf-8")
    assert SeenStore(path).data == {}


@pytest.mark.parametrize("a,b,expected", [
    ("Nintendo Switch 2 fiyatı belli oldu", "Nintendo Switch 2'nin fiyatı belli oldu", True),
    ("İPHONE 18 TANITILDI", "iphone 18 tanıtıldı", True),
    ("GTA 6 delayed again", "Microsoft announces new Xbox handheld", False),
])
def test_similar_titles(a, b, expected):
    assert similar_titles(a, b) is expected


def test_normalize_url():
    assert normalize_url("http://www.X.test/a/?utm_source=1&id=5#c") == "https://x.test/a?id=5"


def test_clean_text_limit():
    assert len(clean_text("a" * 1000, 50)) == 50


def test_feeds_yaml_is_valid_and_balanced():
    feeds = load_feeds()
    tech = [f for f in feeds if f.category == "teknoloji"]
    game = [f for f in feeds if f.category == "oyun"]
    assert len(tech) >= 6 and len(game) >= 6
    assert any(f.lang == "tr" for f in game) and any(f.lang == "tr" for f in tech)
    assert len({f.url for f in feeds}) == len(feeds)


def test_naive_dates_use_feed_timezone():
    xml = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>'
           b'<item><title>Yerel saatli haber</title><link>https://c.test/1</link>'
           b'<pubDate>2026-11-13 13:55:00</pubDate></item></channel></rss>')
    feed = Feed("TzFeed", "https://c.test/rss", "oyun", "tr", tz="Europe/Istanbul")
    res = collect([feed], hours=24, now=NOW, fetcher=lambda u: xml)
    assert res.articles[0].published == datetime(2026, 11, 13, 10, 55, tzinfo=timezone.utc)


def test_http_fetch_retries_once(monkeypatch):
    import requests
    from bot import collector

    calls = {"n": 0}

    class Resp:
        content = b"ok"
        def raise_for_status(self):
            pass

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.ConnectionError("reset")
        return Resp()

    monkeypatch.setattr(collector.requests, "get", flaky)
    monkeypatch.setattr(collector.time, "sleep", lambda s: None)
    assert collector.http_fetch("https://x.test") == b"ok"
    assert calls["n"] == 2


def test_same_url_in_two_feeds_prefers_game_category():
    xml = rss([("Yeni oyun duyuruldu", "https://sd.test/x", 1)])
    main = Feed("SD", "https://sd.test/feed", "teknoloji", "tr")
    game = Feed("SD Oyun", "https://sd.test/oyun/feed", "oyun", "tr", topic=None)
    res = collect([main, game], hours=24, now=NOW, fetcher=lambda u: xml)
    items = dedupe(res.articles)
    assert len(items) == 1 and items[0].category == "oyun"
