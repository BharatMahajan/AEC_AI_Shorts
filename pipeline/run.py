"""run.py — the orchestrator: sequences L0 → L1 → L2 → L3 → L4 → Publish.

This is the per-run body of L1 (the recurrence loop). It mounts each inner loop
(L2/L3/L4) and threads the L0 learning signal in at the top. Every run emits a
``build/run-report.json`` (plan §14) summarizing each loop's attempts, score and
exit reason — the artifact reviewers inspect to confirm every loop terminated
for a declared reason within its bound.

The agents are injected (``Agents``) so the whole pipeline runs end-to-end in
tests with fakes — no network, no Node, no ffmpeg. ``main()`` builds the real
adapters from config + env.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .agent_publish import build_video_metadata, publish_short
from .agent_script import generate_script
from .agent_video import render_video
from .agent_voice import synthesize_voice
from .analytics import LearningResult, StatsClient, compute_learning
from .config import Config, load_config
from .critic_script import LLMJudge
from .errors import PipelineError, exit_code_for
from .history import History, HistoryEntry
from .logging_setup import get_logger, log_event
from .loops import Result
from .notify import notify
from .render_props import build_render_props, write_render_props
from .render_qa import mp4_duration, sample_frame_luma
from .topic_select import select_topic
from .voice_qa import mp3_duration

_logger = get_logger("pipeline.run")

STAGES = ("script", "voice", "video", "publish", "all")


@dataclass
class Agents:
    """Injectable external dependencies (real adapters in prod, fakes in tests)."""

    llm: Any = None
    synth: Any = None
    renderer: Any = None
    uploader: Any = None
    judge: Optional[LLMJudge] = None
    stats_client: Optional[StatsClient] = None
    voice_probe: Callable[[Path], float] = mp3_duration
    render_duration_probe: Callable[[Path], float] = mp4_duration
    render_luma_probe: Callable[[Path], float] = sample_frame_luma
    # where the renderer expects staticFile() assets (remotion/public)
    render_public_dir: Optional[Path] = None


@dataclass
class RunReport:
    run_id: str
    slot: str
    do_render: bool
    do_upload: bool
    bucket: str = ""
    fingerprint: str = ""
    weights: dict[str, float] = field(default_factory=dict)
    l2: dict[str, Any] = field(default_factory=dict)
    l3: dict[str, Any] = field(default_factory=dict)
    l4: dict[str, Any] = field(default_factory=dict)
    publish: dict[str, Any] = field(default_factory=dict)
    history_appended: bool = False
    errors: list[str] = field(default_factory=list)

    def write(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, default=str), encoding="utf-8")


def _summarize(result: Result) -> dict[str, Any]:
    return {
        "attempts": result.attempts,
        "final_score": result.evaluation.score if result.evaluation else None,
        "exit": result.exit_reason,
    }


def run_pipeline(
    cfg: Config,
    agents: Agents,
    *,
    build_dir: Optional[Path] = None,
    do_render: bool = True,
    do_upload: bool = True,
    stop_after: Optional[str] = None,
    rng: Optional[random.Random] = None,
    now: Optional[datetime] = None,
) -> RunReport:
    """Run one full pipeline pass and return its RunReport.

    Raises a typed :class:`PipelineError` on any stage abort; the report is still
    written (in the ``finally``) so a failed run is just as auditable as a good
    one. ``stop_after`` lets a stage be the final one (run-up-to semantics).
    """
    rng = rng or random.Random()
    now = now or datetime.now(timezone.utc)
    build_dir = Path(build_dir or cfg.build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    import os

    slot = os.environ.get("SLOT_KEY", now.date().isoformat())
    report = RunReport(run_id=run_id, slot=slot, do_render=do_render, do_upload=do_upload)
    history = History(cfg.history_path)

    try:
        # --- L0: learning (safe no-op when disabled) --- #
        learning: LearningResult = compute_learning(
            history, cfg=cfg.analytics, stats_client=agents.stats_client
        )
        report.weights = learning.weights_bucket

        # --- L1: non-repeat topic selection --- #
        topic = select_topic(
            history,
            lookback=cfg.script.dedup_lookback,
            jaccard_max=cfg.script.dedup_jaccard_max,
            weights=learning.weights_bucket,
            weight_floor=cfg.analytics.weight_floor,
            rng=rng,
        )
        report.bucket = topic.bucket
        report.fingerprint = topic.fingerprint
        log_event(_logger, "run_topic", run_id=run_id, bucket=topic.bucket, fp=topic.fingerprint)

        # --- L2: script writer ⇄ critic --- #
        script = generate_script(
            topic,
            llm=agents.llm,
            cfg=cfg.script,
            history=history,
            judge=agents.judge,
            perf_hint=learning.perf_hint,
            rng=rng,
            on_result=lambda r: report.l2.update(_summarize(r)),
        )
        (build_dir / "script.json").write_text(
            json.dumps(script.to_dict(), indent=2), encoding="utf-8"
        )
        if stop_after == "script":
            return report

        # --- L3: voice synth ⇄ QA --- #
        voice_path = build_dir / "voice.mp3"
        voice = synthesize_voice(
            script,
            synth=agents.synth,
            cfg=cfg.voice,
            out_path=voice_path,
            probe=agents.voice_probe,
            on_result=lambda r: report.l3.update(_summarize(r)),
        )
        if stop_after == "voice":
            return report

        # --- render props (the Python↔Remotion contract) --- #
        props = build_render_props(script, voice, cfg=cfg.render)
        write_render_props(props, build_dir / "render-props.json")
        # Make the audio available to the renderer's staticFile() if configured.
        if agents.render_public_dir is not None:
            pub = Path(agents.render_public_dir)
            pub.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(voice_path, pub / "voice.mp3")

        # --- L4: render ⇄ QA --- #
        out_path = build_dir / "out.mp4"
        if do_render:
            render_video(
                renderer=agents.renderer,
                props_path=build_dir / "render-props.json",
                out_path=out_path,
                audio_duration=voice.duration_seconds,
                cfg=cfg.render,
                duration_probe=agents.render_duration_probe,
                luma_probe=agents.render_luma_probe,
                on_result=lambda r: report.l4.update(_summarize(r)),
            )
        else:
            report.l4 = {"exit": "skipped"}
        if stop_after == "video":
            return report

        # --- Publish (closes L1, seeds L0) --- #
        if do_upload:
            entry = publish_short(
                script,
                out_path,
                duration_seconds=voice.duration_seconds,
                uploader=agents.uploader,
                cfg=cfg.publish,
                history=history,
                now=now,
            )
            report.publish = {"video_id": entry.video_id, "url": entry.url}
            report.history_appended = True
        else:
            # Dry-run: emit the would-be history entry (no video_id) for inspection.
            pending = HistoryEntry(
                date=now.date().isoformat(),
                bucket=script.bucket,
                feature_fingerprint=script.feature_fingerprint,
                title=script.title,
                title_variants=script.title_variants,
                hook_style=script.hook_style,
                script_lines=script.lines,
                narration=script.narration,
                duration_seconds=round(voice.duration_seconds, 2),
            )
            (build_dir / "pending-history.json").write_text(
                json.dumps(pending.to_dict(), indent=2), encoding="utf-8"
            )
            report.publish = {"exit": "skipped"}

        return report
    except Exception as exc:  # record, alert, re-raise for exit-code mapping
        report.errors.append(f"{type(exc).__name__}: {exc}")
        notify(f"run {run_id} failed: {exc}", webhook_url=cfg.slack_webhook_url or None)
        raise
    finally:
        report.write(build_dir / "run-report.json")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_real_agents(cfg: Config) -> Agents:  # pragma: no cover - wires real I/O
    from .agent_video import RemotionRenderer
    from .agent_voice import EdgeTTSSynthesizer
    from .analytics import YouTubeStatsClient
    from .llm_gemini import GeminiJudge, build_llm

    import os

    llm = build_llm(cfg)
    judge = GeminiJudge(llm) if (llm and cfg.script.use_llm_judge) else None
    stats = YouTubeStatsClient(cfg.yt_data_api_key) if (cfg.analytics.enabled and cfg.yt_data_api_key) else None

    uploader = None
    if all(os.environ.get(v) for v in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")):
        from .agent_publish import YouTubeUploader

        uploader = YouTubeUploader(
            os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"],
            os.environ["YT_REFRESH_TOKEN"], cfg.publish,
        )

    remotion_dir = cfg.state_dir.parent / "remotion"
    return Agents(
        llm=llm,
        synth=EdgeTTSSynthesizer(),
        renderer=RemotionRenderer(project_dir=remotion_dir),
        uploader=uploader,
        judge=judge,
        stats_client=stats,
        render_public_dir=remotion_dir / "public",
    )


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover - thin CLI shell
    parser = argparse.ArgumentParser(description="AEC AI Shorts pipeline")
    parser.add_argument("stage", nargs="?", default="all", choices=STAGES)
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--build-dir", default=None)
    args = parser.parse_args(argv)

    from .logging_setup import setup_logging

    setup_logging()
    cfg = load_config()

    stop_after = None if args.stage in ("publish", "all") else args.stage
    do_render = not args.no_render and args.stage in ("video", "publish", "all")
    do_upload = not args.no_upload and args.stage in ("publish", "all")

    try:
        agents = _build_real_agents(cfg)
        report = run_pipeline(
            cfg, agents,
            build_dir=Path(args.build_dir) if args.build_dir else None,
            do_render=do_render, do_upload=do_upload, stop_after=stop_after,
        )
        log_event(_logger, "run_complete", run_id=report.run_id, appended=report.history_appended)
        return exit_code_for(None)
    except PipelineError as exc:
        log_event(_logger, "run_aborted", error=str(exc))
        return exit_code_for(exc)
    except Exception as exc:  # noqa: BLE001
        log_event(_logger, "run_crashed", error=str(exc))
        return exit_code_for(exc)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
