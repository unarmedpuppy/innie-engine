"""Tests for TOML config loader."""

import pytest

from innie.core import config


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("INNIE_HOME", str(tmp_path))
    config.clear_cache()
    yield
    config.clear_cache()


def test_get_default():
    assert config.get("nonexistent.key", "fallback") == "fallback"


def test_get_nested_default():
    assert config.get("embedding.provider", "docker") == "docker"


def test_load_custom_config(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[user]\nname = "TestUser"\n')
    config.clear_cache()
    val = config.load_config(cfg)
    assert val["user"]["name"] == "TestUser"


def test_default_config_has_required_sections():
    defaults = config.DEFAULT_CONFIG
    assert "[user]" in defaults
    assert "[embedding]" in defaults
    assert "[heartbeat]" in defaults
    assert "[git]" in defaults
