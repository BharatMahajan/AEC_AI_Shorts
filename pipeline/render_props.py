"""render_props.py — the typed contract handed from Python to Remotion (plan §4.1).

This is the single boundary between the Python pipeline and the TypeScript
renderer. Python *produces* ``render-props.json``; the Remotion ``Root.tsx`` zod
schema *consumes* it. The two must agree, so the canonical key set lives here as
:data:`REQUIRED_PROP_KEYS` and is asserted against the zod schema by a golden
parity test (plan §13 "Contract").

Crucially, ``durationInFrames`` is derived from the *real* audio duration
measured in L3 — the video length always matches the voice, never a guess.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .agent_voice import VoiceArtifact
from .config import RenderLoopConfig
from .script_types import Script

PROPS_VERSION = 1

# Canonical prop keys (the contract). Order is irrelevant; membership is checked.
REQUIRED_PROP_KEYS: frozenset[str] = frozenset({
    "version", "durationInFrames", "fps", "width", "height", "audioSrc",
    "bucket", "accent", "pattern", "hookStyle", "title", "hook", "captions",
    "points", "flow", "cta",
})


# Per-bucket visual theme: accent colour + background pattern name. Extensible
# alongside the taxonomy; the renderer maps ``pattern`` to a GPU-cheap backdrop.
THEME: dict[str, dict[str, str]] = {
    "bim_authoring":      {"accent": "#4F8DFD", "pattern": "grid"},
    "cad":                {"accent": "#22C7A9", "pattern": "lines"},
    "civil_infra":        {"accent": "#F2A33C", "pattern": "contour"},
    "coordination_clash": {"accent": "#FF5D5D", "pattern": "grid"},
    "project_controls":   {"accent": "#8B7CF6", "pattern": "bars"},
    "reality_capture":    {"accent": "#2DD4BF", "pattern": "dots"},
    "structural":         {"accent": "#E0B341", "pattern": "truss"},
    "mep":                {"accent": "#38BDF8", "pattern": "lines"},
    "transport":          {"accent": "#34D399", "pattern": "lanes"},
    "water_environmental":{"accent": "#3BA7FF", "pattern": "waves"},
    "site_ops":           {"accent": "#FB923C", "pattern": "dots"},
    "docs_specs":         {"accent": "#A78BFA", "pattern": "grid"},
    "gis_planning":       {"accent": "#4ADE80", "pattern": "contour"},
}
_DEFAULT_THEME = {"accent": "#4F8DFD", "pattern": "grid"}

_DEFAULT_CTA = "Follow for daily AEC AI workflows!"


def theme_for(bucket: str) -> dict[str, str]:
    return THEME.get(bucket, _DEFAULT_THEME)


def _derive_cta(script: Script) -> str:
    """Use the script's CTA-bearing last line if present, else a default."""
    for line in reversed(script.lines):
        low = line.lower()
        if any(w in low for w in ("follow", "subscribe", "comment", "save", "share")):
            return line.strip()
    return _DEFAULT_CTA


def build_render_props(
    script: Script,
    voice: VoiceArtifact,
    *,
    cfg: RenderLoopConfig,
    audio_src: str = "voice.mp3",
) -> dict[str, Any]:
    """Build the render-props dict. ``durationInFrames`` follows the real audio."""
    duration_frames = max(1, math.ceil(voice.duration_seconds * cfg.fps))
    theme = theme_for(script.bucket)
    return {
        "version": PROPS_VERSION,
        "durationInFrames": duration_frames,
        "fps": cfg.fps,
        "width": cfg.width,
        "height": cfg.height,
        "audioSrc": audio_src,
        "bucket": script.bucket,
        "accent": theme["accent"],
        "pattern": theme["pattern"],
        "hookStyle": script.hook_style,
        "title": script.title,
        "hook": script.hook,
        "captions": list(voice.captions) if voice.captions else list(script.lines),
        "points": [p.to_dict() for p in script.points],
        "flow": list(script.flow),
        "cta": _derive_cta(script),
    }


def write_render_props(props: dict[str, Any], path: Path) -> None:
    """Validate against the contract, then write JSON."""
    missing = REQUIRED_PROP_KEYS - set(props)
    if missing:
        raise ValueError(f"render props missing required keys: {sorted(missing)}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(props, indent=2), encoding="utf-8")
