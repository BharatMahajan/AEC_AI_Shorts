"""notify.py — best-effort alerting (Slack webhook). Never raises.

Alerts are a side-channel; a failure to alert must never crash a run or mask the
original error (plan §13 "notify never raises"). All paths swallow exceptions.
"""
from __future__ import annotations

from typing import Optional

from .logging_setup import get_logger, log_event

_logger = get_logger("pipeline.notify")


def notify(message: str, *, webhook_url: Optional[str] = None, level: str = "error") -> bool:
    """Post ``message`` to the Slack webhook if configured. Returns success bool.

    Always logs the message locally so alerting failures never lose information.
    """
    log_event(_logger, "notify", level=level, message=message)
    if not webhook_url:
        return False
    try:
        import json
        import urllib.request

        data = json.dumps({"text": f"[{level.upper()}] {message}"}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except Exception as exc:  # never raise
        log_event(_logger, "notify_failed", error=str(exc))
        return False
