"""llm_gemini.py — concrete free-Gemini adapters for the L2 writer and judge.

These implement the ``LLMClient`` and ``LLMJudge`` protocols used by
``agent_script`` / ``critic_script``. The ``google.genai`` import is
deferred to construction time so the rest of the pipeline (and the whole test
suite) imports and runs without the dependency or an API key. Network calls are
wrapped in the bounded retry decorator (plan §2 bounded network loop).
"""
from __future__ import annotations

import importlib
import json
from typing import Optional

from .config import Config
from .errors import ConfigError, RetryableError, retry
from .script_types import Script


class GeminiClient:
    """LLMClient backed by the free Gemini API."""

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        if not api_key:
            raise ConfigError("GEMINI_API_KEY is required for GeminiClient")
        try:
            genai = importlib.import_module("google.genai")  # deferred import
        except ImportError as exc:
            raise ConfigError(
                "google-genai is not installed; `pip install google-genai`"
            ) from exc
        self._client = genai.Client(api_key=api_key)
        self._model_name = model

    @retry(max_attempts=3, retry_on=(RetryableError,))
    def generate(self, prompt: str) -> str:
        try:
            resp = self._client.models.generate_content(model=self._model_name, contents=prompt)
        except Exception as exc:  # transient API/network error -> bounded retry
            raise RetryableError(str(exc)) from exc
        return (getattr(resp, "text", None) or str(resp) or "").strip()


class GeminiJudge:
    """Optional LLM-as-judge; returns clarity/excitement/accuracy in 0-10."""

    def __init__(self, client: GeminiClient):
        self._client = client

    def judge(self, script: Script) -> dict[str, float]:
        prompt = (
            "Rate this AEC YouTube Short script for an audience of practicing "
            "engineers. Return STRICT JSON only: "
            '{"clarity":0-10,"excitement":0-10,"accuracy":0-10}.\n\n'
            f"HOOK: {script.hook}\nNARRATION: {script.narration}"
        )
        raw = self._client.generate(prompt)
        data = json.loads(raw.strip().strip("`"))
        return {k: float(data.get(k, 0)) for k in ("clarity", "excitement", "accuracy")}


def build_llm(cfg: Config) -> Optional[GeminiClient]:
    """Construct a GeminiClient if a key is configured, else None (tests/CI)."""
    if not cfg.gemini_api_key:
        return None
    return GeminiClient(cfg.gemini_api_key, model=cfg.gemini_model)
