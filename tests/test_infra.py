"""Tests for notify.py, preflight.py, healthcheck.py (plan §13 'Infra')."""
from __future__ import annotations

from pipeline.config import load_config
from pipeline.healthcheck import run_healthcheck
from pipeline.notify import notify
from pipeline.preflight import check_preflight


def test_notify_no_webhook_returns_false():
    assert notify("hello", webhook_url=None) is False


def test_notify_never_raises_on_bad_url():
    # malformed URL must be swallowed, not raised
    assert notify("hello", webhook_url="http://nonexistent.invalid/hook") is False


def test_preflight_flags_missing_llm(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    problems = check_preflight(load_config(), need_llm=True, need_upload=False)
    assert any("GEMINI_API_KEY" in p for p in problems)


def test_preflight_flags_missing_upload(monkeypatch):
    for v in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    problems = check_preflight(load_config(), need_llm=False, need_upload=True)
    assert len(problems) == 3


def test_preflight_clean_when_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("YT_CLIENT_ID", "a")
    monkeypatch.setenv("YT_CLIENT_SECRET", "b")
    monkeypatch.setenv("YT_REFRESH_TOKEN", "c")
    assert check_preflight(load_config(), need_llm=True, need_upload=True) == []


def test_healthcheck_reports_pass_and_fail():
    rep = run_healthcheck(
        load_config(),
        llm_probe=lambda: True,
        token_probe=lambda: (_ for _ in ()).throw(RuntimeError("expired")),
    )
    assert rep.checks["llm"] is True
    assert rep.checks["youtube_token"] is False
    assert not rep.healthy
    assert "youtube_token" in rep.errors


def test_healthcheck_all_pass():
    rep = run_healthcheck(load_config(), llm_probe=lambda: True, token_probe=lambda: True)
    assert rep.healthy
