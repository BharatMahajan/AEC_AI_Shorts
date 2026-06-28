"""Tests for agent_publish.py — upload retry + history append-once (plan §13)."""
from __future__ import annotations

import builtins
import sys
from types import ModuleType
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.agent_publish import (
    YouTubeUploader,
    build_video_metadata,
    publish_short,
    upload_with_retries,
)
from pipeline.config import PublishConfig
from pipeline.errors import RetryableError, UploadError
from pipeline.history import History
from pipeline.script_types import Script, ScriptPoint


def _script() -> Script:
    return Script(
        title="Revit automates floorplans",
        hook="What if Revit designed your floorplate?",
        lines=["Forma scores massing.", "Follow for more!"],
        title_variants=["AI in Revit", "Revit + Forma"],
        points=[ScriptPoint("Massing", "Forma scores daylight")],
        description="AI in Revit. #AEC #BIM",
        tags=["revit", "bim"],
        bucket="bim_authoring",
        hook_style="question",
        feature_fingerprint="bim_authoring:generative floorplate layout",
    )


def _cfg(**kw) -> PublishConfig:
    base = dict(max_retries=4, backoff_base=1.0, backoff_cap=10.0)
    base.update(kw)
    return PublishConfig(**base)


def _video(tmp_path, size=200_000) -> Path:
    p = tmp_path / "out.mp4"
    p.write_bytes(b"x" * size)
    return p


class FakeUploader:
    def __init__(self, video_id="vid_abc", fail_times=0):
        self.video_id = video_id
        self.fail_times = fail_times
        self.calls = 0
        self.thumbnail_calls = 0
        self.last_metadata = None

    def upload(self, video_path, metadata):
        self.calls += 1
        self.last_metadata = metadata
        return self.video_id

    def set_thumbnail(self, video_id, thumbnail_path):
        self.thumbnail_calls += 1


# ---- upload_with_retries -------------------------------------------------- #
def test_retry_succeeds_after_transient():
    calls = {"n": 0}
    sleeps = []

    def once():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RetryableError("503")
        return "vid_ok"

    vid = upload_with_retries(once, cfg=_cfg(), sleep=sleeps.append, rng=lambda: 1.0)
    assert vid == "vid_ok"
    assert calls["n"] == 3
    assert sleeps == [1.0, 2.0]  # capped exponential, rng=1.0


def test_retry_exhausts_to_upload_error():
    def once():
        raise RetryableError("always 500")

    with pytest.raises(UploadError):
        upload_with_retries(once, cfg=_cfg(max_retries=3), sleep=lambda d: None)


def test_non_retryable_propagates():
    def once():
        raise ValueError("auth failure")

    with pytest.raises(ValueError):
        upload_with_retries(once, cfg=_cfg(), sleep=lambda d: None)


def test_retry_with_zero_max_retries_raises_immediately():
    with pytest.raises(UploadError, match="after 0 attempts"):
        upload_with_retries(lambda: "vid", cfg=_cfg(max_retries=0), sleep=lambda d: None)


# ---- metadata ------------------------------------------------------------- #
def test_metadata_private_when_review_on():
    md = build_video_metadata(_script(), cfg=_cfg(review_before_publish=True))
    assert md["status"]["privacyStatus"] == "private"
    assert md["snippet"]["categoryId"] == "28"
    assert md["status"]["selfDeclaredMadeForKids"] is False
    assert md["snippet"]["tags"] == ["revit", "bim"]


def test_metadata_public_when_review_off():
    md = build_video_metadata(_script(), cfg=_cfg(review_before_publish=False))
    assert md["status"]["privacyStatus"] == "public"


# ---- publish_short -------------------------------------------------------- #
def test_publish_appends_history_once_after_video_id(tmp_path):
    h = History(tmp_path / "hist.json")
    up = FakeUploader(video_id="vid_xyz")
    entry = publish_short(
        _script(), _video(tmp_path), duration_seconds=52.0,
        uploader=up, cfg=_cfg(), history=h,
        now=datetime(2026, 6, 28, tzinfo=timezone.utc),
    )
    assert entry.video_id == "vid_xyz"
    assert entry.url == "https://youtu.be/vid_xyz"
    stored = h.load()
    assert len(stored) == 1
    assert stored[0].feature_fingerprint == "bim_authoring:generative floorplate layout"
    assert stored[0].duration_seconds == 52.0
    assert stored[0].perf == {}


def test_publish_aborts_and_does_not_append_when_no_video(tmp_path):
    h = History(tmp_path / "hist.json")
    with pytest.raises(UploadError):
        publish_short(
            _script(), tmp_path / "missing.mp4", duration_seconds=52.0,
            uploader=FakeUploader(), cfg=_cfg(), history=h,
        )
    assert h.load() == []  # nothing appended on failure


def test_publish_aborts_on_empty_file(tmp_path):
    h = History(tmp_path / "hist.json")
    empty = tmp_path / "out.mp4"
    empty.write_bytes(b"")
    with pytest.raises(UploadError):
        publish_short(
            _script(), empty, duration_seconds=52.0,
            uploader=FakeUploader(), cfg=_cfg(), history=h,
        )
    assert h.load() == []


def test_publish_thumbnail_best_effort_never_fatal(tmp_path):
    h = History(tmp_path / "hist.json")
    thumb = tmp_path / "thumb.png"
    thumb.write_bytes(b"PNGDATA")

    class ThrowingThumb(FakeUploader):
        def set_thumbnail(self, video_id, thumbnail_path):
            raise RuntimeError("thumbnail api down")

    up = ThrowingThumb()
    entry = publish_short(
        _script(), _video(tmp_path), duration_seconds=40.0,
        uploader=up, cfg=_cfg(), history=h, thumbnail_path=thumb,
    )
    # publish still succeeds + history appended despite thumbnail failure
    assert entry.video_id
    assert len(h.load()) == 1


def test_publish_empty_video_id_raises(tmp_path):
    h = History(tmp_path / "hist.json")
    with pytest.raises(UploadError):
        publish_short(
            _script(), _video(tmp_path), duration_seconds=40.0,
            uploader=FakeUploader(video_id=""), cfg=_cfg(), history=h,
        )
    assert h.load() == []


def test_privacy_honors_yt_privacy_when_review_off():
    md = build_video_metadata(_script(), cfg=_cfg(review_before_publish=False, privacy="unlisted"))
    assert md["status"]["privacyStatus"] == "unlisted"


def test_privacy_review_overrides_to_private():
    md = build_video_metadata(_script(), cfg=_cfg(review_before_publish=True, privacy="public"))
    assert md["status"]["privacyStatus"] == "private"


def test_privacy_invalid_value_falls_back_to_private():
    md = build_video_metadata(_script(), cfg=_cfg(review_before_publish=False, privacy="bogus"))
    assert md["status"]["privacyStatus"] == "private"


def test_youtube_uploader_import_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("google.oauth2") or name.startswith("googleapiclient"):
            raise ImportError("missing google libs")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(UploadError, match="google-api-python-client"):
        YouTubeUploader("id", "secret", "refresh", _cfg())


def test_youtube_uploader_constructor_success(monkeypatch):
    class FakeCredentials:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    built = {}

    def fake_build(service, version, credentials):
        built["service"] = service
        built["version"] = version
        built["credentials"] = credentials
        return object()

    google_pkg = ModuleType("google")
    google_oauth2_pkg = ModuleType("google.oauth2")
    google_oauth2_credentials = ModuleType("google.oauth2.credentials")
    google_oauth2_credentials.Credentials = FakeCredentials

    googleapiclient_pkg = ModuleType("googleapiclient")
    googleapiclient_discovery = ModuleType("googleapiclient.discovery")
    googleapiclient_discovery.build = fake_build

    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.oauth2", google_oauth2_pkg)
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", google_oauth2_credentials)
    monkeypatch.setitem(sys.modules, "googleapiclient", googleapiclient_pkg)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", googleapiclient_discovery)

    up = YouTubeUploader("cid", "csecret", "rtok", _cfg())
    assert up._youtube is not None
    assert built["service"] == "youtube"
    assert built["version"] == "v3"
    assert built["credentials"].kwargs["client_id"] == "cid"
