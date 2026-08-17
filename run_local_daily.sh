#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Daily LOCAL collection runner (residential IP).
#
# Why this exists: SullyGnome blocks the GitHub Actions datacenter IP (HTTP 403),
# so update-data.yml / competitor-scan.yml die on every run. This machine's
# residential IP is allowed, so we run the same pipeline here on a schedule and
# push the refreshed data.json ourselves. Twitch Helix steps still work in CI,
# but we run them here too for a single self-contained refresh.
#
# Invoked by Windows Task Scheduler (see run_local_daily.bat wrapper).
# ---------------------------------------------------------------------------
set -o pipefail
cd "$(dirname "$0")" || exit 1

export $(grep -vE '^#' .env | xargs)                       # TWITCH_CLIENT_ID / SECRET
export LP_RECENT_WINDOW=7 LP_STREAM_WINDOW=30
export PYTHONUTF8=1 PYTHONUNBUFFERED=1

mkdir -p local_runs
LOG="local_runs/$(date +%Y%m%d_%H%M%S).log"
exec >>"$LOG" 2>&1
echo "================ LOCAL RUN $(date -u '+%Y-%m-%d %H:%M UTC') ================"

run(){ echo "----- $1"; python "$1" || echo "WARN: $1 exited $?"; }

# --- dashboard data pipeline (SullyGnome + Twitch Helix) ---
run sullygnome_collector.py
run collect_streams.py
run collect_recent.py
run collect_channel_meta.py
run collect_videos.py
echo "----- pull live_history from data branch"
curl -sfL "https://raw.githubusercontent.com/cmnick-RSG/lp-twitch-deck/data/site/public/live_history.json" \
  -o site/public/live_history.json || echo "[]" > site/public/live_history.json
run enrich_helix.py
echo "----- build_site_data.py"
python build_site_data.py || { echo "FATAL: build_site_data failed"; exit 1; }

# --- commit + push refreshed dashboard data ---
git add site/public/data.json site/public/roster.json site/public/channel_meta.json
if git diff --staged --quiet; then
  echo "no data changes to commit"
else
  git -c user.name=lp-deck-bot -c user.email=actions@users.noreply.github.com \
      commit -m "data: refresh streams (local runner)"
  for i in 1 2 3; do
    git push && break || { echo "push race, rebasing"; git pull --rebase --autostash origin main; }
  done
fi

# --- competitor coverage scan (daily 1-day window -> Google Sheet, no repo write) ---
echo "----- competitor_scan.py (window=1)"
LP_SCAN_WINDOW=1 python competitor_scan.py || echo "WARN: competitor_scan exited $?"

echo "================ DONE $(date -u '+%Y-%m-%d %H:%M UTC') ================"
