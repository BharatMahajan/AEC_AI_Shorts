"""agent_voice.py — Agent 2 (edge-tts) and the L3 voice QA loop.

The synthesizer is hidden behind the :class:`Synthesizer` protocol so the loop
is fully testable with a fake (no network, no audio codecs). The real
:class:`EdgeTTSSynthesizer` uses free Microsoft neural voices (US female by
default) and is imported lazily.

Between attempts the loop *adapts*: it nudges the speaking rate to push the clip
toward the target duration band — that input change is what makes the retry real
progress rather than an identical call. If the clip is still below the hard
floor after the bound, the run aborts (never render a stub).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol

from .config import VoiceLoopConfig
from .errors import RetryableError, VoiceSynthesisError, retry
from .loops import Evaluation, ExitReason, Result, run_loop
from .script_types import Script
from .voice_qa import apply_pronunciations, evaluate_voice, mp3_duration


# --------------------------------------------------------------------------- #
# Synthesizer protocol + the real edge-tts implementation
# --------------------------------------------------------------------------- #
class Synthesizer(Protocol):
    def synth(
        self, text: str, *, voice: str, rate: str, pitch: str, volume: str, out_path: Path
    ) -> None:
        """Write an MP3 of ``text`` to ``out_path``."""
        ...


class EdgeTTSSynthesizer:
    """Free Microsoft neural TTS via the ``edge-tts`` package (lazy import)."""

    @retry(max_attempts=3, retry_on=(RetryableError,))
    def synth(
        self, text: str, *, voice: str, rate: str, pitch: str, volume: str, out_path: Path
    ) -> None:
        import asyncio

        try:
            import edge_tts  # deferred import
        except ImportError as exc:  # pragma: no cover
            raise VoiceSynthesisError("edge-tts is not installed") from exc

        async def _run() -> None:
            communicate = edge_tts.Communicate(
                text, voice=voice, rate=rate, pitch=pitch, volume=volume
            )
            await communicate.save(str(out_path))

        try:
            asyncio.run(_run())
        except Exception as exc:  # transient network -> bounded retry
            raise RetryableError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Artifact
# --------------------------------------------------------------------------- #
@dataclass
class VoiceArtifact:
    audio_path: Path
    duration_seconds: float
    edge_silence: float
    text_used: str
    voice: str
    rate: str
    captions: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Rate nudging (adapt step)
# --------------------------------------------------------------------------- #
_RATE_RE = re.compile(r"^([+-]?)(\d+)%$")


def nudge_rate(rate: str, *, faster: bool, step: int = 12) -> str:
    """Shift an edge-tts rate string like ``+8%`` by ``step`` points.

    ``faster=True`` raises the rate (shortens the clip); ``faster=False`` lowers
    it (lengthens the clip). Clamped to a sane [-40%, +40%] band.
    """
    m = _RATE_RE.match(rate.strip())
    current = int(m.group(1) + m.group(2)) if m and m.group(2) else 0
    nxt = current + step if faster else current - step
    nxt = max(-40, min(40, nxt))
    return f"{'+' if nxt >= 0 else ''}{nxt}%"


# --------------------------------------------------------------------------- #
# The L3 loop
# --------------------------------------------------------------------------- #
def synthesize_voice(
    script: Script,
    *,
    synth: Synthesizer,
    cfg: VoiceLoopConfig,
    out_path: Path,
    probe: Callable[[Path], float] = mp3_duration,
    silence_probe: Optional[Callable[[Path], float]] = None,
    on_result: Optional[Callable[[Result[VoiceArtifact]], None]] = None,
) -> VoiceArtifact:
    """Run the synth ⇄ QA loop and return an acceptable VoiceArtifact.

    Raises :class:`VoiceSynthesisError` if the clip stays below the hard floor
    (``min_seconds``) after exhausting attempts.
    """
    out_path = Path(out_path)
    # Pronunciation substitutions are applied once up front; rate is what we adapt.
    text_used = apply_pronunciations(script.narration)
    captions = list(script.lines) if script.lines else [script.narration]
    state = {"rate": cfg.rate}

    def body(attempt: int, last_eval: Optional[Evaluation]) -> VoiceArtifact:
        synth.synth(
            text_used,
            voice=cfg.voice,
            rate=state["rate"],
            pitch=cfg.pitch,
            volume=cfg.volume,
            out_path=out_path,
        )
        duration = probe(out_path)
        silence = silence_probe(out_path) if silence_probe else 0.0
        return VoiceArtifact(
            audio_path=out_path,
            duration_seconds=duration,
            edge_silence=silence,
            text_used=text_used,
            voice=cfg.voice,
            rate=state["rate"],
            captions=captions,
        )

    def evaluate(art: VoiceArtifact) -> Evaluation:
        return evaluate_voice(
            duration=art.duration_seconds,
            edge_silence=art.edge_silence,
            text_used=art.text_used,
            cfg=cfg,
        )

    def adapt(art: VoiceArtifact, ev: Evaluation) -> None:
        # Too short -> slow down (faster=False); too long -> speed up.
        if art.duration_seconds < cfg.min_seconds:
            state["rate"] = nudge_rate(state["rate"], faster=False)
        elif art.duration_seconds > cfg.max_seconds:
            state["rate"] = nudge_rate(state["rate"], faster=True)

    def on_exhausted(provisional: Result[VoiceArtifact]) -> Result[VoiceArtifact]:
        ev = provisional.evaluation
        fatal = bool(ev.details.get("fatal")) if ev else True
        if provisional.artifact is not None and not fatal:
            return Result(
                artifact=provisional.artifact,
                evaluation=ev,
                exit_reason=ExitReason.FALLBACK_ACCEPTED,
                attempts=provisional.attempts,
                history=provisional.history,
            )
        dur = provisional.artifact.duration_seconds if provisional.artifact else 0.0
        raise VoiceSynthesisError(
            f"voice below floor after {provisional.attempts} attempts (duration={dur:.1f}s)"
        )

    result = run_loop(
        "L3.voice",
        body=body,
        evaluate=evaluate,
        adapt=adapt,
        on_exhausted=on_exhausted,
        max_iters=cfg.max_attempts,
        logger_name="pipeline.agent_voice",
    )
    if on_result is not None:
        on_result(result)
    assert result.artifact is not None
    return result.artifact
