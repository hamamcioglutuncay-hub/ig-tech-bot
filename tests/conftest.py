import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


import pytest


@pytest.fixture(autouse=True)
def _no_select_retry_wait(monkeypatch):
    """Testlerde seçim yeniden denemesi beklemesin."""
    from bot import llm_gemini
    monkeypatch.setattr(llm_gemini, "SELECT_RETRY_WAIT_S", 0)
