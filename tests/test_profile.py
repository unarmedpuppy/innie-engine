"""Tests for agent profile loading and saving."""

import pytest

from innie.core import paths, profile


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("INNIE_HOME", str(tmp_path / ".innie"))


def _scaffold_agent(name="test"):
    """Create minimal agent scaffold."""
    d = paths.agent_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.yaml").write_text(f"name: {name}\nrole: Test Bot\npermissions: interactive\n")
    (d / "SOUL.md").write_text("# Soul\nI am a test bot.\n")
    (d / "CONTEXT.md").write_text("# Context\nNothing yet.\n")
    return d


def test_load_profile():
    _scaffold_agent("bot1")
    p = profile.load_profile("bot1")
    assert p.name == "bot1"
    assert p.role == "Test Bot"
    assert "test bot" in p.soul.lower()


def test_save_profile():
    _scaffold_agent("bot2")
    p = profile.load_profile("bot2")
    p.role = "Updated Role"
    profile.save_profile(p)

    p2 = profile.load_profile("bot2")
    assert p2.role == "Updated Role"


def test_list_agents():
    _scaffold_agent("alpha")
    _scaffold_agent("beta")
    agents = profile.list_agents()
    assert "alpha" in agents
    assert "beta" in agents
