"""agent_script.py — Agent 1 (writer) and the L2 generate <-> critique loop.

The writer is the *only* LLM caller in the system. It is wired to the critic
through :func:`pipeline.loops.run_loop`, so L2 inherits the §2 contract:
bounded attempts, best-so-far progress, per-iteration logging, and a
deterministic fallback (ship best-acceptable, else abort).

The LLM is hidden behind the small :class:`LLMClient` protocol so the whole
loop is testable with a mocked client — no network, no keys.
"""
from __future__ import annotations

import random
from typing import Callable, Optional, Protocol

from .config import ScriptLoopConfig
from .critic_script import LLMJudge, evaluate_script
from .errors import ScriptGenerationError
from .history import History
from .loops import Evaluation, ExitReason, Result, run_loop
from .script_types import Script, ScriptParseError, parse_script
from .topic_select import TopicChoice
from .topics_aec import BUCKETS_BY_KEY, HOOK_STYLES


class LLMClient(Protocol):
    def generate(self, prompt: str) -> str:
        """Return the model's raw text response (expected to be JSON)."""
        ...


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
SYSTEM_INSTRUCTIONS = (
    "You are a scriptwriter for ~50-60 second vertical YouTube Shorts about AI "
    "in the AEC (architecture, engineering, construction) industry. Your audience "
    "is practicing AEC engineers, regional team leads and consultants — write to a "
    "practitioner, be technically accurate and concrete, never vague. Cover ONE to "
    "TWO specific AI features. Output STRICT JSON only, no prose, no code fences."
)

JSON_SHAPE = (
    '{\n'
    '  "title": "string",\n'
    '  "title_variants": ["string", "string"],\n'
    '  "hook": "one punchy sentence ending in ! or ?",\n'
    '  "lines": ["spoken caption line", "..."],\n'
    '  "points": [{"heading": "string", "detail": "string"}],\n'
    '  "flow": ["workflow step", "..."],\n'
    '  "description": "YouTube description with #AEC hashtags",\n'
    '  "tags": ["string", "..."]\n'
    '}'
)


def build_prompt(
    topic: TopicChoice,
    *,
    cfg: ScriptLoopConfig,
    hook_style: str,
    avoid: list[str],
    critique: Optional[str] = None,
    perf_hint: str = "",
) -> str:
    avoid_block = (
        "Avoid repeating these recently-covered topics:\n- " + "\n- ".join(avoid)
        if avoid
        else "No recent topics to avoid."
    )
    perf_block = f"\nPerformance hint (lean into what worked): {perf_hint}" if perf_hint else ""
    critique_block = (
        f"\nYOUR PREVIOUS ATTEMPT WAS REJECTED. {critique} Rewrite to fix every issue."
        if critique
        else ""
    )
    bucket = BUCKETS_BY_KEY.get(topic.bucket)
    bucket_name = bucket.name if bucket else topic.bucket
    return (
        f"{SYSTEM_INSTRUCTIONS}\n\n"
        f"Topic area: {bucket_name}\n"
        f"Specific AI feature to cover: {topic.feature}\n"
        f"Suggested tool to name: {topic.tool_hint}\n"
        f"Hook style: {hook_style}\n"
        f"Constraints: narration {cfg.min_words}-{cfg.max_words} words; name a real "
        f"tool AND a specific feature AND a concrete/quantified benefit; include a "
        f"call-to-action; no emojis in spoken lines.\n"
        f"{avoid_block}{perf_block}{critique_block}\n\n"
        f"Return JSON exactly in this shape:\n{JSON_SHAPE}"
    )


# --------------------------------------------------------------------------- #
# The L2 loop
# --------------------------------------------------------------------------- #
def _invalid_script(topic: TopicChoice, hook_style: str) -> Script:
    """A placeholder the critic scores ~0 when the writer output won't parse."""
    return Script(
        title="",
        hook="(invalid output)",
        bucket=topic.bucket,
        hook_style=hook_style,
        feature_fingerprint=topic.fingerprint,
    )


def generate_script(
    topic: TopicChoice,
    *,
    llm: LLMClient,
    cfg: ScriptLoopConfig,
    history: Optional[History] = None,
    judge: Optional[LLMJudge] = None,
    perf_hint: str = "",
    rng: Optional[random.Random] = None,
    on_result: Optional[Callable[[Result[Script]], None]] = None,
) -> Script:
    """Run the writer ⇄ critic loop and return an acceptable Script.

    Raises :class:`ScriptGenerationError` if no attempt reaches the minimum
    acceptable score or every attempt has a fatal violation (e.g. repetition) —
    the loop never returns a sub-floor or unsafe-to-publish script.
    """
    rng = rng or random.Random()
    hook_style = rng.choice(HOOK_STYLES)
    avoid = [e.feature_fingerprint for e in history.recent(cfg.dedup_lookback)] if history else []

    def body(attempt: int, last_eval: Optional[Evaluation]) -> Script:
        critique = last_eval.feedback if last_eval is not None else None
        prompt = build_prompt(
            topic,
            cfg=cfg,
            hook_style=hook_style,
            avoid=avoid,
            critique=critique,
            perf_hint=perf_hint,
        )
        raw = llm.generate(prompt)
        try:
            return parse_script(
                raw, bucket=topic.bucket, feature=topic.feature, hook_style=hook_style
            )
        except ScriptParseError:
            return _invalid_script(topic, hook_style)

    def evaluate(script: Script) -> Evaluation:
        if not script.title:  # unparsable placeholder
            return Evaluation(
                score=0.0,
                passed=False,
                violations=["invalid_json"],
                feedback="previous output was not valid JSON; return STRICT JSON only.",
                details={"fatal": True},
            )
        return evaluate_script(script, cfg=cfg, history=history, judge=judge)

    def on_exhausted(provisional: Result[Script]) -> Result[Script]:
        ev = provisional.evaluation
        fatal = bool(ev.details.get("fatal")) if ev else True
        if ev is not None and ev.score >= cfg.min_acceptable and not fatal:
            return Result(
                artifact=provisional.artifact,
                evaluation=ev,
                exit_reason=ExitReason.FALLBACK_ACCEPTED,
                attempts=provisional.attempts,
                history=provisional.history,
            )
        raise ScriptGenerationError(
            f"no acceptable script after {provisional.attempts} attempts; "
            f"best score={ev.score if ev else 'n/a'}, fatal={fatal}"
        )

    result = run_loop(
        "L2.script",
        body=body,
        evaluate=evaluate,
        on_exhausted=on_exhausted,
        max_iters=cfg.max_attempts,
        logger_name="pipeline.agent_script",
    )
    if on_result is not None:
        on_result(result)
    assert result.artifact is not None  # PASSED/FALLBACK always carry an artifact
    return result.artifact
