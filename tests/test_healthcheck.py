"""Tests for healthcheck.py liveness probe behavior."""
from __future__ import annotations

from pipeline.config import Config
from pipeline.healthcheck import run_healthcheck


def _cfg() -> Config:
    return Config()


def test_healthcheck_all_checks_pass():
    r = run_healthcheck(_cfg(), llm_probe=lambda: True, token_probe=lambda: True)
    assert r.checks == {"llm": True, "youtube_token": True}
    assert r.healthy is True


def test_healthcheck_probe_exceptions_recorded():
    def boom():
        raise RuntimeError("bad")

    r = run_healthcheck(_cfg(), llm_probe=boom, token_probe=lambda: False)
    assert r.checks["llm"] is False
    assert r.checks["youtube_token"] is False
    assert "llm" in r.errors
    assert r.healthy is False


def test_healthcheck_with_only_llm_probe():
    r = run_healthcheck(_cfg(), llm_probe=lambda: True, token_probe=None)
    assert r.checks == {"llm": True}
    assert r.healthy is True


def test_healthcheck_with_no_probes_is_unhealthy_but_safe():
    r = run_healthcheck(_cfg(), llm_probe=None, token_probe=None)
    assert r.checks == {}
    assert r.errors == {}
    assert r.healthy is False
