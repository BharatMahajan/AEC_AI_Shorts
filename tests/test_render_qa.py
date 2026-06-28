"""Tests for render_qa.py — duration-match + blank-frame gate (plan §13)."""
from __future__ import annotations

from types import SimpleNamespace

from pipeline.config import RenderLoopConfig
from pipeline.render_qa import (
    _resolve_ffmpeg_binary,
    evaluate_render,
    mp4_duration,
    sample_frame_luma,
)


def _cfg(**kw) -> RenderLoopConfig:
    base = dict(duration_tolerance=0.5, min_output_bytes=1000, min_frame_luma=6.0)
    base.update(kw)
    return RenderLoopConfig(**base)


def _good_file(tmp_path, size=200_000):
    p = tmp_path / "out.mp4"
    p.write_bytes(b"x" * size)
    return p


def test_missing_output_is_fatal(tmp_path):
    ev = evaluate_render(
        output_path=tmp_path / "nope.mp4",
        audio_duration=50.0,
        cfg=_cfg(),
        duration_probe=lambda p: 50.0,
        luma_probe=lambda p: 40.0,
    )
    assert not ev.passed
    assert ev.details["fatal"] is True


def test_too_small_is_fatal(tmp_path):
    p = _good_file(tmp_path, size=100)
    ev = evaluate_render(
        output_path=p, audio_duration=50.0, cfg=_cfg(),
        duration_probe=lambda _p: 50.0, luma_probe=lambda _p: 40.0,
    )
    assert ev.details["fatal"] is True
    assert any("too small" in v for v in ev.violations)


def test_passes_when_all_good(tmp_path):
    p = _good_file(tmp_path)
    ev = evaluate_render(
        output_path=p, audio_duration=50.0, cfg=_cfg(),
        duration_probe=lambda _p: 50.2, luma_probe=lambda _p: 40.0,
    )
    assert ev.passed
    assert ev.details["fatal"] is False


def test_duration_mismatch_fails_not_fatal(tmp_path):
    p = _good_file(tmp_path)
    ev = evaluate_render(
        output_path=p, audio_duration=50.0, cfg=_cfg(),
        duration_probe=lambda _p: 47.0, luma_probe=lambda _p: 40.0,
    )
    assert not ev.passed
    assert ev.details["fatal"] is False
    assert any("duration mismatch" in v for v in ev.violations)


def test_blank_frame_fails(tmp_path):
    p = _good_file(tmp_path)
    ev = evaluate_render(
        output_path=p, audio_duration=50.0, cfg=_cfg(),
        duration_probe=lambda _p: 50.0, luma_probe=lambda _p: 1.0,
    )
    assert not ev.passed
    assert any("blank" in v or "black" in v for v in ev.violations)


def test_probe_failure_is_handled(tmp_path):
    p = _good_file(tmp_path)

    def boom(_p):
        raise RuntimeError("ffprobe missing")

    ev = evaluate_render(
        output_path=p, audio_duration=50.0, cfg=_cfg(),
        duration_probe=boom, luma_probe=lambda _p: 40.0,
    )
    assert not ev.passed
    assert any("probe failed" in v for v in ev.violations)


def test_frame_probe_failure_is_handled(tmp_path):
    p = _good_file(tmp_path)

    def boom(_p):
        raise RuntimeError("ffmpeg missing")

    ev = evaluate_render(
        output_path=p, audio_duration=50.0, cfg=_cfg(),
        duration_probe=lambda _p: 50.0, luma_probe=boom,
    )
    assert not ev.passed
    assert any("frame probe failed" in v for v in ev.violations)


def test_sample_frame_luma_parses_colon_format(monkeypatch, tmp_path):
    def fake_run(*_a, **_k):
        return SimpleNamespace(stderr="... YAVG:41.7 ...")

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert sample_frame_luma(tmp_path / "out.mp4") == 41.7


def test_sample_frame_luma_parses_equals_format(monkeypatch, tmp_path):
    def fake_run(*_a, **_k):
        return SimpleNamespace(stderr="lavfi.signalstats.YAVG=38.2")

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert sample_frame_luma(tmp_path / "out.mp4") == 38.2


def test_resolve_ffmpeg_binary_prefers_env_bin(monkeypatch, tmp_path):
    _resolve_ffmpeg_binary.cache_clear()
    bin_dir = tmp_path / "ffbin"
    bin_dir.mkdir()
    exe_name = "ffmpeg.exe" if __import__("os").name == "nt" else "ffmpeg"
    tool = bin_dir / exe_name
    tool.write_text("", encoding="utf-8")

    monkeypatch.setenv("FFMPEG_BIN", str(bin_dir))
    monkeypatch.setattr("shutil.which", lambda _name: None)

    assert _resolve_ffmpeg_binary("ffmpeg") == str(tool)


def test_resolve_ffmpeg_binary_prefers_path_lookup(monkeypatch):
    _resolve_ffmpeg_binary.cache_clear()
    monkeypatch.setattr("shutil.which", lambda _name: "C:/tools/ffprobe.exe")
    assert _resolve_ffmpeg_binary("ffprobe") == "C:/tools/ffprobe.exe"


def test_resolve_ffmpeg_binary_falls_back_to_name(monkeypatch):
    _resolve_ffmpeg_binary.cache_clear()
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", "")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert _resolve_ffmpeg_binary("ffmpeg") == "ffmpeg"


def test_resolve_ffmpeg_env_candidate_missing_falls_through(monkeypatch, tmp_path):
    _resolve_ffmpeg_binary.cache_clear()
    monkeypatch.setenv("FFMPEG_BIN", str(tmp_path / "no-bin"))
    monkeypatch.setenv("LOCALAPPDATA", "")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert _resolve_ffmpeg_binary("ffmpeg") == "ffmpeg"


def test_resolve_ffmpeg_non_windows_skips_winget(monkeypatch):
    _resolve_ffmpeg_binary.cache_clear()
    monkeypatch.setattr("pipeline.render_qa.os.name", "posix")
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert _resolve_ffmpeg_binary("ffprobe") == "ffprobe"


def test_resolve_ffmpeg_windows_missing_package_root_falls_back(monkeypatch, tmp_path):
    _resolve_ffmpeg_binary.cache_clear()
    monkeypatch.setattr("pipeline.render_qa.os.name", "nt")
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "no-localapp"))
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert _resolve_ffmpeg_binary("ffmpeg") == "ffmpeg"


def test_resolve_ffmpeg_windows_empty_candidates_falls_back(monkeypatch, tmp_path):
    _resolve_ffmpeg_binary.cache_clear()
    monkeypatch.setattr("pipeline.render_qa.os.name", "nt")
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    local = tmp_path / "local"
    pkg_root = local / "Microsoft" / "WinGet" / "Packages"
    pkg_root.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert _resolve_ffmpeg_binary("ffmpeg") == "ffmpeg"


def test_mp4_duration_parses_ffprobe_json(monkeypatch, tmp_path):
    def fake_run(cmd, **_kwargs):
        assert cmd[0] == "ffprobe"
        return SimpleNamespace(stdout='{"format":{"duration":"12.34"}}')

    import subprocess

    monkeypatch.setattr("pipeline.render_qa._resolve_ffmpeg_binary", lambda _name: "ffprobe")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert mp4_duration(tmp_path / "out.mp4") == 12.34


