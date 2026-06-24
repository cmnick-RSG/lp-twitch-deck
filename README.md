# Last Pirates — Traffic Deck

Self-hosted traffic-analytics dashboard for **Last Pirates: Die Together**.
First module: **Twitch** (data from SullyGnome). Designed to extend to YouTube,
Steam, Reddit, TikTok, etc. — each source = one collector writing the same
shapes, the frontend reuses the same components.

## Architecture

```
collectors (Python, requests) → data/ → build_site_data.py → site/public/data.json → static site
```

- `sullygnome_collector.py` — channel table (1076 channels) + daily charts + headline metrics
- `collect_streams.py` — recent Last Pirates streams (scans the recent game window)
- `build_site_data.py` — consolidates everything into `site/public/data.json`
- `site/public/index.html` — the dashboard (vanilla JS + Chart.js, reads data.json)

Endpoint discovery (one-off, needs a browser): `discover_*.py` (Playwright).
Runtime collectors need **no browser** — plain HTTPS requests.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe sullygnome_collector.py
.\.venv\Scripts\python.exe collect_streams.py
.\.venv\Scripts\python.exe build_site_data.py
# serve the static site
cd site\public
..\..\.venv\Scripts\python.exe -m http.server 8123
# open http://127.0.0.1:8123/
```

## Deploy (Vercel + GitHub)

1. Push this repo to GitHub.
2. On vercel.com → **Add New → Project → Import** the repo.
   - Framework Preset: **Other**
   - Output Directory: **site/public** (already set in `vercel.json`)
3. Deploy. The site is now live at a `*.vercel.app` URL.
4. Auto-refresh: the GitHub Action `.github/workflows/update-data.yml` runs every
   6 hours, regenerates `site/public/data.json`, and commits it → Vercel redeploys
   automatically. (Enable Actions on the repo; trigger once via **Run workflow**.)

## Secrets

- `.env` (gitignored) holds Twitch Helix keys for the live tier (not yet wired):
  `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`.
- Never commit the Google service-account JSON (gitignored).
