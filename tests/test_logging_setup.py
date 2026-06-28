"""Tests for logging_setup.py structured logging behavior."""
from __future__ import annotations

import json
import logging

from pipeline import logging_setup
from pipeline.logging_setup import JsonFormatter, log_event, setup_logging


def test_json_formatter_includes_dict_fields_only():
    fmt = JsonFormatter()

    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hello", (), None)
    rec.fields = {"a": 1}
    out = json.loads(fmt.format(rec))
    assert out["msg"] == "hello"
    assert out["a"] == 1

    rec2 = logging.LogRecord("x", logging.INFO, __file__, 1, "hello", (), None)
    rec2.fields = "not-dict"
    out2 = json.loads(fmt.format(rec2))
    assert "a" not in out2


def test_json_formatter_includes_exception_text():
    fmt = JsonFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), exc_info=True)
        rec.exc_info = __import__("sys").exc_info()
    out = json.loads(fmt.format(rec))
    assert out["msg"] == "failed"
    assert "exc" in out


def test_setup_logging_idempotent_and_log_event_fields(monkeypatch):
    # Reset module-level guard for isolated test execution.
    monkeypatch.setattr(logging_setup, "_CONFIGURED", False)

    setup_logging()
    root = logging.getLogger()
    count1 = len(root.handlers)

    setup_logging()
    count2 = len(root.handlers)
    assert count1 == count2 == 1

    class CaptureLogger:
        def __init__(self):
            self.calls = []

        def info(self, msg, extra=None):
            self.calls.append((msg, extra))

    logger = CaptureLogger()
    log_event(logger, "event", x=1)
    assert logger.calls[0][0] == "event"
    assert logger.calls[0][1] == {"fields": {"x": 1}}
