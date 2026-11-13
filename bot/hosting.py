"""Slaytların herkese açık URL'leri: public GitHub reposunun raw adresi.

Instagram görseli bu URL'den kendisi çeker; bu yüzden dosyalar önce push edilmiş olmalı.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import quote

import requests

from .config import ROOT

RAW = "https://raw.githubusercontent.com/{slug}/{branch}/{path}"


def repo_slug() -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.strip()
    slug = url.split("github.com")[-1].lstrip(":/").removesuffix(".git")
    return slug


def branch() -> str:
    return os.environ.get("GITHUB_REF_NAME") or "main"


def raw_url(path: Path) -> str:
    rel = Path(path).resolve().relative_to(ROOT).as_posix()
    return RAW.format(slug=repo_slug(), branch=branch(), path=quote(rel))


def check_url(url: str) -> tuple[bool, str]:
    """URL herkese açık ve JPEG mi?"""
    try:
        r = requests.head(url, timeout=20, allow_redirects=True)
    except requests.RequestException as exc:
        return False, type(exc).__name__
    ctype = r.headers.get("content-type", "")
    return (r.status_code == 200 and ctype.startswith("image/")), f"{r.status_code} {ctype}"


def push_paths(paths: list[Path], message: str) -> bool:
    """Verilen dosyaları commit edip push eder. Değişiklik yoksa False."""
    rels = [Path(p).resolve().relative_to(ROOT).as_posix() for p in paths]
    subprocess.run(["git", "add", "--", *rels], cwd=ROOT, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet", "--", *rels], cwd=ROOT)
    if diff.returncode == 0:
        return False
    subprocess.run(["git", "commit", "-q", "-m", message, "--", *rels], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "-q"], cwd=ROOT, check=True)
    return True
