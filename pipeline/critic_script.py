"""critic_script.py — the L2 evaluator (plan §5.2).

Deterministic checks carry the weight and are fully unit-testable; an optional
LLM-as-judge can be blended in but is disabled for deterministic CI. The critic
returns a :class:`pipeline.loops.Evaluation` whose ``feedback`` is fed straight
back into the next writer prompt — that targeted feedback is what makes the loop
*converge* rather than randomly retry.

Scoring model (0–100, transparent weighted rubric):

    words           20   narration word count inside [min, max]
    aec_density     25   distinct AEC lexicon terms (scaled to min_aec_terms)
    concreteness    30   names a real tool (10) + specific feature (10) + benefit (10)
    hook            15   ends with ! / ? or matches a hook style; length cap
    cta             10   a call-to-action is present

A script PASSES only when ``score >= pass_threshold`` AND it has no *fatal*
violation. Fatal violations (repetition, invalid JSON, emoji in spoken lines,
word count wildly out of range) mean the artifact must never ship, even as a
fallback — they set ``details['fatal'] = True``.
"""
from __future__ import annotations

import re
from typing import Optional, Protocol

from .config import ScriptLoopConfig
from .history import History, fingerprint_tokens, is_repeat, jaccard
from .loops import Evaluation
from .script_types import Script
from .topics_aec import AEC_LEXICON, BUCKETS, HOOK_STYLES

# Emoji detection (covers the common pictographic ranges).
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF\U00002190-\U000021FF]"
)

# Benefit signals: a quantity/percentage or an explicit value verb.
_QUANTITY_RE = re.compile(
    r"(\d+\s?%|\d+\s?(x|times|hours?|days?|weeks?|minutes?|mins?|%|percent))", re.IGNORECASE
)
_BENEFIT_WORDS = (
    "faster", "save", "saves", "saving", "reduce", "reduces", "cut", "cuts",
    "fewer", "automatically", "accuracy", "instantly", "in minutes", "no more",
    "eliminate", "eliminates", "avoid", "catch", "catches",
)
_CTA_WORDS = (
    "follow", "subscribe", "comment", "like", "save this", "share", "watch",
    "try", "check out", "learn more", "drop a", "tell us",
)

# Tools across all buckets, lowercased, for the "names a real tool" check.
_ALL_TOOLS: tuple[str, ...] = tuple(
    sorted({t.lower() for b in BUCKETS for t in b.tools}, key=len, reverse=True)
)


class LLMJudge(Protocol):
    def judge(self, script: Script) -> dict[str, float]:
        """Return {'clarity':0-10,'excitement':0-10,'accuracy':0-10}."""
        ...


# --------------------------------------------------------------------------- #
# Individual deterministic detectors (each independently unit-testable)
# --------------------------------------------------------------------------- #
def count_aec_terms(text: str) -> int:
    low = text.lower()
    return sum(1 for term in AEC_LEXICON if term in low)


def names_tool(text: str) -> bool:
    low = text.lower()
    return any(tool in low for tool in _ALL_TOOLS)


def has_benefit(text: str) -> bool:
    if _QUANTITY_RE.search(text):
        return True
    low = text.lower()
    return any(w in low for w in _BENEFIT_WORDS)


def has_cta(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in _CTA_WORDS)


def has_emoji(text: str) -> bool:
    return bool(_EMOJI_RE.search(text))


def hook_is_strong(hook: str, *, max_len: int = 90) -> bool:
    h = hook.strip()
    if not h or len(h) > max_len:
        return False
    return h.endswith("!") or h.endswith("?")


# --------------------------------------------------------------------------- #
# Composite rubric
# --------------------------------------------------------------------------- #
def evaluate_script(
    script: Script,
    *,
    cfg: ScriptLoopConfig,
    history: Optional[History] = None,
    judge: Optional[LLMJudge] = None,
) -> Evaluation:
    violations: list[str] = []
    fatal = False
    sub: dict[str, float] = {}

    narration = script.narration
    wc = script.word_count

    # --- words (20) — fatal only if wildly out of range (>25% past a bound) --- #
    if cfg.min_words <= wc <= cfg.max_words:
        sub["words"] = 20.0
    else:
        # linear penalty by distance from the nearest bound
        if wc < cfg.min_words:
            dist = cfg.min_words - wc
            bound = cfg.min_words
        else:
            dist = wc - cfg.max_words
            bound = cfg.max_words
        sub["words"] = max(0.0, 20.0 * (1 - dist / max(bound, 1)))
        violations.append(f"word_count={wc} outside [{cfg.min_words},{cfg.max_words}]")
        if dist > 0.25 * bound:
            fatal = True

    # --- AEC vocabulary density (25) --- #
    terms = count_aec_terms(narration)
    sub["aec_density"] = min(25.0, 25.0 * terms / max(cfg.min_aec_terms, 1))
    if terms < cfg.min_aec_terms:
        violations.append(f"only {terms} AEC terms (need {cfg.min_aec_terms})")

    # --- concreteness (30): tool + specific feature + benefit --- #
    tool_ok = names_tool(narration)
    benefit_ok = has_benefit(narration)
    # "specific feature": at least one point with both a heading and a detail.
    feature_ok = any(p.heading and p.detail for p in script.points)
    sub["concreteness"] = (10.0 if tool_ok else 0.0) + (
        10.0 if feature_ok else 0.0
    ) + (10.0 if benefit_ok else 0.0)
    if not tool_ok:
        violations.append("no concrete tool named")
    if not feature_ok:
        violations.append("no specific feature point (heading+detail)")
    if not benefit_ok:
        violations.append("no quantified/explicit benefit")

    # --- hook strength (15) --- #
    style_match = script.hook_style in HOOK_STYLES
    if hook_is_strong(script.hook):
        sub["hook"] = 15.0
    elif style_match:
        sub["hook"] = 8.0
        violations.append("hook lacks ! or ? punch")
    else:
        sub["hook"] = 0.0
        violations.append("weak hook")

    # --- CTA (10) — fatal if missing (hard rule) --- #
    if has_cta(narration) or has_cta(script.description):
        sub["cta"] = 10.0
    else:
        sub["cta"] = 0.0
        violations.append("missing call-to-action")
        fatal = True

    # --- emoji in spoken lines (hard rule) --- #
    if has_emoji(narration):
        violations.append("emoji in spoken lines")
        fatal = True

    # --- non-repetition (hard rule, re-roll) --- #
    if history is not None and is_repeat(
        script.feature_fingerprint,
        history,
        lookback=cfg.dedup_lookback,
        jaccard_max=cfg.dedup_jaccard_max,
    ):
        violations.append("topic repeats recent history")
        fatal = True

    rubric_score = sum(sub.values())

    # --- optional LLM judge blend (disabled in CI) --- #
    judge_scores: dict[str, float] = {}
    if cfg.use_llm_judge and judge is not None:
        try:
            judge_scores = judge.judge(script)
            avg = sum(judge_scores.values()) / max(len(judge_scores), 1)  # 0-10
            score = 0.8 * rubric_score + 0.2 * (avg * 10.0)
        except Exception:  # judge failure must never break the loop
            score = rubric_score
    else:
        score = rubric_score

    passed = (score >= cfg.pass_threshold) and not fatal

    return Evaluation(
        score=round(score, 2),
        passed=passed,
        violations=violations,
        feedback=_build_feedback(score, violations),
        details={
            "sub_scores": sub,
            "fatal": fatal,
            "word_count": wc,
            "aec_terms": terms,
            "judge": judge_scores,
        },
    )


def _build_feedback(score: float, violations: list[str]) -> str:
    if not violations:
        return f"scored {score:.0f}; clean."
    return (
        f"previous attempt scored {score:.0f}. Fix these to improve: "
        + "; ".join(violations)
        + "."
    )
