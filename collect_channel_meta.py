"""
Per-channel ALL-TIME Last Pirates meta: total LP streams + last LP stream date.

SullyGnome's game channel table has NO stream count or last-stream date — only
all-time minutes. Those facts live in the per-channel streams endpoint, which is
1 request/channel. Hitting all ~1200 channels every build would be rude, so we
refresh in ROUND-ROBIN BATCHES and PERSIST the result in
site/public/channel_meta.json (committed, like roster.json). Over ~a day every
channel gets covered, then keeps refreshing — fully autonomous, polite.

Output: site/public/channel_meta.json
  { "updated": iso, "cursor": int, "channels": { login: {"n": int, "last": iso} } }
"""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

GAME_MATCH = "last pirates"
DELAY = float(os.environ.get("LP_DELAY", "1.0"))
BATCH = int(os.environ.get("LP_META_BATCH", "120"))   # channels refreshed per run
WINDOW = 365                                          # ≈ all-time for this campaign
ROOT = Path(__file__).parent
SRC = ROOT / "data" / "sullygnome"
OUT = ROOT / "site" / "public" / "channel_meta.json"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/148.0.0.0 Safari/537.36"),
    "Referer": "https://sullygnome.com/game/last_pirates",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def login_of(row):
    url = (row.get("twitchurl") or "").rstrip("/").rsplit("/", 1)[-1]
    return url.lower()


def read_channels():
    p = SRC / "channels_latest.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return [{"id": r.get("id"), "login": login_of(r)}
                for r in csv.DictReader(f) if r.get("id") and login_of(r)]


def lp_meta(session, cid):
    """Return (lp_stream_count, last_lp_iso) for a channel, LP-filtered."""
    url = (f"https://sullygnome.com/api/tables/channeltables/streams/"
           f"{WINDOW}/{cid}/%20/1/1/desc/0/100")
    rows = session.get(url, timeout=30).json().get("data", [])
    lp = [r for r in rows if GAME_MATCH in (r.get("gamesplayed") or "").lower()]
    last = max((r.get("startDateTime") or "" for r in lp), default="")
    return len(lp), last


def main():
    channels = read_channels()
    if not channels:
        print("channel_meta: no channels_latest.csv — skipping.")
        return
    state = {"updated": None, "cursor": 0, "channels": {}}
    if OUT.exists():
        try:
            state = json.loads(OUT.read_text(encoding="utf-8"))
            state.setdefault("channels", {})
        except Exception:
            pass

    n = len(channels)
    cursor = int(state.get("cursor", 0)) % n
    batch = [channels[(cursor + i) % n] for i in range(min(BATCH, n))]
    print(f"channel_meta: {n} channels, refreshing {len(batch)} from cursor {cursor}")

    done = 0
    with requests.Session() as s:
        s.headers.update(HEADERS)
        for ch in batch:
            try:
                cnt, last = lp_meta(s, ch["id"])
                state["channels"][ch["login"]] = {"n": cnt, "last": last}
                done += 1
            except Exception as e:  # noqa: BLE001
                print(f"  {ch['login']}: ERROR {e}")
            time.sleep(DELAY)

    state["cursor"] = (cursor + len(batch)) % n
    state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    covered = len(state["channels"])
    print(f"channel_meta: refreshed {done}, total covered {covered}/{n} "
          f"({covered*100//n}%), next cursor {state['cursor']}")


if __name__ == "__main__":
    main()
