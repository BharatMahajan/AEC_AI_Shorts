"""healthcheck.py — weekly liveness probe (plan §11).

Catches the two slow failures that silently break a daily pipeline: the YouTube
OAuth refresh token expiring (~7 days in test mode) and the LLM key going dead.
Returns a structured report; the CLI maps failures to a non-zero exit + alert.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .config import Config
from .logging_setup import get_logger, log_event

_logger = get_logger("pipeline.healthcheck")


@dataclass
class HealthReport:
    checks: dict[str, bool] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return all(self.checks.values()) if self.checks else False


def run_healthcheck(
    cfg: Config,
    *,
    llm_probe: Optional[callable] = None,
    token_probe: Optional[callable] = None,
) -> HealthReport:
    """Run liveness probes. Probes are injected so this is testable offline."""
    report = HealthReport()

    if llm_probe is not None:
        try:
            report.checks["llm"] = bool(llm_probe())
        except Exception as exc:
            report.checks["llm"] = False
            report.errors["llm"] = str(exc)

    if token_probe is not None:
        try:
            report.checks["youtube_token"] = bool(token_probe())
        except Exception as exc:
            report.checks["youtube_token"] = False
            report.errors["youtube_token"] = str(exc)

    log_event(_logger, "healthcheck", checks=report.checks, errors=report.errors)
    return report


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover - CLI shell
    """Build real probes, run the healthcheck, alert + non-zero exit on failure."""
    from .llm_gemini import build_llm
    from .notify import notify

    cfg = Config()

    def llm_probe() -> bool:
        llm = build_llm(cfg)
        if llm is None:
            raise RuntimeError("no GEMINI_API_KEY")
        return bool(llm.generate("Reply with the single word OK."))

    def token_probe() -> bool:
        import os

        from .agent_publish import YouTubeUploader

        YouTubeUploader(
            os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"],
            os.environ["YT_REFRESH_TOKEN"], cfg.publish,
        )
        return True

    report = run_healthcheck(cfg, llm_probe=llm_probe, token_probe=token_probe)
    if not report.healthy:
        notify(f"healthcheck failed: {report.errors}", webhook_url=cfg.slack_webhook_url or None)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
