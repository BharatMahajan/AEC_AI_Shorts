"""agent_video.py — Agent 3 (Remotion driver) and the L4 render quality-gate loop.

The renderer is hidden behind the :class:`Renderer` protocol so the loop is
testable without Node, Chromium, or ffmpeg. The real :class:`RemotionRenderer`
shells out to ``npx remotion render`` with a performance profile.

Between attempts the loop *adapts the cost down* — lower scale, lower
concurrency, toggle the GL backend — to dodge the transient OOM / GL faults that
free CI runners throw. If the output still fails after the bound, the run aborts
with :class:`RenderError` (never publish a broken video).
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional, Protocol

from .config import RenderLoopConfig
from .errors import RenderError
from .logging_setup import get_logger, log_event
from .loops import Evaluation, Result, run_loop
from .render_qa import evaluate_render, mp4_duration, sample_frame_luma


@dataclass(frozen=True)
class RenderProfile:
    """The performance knobs Remotion is invoked with (plan §8.1)."""

    scale: float
    concurrency: str
    gl: str
    jpeg_quality: int
    codec: str
    crf: int
    x264_preset: str
    pixel_format: str
    audio_codec: str

    @classmethod
    def from_config(cls, cfg: RenderLoopConfig) -> "RenderProfile":
        return cls(
            scale=cfg.scale, concurrency=cfg.concurrency, gl=cfg.gl,
            jpeg_quality=cfg.jpeg_quality, codec=cfg.codec, crf=cfg.crf,
            x264_preset=cfg.x264_preset, pixel_format=cfg.pixel_format,
            audio_codec=cfg.audio_codec,
        )


def cheaper_profile(profile: RenderProfile) -> RenderProfile:
    """Reduce render cost for a retry: smaller scale, single-thread, swiftshader GL."""
    new_scale = round(max(0.5, profile.scale - 0.25), 2)
    new_gl = "angle" if profile.gl == "swangle" else "swangle"
    return replace(profile, scale=new_scale, concurrency="1", gl=new_gl)


class Renderer(Protocol):
    def render(self, *, props_path: Path, out_path: Path, profile: RenderProfile) -> None:
        """Render the composition to ``out_path`` using ``props_path``."""
        ...


class RemotionRenderer:
    """Drives ``npx remotion render`` (subprocess). Lazy/real-IO only."""

    def __init__(self, project_dir: Path, composition_id: str = "Short"):
        self.project_dir = Path(project_dir)
        self.composition_id = composition_id

    def _resolve_npx(self) -> str:
        candidates = ["npx"]
        if os.name == "nt":
            candidates.insert(0, "npx.cmd")
        for name in candidates:
            found = shutil.which(name)
            if found:
                return found
        return "npx"

    def build_command(
        self, *, props_path: Path, out_path: Path, profile: RenderProfile
    ) -> list[str]:
        return [
            self._resolve_npx(), "remotion", "render", self.composition_id, str(out_path),
            f"--props={props_path}",
            f"--scale={profile.scale}",
            f"--concurrency={profile.concurrency}",
            f"--gl={profile.gl}",
            f"--jpeg-quality={profile.jpeg_quality}",
            f"--codec={profile.codec}",
            f"--crf={profile.crf}",
            f"--x264-preset={profile.x264_preset}",
            f"--pixel-format={profile.pixel_format}",
            f"--audio-codec={profile.audio_codec}",
        ]

    def render(self, *, props_path: Path, out_path: Path, profile: RenderProfile) -> None:
        import subprocess

        cmd = self.build_command(props_path=props_path, out_path=out_path, profile=profile)
        try:
            proc = subprocess.run(cmd, cwd=str(self.project_dir), capture_output=True, text=True)
        except OSError as exc:
            raise RenderError(f"remotion command failed to start: {exc}") from exc
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            raise RenderError(
                "remotion render failed "
                f"(exit={proc.returncode})\nSTDERR:\n{stderr}\nSTDOUT:\n{stdout}"
            )


def render_video(
    *,
    renderer: Renderer,
    props_path: Path,
    out_path: Path,
    audio_duration: float,
    cfg: RenderLoopConfig,
    duration_probe: Callable[[Path], float] = mp4_duration,
    luma_probe: Callable[[Path], float] = sample_frame_luma,
    on_result: Optional[Callable[[Result[Path]], None]] = None,
) -> Path:
    """Run the render ⇄ QA loop and return the path to an acceptable MP4.

    Raises :class:`RenderError` if no attempt passes QA within the bound.
    """
    out_path = Path(out_path)
    state = {"profile": RenderProfile.from_config(cfg), "last_render_error": ""}
    logger = get_logger("pipeline.agent_video")

    def body(attempt: int, last_eval: Optional[Evaluation]) -> Path:
        state["last_render_error"] = ""
        if out_path.exists():
            out_path.unlink()
        try:
            renderer.render(props_path=Path(props_path), out_path=out_path, profile=state["profile"])
        except RenderError as exc:
            state["last_render_error"] = str(exc)
            log_event(
                logger,
                "render_attempt_error",
                loop="L4.render",
                attempt=attempt,
                error=str(exc),
            )
            # A hard render failure leaves no/partial output; QA will mark it fatal
            # and the loop will adapt+retry or abort. Swallow here so the loop owns
            # the control flow uniformly.
            pass
        return out_path

    def evaluate(path: Path) -> Evaluation:
        ev = evaluate_render(
            output_path=path,
            audio_duration=audio_duration,
            cfg=cfg,
            duration_probe=duration_probe,
            luma_probe=luma_probe,
        )
        if state["last_render_error"]:
            ev.violations.append(f"remotion error: {state['last_render_error']}")
            ev.feedback = "; ".join(ev.violations)
            ev.details["remotion_error"] = state["last_render_error"]
        return ev

    def adapt(path: Path, ev: Evaluation) -> None:
        state["profile"] = cheaper_profile(state["profile"])

    def on_exhausted(provisional: Result[Path]) -> Result[Path]:
        ev = provisional.evaluation
        render_error = state.get("last_render_error") or ""
        suffix = f" | last remotion error: {render_error}" if render_error else ""
        raise RenderError(
            f"render failed QA after {provisional.attempts} attempts: "
            f"{ev.feedback if ev else 'no evaluation'}{suffix}"
        )

    result = run_loop(
        "L4.render",
        body=body,
        evaluate=evaluate,
        adapt=adapt,
        on_exhausted=on_exhausted,
        max_iters=cfg.max_attempts,
        logger_name="pipeline.agent_video",
    )
    if on_result is not None:
        on_result(result)
    assert result.artifact is not None
    return result.artifact
