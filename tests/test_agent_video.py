"""Tests for agent_video.py — L4 loop with a MOCKED renderer (plan §13)."""
from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.agent_video import (
    RemotionRenderer,
    RenderProfile,
    cheaper_profile,
    render_video,
)
from pipeline.config import RenderLoopConfig
from pipeline.errors import RenderError


class FakeRenderer:
    """Writes a stub MP4 and records the profile used each attempt."""

    def __init__(self, size=200_000):
        self.size = size
        self.profiles = []

    def render(self, *, props_path, out_path, profile):
        self.profiles.append(profile)
        Path(out_path).write_bytes(b"x" * self.size)


def _cfg(**kw) -> RenderLoopConfig:
    base = dict(max_attempts=2, duration_tolerance=0.5, min_output_bytes=1000, min_frame_luma=6.0)
    base.update(kw)
    return RenderLoopConfig(**base)


def _probe_seq(values):
    state = {"i": -1}

    def probe(_p):
        state["i"] += 1
        return values[min(state["i"], len(values) - 1)]

    return probe


def test_cheaper_profile_reduces_cost():
    base = RenderProfile.from_config(_cfg())
    cheap = cheaper_profile(base)
    assert cheap.scale < base.scale
    assert cheap.concurrency == "1"
    assert cheap.gl != base.gl


def test_passes_first_try(tmp_path):
    r = FakeRenderer()
    out = render_video(
        renderer=r,
        props_path=tmp_path / "p.json",
        out_path=tmp_path / "out.mp4",
        audio_duration=50.0,
        cfg=_cfg(),
        duration_probe=lambda _p: 50.1,
        luma_probe=lambda _p: 40.0,
    )
    assert Path(out).exists()
    assert len(r.profiles) == 1


def test_rerenders_with_reduced_cost_then_passes(tmp_path):
    r = FakeRenderer()
    # attempt 1: duration mismatch -> adapt -> attempt 2: good
    out = render_video(
        renderer=r,
        props_path=tmp_path / "p.json",
        out_path=tmp_path / "out.mp4",
        audio_duration=50.0,
        cfg=_cfg(),
        duration_probe=_probe_seq([46.0, 50.0]),
        luma_probe=lambda _p: 40.0,
    )
    assert Path(out).exists()
    assert len(r.profiles) == 2
    # second attempt used a cheaper profile (lower scale)
    assert r.profiles[1].scale < r.profiles[0].scale


def test_aborts_after_cap(tmp_path):
    r = FakeRenderer()
    with pytest.raises(RenderError):
        render_video(
            renderer=r,
            props_path=tmp_path / "p.json",
            out_path=tmp_path / "out.mp4",
            audio_duration=50.0,
            cfg=_cfg(),
            duration_probe=lambda _p: 40.0,  # always mismatched
            luma_probe=lambda _p: 40.0,
        )
    assert len(r.profiles) == 2  # used full bound


def test_render_failure_swallowed_then_aborts(tmp_path):
    class BrokenRenderer:
        def __init__(self):
            self.calls = 0

        def render(self, *, props_path, out_path, profile):
            self.calls += 1
            raise RenderError("GL fault")

    r = BrokenRenderer()
    with pytest.raises(RenderError):
        render_video(
            renderer=r,
            props_path=tmp_path / "p.json",
            out_path=tmp_path / "out.mp4",
            audio_duration=50.0,
            cfg=_cfg(),
            duration_probe=lambda _p: 50.0,
            luma_probe=lambda _p: 40.0,
        )
    assert r.calls == 2  # retried within bound, then aborted


def test_removes_stale_output_before_attempt(tmp_path):
    class BrokenRenderer:
        def render(self, *, props_path, out_path, profile):
            raise RenderError("boom")

    out = tmp_path / "out.mp4"
    out.write_bytes(b"stale")

    with pytest.raises(RenderError):
        render_video(
            renderer=BrokenRenderer(),
            props_path=tmp_path / "p.json",
            out_path=out,
            audio_duration=50.0,
            cfg=_cfg(max_attempts=1),
            duration_probe=lambda _p: 50.0,
            luma_probe=lambda _p: 40.0,
        )

    assert not out.exists()


def test_build_command_has_perf_flags(tmp_path):
    rr = RemotionRenderer(project_dir=tmp_path, composition_id="Short")
    cmd = rr.build_command(
        props_path=tmp_path / "p.json",
        out_path=tmp_path / "out.mp4",
        profile=RenderProfile.from_config(_cfg()),
    )
    joined = " ".join(cmd)
    assert "remotion render Short" in joined
    assert "--scale=" in joined and "--gl=" in joined and "--codec=" in joined


def test_remotion_renderer_maps_oserror_to_render_error(tmp_path, monkeypatch):
    import subprocess

    rr = RemotionRenderer(project_dir=tmp_path, composition_id="Short")

    def _boom(*_a, **_k):
        raise FileNotFoundError("npx not found")

    monkeypatch.setattr(subprocess, "run", _boom)

    with pytest.raises(RenderError, match="failed to start"):
        rr.render(
            props_path=tmp_path / "p.json",
            out_path=tmp_path / "out.mp4",
            profile=RenderProfile.from_config(_cfg()),
        )


def test_build_command_uses_resolved_npx(tmp_path, monkeypatch):
    rr = RemotionRenderer(project_dir=tmp_path, composition_id="Short")

    monkeypatch.setattr("shutil.which", lambda name: "C:/tools/npx.cmd" if name == "npx.cmd" else None)

    cmd = rr.build_command(
        props_path=tmp_path / "p.json",
        out_path=tmp_path / "out.mp4",
        profile=RenderProfile.from_config(_cfg()),
    )

    assert cmd[0] == "C:/tools/npx.cmd"


def test_resolve_npx_falls_back_to_literal_npx(tmp_path, monkeypatch):
    rr = RemotionRenderer(project_dir=tmp_path, composition_id="Short")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert rr._resolve_npx() == "npx"


def test_resolve_npx_on_non_windows_prefers_npx(tmp_path, monkeypatch):
    rr = RemotionRenderer(project_dir=tmp_path, composition_id="Short")
    monkeypatch.setattr("pipeline.agent_video.os.name", "posix")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npx" if name == "npx" else None)
    assert rr._resolve_npx() == "/usr/bin/npx"


def test_remotion_renderer_nonzero_exit_includes_stdio(tmp_path, monkeypatch):
    import subprocess

    rr = RemotionRenderer(project_dir=tmp_path, composition_id="Short")

    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess(args=[], returncode=2, stdout="o", stderr="e")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RenderError, match="exit=2") as exc:
        rr.render(
            props_path=tmp_path / "p.json",
            out_path=tmp_path / "out.mp4",
            profile=RenderProfile.from_config(_cfg()),
        )

    assert "STDERR:" in str(exc.value)
    assert "STDOUT:" in str(exc.value)


def test_remotion_renderer_success_exit_does_not_raise(tmp_path, monkeypatch):
    import subprocess

    rr = RemotionRenderer(project_dir=tmp_path, composition_id="Short")

    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    rr.render(
        props_path=tmp_path / "p.json",
        out_path=tmp_path / "out.mp4",
        profile=RenderProfile.from_config(_cfg()),
    )
