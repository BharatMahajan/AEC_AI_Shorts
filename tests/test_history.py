"""Tests for history.py (L1 memory + L0 ledger) — plan §13.

Covers: append exactly once and only after a video_id, corruption-tolerant read,
fingerprint dedup, and the Jaccard repeat detector.
"""
from __future__ import annotations

import json
import os

import pytest

from pipeline.history import (
    History,
    HistoryEntry,
    is_repeat,
    jaccard,
)


def _entry(fp: str, vid: str = "vid123", bucket: str = "cad") -> HistoryEntry:
    return HistoryEntry(
        date="2026-06-28",
        bucket=bucket,
        feature_fingerprint=fp,
        title="t",
        video_id=vid,
    )


def test_load_missing_file_returns_empty(tmp_path):
    h = History(tmp_path / "nope.json")
    assert h.load() == []


def test_append_then_load_roundtrip(tmp_path):
    h = History(tmp_path / "hist.json")
    h.append(_entry("cad:markup assist"))
    entries = h.load()
    assert len(entries) == 1
    assert entries[0].feature_fingerprint == "cad:markup assist"
    assert entries[0].video_id == "vid123"


def test_append_refuses_without_video_id(tmp_path):
    h = History(tmp_path / "hist.json")
    with pytest.raises(ValueError):
        h.append(_entry("cad:x", vid=""))
    # nothing written
    assert h.load() == []


def test_append_is_additive_once_per_call(tmp_path):
    h = History(tmp_path / "hist.json")
    h.append(_entry("a:1"))
    h.append(_entry("b:2"))
    assert len(h.load()) == 2


def test_corrupt_file_degrades_to_empty(tmp_path):
    p = tmp_path / "hist.json"
    p.write_text("{ this is not valid json ]", encoding="utf-8")
    h = History(p)
    assert h.load() == []
    # and we can still append on top of a corrupt file
    h.append(_entry("a:1"))
    assert len(h.load()) == 1


def test_non_list_json_degrades_to_empty(tmp_path):
    p = tmp_path / "hist.json"
    p.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert History(p).load() == []


def test_fingerprints_and_bucket_counts(tmp_path):
    h = History(tmp_path / "hist.json")
    h.append(_entry("cad:a", bucket="cad"))
    h.append(_entry("mep:b", bucket="mep"))
    h.append(_entry("cad:c", bucket="cad"))
    assert h.fingerprints() == {"cad:a", "mep:b", "cad:c"}
    assert h.bucket_counts() == {"cad": 2, "mep": 1}


def test_jaccard_basic():
    assert jaccard([], []) == 0.0
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a", "b"}, {"a", "c"}) == pytest.approx(1 / 3)


def test_is_repeat_exact_and_similar(tmp_path):
    h = History(tmp_path / "hist.json")
    h.append(_entry("cad:markup assist for redlines"))

    # exact fingerprint -> repeat
    assert is_repeat("cad:markup assist for redlines", h, lookback=10, jaccard_max=0.6)
    # highly similar wording -> repeat by Jaccard
    assert is_repeat("cad:markup assist redlines", h, lookback=10, jaccard_max=0.5)
    # unrelated -> not a repeat
    assert not is_repeat("mep:energy modeling", h, lookback=10, jaccard_max=0.6)


def test_recent_lookback_window(tmp_path):
    h = History(tmp_path / "hist.json")
    for i in range(5):
        h.append(_entry(f"cad:{i}"))
    assert [e.feature_fingerprint for e in h.recent(2)] == ["cad:3", "cad:4"]


def test_recent_with_non_positive_k_returns_all(tmp_path):
    h = History(tmp_path / "hist.json")
    h.append(_entry("cad:1"))
    h.append(_entry("cad:2"))
    assert len(h.recent(0)) == 2


def test_load_skips_malformed_dict_entries(tmp_path):
    p = tmp_path / "hist.json"
    p.write_text(
        json.dumps(
            [
                {"date": "2026-06-28", "bucket": "cad", "feature_fingerprint": "ok", "title": "t", "video_id": "v1"},
                {"bucket": "cad"},
                "not-a-dict",
            ]
        ),
        encoding="utf-8",
    )
    out = History(p).load()
    assert len(out) == 1
    assert out[0].feature_fingerprint == "ok"


def test_append_retries_transient_permission_error(tmp_path, monkeypatch):
    h = History(tmp_path / "hist.json")
    calls = {"n": 0}
    real_replace = os.replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("transient lock")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    h.append(_entry("cad:retry"))
    assert calls["n"] >= 2
    assert len(h.load()) == 1


def test_append_raises_after_persistent_permission_error(tmp_path, monkeypatch):
    h = History(tmp_path / "hist.json")

    def always_locked(_src, _dst):
        raise PermissionError("always locked")

    monkeypatch.setattr(os, "replace", always_locked)
    with pytest.raises(PermissionError):
        h.append(_entry("cad:locked"))
