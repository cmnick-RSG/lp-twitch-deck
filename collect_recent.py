"""
Recent/short-window SullyGnome data (fresh to TODAY, hourly).
- hourly viewers + channels for the last 3 days (chart data updates near real-time)
- streamer counts per window (3/7/30/365 days) for momentum tiles
- per-window totals (watch-hours / stream-hours / peak) for the Trends tiles
Writes: timeseries_hourly_*.csv, windows.json, window_stats.json
"""
import csv
import json
import time
from pathlib import Path
import requests

GAME_ID = 219113
GAME = "Last%20Pirates%3A%20Die%20Together"
DATA = Path(__file__).parent / "data" / "sullygnome"
H = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"),
     "Referer": "https://sullygnome.com/game/last_pirates",
     "X-Requested-With": "XMLHttpRequest"}


def hourly(chart):
    u = (f"https://sullygnome.com/api/charts/linecharts/getconfig/{chart}/3/0/"
         f"{GAME_ID}/{GAME}/%20/%20/0/0/%20/0/")
    cfg = requests.get(u, headers=H, timeout=20).json().get("data", {})
    lab = cfg.get("labels", [])
    val = cfg.get("datasets", [{}])[0].get("data", [])
    return [{"t": l, "v": v} for l, v in zip(lab, val)]


def streamers_in(days):
    u = (f"https://sullygnome.com/api/tables/gametables/getgamechannels/{days}/"
         f"{GAME_ID}/{GAME}/0/1/3/desc/0/1")
    return requests.get(u, headers=H, timeout=20).json().get("recordsTotal", 0)


def window_totals(days):
    """Sum a window's per-channel aggregates -> watch-hours / stream-hours / peak.

    The Trends tiles used to derive watch-hours by summing `viewminutes` off the
    stream feed, but that field only ever came from SullyGnome's per-channel
    endpoints, which now sit behind a Cloudflare challenge (403) — so the tile
    always read 0 for a date range. `gametables/getgamestreams` is still open and
    carries the same numbers per channel, so we total it here instead.
    """
    rows, start = [], 0
    while True:
        u = (f"https://sullygnome.com/api/tables/gametables/getgamestreams/{days}/"
             f"{GAME_ID}/{GAME}/0/1/3/desc/{start}/100")
        try:
            j = requests.get(u, headers=H, timeout=25).json()
        except Exception as e:  # noqa: BLE001 — a bad window must not kill the run
            print(f"   window {days}d failed: {e}")
            return None
        batch = j.get("data", [])
        rows += batch
        total = j.get("recordsTotal", 0)
        start += 100
        if not batch or start >= total:
            break
        time.sleep(0.5)
    if not rows:
        return None
    return {"streamers": len(rows),
            "watch_hours": round(sum(c.get("viewminutes") or 0 for c in rows) / 60, 1),
            "stream_hours": round(sum(c.get("streamedminutes") or 0 for c in rows) / 60, 1),
            "peak": max((c.get("maxviewers") or 0) for c in rows)}


def write_csv(name, rows):
    with (DATA / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["t", "v"])
        w.writeheader(); w.writerows(rows)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    write_csv("hourly_viewers.csv", hourly("GameViewers"))
    write_csv("hourly_channels.csv", hourly("GameChannels"))
    windows = {str(d): streamers_in(d) for d in [3, 7, 30, 365]}
    (DATA / "windows.json").write_text(json.dumps(windows), encoding="utf-8")
    # keep windows.json as plain counts (the frontend reads it that way); the richer
    # per-window totals go in their own file so nothing downstream has to change shape
    stats = {}
    for d in [1, 3, 7, 30]:
        t = window_totals(d)
        if t:
            stats[str(d)] = t
        time.sleep(0.5)
    (DATA / "window_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    print("recent: hourly points + windows", windows)
    for d, t in stats.items():
        print(f"   {d:>3}d: {t['streamers']:>5} streamers, "
              f"{t['watch_hours']:>12,.1f} watch-h, {t['stream_hours']:>9,.1f} stream-h")


if __name__ == "__main__":
    main()
