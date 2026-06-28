"""logging_setup.py — structured JSON logging.

Every loop iteration emits one structured record (plan §2 "Observability" and
§14). Using JSON lines keeps records machine-parseable for the run-report and
future dashboards without pulling in a heavy logging framework.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Anything attached via logger.info(msg, extra={"fields": {...}})
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Idempotently attach a JSON stdout handler to the root logger."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def log_event(logger: logging.Logger, msg: str, **fields: Any) -> None:
    """Emit a structured event with arbitrary key/value fields."""
    logger.info(msg, extra={"fields": fields})
