"""Tests for fetch_news.py — safe grounding with a monkeypatched parser."""
from __future__ import annotations

import sys
import types

import pipeline.fetch_news as fn


class _Entry:
    def __init__(self, title):
        self.title = title


class _Parsed:
    def __init__(self, titles):
        self.entries = [_Entry(t) for t in titles]


def test_returns_list_and_is_safe():
    assert isinstance(fn.fetch_headlines(feeds=(), limit=3), list)


def test_dedupes_and_limits(monkeypatch):
    # Two feeds return overlapping titles; cross-feed dedup keeps first-seen order.
    fake = types.SimpleNamespace(parse=lambda url: _Parsed(["A", "B", "C"]))
    monkeypatch.setitem(sys.modules, "feedparser", fake)
    out = fn.fetch_headlines(feeds=("http://x", "http://y"), limit=3)
    assert out == ["A", "B", "C"]


def test_feed_error_is_skipped(monkeypatch):
    def boom(url):
        raise RuntimeError("bad feed")

    fake = types.SimpleNamespace(parse=boom)
    monkeypatch.setitem(sys.modules, "feedparser", fake)
    assert fn.fetch_headlines(feeds=("http://x",), limit=3) == []


def test_missing_feedparser_returns_empty(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "feedparser":
            raise ImportError("not installed")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert fn.fetch_headlines(feeds=("http://x",)) == []


def test_empty_titles_are_filtered_out(monkeypatch):
    fake = types.SimpleNamespace(parse=lambda _url: _Parsed(["", "  ", "Valid"]))
    monkeypatch.setitem(sys.modules, "feedparser", fake)
    assert fn.fetch_headlines(feeds=("http://x",), limit=5) == ["Valid"]
