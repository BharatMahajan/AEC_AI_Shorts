"""Tests for voice_qa.py — pronunciation + duration/silence gate (plan §13)."""
from __future__ import annotations

import sys
from types import ModuleType

from pipeline.config import VoiceLoopConfig
from pipeline.voice_qa import apply_pronunciations, evaluate_voice, mp3_duration, pronunciation_applied


def _cfg(**kw) -> VoiceLoopConfig:
    return VoiceLoopConfig(**kw)


def test_apply_pronunciations_expands_terms():
    out = apply_pronunciations("Use Civil 3D and Navisworks with BIM.")
    assert "Civil three D" in out
    assert "Navis works" in out
    assert "B I M" in out
    assert "Civil 3D" not in out


def test_pronunciation_applied_check():
    assert pronunciation_applied("Civil three D and Navis works")
    assert not pronunciation_applied("raw Civil 3D survived")


def test_word_boundary_not_overzealous():
    # "3D" inside another token should not be mangled mid-word.
    out = apply_pronunciations("the model3Dfile stays")
    assert "model3Dfile" in out


def test_in_range_passes():
    ev = evaluate_voice(duration=55.0, edge_silence=0.2, text_used="B I M ok", cfg=_cfg())
    assert ev.passed
    assert ev.details["fatal"] is False


def test_too_short_is_fatal():
    ev = evaluate_voice(duration=9.0, edge_silence=0.0, text_used="ok", cfg=_cfg())
    assert not ev.passed
    assert ev.details["fatal"] is True
    assert any("too short" in v for v in ev.violations)


def test_too_long_not_fatal_but_fails():
    ev = evaluate_voice(duration=85.0, edge_silence=0.0, text_used="ok", cfg=_cfg())
    assert not ev.passed
    assert ev.details["fatal"] is False
    assert any("too long" in v for v in ev.violations)


def test_excess_silence_fails():
    ev = evaluate_voice(duration=40.0, edge_silence=3.0, text_used="ok", cfg=_cfg())
    assert not ev.passed
    assert any("silence" in v for v in ev.violations)


def test_unapplied_pronunciation_fails():
    ev = evaluate_voice(
        duration=40.0, edge_silence=0.0, text_used="raw Civil 3D here", cfg=_cfg()
    )
    assert not ev.passed
    assert any("pronunciation" in v for v in ev.violations)


def test_mp3_duration_uses_mutagen_info_length(tmp_path, monkeypatch):
    class FakeMP3:
        def __init__(self, _path):
            self.info = type("Info", (), {"length": 12.5})()

    mutagen_pkg = ModuleType("mutagen")
    mutagen_mp3 = ModuleType("mutagen.mp3")
    mutagen_mp3.MP3 = FakeMP3
    monkeypatch.setitem(sys.modules, "mutagen", mutagen_pkg)
    monkeypatch.setitem(sys.modules, "mutagen.mp3", mutagen_mp3)

    assert mp3_duration(tmp_path / "voice.mp3") == 12.5
