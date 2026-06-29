"""history.py — scripts_created.json (L1 memory + L0 ledger).

This file is the only persistent state besides build artifacts. It backs two
loops:

* L1 (recurrence): read at the start of a run to build the avoid-list; appended
  to **once**, only after a confirmed ``video_id`` (plan §6 invariant). This is
  the closed edge that guarantees the next run cannot repeat this one.
* L0 (learning): the same entries carry a ``perf`` placeholder that analytics
  later fills, so the ledger doubles as the performance record.

Writes are atomic (temp file + ``os.replace``) and reads are corruption
tolerant (a malformed file degrades to an empty history rather than crashing a
run), per the test plan in §13.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


# --------------------------------------------------------------------------- #
# Entry schema (plan §9 "Post-success" append)
# --------------------------------------------------------------------------- #
@dataclass
class HistoryEntry:
    date: str
    bucket: str
    feature_fingerprint: str
    title: str
    title_variants: list[str] = field(default_factory=list)
    hook_style: str = ""
    script_lines: list[str] = field(default_factory=list)
    narration: str = ""
    video_id: str = ""
    url: str = ""
    published_at: str = ""
    duration_seconds: float = 0.0
    perf: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HistoryEntry":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_hist_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        # Windows can transiently lock files during AV/indexing scans.
        attempt = 0
        while True:
            try:
                os.replace(tmp, path)  # atomic on POSIX and Windows
                break
            except PermissionError:
                if attempt >= 2:
                    raise
                time.sleep(0.05 * (attempt + 1))
                attempt += 1
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class History:
    """Read/append wrapper around the JSON ledger."""

    def __init__(self, path: Path):
        self.path = Path(path)

    # ---- read -------------------------------------------------------------- #
    def load(self) -> list[HistoryEntry]:
        """Return all entries. Corruption-tolerant: returns [] on bad/missing file."""
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        entries: list[HistoryEntry] = []
        for item in raw:
            if isinstance(item, dict):
                try:
                    entries.append(HistoryEntry.from_dict(item))
                except TypeError:
                    continue
        return entries

    def recent(self, k: int) -> list[HistoryEntry]:
        entries = self.load()
        return entries[-k:] if k > 0 else entries

    def fingerprints(self, lookback: int = 0) -> set[str]:
        entries = self.recent(lookback) if lookback > 0 else self.load()
        return {e.feature_fingerprint for e in entries if e.feature_fingerprint}

    def bucket_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.load():
            counts[e.bucket] = counts.get(e.bucket, 0) + 1
        return counts

    # ---- append ------------------------------------------------------------ #
    def append(self, entry: HistoryEntry) -> None:
        """Append exactly one entry. Caller must only invoke after a video_id.

        Guards the L1 invariant defensively: refuses to append an entry with no
        ``video_id`` so a half-finished run can never poison the avoid-list.
        """
        if not entry.video_id:
            raise ValueError("refusing to append history entry without a video_id")
        entries = self.load()
        entries.append(entry)
        _atomic_write(self.path, json.dumps([e.to_dict() for e in entries], indent=2))


# --------------------------------------------------------------------------- #
# Fingerprint + non-repetition helpers (shared by L2 critic and topic_select)
# --------------------------------------------------------------------------- #
def fingerprint_tokens(text: str) -> set[str]:
    """Lowercased alphanumeric token set used for Jaccard similarity."""
    import re

    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def is_repeat(
    candidate_fp: str,
    history: History,
    *,
    lookback: int,
    jaccard_max: float,
) -> bool:
    """True if the candidate fingerprint is too similar to a recent entry."""
    recent = history.recent(lookback)
    cand_tokens = fingerprint_tokens(candidate_fp)
    for e in recent:
        if e.feature_fingerprint == candidate_fp:
            return True
        if jaccard(cand_tokens, fingerprint_tokens(e.feature_fingerprint)) >= jaccard_max:
            return True
    return False
