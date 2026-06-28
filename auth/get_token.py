"""auth/get_token.py — one-time OAuth bootstrap for the YouTube Data API.

Exchanges a **Desktop** OAuth client (`client_secret.json` downloaded from Google
Cloud Console) for a long-lived refresh token, then prints the three values to
paste into ``.env`` (or add as GitHub repo Secrets):

    YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN

Run once on a machine with a browser:

    python auth/get_token.py client_secret.json
    # headless / SSH? add --no-browser and follow the printed URL

Prerequisites (see FIRST_RUN.md):
  * YouTube Data API v3 enabled
  * OAuth consent screen published to **Production** (test-mode refresh tokens
    expire ~7 days — the #1 cause of the daily pipeline silently dying)

The google library import is deferred so importing this module (e.g. in tests)
needs no dependency.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Upload + manage (thumbnails) scopes.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def _read_client(client_secret_path: Path) -> dict:
    data = json.loads(Path(client_secret_path).read_text(encoding="utf-8"))
    # Desktop clients nest under "installed"; web under "web".
    return data.get("installed") or data.get("web") or data


def mint_refresh_token(client_secret_path: Path, *, no_browser: bool = False) -> dict[str, str]:
    """Run the OAuth flow and return {client_id, client_secret, refresh_token}."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "google-auth-oauthlib not installed; `pip install -r requirements.txt`"
        ) from exc

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), scopes=SCOPES)
    # access_type=offline + prompt=consent forces a refresh_token to be issued.
    if no_browser:  # pragma: no cover - interactive
        creds = flow.run_console()
    else:  # pragma: no cover - interactive
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    if not creds.refresh_token:  # pragma: no cover
        raise SystemExit(
            "No refresh_token returned. Revoke prior access at "
            "https://myaccount.google.com/permissions and retry with a published "
            "(Production) consent screen."
        )

    client = _read_client(client_secret_path)
    return {
        "client_id": client.get("client_id", creds.client_id or ""),
        "client_secret": client.get("client_secret", creds.client_secret or ""),
        "refresh_token": creds.refresh_token,
    }


def format_env(values: dict[str, str]) -> str:
    return (
        f"YT_CLIENT_ID={values['client_id']}\n"
        f"YT_CLIENT_SECRET={values['client_secret']}\n"
        f"YT_REFRESH_TOKEN={values['refresh_token']}\n"
    )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - interactive shell
    parser = argparse.ArgumentParser(description="Mint a YouTube refresh token")
    parser.add_argument("client_secret", help="path to the Desktop client_secret.json")
    parser.add_argument("--no-browser", action="store_true", help="use console flow (headless)")
    args = parser.parse_args(argv)

    values = mint_refresh_token(Path(args.client_secret), no_browser=args.no_browser)
    print("\n# ---- paste into .env (and add as GitHub repo Secrets) ----")
    print(format_env(values))
    print("# Keep these secret. Rotate if ever exposed.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
