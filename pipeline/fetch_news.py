"""fetch_news.py — optional AEC news grounding for the L2 writer.

Pulls recent headlines from AEC-industry RSS feeds so scripts can reference
current developments. This is *grounding*, not a hard dependency: any failure
(no network, bad feed, missing parser) returns an empty pool and the writer
proceeds on the taxonomy alone.
"""
from __future__ import annotations

from typing import Optional

from .logging_setup import get_logger, log_event

_logger = get_logger("pipeline.fetch_news")

# A small set of AEC / construction-tech feeds (extensible).
DEFAULT_FEEDS: tuple[str, ...] = (
    "https://www.aec-business.com/feed/",
    "https://constructible.trimble.com/rss.xml",
    "https://www.engineering.com/rss",
)


def fetch_headlines(
    *,
    feeds: Optional[tuple[str, ...]] = None,
    limit: int = 12,
    timeout: int = 8,
) -> list[str]:
    """Return up to ``limit`` recent AEC headlines. Always safe (returns [])."""
    feeds = feeds or DEFAULT_FEEDS
    headlines: list[str] = []
    try:
        import feedparser  # deferred import
    except ImportError:
        log_event(_logger, "news_skipped", reason="feedparser_missing")
        return []

    for url in feeds:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:limit]:
                title = getattr(entry, "title", "").strip()
                if title:
                    headlines.append(title)
        except Exception as exc:
            log_event(_logger, "news_feed_failed", feed=url, error=str(exc))
            continue

    deduped = list(dict.fromkeys(headlines))[:limit]  # order-preserving dedup
    log_event(_logger, "news_fetched", count=len(deduped))
    return deduped
