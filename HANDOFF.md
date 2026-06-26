# HANDOFF — Last Pirates Twitch Deck (read me first)

You are picking up an in-progress project from a previous Claude Code session. This
document is the full, CURRENT context. Read it top to bottom, then continue from
"§11 Where we are / next steps". The user is **Nikita** (RetroStyleGames,
marketing/content). Communicate in **Russian** (he writes in Russian).

---

## 1. What this is

A self-hosted traffic-analytics dashboard for the Steam/Twitch game **Last Pirates:
Die Together**. It's the **Twitch module** of a larger "GamePlanner-style" traffic
dashboard for the whole marketing campaign. Sibling dashboards (separate projects,
linked from our header):
- RSG Hub (umbrella): https://rsg-hub-two.vercel.app/
- Steam Deck (Sasha's, Steam analytics): https://lpdt-dashboard.vercel.app/

Planned future sources for the broader dashboard (not built yet): YouTube, Steam,
Reddit, Twitter, TikTok/Instagram, plus manual-number sources (GigaCRM, Jestr,
Keymailer, Terminus, Lurkit). Nikita owns **Twitch** + website parsing. This repo
currently = Twitch only.

## 2. Live deployment

- **Live site:** https://lp-twitch-deck.vercel.app/
- **GitHub repo:** https://github.com/cmnick-RSG/lp-twitch-deck (public)
- **Vercel:** Hobby plan, under Nikita's account, deploys on git push to **`main`**.
- Local working dir: `D:\AI Nikita\Traffic Dashboard Project Nikita`

## 3. Stack & architecture

**Python collectors + a static HTML/JS dashboard. No Node/framework.**

```
collectors (Python, plain `requests`, NO browser at runtime)
  ├─ sullygnome_collector.py  → channel table (1076 ch) + daily charts + headline metrics
  ├─ collect_streams.py       → SullyGnome per-stream feed (scans recent game window; lags ~1d)
  ├─ collect_recent.py        → hourly (3-day) charts + streamer counts per window
  ├─ collect_videos.py        → Helix /videos?game_id&type=archive (recently-ended VODs) → data/twitch/
  ├─ collect_stream_history.py→ snapshots LIVE streams (Helix /streams + /channels/followers + /users)
  │                             → site/public/live_history.json. The real-time spine (see §8).
  └─ enrich_helix.py          → adds Twitch VOD data to the SullyGnome feed (matched by time)
build_site_data.py            → MERGES 3 stream sources by channel+time into site/public/data.json:
                                live_history (live/ended + peak/followers) ∪ Twitch /videos (VOD url/
                                views/dur) ∪ SullyGnome (avg/watch-min/follower-gain). Dedup by
                                stream_id / login+time. Also emits channels, timeseries, languages.
site/public/index.html        → the dashboard (ONE file: vanilla JS + Chart.js CDN, reads data.json)
site/public/assets/           → game-branded web assets (logo, favicon, pirates) via make_assets.py
site/public/milestones.json   → project milestone dates for the Trends timeline (committed)
api/live.py                   → Vercel serverless fn /api/live: real-time live Twitch streams (Helix)
make_assets.py                → one-off: optimizes raw art in "site customization/" → assets/
discover_*.py                 → one-off endpoint discovery (Playwright); NOT needed at runtime
```

**Frontend data flow (3 freshness tiers — important):**
1. **Live now** = `/api/live` serverless (real-time, every page load) — Live tab + overlaid into Newest.
2. **Live history** = `live_history.json` on the **`data` branch** (see §8) read via GitHub raw — gives
   persisted just-ended streams with captured peak/followers, fresh within minutes, NO deploy needed.
3. **Baseline** = `data.json` on `main` (rebuilt every 2h, deployed) — SullyGnome depth + Twitch VODs + channels.
   The frontend `overlayLive()` merges (1)+(2) on top of (3) every 60s.

- `data/` (raw collector output) and `site/public/live.json` are gitignored.
  `site/public/data.json`, `live_history.json`, `milestones.json`, `assets/*` ARE committed.
- `.gitignore` has a blanket `*.png` — `site/public/assets/*.png` are **force-unignored**; keep that.

## 4. Key constants & endpoints (ALL VERIFIED)

**SullyGnome** (Twitch history/aggregates):
- Game numeric id: **219113**. Game name param: `Last%20Pirates%3A%20Die%20Together`.
- Required headers (else blocked): real browser `User-Agent` + `Referer: https://sullygnome.com/game/last_pirates` + `X-Requested-With: XMLHttpRequest`.
- ⚠️ **Day windows must be one of `1 / 3 / 7 / 30 / 90 / 365`** — other values (e.g. 5, 14) return EMPTY.
  collect_streams uses `LP_RECENT_WINDOW` (channels active in N days) + `LP_STREAM_WINDOW` (each channel's
  history). CI uses **7 / 30**. (5/14 silently returned 0 — cost us a debugging round.)
- Charts: `…/api/charts/linecharts/getconfig/{Chart}/{days}/0/219113/{name}/…`. Charts: `GameChannels`,
  `GameViewers`, `GameViewerRatio`; pie `GameChannelLanguage`. Short windows = hourly & fresh to today.
- Channel table: `…/api/tables/gametables/getgamechannels/{days}/219113/{name}/0/1/3/desc/{start}/{length}`
  — length capped 100, recordsTotal=1076 all-time. Cols: id, displayname, twitchurl, logo, language,
  viewminutes, streamedminutes, maxviewers, avgviewers, followers, partner.
- Per-stream (per channel): `…/api/tables/channeltables/streams/{days}/{channelid}/%20/1/1/desc/{start}/{length}`.
  There is NO game-wide stream feed — we scan recent-window channels and pull each one's streams.
- **SullyGnome inherently LAGS ~hours-to-a-day**: it records a stream only AFTER it ends + processing.
  Its charts/aggregates are fresh; its per-stream list is not. So "what just happened" must come from Twitch.

**Twitch Helix** (real-time + VODs + followers) — app token via client-credentials `POST https://id.twitch.tv/oauth2/token`:
- Twitch game id: **350287257** (≠ SullyGnome 219113! via `/helix/games?name=`).
- `/helix/streams?game_id=350287257` → LIVE now (viewer_count, title, language, started_at, thumbnail).
- `/helix/videos?game_id=350287257&type=archive&sort=time` → recently-ENDED VODs game-wide, fresh to minutes
  (url, view_count, duration, thumbnail, title, language). Only exists if the streamer kept the VOD.
- `/helix/channels/followers?broadcaster_id=X` → returns `{total}` **WITH AN APP TOKEN** (no user scope!).
  That's how we show follower counts (like Gameplainer).
- `/helix/users?id=…` → profile_image_url (logo), broadcaster_type (partner/affiliate).
- VODs expire on Twitch (1–6 wks) → capture url/views/thumb while they exist; expired show "no VOD".

## 5. Secrets (NEVER commit; all gitignored)

- `.env` (project root): `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` (dev.twitch.tv, Nikita's app
  "Last Pirates Traffic Deck", Confidential). Collectors read os.environ first, then `.env`.
- **Vercel** Environment Variables: both keys set (so `/api/live` works in prod). ✅
- **GitHub repo Actions secrets**: both keys ADDED & CONFIRMED working (CI VOD enrichment + live capture run). ✅
- A fine-grained **PAT** (Actions:read/write on this repo only) lives in **cron-job.org**, held by Nikita —
  it triggers the workflows (see §8). Not in the repo; Nikita never shares it with the agent.
- `ai-labs-rsg-*.json` = Sasha's Google service-account key (broader project, not this repo). Gitignored. Keep it.

## 6. Git / auth gotcha (IMPORTANT)

Machine git is authed as GitHub user **`content-rsg`**, but the repo is owned by **`cmnick-RSG`**.
Plain `git push` → 403. Always push like this:
```
git -c credential.useHttpPath=true push origin main      # remote already set with cmnick-RSG@
```
Bots commit to `main` (data.json, 2h) and to the **`data` branch** (live_history, every ~5 min), so your
`main` pushes may be rejected (non-fast-forward) by a concurrent bot commit. Pattern that works:
```
git -c credential.useHttpPath=true fetch origin
git rebase origin/main          # if data.json conflicts: python build_site_data.py; git add it; git rebase --continue
git -c credential.useHttpPath=true push origin main
```
A small retry loop around fetch→rebase→push handles the race (the live-snapshot bot no longer touches main,
so races are rarer now — only the 2h data bot).

## 7. Run locally

```powershell
# venv at .venv (Python 3.14). Recreate: python -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONIOENCODING="utf-8"           # Windows console chokes on emoji/cyrillic prints otherwise
$env:LP_RECENT_WINDOW="7"; $env:LP_STREAM_WINDOW="30"
.\.venv\Scripts\python.exe sullygnome_collector.py
.\.venv\Scripts\python.exe collect_streams.py
.\.venv\Scripts\python.exe collect_recent.py
.\.venv\Scripts\python.exe collect_videos.py            # needs .env
.\.venv\Scripts\python.exe collect_stream_history.py    # needs .env (writes live_history.json)
.\.venv\Scripts\python.exe enrich_helix.py              # needs .env
.\.venv\Scripts\python.exe build_site_data.py
# serve: .\.venv\Scripts\python.exe -m http.server 8123 --directory site/public  → http://127.0.0.1:8123/
```
**Verify UI with Playwright** (installed, chromium works) against the local server — load the page, check
`pageerror`/console, screenshot, eval element counts. The Claude_Preview MCP **blocks external images**
(jtvnw logos, twemoji flags) so flags/thumbnails look broken there — use Playwright (real internet) to
verify those. Build a small throwaway `verify*.py`, run, then delete it (don't leave temp files committed).

## 8. CI / auto-refresh (current architecture — READ THIS)

Two GitHub Actions workflows. **GitHub's free-tier `schedule:` is UNRELIABLE here** (often doesn't fire),
so the real trigger is **cron-job.org** hitting the `workflow_dispatch` API with Nikita's PAT:
```
POST https://api.github.com/repos/cmnick-RSG/lp-twitch-deck/actions/workflows/<file>/dispatches
headers: Authorization: Bearer <PAT>, Accept: application/vnd.github+json, X-GitHub-Api-Version: 2022-11-28
body: {"ref":"main"}   (success = HTTP 204)
```
Two cron-job.org jobs: **"LP live snapshot"** every **5 min** → live-snapshot.yml; **"LP full build"** every
**2h** → update-data.yml. GitHub `schedule:` kept as a flaky backup (live=*/10, full=0 */2).

- **`live-snapshot.yml`** (every 5 min): runs ONLY `collect_stream_history.py` and **force-pushes
  `live_history.json` + `live_samples.json` to the `data` branch** (NOT main). Cheap, Twitch-only, no SullyGnome.
- **`update-data.yml`** (every 2h): full pipeline (sullygnome + streams + recent + videos + enrich + build).
  Pulls latest `live_history.json` from the `data` branch (curl raw) before building, then commits
  **`data.json` + `roster.json` to `main`** (no `[skip ci]`).

**Deploy gotchas that cost us debugging rounds (do NOT regress):**
1. ⚠️ **Vercel DEPLOYS EVERY BRANCH BY DEFAULT — including `data`.** The old assumption "Vercel watches only
   main" was WRONG and bit us hard (2026-06-26): the every-5-min `data`-branch snapshots each spawned a
   Preview deployment, which clogged the Hobby build queue (On-Demand Concurrent Builds = off) so that real
   `main` commits stopped deploying for hours. **Fix (in repo):** `vercel.json` →
   `"git": { "deploymentEnabled": { "data": false } }` disables builds for the `data` branch entirely.
   Keep that. (Belt-and-suspenders if it ever regresses: Settings → Git → Ignored Build Step →
   `if [ "$VERCEL_GIT_COMMIT_REF" = "main" ]; then exit 1; else exit 0; fi`.)
2. **Force a production deploy** (when the auto-webhook is stuck/queued): a **Vercel Deploy Hook** for `main`
   (Settings → Git → Deploy Hooks) → `curl -X POST "<hook-url>"` builds main's tip into production, bypassing
   the webhook queue. Verified working 2026-06-26.
3. `[skip ci]` in a commit message makes Vercel skip that commit's deploy — keep main commits WITHOUT it.
4. The frontend reads `live_history.json` + `live_samples.json` from the **`data` branch via
   raw.githubusercontent.com** (CORS=*, ~5-min CDN cache) → live/ended streams + the real-time trend spine
   refresh within minutes with NO Vercel deploy. The Live tab is truly real-time via `/api/live`.

Repo Settings → Actions → Workflow permissions = Read and write (set).

## 9. Hard-won lessons (don't relearn the hard way)

- **VERIFY before claiming.** Nikita strongly dislikes confident-but-wrong ("не рассказывай сказки").
  Fetch/test the actual endpoint before asserting a limit. Triple-check.
- **All displayed timestamps are Kyiv time** (`Europe/Kyiv` via the `kyiv()` helper); stored data stays UTC.
  Future modules should display Kyiv too. (Relative "Xh ago" is tz-agnostic.)
- **Windows has NO flag emoji glyphs** → use **Twemoji PNGs** (`flag()` → jsDelivr `twitter/twemoji@14.0.2`).
  Russian = neutral white flag (1f3f3), never the RU flag (RSG is Ukrainian — political).
- **SullyGnome windows: only 1/3/7/30/90/365** (others return empty). It also lags ~hours-to-a-day.
- **Twitch /videos only returns VODs the streamer kept** → no-VOD streams are invisible UNLESS we catch them
  live (collect_stream_history). A stream that starts AND ends inside a 5-min snapshot gap with no VOD is lost.
- **SullyGnome footer says "please don't scrape"** → stay polite: throttled (`LP_DELAY`), modest windows, session reuse.
- Last Pirates is a **small game** (a handful of streamers/day) — sparse feeds are usually real, not a bug.

## 10. Current dashboard features (v5)

Tabs (in order): **Overview** · **Trends & Analytics** · **Live now** · **Top channels** · **All channels**
· **Newest streams** · **Regions**.

- **Theme:** game-branded "treasure-dark" — gold `#f5c451` (signature), pirate purple `#8b5cf6`, ember
  `#f0573c`, warm-dark surfaces. Header = real LAST PIRATES logo × Twitch wordmark + "Analytics / Live Deck",
  captain favicon, faint pirates art. ALL emoji = inline Lucide SVG icons (flags are the only image emoji).
- **Overview:** clickable KPI hero (sparklines + real-time Live count) · "Live & latest streams" preview ·
  momentum windows · all-time tiles · hourly dual chart · channels-over-time bar · top channels.
- **Trends & Analytics:** metric × range × granularity × line/bar + 7-pt moving avg + stat tiles + auto
  read-out; **milestone timeline** (events from milestones.json overlaid on the daily channels curve via a
  custom Chart.js plugin + legend); **streaming calendar** heatmap; **returning streamers** grid (channels
  with >1 stream in the feed).
- **Newest streams:** Twitch-first mini-cards (thumbnail+duration, big name, title, chip row, peak-or-VOD-views
  headline coloured by magnitude, followers, Watch live/VOD). Filters: search · language · sort · **source**
  (Live / Captured / Twitch VOD / SullyGnome) · with-VOD. Source badges: LIVE(ember) · Captured(green, our
  live capture) · VOD(purple, Twitch archive) · SullyGnome(blue).
- **Top / All channels:** card grids; follower **tier badges colour-coded** (t0<1k grey · t1 1k+ blue ·
  t2 10k+ purple · t3 100k+ gold · t4 1M+ gradient). Stats coloured (watch=gold, peak=magnitude, avg=purple).
- **Regions:** 7 region cards (share/watch-hrs/channels/top-lang) — **clickable → drill-down** (languages in
  region + top channels there) · doughnut by region · language bars. All with country flags.
- **Live now:** real-time `/api/live`, auto-refresh 60s.
- Tabs lazy-render (only Overview at boot). `prefers-reduced-motion` respected.

Design was guided by `ui-ux-pro-max-skill/` (gitignored local reference; run its `scripts/search.py` for
design-system recommendations).

## 11. Where we are / next steps

**Done (v5, 2026-06-26):** full Twitch module live & auto-refreshing reliably (5-min live capture to `data`
branch + 2h full build to `main`, both via cron-job.org). Gameplainer-style live capture with persistence,
followers, peaks. Game-branded redesign. Colorized cards/tiers. Trends & Analytics with milestone timeline,
calendar heatmap, returning streamers. Regions drill-down. Source filter + badges. Kyiv time. Twemoji flags.
Deploy architecture fixed (data branch + no `[skip ci]` on main). SullyGnome backfill (window 7/30).

**Done (v6, 2026-06-26):** (1) **all-time streamer count fixed** — was frozen at 1076 (SullyGnome's 365-day
table is a stale snapshot, even LOWER than its 90-day total). Now a cumulative `site/public/roster.json`
(union of every login ever seen, only grows; seeded 1233); `build_site_data` maintains it, frontend reads it
directly so the real figure shows immediately. (2) **real-time sample spine** — `collect_stream_history`
appends `{t,viewers,channels}` per ~5-min run to `live_samples.json` (data branch); Trends has a "Real-time"
granularity off it (no SullyGnome lag). (3) merged **Channels** tab (Top+All); nav order
Overview·Trends·Live·Newest·Channels·Regions; Regions drill-down under the cards; Twitch restart-duplicates
collapse (≤45 min). (4) Trends metric **overlay** (2nd axis) + Real-time/Hourly/Daily ranges. (5) milestone
timeline + calendar **clamped to the campaign window** (Steam page launch 2026-02-23, added as a milestone);
type-filter chips + roadmap legend with upcoming events. (6) **Fixed the real deploy bug:** Vercel was
auto-deploying the `data` branch (every-5-min snapshots), clogging the Hobby build queue so `main` stopped
deploying for hours — fixed via `vercel.json` `git.deploymentEnabled.data=false`; forced v6 live via a
Deploy Hook (see §8).

**Next:**
1. **Overview deeper rework** — Nikita & team will send screenshots + comments; iterate.
2. **Verify the deploy fix held:** after the next live-snapshot, confirm the `data` branch no longer spawns
   Preview deployments and that `main` 2h-build auto-deploys resume (else use the Deploy Hook / Ignored Build
   Step from §8). Per-region → per-country deeper drill is still open.
3. **YouTube module** (his next source) — same pattern: a collector writing the same shapes, reuse the
   frontend components / tabs.
4. Eventually other sources + manual-number/CRM tiles (Google Sheets via Sasha's service account) for the
   broader dashboard.

**Style Nikita likes:** move fast; actually build & deploy & verify (screenshots/real data); be honest about
limits; don't make him do manual steps you can do yourself; professional analytical-tool quality (data
density, no tiny text, no sloppiness, working interactions). Milestone dates he provided are in
`site/public/milestones.json` and the memory `project-lp-milestones`.
