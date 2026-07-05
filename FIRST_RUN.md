# First-run setup checklist

A short path from clone to a published Short. Steps 1–4 are one-time.

## 0. Security first
Your `.env` holds live secrets and is **gitignored** — never commit it. If any
secret was ever shared in chat/email, **rotate it** (regenerate the Gemini key;
reset the OAuth client secret, which invalidates the refresh token).

## 1. Install toolchains
```bash
# Python (3.11 recommended)
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# Node 20 + Remotion deps + headless browser
cd remotion && npm install && npx remotion browser ensure && cd ..

# ffmpeg (render QA probes) — macOS: brew install ffmpeg | Ubuntu: apt install ffmpeg
```

## 2. Credentials → `.env`
```bash
cp .env.example .env      # then fill in the values
```
- **Gemini key**: https://aistudio.google.com/apikey (free tier).
- **YouTube OAuth** (one-time): in Google Cloud Console enable *YouTube Data API v3*,
  create a **Desktop** OAuth client, and **publish the consent screen to Production**
  (test-mode refresh tokens expire ~7 days). Then exchange the client for a refresh
  token (`auth/get_token.py client_secret.json`) and paste `YT_CLIENT_ID`,
  `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
- Set `REVIEW_BEFORE_PUBLISH=false` and `YT_PRIVACY=public` for fully-automatic
  publishing (leave `REVIEW_BEFORE_PUBLISH=true` to upload private drafts first).

## 3. Verify locally (no upload)
```bash
pytest --cov=pipeline          # 127 tests should pass
cd remotion && npm run typecheck && npm run bundle && cd ..   # TS build-gate

# Dry run: writes build/script.json, voice.mp3, render-props.json, run-report.json
set -a && source .env && set +a
python -m pipeline.run all --no-render --no-upload
```
Inspect `build/run-report.json` — every loop should show a bounded `attempts`
count and an `exit` reason.

## 4. First real publish
```bash
set -a && source .env && set +a
python -m pipeline.run all       # renders + uploads, appends state/scripts_created.json
```
Check the new entry in `state/scripts_created.json` and the video on your channel.

## 5. Automate (GitHub Actions)
1. Push the repo to GitHub.
2. Add each `.env` value as a **repo Secret** (Settings → Secrets and variables → Actions).
   Add `ENABLE_ANALYTICS`, `REVIEW_BEFORE_PUBLISH`, `REMOTION_SCALE`, etc. as **Variables**.
3. Edit the publish window in `.github/workflows/daily-short.yml` (the gate fires at
  `09:00` and `21:00` IST by default) and adjust `TZ`.
4. Run the workflow once manually (**Actions → daily-short → Run workflow**, `force=true`)
   to confirm the full chain, then let the cron take over.

## Troubleshooting
- *9-second video / duration mismatch* → L3/L4 gates already catch this; check
  `build/run-report.json` for the loop that escalated.
- *Token expired after ~7 days* → consent screen still in "Testing"; publish it to
  Production. The weekly `healthcheck` workflow warns you before the daily run breaks.
- *Slow renders on CI* → lower `REMOTION_SCALE` / set `REMOTION_CONCURRENCY=1`.
