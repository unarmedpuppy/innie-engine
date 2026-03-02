"""Tests for built-in skills."""

import pytest

from innie.core import paths
from innie.skills import builtins


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("INNIE_HOME", str(tmp_path / ".innie"))
    # Create data dirs
    for d in ["journal", "learnings/patterns", "learnings/debugging", "inbox"]:
        (paths.data_dir() / d).mkdir(parents=True, exist_ok=True)


def test_daily_creates_journal():
    result = builtins.daily(summary="Built the auth system")
    assert result.exists()
    content = result.read_text()
    assert "Built the auth system" in content


def test_daily_appends():
    builtins.daily(summary="Morning standup")
    result = builtins.daily(summary="Afternoon review")
    content = result.read_text()
    assert "Morning standup" in content
    assert "Afternoon review" in content


def test_learn_creates_file():
    result = builtins.learn(
        category="patterns",
        title="RRF Search",
        content="Reciprocal Rank Fusion combines keyword and vector results.",
    )
    assert result.exists()
    assert "patterns" in str(result)
    content = result.read_text()
    assert "RRF Search" in content


def test_inbox_appends():
    builtins.inbox(content="First thought")
    result = builtins.inbox(content="Second thought")
    content = result.read_text()
    assert "First thought" in content
    assert "Second thought" in content


def test_all_builtins_callable():
    for name in ["daily", "learn", "meeting", "contact", "inbox", "adr"]:
        assert callable(getattr(builtins, name))
