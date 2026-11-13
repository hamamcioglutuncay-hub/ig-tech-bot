"""Faz 5 testleri — günlük akış, MODE kapısı, temizlik, workflow dosyaları."""
import argparse
from pathlib import Path

import pytest
import yaml

from bot import cli, config, token_refresh as TR
from bot.config import ROOT

WF = ROOT / ".github" / "workflows"


def test_publish_refuses_in_dry_run(monkeypatch, capsys):
    from bot import telegram
    monkeypatch.setenv("MODE", "dry-run")
    sent = []
    monkeypatch.setattr(telegram, "notify", lambda m: sent.append(m) or True)
    rc = cli.cmd_publish(argparse.Namespace(date=None, yes=True, force=False, ignore_mode=False))
    assert rc == 0 and "dry-run" in capsys.readouterr().out and sent  # atlandı, yayın yok


def test_cleanup_removes_only_old_day_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    for name in ["2020-01-01", "2020-01-02", "notes", "2999-01-01"]:
        (tmp_path / name).mkdir()
    cli.cmd_cleanup(argparse.Namespace(days=30))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2999-01-01", "notes"]


def test_run_skips_write_when_content_exists_and_quota_skip_is_success(tmp_path, monkeypatch):
    day = tmp_path / "2026-11-13"
    day.mkdir()
    (day / "content.json").write_text("{}")
    monkeypatch.setattr(cli, "today_dir", lambda: day)
    called = {"write": 0}
    monkeypatch.setattr(cli, "cmd_write", lambda a: called.__setitem__("write", 1) or 0)
    monkeypatch.setattr(cli, "cmd_render", lambda a: 2)  # görsel kotası doldu → tur atlandı
    rc = cli.cmd_run(argparse.Namespace(force=False, no_mark=False, no_telegram=True))
    assert rc == 0 and called["write"] == 0


def test_push_secret_requires_pat(monkeypatch, capsys):
    monkeypatch.delenv("GH_PAT", raising=False)
    with pytest.raises(TR.TokenRefreshError, match="GH_PAT"):
        TR.push_secret("IG_ACCESS_TOKEN", "secretvalue123")
    assert "::add-mask::secretvalue123" in capsys.readouterr().out  # önce maskelenir


@pytest.mark.parametrize("name", ["generate.yml", "publish.yml", "refresh-token.yml", "cleanup.yml"])
def test_workflows_valid_and_safe(name):
    text = (WF / name).read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    assert "workflow_dispatch" in wf[True] and "schedule" in wf[True]
    assert wf["concurrency"]["group"] == "ig-tech-bot"
    # gizli değerler yalnızca secrets.* üzerinden gelir, düz metin yok
    for line in text.splitlines():
        if any(k in line for k in ("TOKEN:", "API_KEY:", "SECRET:")):
            assert "${{ secrets." in line


def test_schedules_match_istanbul_times():
    gen = yaml.safe_load((WF / "generate.yml").read_text())[True]["schedule"][0]["cron"]
    pub = yaml.safe_load((WF / "publish.yml").read_text())[True]["schedule"][0]["cron"]
    assert gen == "30 5 * * *" and pub == "30 9 * * *"   # 08:30 ve 12:30 İstanbul (UTC+3)
    pub_job = yaml.safe_load((WF / "publish.yml").read_text())["jobs"]["publish"]
    assert "vars.MODE == 'auto'" in pub_job["if"]
