"""voice_qa.py — the L3 verifier (plan §7).

Duration is the source of truth for the whole video's length, and it is read
from the *real* MP3 via mutagen — never estimated from word timings (those drift
and have caused 9-second Shorts). The verifier also enforces the pronunciation
lexicon and a leading/trailing-silence bound.

A clip PASSES when its duration is inside [min, max], edge silence is within
bound, and the pronunciation substitutions have been applied. A duration below
``min_seconds`` is *fatal* — it must never be rendered, even as a fallback.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .config import VoiceLoopConfig
from .loops import Evaluation


# --------------------------------------------------------------------------- #
# Pronunciation lexicon (plan §7 "Civil 3D" -> "Civil three D", expand acronyms)
# Ordered longest-first so multi-word keys win over their substrings.
# --------------------------------------------------------------------------- #
PRONUNCIATIONS: dict[str, str] = {
    "Civil 3D": "Civil three D",
    "AutoCAD": "Auto CAD",
    "Navisworks": "Navis works",
    "InfraWorks": "Infra works",
    "Scan-to-BIM": "scan to B I M",
    "BIM": "B I M",
    "MEP": "M E P",
    "RFIs": "R F Eyes",
    "RFI": "R F I",
    "BOQ": "B O Q",
    "GIS": "G I S",
    "LOD": "L O D",
    "IFC": "I F C",
    "HVAC": "H VAC",
    "ACC": "A C C",
    "P6": "P six",
    "3D": "three D",
}

# Keys whose *raw* form must not survive into the spoken text (used by the QA
# "pronunciation applied" check). Multi-char acronyms that TTS mangles.
_RISKY_RAW = ("Civil 3D", "Navisworks", "Scan-to-BIM", "BOQ", "HVAC", "P6")


def apply_pronunciations(text: str, table: Optional[dict[str, str]] = None) -> str:
    """Apply the pronunciation lexicon with word-boundary-aware replacement."""
    table = table if table is not None else PRONUNCIATIONS
    out = text
    for key in sorted(table, key=len, reverse=True):
        # word-ish boundary: not preceded/followed by an alphanumeric
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(key)}(?![A-Za-z0-9])")
        out = pattern.sub(table[key], out)
    return out


def pronunciation_applied(text: str) -> bool:
    """True if no risky raw acronym/token survives in the text."""
    for raw in _RISKY_RAW:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(raw)}(?![A-Za-z0-9])", text):
            return False
    return True


# --------------------------------------------------------------------------- #
# Duration probe (mutagen, deferred import so the suite needs no dependency)
# --------------------------------------------------------------------------- #
def mp3_duration(path: Path) -> float:
    """Return the true duration of an MP3 in seconds, via mutagen."""
    from mutagen.mp3 import MP3  # deferred import

    info = MP3(str(path)).info
    if info is None:
        raise ValueError(f"unable to read MP3 info from: {path}")
    return float(info.length)


# --------------------------------------------------------------------------- #
# Verifier
# --------------------------------------------------------------------------- #
def evaluate_voice(
    *,
    duration: float,
    edge_silence: float,
    text_used: str,
    cfg: VoiceLoopConfig,
) -> Evaluation:
    violations: list[str] = []
    fatal = False
    sub: dict[str, float] = {}

    # --- duration (60) --- #
    if cfg.min_seconds <= duration <= cfg.max_seconds:
        sub["duration"] = 60.0
    else:
        if duration < cfg.min_seconds:
            violations.append(f"too short: {duration:.1f}s < {cfg.min_seconds:.0f}s")
            fatal = True  # never render a stub
            sub["duration"] = max(0.0, 60.0 * duration / max(cfg.min_seconds, 1))
        else:
            over = duration - cfg.max_seconds
            violations.append(f"too long: {duration:.1f}s > {cfg.max_seconds:.0f}s")
            sub["duration"] = max(0.0, 60.0 * (1 - over / max(cfg.max_seconds, 1)))

    # --- edge silence (15) --- #
    if edge_silence <= cfg.max_edge_silence:
        sub["silence"] = 15.0
    else:
        sub["silence"] = 0.0
        violations.append(f"edge silence {edge_silence:.1f}s > {cfg.max_edge_silence:.1f}s")

    # --- pronunciation applied (25) --- #
    if pronunciation_applied(text_used):
        sub["pronunciation"] = 25.0
    else:
        sub["pronunciation"] = 0.0
        violations.append("pronunciation substitutions not applied")

    score = sum(sub.values())
    passed = (not violations) and (not fatal)
    return Evaluation(
        score=round(score, 2),
        passed=passed,
        violations=violations,
        feedback="; ".join(violations) if violations else "voice ok",
        details={"sub_scores": sub, "fatal": fatal, "duration": duration},
    )
