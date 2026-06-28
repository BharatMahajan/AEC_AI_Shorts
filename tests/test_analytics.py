"""Tests for analytics.py — L0 weights/perf_hint + safe no-op + bias (plan §13)."""
from __future__ import annotations

import random
import sys
from types import ModuleType

import pytest

from pipeline.analytics import LearningResult, YouTubeStatsClient, _avg_by, _normalize, compute_learning
from pipeline.config import AnalyticsConfig
from pipeline.history import History, HistoryEntry
from pipeline.topic_select import select_topic


def _hist(tmp_path, rows):
    h = History(tmp_path / "hist.json")
    for i, (bucket, hook, vid) in enumerate(rows):
        h.append(
            HistoryEntry(
                date="2026-06-28", bucket=bucket, feature_fingerprint=f"{bucket}:{i}",
                title=f"title-{i}", hook_style=hook, video_id=vid,
            )
        )
    return h


class FakeStats:
    def __init__(self, mapping):
        self.mapping = mapping

    def fetch_stats(self, video_ids):
        return {v: self.mapping[v] for v in video_ids if v in self.mapping}


def _cfg(**kw):
    base = dict(enabled=True, min_uploads=2, lookback=30, weight_floor=0.25)
    base.update(kw)
    return AnalyticsConfig(**base)


def test_disabled_returns_empty(tmp_path):
    h = _hist(tmp_path, [("cad", "question", "v1"), ("mep", "bold_claim", "v2")])
    res = compute_learning(h, cfg=_cfg(enabled=False), stats_client=FakeStats({}))
    assert res.weights_bucket == {}
    assert res.perf_hint == ""


def test_no_client_returns_empty(tmp_path):
    h = _hist(tmp_path, [("cad", "question", "v1")])
    assert compute_learning(h, cfg=_cfg(), stats_client=None).weights_bucket == {}


def test_too_few_uploads_returns_empty(tmp_path):
    h = _hist(tmp_path, [("cad", "question", "v1")])
    res = compute_learning(h, cfg=_cfg(min_uploads=5), stats_client=FakeStats({"v1": {"views": 10}}))
    assert res.weights_bucket == {}


def test_weights_reflect_performance(tmp_path):
    h = _hist(tmp_path, [
        ("water_environmental", "question", "v1"),
        ("water_environmental", "question", "v2"),
        ("cad", "bold_claim", "v3"),
    ])
    stats = FakeStats({
        "v1": {"views": 1000, "likes": 50},
        "v2": {"views": 1200, "likes": 60},
        "v3": {"views": 10, "likes": 0},
    })
    res = compute_learning(h, cfg=_cfg(), stats_client=stats)
    # water bucket vastly outperforms cad -> higher weight
    assert res.weights_bucket["water_environmental"] > res.weights_bucket["cad"]
    assert res.weights_bucket["cad"] >= 0.25  # floored
    assert "title" in res.perf_hint or res.perf_hint  # hint populated


def test_failure_is_safe(tmp_path):
    class Boom:
        def fetch_stats(self, ids):
            raise RuntimeError("api down")

    h = _hist(tmp_path, [("cad", "question", "v1"), ("mep", "x", "v2")])
    assert compute_learning(h, cfg=_cfg(), stats_client=Boom()).weights_bucket == {}


def test_no_stats_returns_empty(tmp_path):
    h = _hist(tmp_path, [("cad", "question", "v1"), ("mep", "x", "v2")])
    res = compute_learning(h, cfg=_cfg(), stats_client=FakeStats({}))
    assert res == LearningResult.empty()


def test_normalize_non_positive_overall_returns_neutral_weights():
    out = _normalize({"a": 0.0, "b": 0.0}, floor=0.25)
    assert out == {"a": 1.0, "b": 1.0}


def test_normalize_empty_returns_empty():
    assert _normalize({}, floor=0.25) == {}


def test_avg_by_skips_entries_missing_scores(tmp_path):
    h = _hist(tmp_path, [("cad", "question", "v1"), ("mep", "bold_claim", "v2")])
    out = _avg_by(h.load(), {"v1": 10.0}, "bucket")
    assert out == {"cad": 10.0}


def test_weights_bias_topic_selection(tmp_path):
    # An L0 weight on a bucket should bias select_topic toward it.
    h = History(tmp_path / "empty.json")
    weights = {"transport": 1000.0}
    rng = random.Random(11)
    picks = [select_topic(h, weights=weights, weight_floor=0.01, rng=rng).bucket for _ in range(40)]
    assert sum(1 for b in picks if b == "transport") > 30


def test_youtube_stats_client_requires_api_key():
    with pytest.raises(ValueError, match="YT_DATA_API_KEY"):
        YouTubeStatsClient("")


def test_youtube_stats_client_constructor_builds_client(monkeypatch):
    built = {}

    def fake_build(service, version, developerKey):
        built["service"] = service
        built["version"] = version
        built["developerKey"] = developerKey
        return object()

    googleapiclient_pkg = ModuleType("googleapiclient")
    googleapiclient_discovery = ModuleType("googleapiclient.discovery")
    googleapiclient_discovery.build = fake_build

    monkeypatch.setitem(sys.modules, "googleapiclient", googleapiclient_pkg)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", googleapiclient_discovery)

    c = YouTubeStatsClient("api-key")
    assert c._youtube is not None
    assert built == {"service": "youtube", "version": "v3", "developerKey": "api-key"}
