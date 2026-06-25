# HANDOFF — Last Pirates Twitch Deck (read me first)

You are picking up an in-progress project from a previous Claude Code session. This
document is the full context. Read it top to bottom, then continue from "Where we
are / next steps". The user is **Nikita** (RetroStyleGames, marketing/content).
Communicate in **Russian** (he writes in Russian).

---

## 1. What this is

A self-hosted traffic-analytics dashboard for the Steam/Twitch game **Last Pirates:
Die Together**. It's the **Twitch module** of a larger "GamePlanner-style" traffic
dashboard for the whole marketing campaign. Sibling dashboards (separate projects,
linked from our header):
- RSG Hub (umbrella): https://rsg-hub-two.vercel.app/
- Steam Deck (Sasha's, Steam analytics): https://lpdt-dashboard.vercel.app/
- Another dashboard: https://dashboard-vert-three-28.vercel.app/

Planned future sources for the broader dashboard (not built yet): YouTube (keywords/
hashtags), Steam, Reddit, Twitter, TikTok/Instagram, plus manual-number sources
(GigaCRM, Jestr, Keymailer, Terminus, Lurkit). Nikita owns **Twitch** + website
parsing. This repo currently = Twitch only.

## 2. Live deployment

- **Live site:** https://lp-twitch-deck.vercel.app/
- **GitHub repo:** https://github.com/cmnick-RSG/lp-twitch-deck (public)
- **Vercel:** Hobby plan, under Nikita's account, deploys on git push to `main`.
- Local working dir: `D:\AI Nikita\Traffic Dashboard Project Nikita`

## 3. Stack & architecture

**Python collectors + a static HTML/JS dashboard. No Node/framework.** (Chosen to
match Sasha's existing Python dashboard.)

```
collectors (Python, plain `requests`, NO browser at runtime)
  ├─ sullygnome_collector.py  → channel table (1076 ch) + daily charts + headline metrics
  ├─ collect_streams.py       → SullyGnome per-stream feed (scans recent game window; lags ~1d)
  ├─ collect_recent.py        → hourly (3-day) charts + streamer counts per window
  ├─ collect_videos.py        → TWITCH-FIRST recent streams: Helix /videos?game_id&type=archive
  │                             (recently-ended VODs, fresh to minutes; title/views/dur/thumb/lang)
  └─ enrich_helix.py          → adds Twitch VOD data to the SullyGnome feed (matched by time)
        ↓ writes data/sullygnome/*.csv|json  +  data/twitch/videos_latest.json
build_site_data.py            → consolidates + MERGES streams (Twitch-first spine, SullyGnome
                                grafts viewer depth) → site/public/data.json
site/public/index.html        → the dashboard (vanilla JS + Chart.js CDN, reads data.json)
site/public/assets/           → game-branded web assets (logo, favicon, pirates) via make_assets.py
api/live.py                   → Vercel serverless fn: real-time live Twitch streams (Helix)
```

- **Endpoint discovery** (one-off, needs a browser) lives in `discover_*.py` (Playwright).
  Runtime/CI collectors need NO browser — they call the discovered HTTP endpoints directly.
- `data/` (raw collector output) and `site/public/live.json` are gitignored;
  `site/public/data.json` IS committed (it's what the static site serves).

## 4. Key constants & endpoints (verified)

**SullyGnome** (Twitch history/aggregates; data is theirs, originally from Twitch):
- Game numeric id: **219113** (slug `last_pirates` 404s on sub-paths; numeric id is canonical).
  Game name param: `Last%20Pirates%3A%20Die%20Together`.
- Headers required (else blocked): real browser `User-Agent` + `Referer: https://sullygnome.com/game/last_pirates` + `X-Requested-With: XMLHttpRequest`.
- Charts (data inline in Chart.js config): `https://sullygnome.com/api/charts/linecharts/getconfig/{Chart}/{days}/0/219113/{name}/%20/%20/0/0/%20/0/`
  Charts: `GameChannels`, `GameViewers`, `GameViewerRatio`; pie `GameChannelLanguage`.
  Short windows (e.g. `/3`) return **hourly** points and are fresh to *today*; `/365` is daily.
- Channel table (all streamers): `https://sullygnome.com/api/tables/gametables/getgamechannels/{days}/219113/{name}/0/1/3/desc/{start}/{length}` — `length` capped at 100, recordsTotal=1076 (all-time). Columns incl. `id`(=Twitch-independent SullyGnome channel id), `displayname`, `twitchurl`, `logo`, `language`, `viewminutes`, `streamedminutes`, `maxviewers`, `avgviewers`, `followers`, `partner`.
- Per-stream table (per channel): `https://sullygnome.com/api/tables/channeltables/streams/{days}/{channelid}/%20/1/1/desc/{start}/{length}` — fields incl. `starttime`, `startDateTime`, `length`, `avgviewers`, `maxviewers`, `followergain`, `gamesplayed` (filter rows where it contains "last pirates"), `channellogo`, `viewminutes`. There is **no game-wide stream feed**; we build the feed by scanning the recent-window channels and pulling each one's streams.

**Twitch Helix** (real-time live + real VOD data):
- Twitch game id: **350287257** (≠ SullyGnome's 219113! get via `/helix/games?name=`).
- App access token via client-credentials: `POST https://id.twitch.tv/oauth2/token`.
- `/helix/streams?game_id=350287257` → currently LIVE streams (real-time).
- `/helix/videos?user_id=...&type=archive` → real VOD `url`, `view_count`, `thumbnail_url`, `duration`, `created_at`. We match a VOD to a SullyGnome stream by start time (±90 min).

## 5. Secrets (NEVER commit; all gitignored)

- `.env` in project root holds Twitch keys: `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`
  (created at dev.twitch.tv under Nikita's Twitch account "Last Pirates Traffic Deck",
  Confidential client). The collectors read os.environ first, then `.env`.
- Vercel project has these two as **Environment Variables** (so `/api/live` works in prod).
- **GitHub repo Actions secrets**: add `TWITCH_CLIENT_ID` + `TWITCH_CLIENT_SECRET` so the
  hourly CI job can run `enrich_helix.py` (VOD data). **Nikita still needs to add these** —
  without them the hourly refresh works but skips VOD enrichment (graceful skip).
- `ai-labs-rsg-*.json` = a Google Cloud service-account key (Sasha's, for Google Sheets/CRM
  access — used by the *broader* project, not this Twitch repo). Gitignored. Keep it that way.

## 6. Git / auth gotcha (IMPORTANT)

The machine's git is authenticated as GitHub user **`content-rsg`**, but the repo is owned
by **`cmnick-RSG`** (Nikita's account). A plain `git push` gets 403. Push like this:
```
git remote set-url origin https://cmnick-RSG@github.com/cmnick-RSG/lp-twitch-deck.git   # already set
git -c credential.useHttpPath=true push origin main
```
The hourly GitHub Action also commits `site/public/data.json`, so your pushes will often
hit a **data.json merge conflict on `git pull --rebase`**. Resolve it trivially by
regenerating: `python build_site_data.py` → `git add site/public/data.json` →
`git rebase --continue`. (data.json is generated — just take a fresh build.)

## 7. Run locally

```powershell
# venv already exists at .venv (Python 3.14). If recreating:
python -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r requirements.txt
# refresh data (each needs the prior one; enrich+live need .env):
.\.venv\Scripts\python.exe sullygnome_collector.py
.\.venv\Scripts\python.exe collect_streams.py        # env LP_RECENT_WINDOW (default 7; CI uses 3)
.\.venv\Scripts\python.exe collect_recent.py
.\.venv\Scripts\python.exe enrich_helix.py
.\.venv\Scripts\python.exe collect_live.py           # writes live.json for local preview
.\.venv\Scripts\python.exe build_site_data.py
# serve:
cd site\public ; ..\..\.venv\Scripts\python.exe -m http.server 8123
# open http://127.0.0.1:8123/
```
Playwright (`requirements-dev.txt`) is only for re-discovering endpoints; not needed to run.
To verify UI changes headless, load the page with Playwright and check `pageerror`/screenshot
(the previous session validated every change this way before committing).

## 8. CI / auto-refresh

`.github/workflows/update-data.yml` runs **every 2h** (cron `0 */2 * * *`, and on manual
dispatch): runs all collectors (incl. collect_videos) + enrich + build, commits
`site/public/data.json` → Vercel redeploys. (History: hourly → 6h on 2026-06-25 for free-tier
reliability, then → 2h same day so the Newest feed + per-stream viewer stats stay fresh through
the day. Per-stream peak/avg are SullyGnome-only and only exist once SullyGnome processes a
stream, so freshness there is also bounded by SullyGnome's own lag — Twitch /videos gives the
stream + VOD views instantly regardless.)
- Repo Settings → Actions → Workflow permissions must be **Read and write** (it is — the
  Action has successfully committed).
- Uses `LP_RECENT_WINDOW=3` so the hourly stream scan is light (polite to SullyGnome).

## 9. Hard-won facts / lessons (DON'T relearn these the hard way)

- **VERIFY before claiming.** Nikita strongly dislikes confident-but-wrong statements
  ("не рассказывай сказки"). Before asserting a source can't do X, actually fetch/test the
  endpoint. The previous session was corrected several times for guessing. Triple-check.
- **SullyGnome stream LIST lags** ~a day: it records a stream only *after it ends* + a
  processing delay. BUT its **charts/aggregates are fresh to today** (hourly in short windows).
  So: "what's happening right now/today" → **Live now (Helix)**; recent completed streams →
  SullyGnome (will trail). If "newest streams" looks stale, first check it's not just our
  `data.json` not being refreshed (CI cadence), THEN check SullyGnome's actual freshest via a
  scan — don't assume.
- **VODs expire on Twitch** (1–6 weeks). So we capture VOD url/views/thumbnail via Helix while
  they exist; expired ones show "VOD expired". Persist metrics in our data so they survive.
- **SullyGnome footer says "please do not scrape"** (hobby project, limited resources). The
  team chose to proceed (Option B) but **politely**: throttled requests (`LP_DELAY`), low
  frequency, session reuse. Keep it polite; don't hammer.
- Don't reach for Helix as a lazy default — but DO use it where SullyGnome genuinely can't
  (live now; real VOD links/views/thumbnails). Both are verified-correct uses.
- Windows console can choke on emoji/cyrillic in Python prints — set `PYTHONIOENCODING=utf-8`.

## 10. Current dashboard features (what's built)

Tab order (v4): **Overview** (clickable KPI hero w/ sparklines incl. real-time Live count,
momentum windows, all-time tiles, hourly dual chart, channels-streaming bar, top channels),
**Trends & Analytics** (2nd now; metric × range × granularity × line/bar + 7-pt moving-avg
overlay + stat tiles incl. % change + auto "Read-out" insight), **Live now** (real-time
/api/live), **Top channels**, **All channels** (1076), **Newest streams** (Twitch-first
mini-cards: source badge, thumbnail+duration, prominent name, title, chip row, peak-or-VOD-views
headline, Watch VOD btn), **Regions** (was Languages: 7 region cards w/ share/watch-hrs/channels/
top-lang + doughnut by region + language bars).

v4 design (2026-06-25): game-branded "treasure-dark" theme — gold #f5c451 (primary/signature),
pirate purple #8b5cf6, ember #f0573c; warm-dark surfaces. Real LAST PIRATES logo wordmark +
favicon (captain face) + faint pirates art in header. ALL emoji replaced with inline Lucide SVG
icons. Tabs lazy-render (only Overview at boot) for fast load. Fixed the old `.filters input
{min-width}` bug that detached checkboxes. prefers-reduced-motion respected. Design guided by the
`ui-ux-pro-max-skill` (gitignored local reference; run its search.py for design-system recs).
NOTE: `.gitignore` has `*.png` — assets under site/public/assets/ are force-unignored; keep that.
v4.1: header = game logo + Twitch wordmark + "Analytics"; ALL displayed timestamps are in
**Kyiv time** (`Europe/Kyiv` via the `kyiv()` helper) — stored data stays UTC. Future modules
should display Kyiv time too.

## 11. Where we are / next steps

Done: full Twitch module live & auto-refreshing hourly, v3 UI (pro Trends, dual hourly chart,
sorting everywhere, VOD enrichment, bigger typography, fixed chart tooltips).

2026-06-25 health check: full pipeline verified end-to-end locally (all 5 collectors + build
OK), local Twitch keys valid (VOD enrichment 60/86), live site + `/api/live` healthy, data
refreshed & pushed. Found the scheduled CI had effectively stalled (only 2 lifetime runs,
none on 06-25) → switched cron hourly→6h to improve free-tier reliability.

Open / likely next (confirm priority with Nikita):
1. **Nikita to add the two Twitch secrets to the GitHub repo** (see §5) so the CI refresh
   includes VOD enrichment. STILL PENDING as of 2026-06-25 — the one scheduled run committed
   nothing, so we can't confirm the secrets are set. Verify CI VOD enrichment after the next
   6h run; if missing, that's the cause.
2. Further UI polish if he wants (he pushes hard on "professional analytical tool" quality —
   data density, no tiny text, no grammatical/visual sloppiness, working interactions).
3. **YouTube** module (his next source) — same pattern: a collector writing the same shapes,
   reuse the frontend components.
4. Eventually other sources + the manual-number/CRM tiles (Google Sheets via the service
   account) for the broader dashboard.

Style of work Nikita likes: move fast, actually build & deploy & verify (screenshots/real
data), be honest about limits, and don't make him do manual steps you can do yourself.
