"""script_types.py — the typed Script contract exchanged between L2 and L3.

Agent 1 (writer) emits strict JSON; this module parses it into a validated
:class:`Script` and derives the fields the rest of the pipeline relies on
(``narration`` for L3, ``feature_fingerprint`` for L1 dedup, ``hook_style`` and
``bucket`` for L4 theming). Parsing is fence-tolerant because LLMs habitually
wrap JSON in ```json fences.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .topic_select import make_fingerprint


class ScriptParseError(ValueError):
    """Raised when the writer output cannot be parsed into a Script."""


@dataclass
class ScriptPoint:
    heading: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"heading": self.heading, "detail": self.detail}


@dataclass
class Script:
    # --- authored fields (from the LLM) --- #
    title: str
    hook: str
    lines: list[str] = field(default_factory=list)
    title_variants: list[str] = field(default_factory=list)
    points: list[ScriptPoint] = field(default_factory=list)
    flow: list[str] = field(default_factory=list)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    # --- derived/injected fields --- #
    bucket: str = ""
    hook_style: str = ""
    feature_fingerprint: str = ""
    accent: str = ""

    @property
    def narration(self) -> str:
        """The spoken text: hook followed by the caption lines.

        This is the single source for L3 TTS and word-count scoring, so it is
        derived (never authored) to keep one canonical definition.
        """
        parts = [self.hook.strip()] + [ln.strip() for ln in self.lines if ln.strip()]
        return " ".join(p for p in parts if p)

    @property
    def word_count(self) -> int:
        return len(re.findall(r"[A-Za-z0-9']+", self.narration))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["points"] = [p.to_dict() for p in self.points]
        d["narration"] = self.narration
        d["word_count"] = self.word_count
        return d


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _strip_fences(raw: str) -> str:
    """Remove a single leading/trailing markdown code fence if present."""
    text = raw.strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text)
    return text.strip()


def _coerce_points(value: Any) -> list[ScriptPoint]:
    points: list[ScriptPoint] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                points.append(
                    ScriptPoint(
                        heading=str(item.get("heading", "")).strip(),
                        detail=str(item.get("detail", "")).strip(),
                    )
                )
    return points


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def parse_script(
    raw: str,
    *,
    bucket: str,
    feature: str,
    hook_style: str = "",
    accent: str = "",
) -> Script:
    """Parse raw writer output into a validated Script with derived fields.

    Raises :class:`ScriptParseError` on invalid JSON or a missing title/hook so
    the L2 critic can score the attempt 0 and the loop can re-roll.
    """
    try:
        data = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScriptParseError(f"writer output is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ScriptParseError("writer output JSON must be an object")

    title = str(data.get("title", "")).strip()
    hook = str(data.get("hook", "")).strip()
    if not title or not hook:
        raise ScriptParseError("script missing required 'title' or 'hook'")

    return Script(
        title=title,
        hook=hook,
        lines=_coerce_str_list(data.get("lines")),
        title_variants=_coerce_str_list(data.get("title_variants")),
        points=_coerce_points(data.get("points")),
        flow=_coerce_str_list(data.get("flow")),
        description=str(data.get("description", "")).strip(),
        tags=_coerce_str_list(data.get("tags")),
        bucket=bucket,
        hook_style=hook_style,
        feature_fingerprint=make_fingerprint(bucket, feature),
        accent=accent,
    )
