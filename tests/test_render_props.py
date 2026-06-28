"""Tests for render_props.py incl. producer ↔ zod schema parity (plan §13)."""
from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from pipeline.agent_voice import VoiceArtifact
from pipeline.config import RenderLoopConfig
from pipeline.render_props import (
    REQUIRED_PROP_KEYS,
    build_render_props,
    theme_for,
    write_render_props,
)
from pipeline.script_types import Script, ScriptPoint


def _script() -> Script:
    return Script(
        title="Revit automates floorplans",
        hook="What if Revit designed your floorplate?",
        lines=["Forma scores massing options.", "Follow for daily AEC AI tips!"],
        points=[ScriptPoint("Massing", "Forma scores daylight"), ScriptPoint("Clash", "Navisworks ranks")],
        flow=["model", "analyze", "coordinate"],
        bucket="bim_authoring",
        hook_style="question",
        feature_fingerprint="bim_authoring:generative floorplate layout",
    )


def _voice(duration=52.0) -> VoiceArtifact:
    return VoiceArtifact(
        audio_path=Path("voice.mp3"),
        duration_seconds=duration,
        edge_silence=0.0,
        text_used="...",
        voice="en-US-JennyNeural",
        rate="+8%",
        captions=["Forma scores massing options.", "Follow for daily AEC AI tips!"],
    )


def test_props_have_all_required_keys():
    props = build_render_props(_script(), _voice(), cfg=RenderLoopConfig())
    assert set(props) == set(REQUIRED_PROP_KEYS)


def test_duration_frames_follow_audio():
    cfg = RenderLoopConfig()
    props = build_render_props(_script(), _voice(duration=52.0), cfg=cfg)
    assert props["durationInFrames"] == math.ceil(52.0 * cfg.fps)


def test_theme_applied():
    props = build_render_props(_script(), _voice(), cfg=RenderLoopConfig())
    assert props["accent"] == theme_for("bim_authoring")["accent"]


def test_unknown_bucket_uses_default_theme():
    s = _script()
    s.bucket = "unknown-bucket"
    props = build_render_props(s, _voice(), cfg=RenderLoopConfig())
    assert props["accent"] == theme_for("not-present")["accent"]


def test_cta_derived_from_lines():
    props = build_render_props(_script(), _voice(), cfg=RenderLoopConfig())
    assert "Follow" in props["cta"]


def test_cta_falls_back_to_default_when_missing_in_lines():
    s = _script()
    s.lines = ["No CTA phrase here.", "Just factual content."]
    props = build_render_props(s, _voice(), cfg=RenderLoopConfig())
    assert props["cta"] == "Follow for daily AEC AI workflows!"


def test_captions_fallback_to_script_lines_when_voice_has_no_captions():
    v = _voice()
    v.captions = []
    props = build_render_props(_script(), v, cfg=RenderLoopConfig())
    assert props["captions"] == _script().lines


def test_write_rejects_missing_keys(tmp_path):
    with pytest.raises(ValueError):
        write_render_props({"version": 1}, tmp_path / "p.json")


def test_write_then_readable(tmp_path):
    import json

    props = build_render_props(_script(), _voice(), cfg=RenderLoopConfig())
    p = tmp_path / "render-props.json"
    write_render_props(props, p)
    assert json.loads(p.read_text())["bucket"] == "bim_authoring"


def test_python_producer_matches_zod_schema():
    """Golden parity: every key the Python producer emits must exist in the
    Remotion zod schema (and vice-versa). Guards the cross-language contract."""
    schema_path = Path(__file__).resolve().parents[1] / "remotion" / "src" / "schema.ts"
    if not schema_path.exists():
        pytest.skip("remotion/src/schema.ts not available in this checkout")
    text = schema_path.read_text(encoding="utf-8")
    # Extract the ShortPropsSchema object body and its top-level z.<...> keys.
    body = text.split("ShortPropsSchema = z.object({", 1)[1].split("});", 1)[0]
    zod_keys = set(re.findall(r"^\s*([A-Za-z0-9_]+)\s*:", body, re.MULTILINE))
    assert zod_keys == set(REQUIRED_PROP_KEYS), (
        f"contract drift: python-only={set(REQUIRED_PROP_KEYS) - zod_keys}, "
        f"zod-only={zod_keys - set(REQUIRED_PROP_KEYS)}"
    )
