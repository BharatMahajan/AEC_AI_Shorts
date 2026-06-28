"""Tests for config.py — env override behavior (plan §12 config-driven bounds)."""
from __future__ import annotations

from pipeline.config import load_config


def test_defaults_present():
    cfg = load_config()
    assert cfg.script.max_attempts == 3
    assert cfg.script.pass_threshold == 80.0
    assert cfg.voice.max_attempts == 2
    assert cfg.render.max_attempts == 2
    assert cfg.publish.max_retries == 5


def test_env_overrides_int(monkeypatch):
    monkeypatch.setenv("SCRIPT_MAX_ATTEMPTS", "7")
    assert load_config().script.max_attempts == 7


def test_env_override_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("SCRIPT_MAX_ATTEMPTS", "not-a-number")
    assert load_config().script.max_attempts == 3


def test_env_bool_parsing(monkeypatch):
    monkeypatch.setenv("ENABLE_ANALYTICS", "yes")
    assert load_config().analytics.enabled is True
    monkeypatch.setenv("ENABLE_ANALYTICS", "0")
    assert load_config().analytics.enabled is False


def test_env_override_invalid_float_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("SCRIPT_PASS_THRESHOLD", "not-a-float")
    assert load_config().script.pass_threshold == 80.0
