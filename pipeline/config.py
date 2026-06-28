"""config.py — single source of truth for every loop bound and threshold.

Per the plan (§2 global rule): "No loop may be unbounded." Every max-iteration
bound, quality threshold and timing limit lives here so behavior can be retuned
with zero code change (env vars / CI Variables override defaults).

Every env-derived field uses ``default_factory`` so its value is read when the
config is *constructed* (``load_config()``), not once at import time. That is
what makes CI Variables / env overrides take effect at runtime and keeps the
module trivially testable (monkeypatch env, call ``load_config()``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_str(key: str, default: str) -> str:
    val = os.environ.get(key)
    return val if val not in (None, "") else default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "y")


# Repo root = two levels up from this file (pipeline/config.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_STATE_DIR = REPO_ROOT / "state"
_DEFAULT_BUILD_DIR = REPO_ROOT / "build"
_DEFAULT_HISTORY = _DEFAULT_STATE_DIR / "scripts_created.json"


# L2 — Script generate <-> critique loop
@dataclass(frozen=True)
class ScriptLoopConfig:
    max_attempts: int = field(default_factory=lambda: _env_int("SCRIPT_MAX_ATTEMPTS", 3))
    pass_threshold: float = field(default_factory=lambda: _env_float("SCRIPT_PASS_THRESHOLD", 80.0))
    min_acceptable: float = field(default_factory=lambda: _env_float("SCRIPT_MIN_ACCEPTABLE", 65.0))
    min_words: int = field(default_factory=lambda: _env_int("SCRIPT_MIN_WORDS", 110))
    max_words: int = field(default_factory=lambda: _env_int("SCRIPT_MAX_WORDS", 150))
    min_aec_terms: int = field(default_factory=lambda: _env_int("SCRIPT_MIN_AEC_TERMS", 4))
    dedup_lookback: int = field(default_factory=lambda: _env_int("SCRIPT_DEDUP_LOOKBACK", 30))
    dedup_jaccard_max: float = field(
        default_factory=lambda: _env_float("SCRIPT_DEDUP_JACCARD_MAX", 0.6)
    )
    use_llm_judge: bool = field(default_factory=lambda: _env_bool("SCRIPT_USE_LLM_JUDGE", False))


# L3 — Voice QA loop
@dataclass(frozen=True)
class VoiceLoopConfig:
    max_attempts: int = field(default_factory=lambda: _env_int("VOICE_MAX_ATTEMPTS", 2))
    min_seconds: float = field(default_factory=lambda: _env_float("MIN_AUDIO_SECONDS", 15.0))
    max_seconds: float = field(default_factory=lambda: _env_float("MAX_AUDIO_SECONDS", 70.0))
    max_edge_silence: float = field(
        default_factory=lambda: _env_float("MAX_EDGE_SILENCE_SECONDS", 1.5)
    )
    voice: str = field(default_factory=lambda: _env_str("TTS_VOICE", "en-US-JennyNeural"))
    voice_alt: str = field(default_factory=lambda: _env_str("TTS_VOICE_ALT", "en-US-AriaNeural"))
    rate: str = field(default_factory=lambda: _env_str("TTS_RATE", "+8%"))
    pitch: str = field(default_factory=lambda: _env_str("TTS_PITCH", "+6Hz"))
    volume: str = field(default_factory=lambda: _env_str("TTS_VOLUME", "+10%"))


# L4 — Render quality-gate loop
@dataclass(frozen=True)
class RenderLoopConfig:
    max_attempts: int = field(default_factory=lambda: _env_int("RENDER_MAX_ATTEMPTS", 2))
    duration_tolerance: float = field(
        default_factory=lambda: _env_float("RENDER_DURATION_TOLERANCE", 0.5)
    )
    min_output_bytes: int = field(
        default_factory=lambda: _env_int("RENDER_MIN_OUTPUT_BYTES", 50000)
    )
    min_frame_luma: float = field(default_factory=lambda: _env_float("RENDER_MIN_FRAME_LUMA", 6.0))
    width: int = field(default_factory=lambda: _env_int("RENDER_WIDTH", 1080))
    height: int = field(default_factory=lambda: _env_int("RENDER_HEIGHT", 1920))
    fps: int = field(default_factory=lambda: _env_int("RENDER_FPS", 30))
    concurrency: str = field(default_factory=lambda: _env_str("REMOTION_CONCURRENCY", "cpu-1"))
    scale: float = field(default_factory=lambda: _env_float("REMOTION_SCALE", 0.75))
    jpeg_quality: int = field(default_factory=lambda: _env_int("JPEG_QUALITY", 68))
    codec: str = field(default_factory=lambda: _env_str("CODEC", "h264"))
    crf: int = field(default_factory=lambda: _env_int("CRF", 24))
    x264_preset: str = field(default_factory=lambda: _env_str("X264_PRESET", "veryfast"))
    pixel_format: str = field(default_factory=lambda: _env_str("PIXEL_FORMAT", "yuv420p"))
    audio_codec: str = field(default_factory=lambda: _env_str("AUDIO_CODEC", "aac"))
    gl: str = field(default_factory=lambda: _env_str("REMOTION_GL", "swangle"))


# Publish — bounded upload-retry loop
@dataclass(frozen=True)
class PublishConfig:
    max_retries: int = field(default_factory=lambda: _env_int("UPLOAD_MAX_RETRIES", 5))
    backoff_base: float = field(default_factory=lambda: _env_float("UPLOAD_BACKOFF_BASE", 1.0))
    backoff_cap: float = field(default_factory=lambda: _env_float("UPLOAD_BACKOFF_CAP", 60.0))
    category_id: str = field(default_factory=lambda: _env_str("YT_CATEGORY_ID", "28"))
    review_before_publish: bool = field(
        default_factory=lambda: _env_bool("REVIEW_BEFORE_PUBLISH", True)
    )
    made_for_kids: bool = field(default_factory=lambda: _env_bool("YT_MADE_FOR_KIDS", False))
    privacy: str = field(default_factory=lambda: _env_str("YT_PRIVACY", "public"))
    retry_status_codes: tuple = (500, 502, 503, 504)


# L0 — Learning loop (analytics)
@dataclass(frozen=True)
class AnalyticsConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("ENABLE_ANALYTICS", False))
    min_uploads: int = field(default_factory=lambda: _env_int("ANALYTICS_MIN_UPLOADS", 5))
    lookback: int = field(default_factory=lambda: _env_int("ANALYTICS_LOOKBACK", 30))
    weight_floor: float = field(default_factory=lambda: _env_float("ANALYTICS_WEIGHT_FLOOR", 0.25))


@dataclass(frozen=True)
class Config:
    script: ScriptLoopConfig = field(default_factory=ScriptLoopConfig)
    voice: VoiceLoopConfig = field(default_factory=VoiceLoopConfig)
    render: RenderLoopConfig = field(default_factory=RenderLoopConfig)
    publish: PublishConfig = field(default_factory=PublishConfig)
    analytics: AnalyticsConfig = field(default_factory=AnalyticsConfig)

    gemini_api_key: str = field(default_factory=lambda: _env_str("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: _env_str("GEMINI_MODEL", "gemini-2.5-flash"))
    yt_data_api_key: str = field(default_factory=lambda: _env_str("YT_DATA_API_KEY", ""))
    slack_webhook_url: str = field(default_factory=lambda: _env_str("SLACK_WEBHOOK_URL", ""))

    state_dir: Path = field(
        default_factory=lambda: Path(_env_str("STATE_DIR", str(_DEFAULT_STATE_DIR)))
    )
    build_dir: Path = field(
        default_factory=lambda: Path(_env_str("BUILD_DIR", str(_DEFAULT_BUILD_DIR)))
    )
    history_path: Path = field(
        default_factory=lambda: Path(_env_str("HISTORY_PATH", str(_DEFAULT_HISTORY)))
    )


def load_config() -> Config:
    """Build a fresh Config from the current environment."""
    return Config()
