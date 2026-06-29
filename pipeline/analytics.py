"""analytics.py — L0, the learning loop (plan §10).

Closes the outer feedback edge: "what got watched" → "what we make next". It
reads public stats for recent uploads, turns them into per-bucket and per-hook
performance weights plus a short ``perf_hint``, and hands those to the next run
(``topic_select`` consumes the weights; the L2 prompt receives the hint).

It is a feedback *edge*, not a spin loop — it runs once per run, before L2. Any
failure (disabled, no key, too few uploads, API error) degrades to an empty,
unbiased result so the pipeline always runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from .config import AnalyticsConfig
from .history import History, HistoryEntry
from .logging_setup import get_logger, log_event

_logger = get_logger("pipeline.analytics")


class StatsClient(Protocol):
    def fetch_stats(self, video_ids: list[str]) -> dict[str, dict[str, float]]:
        """Map video_id -> {'views': float, 'likes': float, ...}."""
        ...


@dataclass
class LearningResult:
    weights_bucket: dict[str, float] = field(default_factory=dict)
    weights_hook: dict[str, float] = field(default_factory=dict)
    perf_hint: str = ""

    @classmethod
    def empty(cls) -> "LearningResult":
        return cls()


def _score_of(stats: dict[str, float]) -> float:
    """Single performance scalar. Views dominate; likes are a light bonus."""
    return float(stats.get("views", 0.0)) + 2.0 * float(stats.get("likes", 0.0))


def _normalize(group_scores: dict[str, float], *, floor: float) -> dict[str, float]:
    """Convert per-group average scores into weights centered near 1.0."""
    if not group_scores:
        return {}
    overall = sum(group_scores.values()) / len(group_scores)
    if overall <= 0:
        return {k: 1.0 for k in group_scores}
    return {k: max(floor, v / overall) for k, v in group_scores.items()}


def _avg_by(
    entries: list[HistoryEntry],
    scores: dict[str, float],
    key: str,
) -> dict[str, float]:
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for e in entries:
        if e.video_id not in scores:
            continue
        group = getattr(e, key) or "_unknown"
        sums[group] = sums.get(group, 0.0) + scores[e.video_id]
        counts[group] = counts.get(group, 0) + 1
    return {g: sums[g] / counts[g] for g in sums}


def compute_learning(
    history: History,
    *,
    cfg: AnalyticsConfig,
    stats_client: Optional[StatsClient],
) -> LearningResult:
    """Compute L0 weights + perf_hint. Always safe: returns empty() on any issue."""
    if not cfg.enabled or stats_client is None:
        return LearningResult.empty()
    try:
        entries = [e for e in history.recent(cfg.lookback) if e.video_id]
        if len(entries) < cfg.min_uploads:
            log_event(_logger, "analytics_skipped", reason="too_few_uploads", count=len(entries))
            return LearningResult.empty()

        stats = stats_client.fetch_stats([e.video_id for e in entries])
        scores = {vid: _score_of(s) for vid, s in stats.items()}
        if not scores:
            return LearningResult.empty()

        weights_bucket = _normalize(_avg_by(entries, scores, "bucket"), floor=cfg.weight_floor)
        weights_hook = _normalize(_avg_by(entries, scores, "hook_style"), floor=cfg.weight_floor)

        top = sorted(
            (e for e in entries if e.video_id in scores),
            key=lambda e: scores[e.video_id],
            reverse=True,
        )[:3]
        hint = "; ".join(f"'{e.title}'" for e in top if e.title)
        perf_hint = f"Top performers so far: {hint}." if hint else ""

        log_event(
            _logger, "analytics_weights",
            buckets=weights_bucket, hooks=weights_hook, sample=len(entries),
        )
        return LearningResult(
            weights_bucket=weights_bucket,
            weights_hook=weights_hook,
            perf_hint=perf_hint,
        )
    except Exception as exc:  # never fatal (plan §10 fallback)
        log_event(_logger, "analytics_failed", error=str(exc))
        return LearningResult.empty()


class YouTubeStatsClient:
    """Fetches public video statistics via the YouTube Data API v3 (lazy import)."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("YT_DATA_API_KEY required for YouTubeStatsClient")
        from googleapiclient.discovery import build  # deferred

        self._youtube = build("youtube", "v3", developerKey=api_key)

    def fetch_stats(self, video_ids: list[str]) -> dict[str, dict[str, float]]:  # pragma: no cover
        out: dict[str, dict[str, float]] = {}
        for i in range(0, len(video_ids), 50):  # API allows 50 ids/call
            chunk = video_ids[i : i + 50]
            resp = self._youtube.videos().list(
                part="statistics", id=",".join(chunk)
            ).execute()
            for item in resp.get("items", []):
                st = item.get("statistics", {})
                out[item["id"]] = {
                    "views": float(st.get("viewCount", 0)),
                    "likes": float(st.get("likeCount", 0)),
                }
        return out
