"""agent_publish.py — Agent 4 (publish) and the bounded upload-retry loop (plan §9).

This closes L1 and seeds L0: history is appended **exactly once, and only after a
confirmed ``video_id``** (plan §6 invariant), so a failed upload can never poison
the next run's avoid-list. The upload itself is a bounded retry loop over the
transient YouTube API status codes with capped exponential backoff + jitter.

The actual YouTube client is hidden behind the :class:`Uploader` protocol so the
publish flow — guard, retry, append, thumbnail — is fully testable without
google libraries or network.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from .config import PublishConfig
from .errors import RetryableError, UploadError
from .history import History, HistoryEntry
from .script_types import Script


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #
def build_video_metadata(script: Script, *, cfg: PublishConfig) -> dict[str, Any]:
    """Build the YouTube insert body. Privacy is gated by REVIEW_BEFORE_PUBLISH.

    When review is on, the video is uploaded *private* as an SME-accuracy gate
    for the technical AEC audience (plan §9) — nothing goes public unreviewed.
    """
    # REVIEW_BEFORE_PUBLISH forces a private draft (SME review gate); otherwise
    # honor YT_PRIVACY (public|unlisted|private), defaulting safely to private.
    if cfg.review_before_publish:
        privacy = "private"
    else:
        privacy = cfg.privacy if cfg.privacy in ("public", "unlisted", "private") else "private"
    description = script.description or script.narration
    return {
        "snippet": {
            "title": script.title[:100],
            "description": description,
            "tags": script.tags,
            "categoryId": cfg.category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": cfg.made_for_kids,
        },
    }


# --------------------------------------------------------------------------- #
# Bounded upload retry loop
# --------------------------------------------------------------------------- #
def upload_with_retries(
    upload_once: Callable[[], str],
    *,
    cfg: PublishConfig,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
) -> str:
    """Call ``upload_once`` until it returns a video_id or the bound is hit.

    ``upload_once`` must raise :class:`RetryableError` for transient failures
    (e.g. HTTP 500/502/503/504, socket errors). Any other exception propagates
    immediately. On exhaustion a typed :class:`UploadError` is raised.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, cfg.max_retries + 1):
        try:
            return upload_once()
        except RetryableError as exc:
            last_exc = exc
            if attempt >= cfg.max_retries:
                break
            delay = min(cfg.backoff_cap, cfg.backoff_base * (2 ** (attempt - 1)))
            sleep(delay * rng())
    raise UploadError(f"upload failed after {cfg.max_retries} attempts: {last_exc}")


# --------------------------------------------------------------------------- #
# Uploader protocol + real YouTube implementation
# --------------------------------------------------------------------------- #
class Uploader(Protocol):
    def upload(self, video_path: Path, metadata: dict[str, Any]) -> str:
        """Upload the video and return its video_id."""
        ...

    def set_thumbnail(self, video_id: str, thumbnail_path: Path) -> None:
        ...


class YouTubeUploader:
    """Resumable upload via the YouTube Data API v3 (lazy google import)."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, cfg: PublishConfig):
        self.cfg = cfg
        try:
            from google.oauth2.credentials import Credentials  # deferred
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise UploadError("google-api-python-client not installed") from exc
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        self._youtube = build("youtube", "v3", credentials=creds)

    def upload(self, video_path: Path, metadata: dict[str, Any]) -> str:  # pragma: no cover
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
        request = self._youtube.videos().insert(
            part="snippet,status", body=metadata, media_body=media
        )

        def _once() -> str:
            try:
                response = request.execute()
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                if status in self.cfg.retry_status_codes:
                    raise RetryableError(str(exc)) from exc
                raise UploadError(str(exc)) from exc
            return response["id"]

        return upload_with_retries(_once, cfg=self.cfg)

    def set_thumbnail(self, video_id: str, thumbnail_path: Path) -> None:  # pragma: no cover
        from googleapiclient.http import MediaFileUpload

        self._youtube.thumbnails().set(
            videoId=video_id, media_body=MediaFileUpload(str(thumbnail_path))
        ).execute()


# --------------------------------------------------------------------------- #
# Publish flow (closes L1, seeds L0)
# --------------------------------------------------------------------------- #
def publish_short(
    script: Script,
    video_path: Path,
    *,
    duration_seconds: float,
    uploader: Uploader,
    cfg: PublishConfig,
    history: History,
    thumbnail_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> HistoryEntry:
    """Upload the Short and append its history entry. Returns the appended entry.

    Raises :class:`UploadError` if the video file is missing/empty or the upload
    exhausts retries. In every failure path, history is left untouched.
    """
    video_path = Path(video_path)
    # --- guard: real, non-empty output --- #
    if not video_path.exists() or video_path.stat().st_size == 0:
        raise UploadError(f"no video to publish at {video_path}")

    metadata = build_video_metadata(script, cfg=cfg)
    video_id = uploader.upload(video_path, metadata)  # may raise UploadError
    if not video_id:
        raise UploadError("uploader returned an empty video_id")

    url = f"https://youtu.be/{video_id}"

    # --- best-effort thumbnail (never fatal) --- #
    if thumbnail_path is not None and Path(thumbnail_path).exists():
        try:
            uploader.set_thumbnail(video_id, Path(thumbnail_path))
        except Exception:
            pass

    now = now or datetime.now(timezone.utc)
    entry = HistoryEntry(
        date=now.date().isoformat(),
        bucket=script.bucket,
        feature_fingerprint=script.feature_fingerprint,
        title=script.title,
        title_variants=script.title_variants,
        hook_style=script.hook_style,
        script_lines=script.lines,
        narration=script.narration,
        video_id=video_id,
        url=url,
        published_at=now.isoformat(),
        duration_seconds=round(duration_seconds, 2),
        perf={},  # L0 placeholder; analytics fills this later
    )
    # The closing edge of L1: append happens only here, after a confirmed id.
    history.append(entry)
    return entry
