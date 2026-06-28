"""Tests for errors.py — bounded retry/backoff + exit-code mapping (plan §13)."""
from __future__ import annotations

import pytest

from pipeline.errors import (
    EXIT_ABORT,
    EXIT_OK,
    EXIT_UNEXPECTED,
    PipelineError,
    RetryableError,
    UploadError,
    exit_code_for,
    retry,
)


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}
    sleeps: list[float] = []

    @retry(max_attempts=5, sleep=sleeps.append, jitter=False)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RetryableError("transient")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3
    # backoff after attempts 1 and 2: base*2^0, base*2^1
    assert sleeps == [1.0, 2.0]


def test_retry_reraises_after_max_attempts():
    calls = {"n": 0}

    @retry(max_attempts=3, sleep=lambda d: None)
    def always_fails():
        calls["n"] += 1
        raise RetryableError("nope")

    with pytest.raises(RetryableError):
        always_fails()
    assert calls["n"] == 3


def test_retry_does_not_catch_unlisted_exceptions():
    @retry(max_attempts=3, retry_on=(RetryableError,), sleep=lambda d: None)
    def boom():
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        boom()


def test_retry_backoff_is_capped():
    sleeps: list[float] = []

    @retry(max_attempts=6, base=10.0, cap=15.0, jitter=False, sleep=sleeps.append)
    def f():
        raise RetryableError("x")

    with pytest.raises(RetryableError):
        f()
    assert max(sleeps) <= 15.0


def test_retry_rejects_bad_max_attempts():
    with pytest.raises(ValueError):
        retry(max_attempts=0)


def test_exit_code_mapping():
    assert exit_code_for(None) == EXIT_OK
    assert exit_code_for(UploadError("x")) == EXIT_ABORT
    assert exit_code_for(PipelineError("x")) == EXIT_ABORT
    assert exit_code_for(RuntimeError("x")) == EXIT_UNEXPECTED
