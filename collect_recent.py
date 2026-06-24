"""
Recent/short-window SullyGnome data (fresh to TODAY, hourly).
- hourly viewers + channels for the last 3 days (chart data updates near real-time)
- streamer counts per window (3/7/30/365 days) for momentum tiles
Writes: timeseries_hourly_*.csv, windows.json
"""
import csv
import json
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
    print("recent: hourly points + windows", windows)


if __name__ == "__main__":
    main()
