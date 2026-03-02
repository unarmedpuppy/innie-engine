"""Tests for context assembly."""

import pytest

from innie.core import config, context, paths


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("INNIE_HOME", str(tmp_path / ".innie"))
    config.clear_cache()


def _scaffold(name="ctx-test"):
    d = paths.agent_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.yaml").write_text(f"name: {name}\nrole: Test\npermissions: interactive\n")
    (d / "SOUL.md").write_text("# Soul\nI remember everything.\n")
    (d / "CONTEXT.md").write_text("# Working Memory\n- Build the widget\n")
    paths.home().joinpath("user.md").write_text("# User\nName: Tester\n")
    return name


def test_build_session_context():
    name = _scaffold()
    ctx = context.build_session_context(agent_name=name, cwd="/tmp")
    assert "<agent-identity>" in ctx
    assert "remember everything" in ctx
    assert "<agent-context" in ctx
    assert "widget" in ctx


def test_build_precompact_warning():
    name = _scaffold()
    warn = context.build_precompact_warning(agent_name=name)
    assert "CONTEXT" in warn
