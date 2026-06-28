"""topic_select.py — non-repeat topic selection (L1 guard input, L0 consumer).

Picks the next (bucket, tool, feature) to script. It:

* excludes features whose fingerprint repeats recent history (L1 non-repetition);
* biases the choice by L0 ``weights[bucket]`` when analytics is enabled, while
  always keeping a floor of randomness so the system explores, not just exploits;
* is deterministic under a supplied ``rng`` so tests can assert behavior.

The fingerprint is ``"{bucket}:{feature}"`` lowercased — a stable, compact key
used both here and by the critic's hard non-repetition rule.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from .history import History, is_repeat
from .topics_aec import BUCKETS_BY_KEY, all_features


@dataclass
class TopicChoice:
    bucket: str
    bucket_name: str
    tool_hint: str
    feature: str
    fingerprint: str


def make_fingerprint(bucket: str, feature: str) -> str:
    return f"{bucket}:{feature}".lower()


def _weight_for(bucket: str, weights: dict[str, float], floor: float) -> float:
    w = weights.get(bucket, 1.0) if weights else 1.0
    return max(floor, w)


def select_topic(
    history: History,
    *,
    lookback: int = 30,
    jaccard_max: float = 0.6,
    weights: Optional[dict[str, float]] = None,
    weight_floor: float = 0.25,
    rng: Optional[random.Random] = None,
) -> TopicChoice:
    """Choose a non-repeated feature, weighted by L0 performance if available.

    Falls back gracefully: if *every* feature is currently "used" within the
    lookback window (topic exhaustion), it ignores the repeat filter for this
    pick so a run is never blocked — the dedup window naturally rotates.
    """
    rng = rng or random.Random()
    weights = weights or {}

    candidates = all_features()
    fresh = [
        (bucket, tool, feat)
        for (bucket, tool, feat) in candidates
        if not is_repeat(
            make_fingerprint(bucket, feat),
            history,
            lookback=lookback,
            jaccard_max=jaccard_max,
        )
    ]
    pool = fresh if fresh else candidates  # exhaustion fallback

    bucket_weights = [_weight_for(b, weights, weight_floor) for (b, _t, _f) in pool]
    chosen = rng.choices(pool, weights=bucket_weights, k=1)[0]
    bucket, tool, feature = chosen
    return TopicChoice(
        bucket=bucket,
        bucket_name=BUCKETS_BY_KEY[bucket].name if bucket in BUCKETS_BY_KEY else bucket,
        tool_hint=tool,
        feature=feature,
        fingerprint=make_fingerprint(bucket, feature),
    )
