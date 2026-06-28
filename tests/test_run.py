"""E2E orchestrator tests with fully mocked agents (plan §13 'E2E dry-run')."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.config import Config
from pipeline.errors import ScriptGenerationError, UploadError
from pipeline.history import History
from pipeline.run import Agents, run_pipeline


def _script_json() -> str:
    lines = [
        "Autodesk Forma runs generative design across hundreds of BIM massing options "
        "scoring daylight, area and clash risk inside Revit for engineers and consultants "
        "before a single sheet is drawn on the project.",
        "Navisworks then runs ML prioritized clash detection across structural and MEP "
        "models, grouping clashes by severity so the team resolves the worst corridor "
        "conflicts first instead of chasing every minor clearance issue by hand.",
        "Across the workflow this saves about 40% of coordination time automatically.",
        "Follow for one practical AEC AI workflow every single day!",
    ]
    return json.dumps({
        "title": "Revit automates floorplans",
        "title_variants": ["AI in Revit", "Revit + Forma"],
        "hook": "What if Revit designed your floorplate for you?",
        "lines": lines,
        "points": [
            {"heading": "Generative massing", "detail": "Forma scores daylight automatically"},
            {"heading": "Clash detection", "detail": "Navisworks ranks clashes by severity"},
        ],
        "flow": ["model", "analyze", "coordinate"],
        "description": "AI in Revit and Forma. #AEC #BIM",
        "tags": ["revit", "bim"],
    })


class FakeLLM:
    def __init__(self, response):
        self.response = response

    def generate(self, prompt):
        return self.response


class FakeSynth:
    def synth(self, text, *, voice, rate, pitch, volume, out_path):
        Path(out_path).write_bytes(b"ID3audio")


class FakeRenderer:
    def __init__(self):
        self.calls = 0

    def render(self, *, props_path, out_path, profile):
        self.calls += 1
        Path(out_path).write_bytes(b"x" * 200_000)


class FakeUploader:
    def __init__(self, video_id="vid_e2e"):
        self.video_id = video_id

    def upload(self, video_path, metadata):
        return self.video_id

    def set_thumbnail(self, video_id, thumbnail_path):
        pass


def _cfg(tmp_path) -> Config:
    import os

    os.environ["STATE_DIR"] = str(tmp_path / "state")
    os.environ["BUILD_DIR"] = str(tmp_path / "build")
    os.environ["HISTORY_PATH"] = str(tmp_path / "state" / "scripts_created.json")
    return Config()


def _agents(**kw) -> Agents:
    base = dict(
        llm=FakeLLM(_script_json()),
        synth=FakeSynth(),
        renderer=FakeRenderer(),
        uploader=FakeUploader(),
        voice_probe=lambda _p: 52.0,
        render_duration_probe=lambda _p: 52.0,
        render_luma_probe=lambda _p: 40.0,
    )
    base.update(kw)
    return Agents(**base)


NOW = datetime(2026, 6, 28, 8, 0, tzinfo=timezone.utc)


def test_dry_run_no_render_no_upload(tmp_path):
    cfg = _cfg(tmp_path)
    build = tmp_path / "build"
    report = run_pipeline(
        cfg, _agents(), build_dir=build, do_render=False, do_upload=False, now=NOW,
    )
    # artifacts exist
    assert (build / "script.json").exists()
    assert (build / "voice.mp3").exists()
    assert (build / "render-props.json").exists()
    assert (build / "pending-history.json").exists()
    assert (build / "run-report.json").exists()
    # pending history has the right shape but NO video_id
    pending = json.loads((build / "pending-history.json").read_text())
    assert pending["video_id"] == ""
    assert pending["feature_fingerprint"]
    # loop exit reasons recorded
    assert report.l2["exit"] in ("passed", "fallback_accepted")
    assert report.l3["exit"] in ("passed", "fallback_accepted")
    assert report.l4 == {"exit": "skipped"}
    assert report.publish == {"exit": "skipped"}
    # nothing appended to history on a dry run
    assert History(cfg.history_path).load() == []


def test_full_run_appends_history_once(tmp_path):
    cfg = _cfg(tmp_path)
    build = tmp_path / "build"
    r = FakeRenderer()
    report = run_pipeline(
        cfg, _agents(renderer=r), build_dir=build, do_render=True, do_upload=True, now=NOW,
    )
    assert (build / "out.mp4").exists()
    assert r.calls == 1
    assert report.history_appended is True
    assert report.publish["video_id"] == "vid_e2e"
    entries = History(cfg.history_path).load()
    assert len(entries) == 1
    assert entries[0].video_id == "vid_e2e"
    # run-report records all loop exits
    rep = json.loads((build / "run-report.json").read_text())
    assert rep["l2"]["exit"] and rep["l3"]["exit"] and rep["l4"]["exit"]


def test_stop_after_script(tmp_path):
    cfg = _cfg(tmp_path)
    build = tmp_path / "build"
    run_pipeline(cfg, _agents(), build_dir=build, stop_after="script", do_render=False, do_upload=False, now=NOW)
    assert (build / "script.json").exists()
    assert not (build / "voice.mp3").exists()


def test_stop_after_voice(tmp_path):
    cfg = _cfg(tmp_path)
    build = tmp_path / "build"
    run_pipeline(cfg, _agents(), build_dir=build, stop_after="voice", do_render=False, do_upload=False, now=NOW)
    assert (build / "script.json").exists()
    assert (build / "voice.mp3").exists()
    assert not (build / "render-props.json").exists()


def test_stop_after_video_with_render_skipped(tmp_path):
    cfg = _cfg(tmp_path)
    build = tmp_path / "build"
    report = run_pipeline(
        cfg,
        _agents(),
        build_dir=build,
        stop_after="video",
        do_render=False,
        do_upload=False,
        now=NOW,
    )
    assert (build / "render-props.json").exists()
    assert not (build / "pending-history.json").exists()
    assert report.l4 == {"exit": "skipped"}


def test_render_public_dir_gets_voice_copy(tmp_path):
    cfg = _cfg(tmp_path)
    build = tmp_path / "build"
    public_dir = tmp_path / "remotion-public"

    run_pipeline(
        cfg,
        _agents(render_public_dir=public_dir),
        build_dir=build,
        do_render=False,
        do_upload=False,
        now=NOW,
    )

    assert (public_dir / "voice.mp3").exists()


def test_upload_enabled_with_render_skipped_raises_and_reports(tmp_path):
    cfg = _cfg(tmp_path)
    build = tmp_path / "build"

    with pytest.raises(UploadError):
        run_pipeline(
            cfg,
            _agents(),
            build_dir=build,
            do_render=False,
            do_upload=True,
            now=NOW,
        )

    rep = json.loads((build / "run-report.json").read_text())
    assert rep["errors"]


def test_abort_writes_report_and_does_not_append(tmp_path):
    cfg = _cfg(tmp_path)
    build = tmp_path / "build"
    # LLM returns invalid JSON every time -> L2 aborts.
    with pytest.raises(ScriptGenerationError):
        run_pipeline(
            cfg, _agents(llm=FakeLLM("not json")), build_dir=build,
            do_render=False, do_upload=False, now=NOW,
        )
    # report still written (auditable failure), history untouched
    assert (build / "run-report.json").exists()
    rep = json.loads((build / "run-report.json").read_text())
    assert rep["errors"]
    assert History(cfg.history_path).load() == []
