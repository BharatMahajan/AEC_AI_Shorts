"""Tests for auth/get_token.py pure helpers (no OAuth/network)."""
from __future__ import annotations

import json

from auth.get_token import SCOPES, _read_client, format_env


def test_scopes_include_upload_and_manage():
    assert "https://www.googleapis.com/auth/youtube.upload" in SCOPES
    assert "https://www.googleapis.com/auth/youtube" in SCOPES


def test_read_client_handles_installed(tmp_path):
    p = tmp_path / "client_secret.json"
    p.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
    client = _read_client(p)
    assert client["client_id"] == "cid"
    assert client["client_secret"] == "sec"


def test_read_client_handles_web(tmp_path):
    p = tmp_path / "client_secret.json"
    p.write_text(json.dumps({"web": {"client_id": "wid", "client_secret": "wsec"}}))
    assert _read_client(p)["client_id"] == "wid"


def test_format_env_shape():
    out = format_env({"client_id": "a", "client_secret": "b", "refresh_token": "c"})
    assert out == "YT_CLIENT_ID=a\nYT_CLIENT_SECRET=b\nYT_REFRESH_TOKEN=c\n"
