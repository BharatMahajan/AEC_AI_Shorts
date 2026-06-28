"""errors.py — typed exceptions + a bounded retry/backoff decorator.

The typed exceptions let the orchestrator map failures to deterministic exit
codes and alerts (plan §11). The ``retry`` decorator is the bounded network
loop used by the Publish/LLM/TTS calls; it is itself a §2-compliant loop:
guard = first attempt, body = the call, progress = attempt counter,
termination = success, max-iter = ``max_attempts``, fallback = re-raise.
"""
from __future__ import annotations

import functools
import random
import time
from typing import Callable, Iterable, Type, TypeVar

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# Typed exception hierarchy
# --------------------------------------------------------------------------- #
class PipelineError(Exception):
    """Base for all pipeline errors. Carries a stable ``code`` for exit mapping."""

    code: str = "PIPELINE_ERROR"


class ConfigError(PipelineError):
    code = "CONFIG_ERROR"


class ScriptGenerationError(PipelineError):
    """L2 exhausted attempts below the minimum acceptable score."""

    code = "SCRIPT_GENERATION_ERROR"


class VoiceSynthesisError(PipelineError):
    """L3 could not produce audio meeting the duration/quality gate."""

    code = "VOICE_SYNTHESIS_ERROR"


class RenderError(PipelineError):
    """L4 could not produce a valid MP4 within its bound."""

    code = "RENDER_ERROR"


class UploadError(PipelineError):
    """Publish retry loop exhausted without a video_id."""

    code = "UPLOAD_ERROR"


class LoopExhaustedError(PipelineError):
    """A generic loop hit its max-iteration bound without passing."""

    code = "LOOP_EXHAUSTED"


# Exit-code mapping used by run.py (plan §11: exit codes 0/2/1).
#   0 = success, 2 = clean/typed abort, 1 = unexpected error.
EXIT_OK = 0
EXIT_ABORT = 2
EXIT_UNEXPECTED = 1


def exit_code_for(exc: BaseException | None) -> int:
    if exc is None:
        return EXIT_OK
    if isinstance(exc, PipelineError):
        return EXIT_ABORT
    return EXIT_UNEXPECTED


# --------------------------------------------------------------------------- #
# Bounded retry/backoff decorator
# --------------------------------------------------------------------------- #
class RetryableError(PipelineError):
    """Wraps a transient failure that the retry decorator should retry."""

    code = "RETRYABLE"


def retry(
    max_attempts: int = 5,
    *,
    retry_on: Iterable[Type[BaseException]] = (RetryableError,),
    base: float = 1.0,
    cap: float = 60.0,
    jitter: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
):
    """Capped exponential backoff with optional full jitter.

    Bounded by ``max_attempts`` (>=1). On the final failure the last exception
    is re-raised unchanged so callers can translate it to a typed PipelineError.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            attempt = 0
            retry_on_tuple = tuple(retry_on)
            while True:
                attempt += 1
                try:
                    return fn(*args, **kwargs)
                except retry_on_tuple as exc:
                    if attempt >= max_attempts:
                        raise
                    delay = min(cap, base * (2 ** (attempt - 1)))
                    if jitter:
                        delay = delay * rng()
                    sleep(delay)

        return wrapper

    return decorator
