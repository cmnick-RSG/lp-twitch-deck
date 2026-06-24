"""
SullyGnome collector for Last Pirates: Die Together (Twitch stats).

Pulls, once per run (intended to run daily via Vercel Cron / GitHub Actions):
  1. Daily trend charts  (channels/day, viewers/day, viewer-ratio, languages)
  2. Full per-channel table (all ~1076 channels that streamed the game)
  3. Derived headline metrics (total streamers, stream-hours, watch-hours, ...)

Runtime needs NO browser — plain `requests` against SullyGnome's internal API
(endpoints were discovered once with Playwright; see discover_*.py).

Politeness: paginated table requests are throttled (DELAY_SECONDS) and a single
session is reused. Run at most a few times/day.

Outputs (under data/sullygnome/):
  channels_latest.csv / channels_<date>.csv   - full per-channel rows
  timeseries_channels.csv / _viewers.csv ...   - daily trend points
  languages_latest.json                        - language split
  metrics_snapshot.csv                         - long-format headline metrics
  run_meta.json                                - last run info
"""
from __future__ import annotations

import csv
import json
import time
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
GAME_ID = 219113
GAME_NAME_ENC = "Last%20Pirates%3A%20Die%20Together"
DAYS = 365                      # SullyGnome free-tier window cap
PAGE_SIZE = 100                 # server caps table `length` at 100
DELAY_SECONDS = 2.5             # polite pause between paginated requests
SOURCE = "twitch_sullygnome"

OUT_DIR = Path(__file__).parent / "data" / "sullygnome"

API_CHART = "https://sullygnome.com/api/charts/linecharts/getconfig"
API_PIE = "https://sullygnome.com/api/charts/piecharts/getconfig"
API_TABLE = "https://sullygnome.com/api/tables/gametables/getgamechannels"

REFERER = f"https://sullygnome.com/game/last_pirates/{DAYS}/watched"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/148.0.0.0 Safari/537.36"),
    "Referer": REFERER,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NOW_ISO = datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# HTTP helper (retry + backoff, no hammering)
# --------------------------------------------------------------------------- #
def fetch_json(session: requests.Session, url: str, tries: int = 3) -> dict:
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        wait = DELAY_SECONDS * attempt
        print(f"   retry {attempt}/{tries} after {wait:.1f}s ({last_err})")
        time.sleep(wait)
    raise RuntimeError(f"failed to fetch {url}: {last_err}")


# --------------------------------------------------------------------------- #
# Collectors
# --------------------------------------------------------------------------- #
def chart_url(name: str, pie: bool = False) -> str:
    base = API_PIE if pie else API_CHART
    if pie:
        return f"{base}/{name}/{DAYS}/{GAME_ID}/{GAME_NAME_ENC}/%20/%20/0/0/%20/0/"
    return f"{base}/{name}/{DAYS}/0/{GAME_ID}/{GAME_NAME_ENC}/%20/%20/0/0/%20/0/"


def get_timeseries(session: requests.Session, chart: str) -> list[dict]:
    cfg = fetch_json(session, chart_url(chart))
    data = cfg.get("data", {})
    labels = data.get("labels", [])
    dsets = data.get("datasets", [])
    values = dsets[0].get("data", []) if dsets else []
    return [{"date": lbl, "value": val} for lbl, val in zip(labels, values)]


def get_languages(session: requests.Session) -> dict:
    cfg = fetch_json(session, chart_url("GameChannelLanguage", pie=True))
    data = cfg.get("data", {})
    labels = data.get("labels", [])
    dsets = data.get("datasets", [])
    values = dsets[0].get("data", []) if dsets else []
    return {lbl: val for lbl, val in zip(labels, values)}


def get_all_channels(session: requests.Session) -> list[dict]:
    """Paginate the channel table politely until all rows are collected."""
    rows: list[dict] = []
    start = 0
    total = None
    while True:
        url = (f"{API_TABLE}/{DAYS}/{GAME_ID}/{GAME_NAME_ENC}"
               f"/0/1/3/desc/{start}/{PAGE_SIZE}")
        payload = fetch_json(session, url)
        if total is None:
            total = payload.get("recordsTotal", 0)
            print(f"   recordsTotal = {total}")
        batch = payload.get("data", [])
        rows.extend(batch)
        print(f"   fetched {len(rows)}/{total}")
        start += PAGE_SIZE
        if not batch or start >= total:
            break
        time.sleep(DELAY_SECONDS)  # politeness between pages
    return rows


# --------------------------------------------------------------------------- #
# Derive headline metrics from the channel table
# --------------------------------------------------------------------------- #
def build_summary(channels: list[dict], languages: dict,
                  ts_viewers: list[dict]) -> dict:
    total_stream_min = sum(c.get("streamedminutes") or 0 for c in channels)
    total_watch_min = sum(c.get("viewminutes") or 0 for c in channels)
    # peak CONCURRENT viewers for the game comes from the daily chart,
    # not the per-channel table (those are per-channel maxima)
    peak_concurrent = max((p["value"] or 0 for p in ts_viewers), default=0)
    top_channel_peak = max((c.get("maxviewers") or 0 for c in channels), default=0)
    partners = sum(1 for c in channels if c.get("partner"))
    affiliates = sum(1 for c in channels if c.get("affiliate"))
    return {
        "total_streamers": len(channels),
        "total_hours_streamed": round(total_stream_min / 60, 1),
        "total_hours_watched": round(total_watch_min / 60, 1),
        "peak_concurrent_viewers": int(peak_concurrent),
        "top_channel_peak_viewers": top_channel_peak,
        "partner_channels": partners,
        "affiliate_channels": affiliates,
        "distinct_languages": len(languages),
        "top_language": max(languages, key=languages.get) if languages else None,
    }


# --------------------------------------------------------------------------- #
# Output writers
# --------------------------------------------------------------------------- #
CHANNEL_COLS = [
    "rownum", "id", "displayname", "twitchurl", "language",
    "viewminutes", "streamedminutes", "maxviewers", "avgviewers",
    "followers", "followersgained", "partner", "affiliate",
]


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_metrics_snapshot(summary: dict) -> None:
    """Long format ready for the dashboard's metrics_snapshot store."""
    path = OUT_DIR / "metrics_snapshot.csv"
    new = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not new:
            w.writerow(["date", "source", "metric_key", "value", "confidence"])
        for key, val in summary.items():
            w.writerow([TODAY, SOURCE, key, val, "confirmed"])


# --------------------------------------------------------------------------- #
def main() -> int:
    print(f"SullyGnome collector — {NOW_ISO} (game {GAME_ID}, {DAYS}d window)")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with requests.Session() as s:
        s.headers.update(HEADERS)

        print("1/4 daily trend charts ...")
        ts_channels = get_timeseries(s, "GameChannels")
        time.sleep(DELAY_SECONDS)
        ts_viewers = get_timeseries(s, "GameViewers")
        time.sleep(DELAY_SECONDS)
        ts_ratio = get_timeseries(s, "GameViewerRatio")
        time.sleep(DELAY_SECONDS)

        print("2/4 language split ...")
        languages = get_languages(s)
        time.sleep(DELAY_SECONDS)

        print("3/4 full channel table (paginated, throttled) ...")
        channels = get_all_channels(s)

        print("4/4 deriving metrics + writing outputs ...")
        summary = build_summary(channels, languages, ts_viewers)

    write_csv(OUT_DIR / "channels_latest.csv", channels, CHANNEL_COLS)
    write_csv(OUT_DIR / f"channels_{TODAY}.csv", channels, CHANNEL_COLS)
    write_csv(OUT_DIR / "timeseries_channels.csv", ts_channels, ["date", "value"])
    write_csv(OUT_DIR / "timeseries_viewers.csv", ts_viewers, ["date", "value"])
    write_csv(OUT_DIR / "timeseries_viewerratio.csv", ts_ratio, ["date", "value"])
    (OUT_DIR / "languages_latest.json").write_text(
        json.dumps(languages, ensure_ascii=False, indent=2), encoding="utf-8")
    write_metrics_snapshot(summary)
    (OUT_DIR / "run_meta.json").write_text(
        json.dumps({"run_at": NOW_ISO, "summary": summary,
                    "channels": len(channels)},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k:>22}: {v}")
    print(f"\nWrote outputs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
