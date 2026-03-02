"""Tests for core path resolution."""

from pathlib import Path

import pytest

from innie.core import paths


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("INNIE_HOME", str(tmp_path / ".innie"))
    monkeypatch.delenv("INNIE_AGENT", raising=False)


def test_home_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("INNIE_HOME", str(tmp_path / "custom"))
    assert paths.home() == tmp_path / "custom"


def test_home_default(monkeypatch):
    monkeypatch.delenv("INNIE_HOME", raising=False)
    assert paths.home() == Path.home() / ".innie"


def test_agent_dir():
    d = paths.agent_dir("mybot")
    assert d.name == "mybot"
    assert "agents" in str(d)


def test_data_dir():
    d = paths.data_dir("mybot")
    assert d.name == "data"
    assert "mybot" in str(d)


def test_sessions_dir():
    d = paths.sessions_dir("mybot")
    assert d.name == "sessions"


def test_soul_file():
    f = paths.soul_file("mybot")
    assert f.name == "SOUL.md"


def test_context_file():
    f = paths.context_file("mybot")
    assert f.name == "CONTEXT.md"


def test_config_file():
    f = paths.config_file()
    assert f.name == "config.toml"


def test_index_db():
    f = paths.index_db("mybot")
    assert f.suffix == ".db"
