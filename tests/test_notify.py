"""Tests for notify.py best-effort webhook behavior."""
from __future__ import annotations

import json

import pipeline.notify as n


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_notify_without_webhook_returns_false():
    assert n.notify("msg", webhook_url=None) is False


def test_notify_success_http_2xx(monkeypatch):
    def fake_urlopen(req, timeout):
        assert timeout == 10
        body = json.loads(req.data.decode("utf-8"))
        assert "msg" in body["text"]
        return _Resp(204)

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert n.notify("msg", webhook_url="https://example", level="warning") is True


def test_notify_non_2xx_returns_false(monkeypatch):
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _Resp(500))
    assert n.notify("msg", webhook_url="https://example") is False


def test_notify_swallow_exception_returns_false(monkeypatch):
    import urllib.request

    def boom(*_a, **_k):
        raise RuntimeError("down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert n.notify("msg", webhook_url="https://example") is False
