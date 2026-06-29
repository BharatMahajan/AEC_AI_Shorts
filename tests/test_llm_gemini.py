"""Tests for the Gemini adapter — keyless paths only (no network/dep)."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from pipeline.config import load_config
from pipeline.errors import ConfigError, RetryableError
from pipeline.llm_gemini import GeminiClient, GeminiJudge, build_llm


def test_build_llm_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert build_llm(load_config()) is None


def test_gemini_client_requires_key():
    with pytest.raises(ConfigError):
        GeminiClient("")


def test_gemini_client_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "google.genai", None)
    with pytest.raises(ConfigError, match="google-genai"):
        GeminiClient("k")


def test_gemini_client_generate_success(monkeypatch):
    class FakeModels:
        def generate_content(self, *, model, contents):
            assert model == "m"
            assert contents == "p"
            return SimpleNamespace(text="  hello  ")

    class FakeClient:
        def __init__(self, api_key):
            assert api_key == "k"
            self.models = FakeModels()

    fake_genai = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    c = GeminiClient("k", model="m")
    assert c.generate("p") == "hello"


def test_gemini_client_generate_retries_and_raises_retryable(monkeypatch):
    class BoomModels:
        def generate_content(self, *, model, contents):
            assert model == "m"
            assert contents == "p"
            raise RuntimeError("transient")

    class FakeClient:
        def __init__(self, api_key):
            assert api_key == "k"
            self.models = BoomModels()

    fake_genai = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    c = GeminiClient("k", model="m")
    with pytest.raises(RetryableError):
        c.generate("p")


def test_gemini_judge_parses_scores():
    class FakeClient:
        def generate(self, _prompt):
            return json.dumps({"clarity": 8, "excitement": 7.5, "accuracy": 9})

    j = GeminiJudge(FakeClient())
    out = j.judge(SimpleNamespace(hook="h", narration="n"))
    assert out == {"clarity": 8.0, "excitement": 7.5, "accuracy": 9.0}


def test_build_llm_uses_configured_model(monkeypatch):
    calls = {}

    class FakeGeminiClient:
        def __init__(self, api_key, model):
            calls["api_key"] = api_key
            calls["model"] = model

    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setattr("pipeline.llm_gemini.GeminiClient", FakeGeminiClient)

    _ = build_llm(load_config())
    assert calls == {"api_key": "abc", "model": "gemini-test"}
