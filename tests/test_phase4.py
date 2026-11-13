"""Faz 4 testleri — Instagram API sahte oturumla; gerçek ağ ve token yok."""
import json

import pytest

from bot import instagram as IG
from bot import settings, token_refresh as TR

TOKEN = "IGAAFAKE" + "x" * 40 + "TK99"


class Resp:
    def __init__(self, status, body, ctype="application/json"):
        self.status_code = status
        self._b = body
        self.headers = {"content-type": ctype}
        self.text = json.dumps(body)

    def json(self):
        return self._b


class FakeIG:
    """Instagram Graph API'yi taklit eder ve çağrıları kaydeder."""

    def __init__(self, statuses=None, fail_alt=False, quota=(0, 100)):
        self.calls = []
        self.n = 0
        self.statuses = statuses or {}
        self.fail_alt = fail_alt
        self.quota = quota

    def _ok(self, body):
        return Resp(200, body)

    def get(self, url, params, timeout):
        self.calls.append(("GET", url, dict(params)))
        if url.endswith("/me"):
            return self._ok({"user_id": "17840000000000001", "username": "singleplayer_tr", "account_type": "BUSINESS"})
        if url.endswith("content_publishing_limit"):
            return self._ok({"data": [{"quota_usage": self.quota[0], "config": {"quota_total": self.quota[1]}}]})
        if params.get("fields") == "status_code,status":
            cid = url.rsplit("/", 1)[1]
            seq = self.statuses.setdefault(cid, ["IN_PROGRESS", "FINISHED"])
            return self._ok({"status_code": seq.pop(0) if len(seq) > 1 else seq[0]})
        if params.get("fields") == "permalink":
            return self._ok({"permalink": "https://www.instagram.com/p/TEST123/"})
        return Resp(404, {"error": {"message": "?", "code": 100}})

    def post(self, url, data, timeout):
        self.calls.append(("POST", url, dict(data)))
        if url.endswith("/media"):
            if self.fail_alt and "alt_text" in data:
                return Resp(400, {"error": {"message": "(#100) Param alt_text is not supported", "code": 100}})
            self.n += 1
            return self._ok({"id": f"c{self.n}"})
        if url.endswith("/media_publish"):
            return self._ok({"id": "M999"})
        return Resp(404, {"error": {"message": "?", "code": 100}})


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("IG_USER_ID", "singleplayer_tr")  # sayısal değil → /me'den bulunmalı


URLS = [f"https://raw.githubusercontent.com/x/y/main/output/d/slides/{i:02d}.jpg" for i in range(1, 6)]


def test_publish_carousel_flow():
    s = FakeIG()
    res = IG.publish_carousel(URLS, ["alt"] * 5, "Caption", session=s, sleep=lambda _: None)
    assert res.media_id == "M999" and res.permalink.endswith("/TEST123/") and res.children == 5
    posts = [c for c in s.calls if c[0] == "POST"]
    children = [c for c in posts if c[2].get("is_carousel_item") == "true"]
    assert len(children) == 5 and all(c[2]["alt_text"] == "alt" for c in children)
    assert all("17840000000000001/media" in c[1] for c in children)       # kullanıcı adı değil sayısal kimlik
    parent = next(c for c in posts if c[2].get("media_type") == "CAROUSEL")
    assert parent[2]["children"] == "c1,c2,c3,c4,c5" and parent[2]["caption"] == "Caption"
    assert posts[-1][1].endswith("/media_publish") and posts[-1][2]["creation_id"] == "c6"


def test_container_error_stops_before_publish():
    s = FakeIG(statuses={"c2": ["ERROR"]})
    with pytest.raises(IG.InstagramError, match="ERROR"):
        IG.publish_carousel(URLS, [], "C", session=s, sleep=lambda _: None)
    assert not any(c[1].endswith("/media_publish") for c in s.calls)


def test_alt_text_fallback_when_unsupported():
    s = FakeIG(fail_alt=True)
    IG.publish_carousel(URLS[:2], ["a", "b"], "C", session=s, sleep=lambda _: None)
    ok_children = [c for c in s.calls if c[0] == "POST" and c[2].get("is_carousel_item") and "alt_text" not in c[2]]
    assert len(ok_children) == 2


def test_quota_full_blocks_publish():
    with pytest.raises(IG.RateLimitError):
        IG.publish_carousel(URLS, [], "C", session=FakeIG(quota=(100, 100)), sleep=lambda _: None)


def test_limits_validated():
    with pytest.raises(IG.InstagramError):
        IG.publish_carousel(URLS * 3, [], "C", session=FakeIG(), sleep=lambda _: None)
    with pytest.raises(IG.InstagramError, match="2.200"):
        IG.publish_carousel(URLS, [], "x" * 2201, session=FakeIG(), sleep=lambda _: None)


def test_wait_timeout():
    s = FakeIG(statuses={"c1": ["IN_PROGRESS"]})
    with pytest.raises(IG.InstagramError, match="hazır olmadı"):
        IG.wait_ready(["c1"], session=s, sleep=lambda _: None, max_s=6)


def test_errors_never_contain_token():
    class Bad(FakeIG):
        def get(self, url, params, timeout):
            return Resp(400, {"error": {"message": f"Invalid token {params['access_token']}", "code": 190}})

    with pytest.raises(IG.TokenError) as ei:
        IG.me(session=Bad())
    assert TOKEN not in str(ei.value) and "TK99" in str(ei.value)


# --------------------------------------------------------------------------- token

def test_refresh_writes_env_and_state(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=abc\nIG_ACCESS_TOKEN=old\nMODE=dry-run\n", encoding="utf-8")
    monkeypatch.setattr(TR, "TOKEN_STATE", tmp_path / "token.json")
    new = "IGAANEW" + "y" * 40

    def fake_get(url, params, timeout):
        assert params["grant_type"] == "ig_refresh_token"
        return Resp(200, {"access_token": new, "token_type": "bearer", "expires_in": 5184000})

    monkeypatch.setattr(TR.requests, "get", fake_get)
    st = TR.refresh_and_store(env_file)
    text = env_file.read_text(encoding="utf-8")
    assert f"IG_ACCESS_TOKEN={new}" in text and "GEMINI_API_KEY=abc" in text and "MODE=dry-run" in text
    state = json.loads((tmp_path / "token.json").read_text())
    assert new not in json.dumps(state) and state["expires_at"] == st["expires_at"]
    assert 59 < TR.days_left(path=tmp_path / "token.json") <= 60


def test_refresh_error_is_masked(monkeypatch):
    monkeypatch.setattr(TR.requests, "get", lambda url, params, timeout: Resp(
        400, {"error": {"message": f"bad {params['access_token']}"}}))
    with pytest.raises(TR.TokenRefreshError) as ei:
        TR.refresh_long_lived(TOKEN)
    assert TOKEN not in str(ei.value)


def test_hosting_raw_url():
    from bot import hosting
    from bot.config import ROOT
    url = hosting.raw_url(ROOT / "output" / "2026-11-13" / "slides" / "01.jpg")
    assert url == "https://raw.githubusercontent.com/hamamcioglutuncay-hub/ig-tech-bot/main/output/2026-11-13/slides/01.jpg"
