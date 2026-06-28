"""Tests for topic_select.py (L1 non-repeat + L0 weight bias) — plan §13."""
from __future__ import annotations

import random

from pipeline.history import History, HistoryEntry
from pipeline.topic_select import make_fingerprint, select_topic
from pipeline.topics_aec import BUCKETS_BY_KEY, all_features


def _seed_history(tmp_path, fingerprints):
    h = History(tmp_path / "hist.json")
    for i, fp in enumerate(fingerprints):
        bucket = fp.split(":", 1)[0]
        h.append(
            HistoryEntry(
                date="2026-06-28",
                bucket=bucket,
                feature_fingerprint=fp,
                title=f"t{i}",
                video_id=f"vid{i}",
            )
        )
    return h


def test_selects_valid_feature(tmp_path):
    h = History(tmp_path / "hist.json")
    choice = select_topic(h, rng=random.Random(1))
    assert choice.bucket in BUCKETS_BY_KEY
    assert choice.fingerprint == make_fingerprint(choice.bucket, choice.feature)


def test_does_not_repeat_recent(tmp_path):
    # Mark all but one feature as used; selection must land on the remaining one.
    feats = all_features()
    target_bucket, target_tool, target_feat = feats[0]
    used = [make_fingerprint(b, f) for (b, _t, f) in feats[1:]]
    h = _seed_history(tmp_path, used)

    choice = select_topic(h, lookback=len(used) + 5, rng=random.Random(7))
    assert choice.fingerprint == make_fingerprint(target_bucket, target_feat)


def test_exhaustion_fallback_still_returns(tmp_path):
    # Every feature used -> pool falls back to full set, never blocks.
    used = [make_fingerprint(b, f) for (b, _t, f) in all_features()]
    h = _seed_history(tmp_path, used)
    choice = select_topic(h, lookback=len(used) + 10, rng=random.Random(3))
    assert choice.bucket in BUCKETS_BY_KEY


def test_weights_bias_bucket_selection(tmp_path):
    # With an extreme weight on one bucket and floor near zero, selection should
    # overwhelmingly favor that bucket across many draws.
    h = History(tmp_path / "hist.json")
    weights = {"water_environmental": 1000.0}
    rng = random.Random(42)
    picks = [
        select_topic(h, weights=weights, weight_floor=0.01, rng=rng).bucket
        for _ in range(50)
    ]
    water = sum(1 for b in picks if b == "water_environmental")
    assert water > 40  # heavily biased, but exploration floor keeps it < 50
