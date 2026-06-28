"""Tests for agent_voice.py — L3 loop with a MOCKED synthesizer (plan §13)."""
from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace

import pytest

from pipeline.agent_voice import EdgeTTSSynthesizer, VoiceArtifact, nudge_rate, synthesize_voice
from pipeline.config import VoiceLoopConfig
from pipeline.errors import RetryableError, VoiceSynthesisError
from pipeline.script_types import Script


def _script() -> Script:
    return Script(
        title="t",
        hook="What if Civil 3D graded the site for you?",
        lines=["Civil 3D automates corridor grading.", "Follow for more!"],
        bucket="civil_infra",
        feature_fingerprint="civil_infra:automated corridor modeling",
    )


class FakeSynth:
    """Writes a stub file and reports a duration driven by the rate string.

    Models reality: a *faster* rate produces a *shorter* clip. The duration is
    looked up from a queue or computed from the rate so we can script behavior.
    """

    def __init__(self, durations):
        # durations: list returned in order, OR a callable(rate)->float
        self._durations = durations
        self.calls = []

    def synth(self, text, *, voice, rate, pitch, volume, out_path):
        from pathlib import Path

        Path(out_path).write_bytes(b"ID3stub")
        self.calls.append({"text": text, "rate": rate})

    def duration_for_call(self, n):
        if callable(self._durations):
            return self._durations(self.calls[n]["rate"])
        return self._durations[n]


def _probe_factory(synth: "FakeSynth"):
    state = {"i": -1}

    def probe(_path):
        state["i"] += 1
        return synth.duration_for_call(state["i"])

    return probe


def _cfg(**kw) -> VoiceLoopConfig:
    base = dict(max_attempts=2, min_seconds=15.0, max_seconds=70.0)
    base.update(kw)
    return VoiceLoopConfig(**base)


def test_nudge_rate():
    assert nudge_rate("+8%", faster=True) == "+20%"
    assert nudge_rate("+8%", faster=False) == "-4%"
    assert nudge_rate("+40%", faster=True) == "+40%"   # clamped
    assert nudge_rate("-40%", faster=False) == "-40%"  # clamped


def test_passes_first_try(tmp_path):
    synth = FakeSynth([50.0])
    art = synthesize_voice(
        _script(), synth=synth, cfg=_cfg(), out_path=tmp_path / "v.mp3",
        probe=_probe_factory(synth),
    )
    assert isinstance(art, VoiceArtifact)
    assert art.duration_seconds == 50.0
    assert art.captions == ["Civil 3D automates corridor grading.", "Follow for more!"]
    # pronunciation applied to spoken text
    assert "Civil three D" in art.text_used
    assert len(synth.calls) == 1


def test_pronunciation_applied_to_synth_input(tmp_path):
    synth = FakeSynth([40.0])
    synthesize_voice(
        _script(), synth=synth, cfg=_cfg(), out_path=tmp_path / "v.mp3",
        probe=_probe_factory(synth),
    )
    assert "Civil 3D" not in synth.calls[0]["text"]


def test_too_short_retries_then_aborts(tmp_path):
    # Both attempts below floor -> VoiceSynthesisError, used full bound.
    synth = FakeSynth([9.0, 10.0])
    with pytest.raises(VoiceSynthesisError):
        synthesize_voice(
            _script(), synth=synth, cfg=_cfg(), out_path=tmp_path / "v.mp3",
            probe=_probe_factory(synth),
        )
    assert len(synth.calls) == 2


def test_adapt_slows_rate_when_too_short(tmp_path):
    # Attempt 1 too short -> adapt slows rate -> attempt 2 in range -> pass.
    synth = FakeSynth([12.0, 45.0])
    art = synthesize_voice(
        _script(), synth=synth, cfg=_cfg(rate="+8%"), out_path=tmp_path / "v.mp3",
        probe=_probe_factory(synth),
    )
    assert art.duration_seconds == 45.0
    # second call used a slower (lower) rate than the first
    assert synth.calls[0]["rate"] == "+8%"
    assert synth.calls[1]["rate"] == "-4%"


def test_too_long_falls_back_when_not_fatal(tmp_path):
    # Over max on every attempt: not fatal -> ships best attempt.
    synth = FakeSynth([85.0, 80.0])
    art = synthesize_voice(
        _script(), synth=synth, cfg=_cfg(), out_path=tmp_path / "v.mp3",
        probe=_probe_factory(synth),
    )
    # best (highest score = closest under) returned; both over but no exception
    assert art.duration_seconds in (85.0, 80.0)


def test_adapt_keeps_rate_when_duration_in_range(tmp_path):
    synth = FakeSynth([40.0, 40.0])
    silence_state = {"i": -1}

    def silence_probe(_path):
        silence_state["i"] += 1
        return [2.0, 0.0][silence_state["i"]]

    art = synthesize_voice(
        _script(),
        synth=synth,
        cfg=_cfg(max_attempts=2, max_edge_silence=1.0, rate="+8%"),
        out_path=tmp_path / "v.mp3",
        probe=_probe_factory(synth),
        silence_probe=silence_probe,
    )
    assert art.duration_seconds == 40.0
    assert synth.calls[0]["rate"] == "+8%"
    assert synth.calls[1]["rate"] == "+8%"


def test_edge_tts_synth_import_error(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "edge_tts":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(VoiceSynthesisError, match="edge-tts"):
        EdgeTTSSynthesizer().synth(
            "hello",
            voice="en-US-JennyNeural",
            rate="+0%",
            pitch="+0Hz",
            volume="+0%",
            out_path=tmp_path / "x.mp3",
        )


def test_edge_tts_synth_success(monkeypatch, tmp_path):
    class FakeCommunicate:
        def __init__(self, *_a, **_k):
            pass

        async def save(self, _path):
            return None

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=FakeCommunicate))
    EdgeTTSSynthesizer().synth(
        "hello",
        voice="en-US-JennyNeural",
        rate="+0%",
        pitch="+0Hz",
        volume="+0%",
        out_path=tmp_path / "x.mp3",
    )


def test_edge_tts_synth_wraps_runtime_errors(monkeypatch, tmp_path):
    class FakeCommunicate:
        def __init__(self, *_a, **_k):
            pass

        async def save(self, _path):
            return None

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=FakeCommunicate))
    def fake_run(coro):
        coro.close()
        raise RuntimeError("net")

    monkeypatch.setattr("asyncio.run", fake_run)

    with pytest.raises(RetryableError):
        EdgeTTSSynthesizer().synth(
            "hello",
            voice="en-US-JennyNeural",
            rate="+0%",
            pitch="+0Hz",
            volume="+0%",
            out_path=tmp_path / "x.mp3",
        )
