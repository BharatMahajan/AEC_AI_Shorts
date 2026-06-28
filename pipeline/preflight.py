"""preflight.py — fail fast on missing credentials before doing real work.

Run at the start of stages that need external services. Kept pure (no I/O beyond
reading the already-loaded config) and returns a list of problems so the caller
decides whether to abort, rather than raising deep inside a stage.
"""
from __future__ import annotations

from .config import Config


def check_preflight(cfg: Config, *, need_llm: bool, need_upload: bool) -> list[str]:
    """Return a list of missing-credential problems ([] means good to go)."""
    problems: list[str] = []
    if need_llm and not cfg.gemini_api_key:
        problems.append("GEMINI_API_KEY is not set (required to write scripts)")
    if need_upload:
        # Upload creds live in env; presence is what we check (values stay secret).
        import os

        for var in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
            if not os.environ.get(var):
                problems.append(f"{var} is not set (required to upload)")
    return problems
