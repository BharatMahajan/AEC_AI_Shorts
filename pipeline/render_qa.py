"""render_qa.py — the L4 verifier (plan §8).

Gates a rendered MP4 on three things: it exists and is non-trivially sized, its
duration matches the audio within tolerance, and a sampled frame is not blank
(guards against the all-black render that GL faults produce). A missing or empty
output is *fatal* — there is nothing to re-render-into-acceptable, so the loop
aborts rather than shipping a broken file.

The duration and luma probes are injected so the loop is testable without ffmpeg
or a real video file.
"""
from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .config import RenderLoopConfig
from .loops import Evaluation


@lru_cache(maxsize=4)
def _resolve_ffmpeg_binary(name: str) -> str:
    """Resolve ffmpeg/ffprobe path across shells (esp. fresh Windows sessions).

    Priority:
    1) current PATH
    2) explicit FFMPEG_BIN env var
    3) common winget install location on Windows
    4) fallback to command name
    """
    found = shutil.which(name)
    if found:
        return found

    env_bin = os.environ.get("FFMPEG_BIN", "").strip()
    if env_bin:
        candidate = Path(env_bin) / (f"{name}.exe" if sys.platform == "win32" else name)
        if candidate.exists():
            return str(candidate)

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            pkg_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
            if pkg_root.exists():
                candidates = sorted(pkg_root.glob(f"**/bin/{name}.exe"), reverse=True)
                if candidates:
                    return str(candidates[0])

    return name


def mp4_duration(path: Path) -> float:
    """True duration of a video in seconds (ffprobe via the ffmpeg toolchain)."""
    import json
    import subprocess

    out = subprocess.run(
        [
            _resolve_ffmpeg_binary("ffprobe"),
            "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def sample_frame_luma(path: Path, *, at_seconds: float = 1.0) -> float:
    """Mean luma (0-255) of a frame sampled at ``at_seconds`` (via ffmpeg).

    Returns the average of the signalstats YAVG over the sampled frame.
    """
    import re
    import subprocess

    proc = subprocess.run(
        [
            _resolve_ffmpeg_binary("ffmpeg"),
            "-ss", str(at_seconds), "-i", str(path), "-vframes", "1",
            "-vf", "signalstats,metadata=print", "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    m = re.search(r"(?:^|\W)YAVG[:=]([\d.]+)", proc.stderr)
    return float(m.group(1)) if m else 0.0


def evaluate_render(
    *,
    output_path: Path,
    audio_duration: float,
    cfg: RenderLoopConfig,
    duration_probe: Callable[[Path], float] = mp4_duration,
    luma_probe: Callable[[Path], float] = sample_frame_luma,
) -> Evaluation:
    output_path = Path(output_path)
    violations: list[str] = []
    fatal = False
    sub: dict[str, float] = {}

    # --- existence + size (fatal) --- #
    if not output_path.exists():
        return Evaluation(
            score=0.0, passed=False, violations=["output missing"],
            feedback="render produced no file", details={"fatal": True},
        )
    size = output_path.stat().st_size
    if size < cfg.min_output_bytes:
        violations.append(f"output too small: {size}B < {cfg.min_output_bytes}B")
        fatal = True
        sub["size"] = 0.0
    else:
        sub["size"] = 30.0

    # --- duration match (40) --- #
    try:
        vdur = duration_probe(output_path)
        delta = abs(vdur - audio_duration)
        if delta <= cfg.duration_tolerance:
            sub["duration"] = 40.0
        else:
            sub["duration"] = max(0.0, 40.0 * (1 - delta / max(audio_duration, 1)))
            violations.append(
                f"duration mismatch: video {vdur:.2f}s vs audio {audio_duration:.2f}s "
                f"(delta {delta:.2f}s > {cfg.duration_tolerance:.2f}s)"
            )
    except Exception as exc:
        sub["duration"] = 0.0
        violations.append(f"duration probe failed: {exc}")

    # --- blank-frame guard (30) --- #
    try:
        luma = luma_probe(output_path)
        if luma >= cfg.min_frame_luma:
            sub["frame"] = 30.0
        else:
            sub["frame"] = 0.0
            violations.append(f"blank/near-black frame: luma {luma:.1f} < {cfg.min_frame_luma}")
    except Exception as exc:
        sub["frame"] = 0.0
        violations.append(f"frame probe failed: {exc}")

    score = sum(sub.values())
    passed = (not violations) and (not fatal)
    return Evaluation(
        score=round(score, 2),
        passed=passed,
        violations=violations,
        feedback="; ".join(violations) if violations else "render ok",
        details={"sub_scores": sub, "fatal": fatal, "size": size},
    )
