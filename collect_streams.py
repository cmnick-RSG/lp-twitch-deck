"""
Build a FRESH, COMPLETE "newest Last Pirates streams" feed from SullyGnome.

SullyGnome serves per-stream data at the CHANNEL level and has NO global stream
feed. To capture every recent stream (incl. today) we scan the FULL recent game
window (RECENT_WINDOW days = every channel that streamed LP recently), not a
top-N slice, then pull each channel's streams and keep the Last Pirates ones.

VOD links: SullyGnome does NOT store the Twitch video id (verified — its
streamId is internal and the stream page is Cloudflare-gated). So we link to the
channel's Twitch VOD list. Exact per-VOD links require Twitch Helix (/videos).

Throttled (DELAY). Heavier than the channel table (~RECENT_WINDOW size requests).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

GAME_ID = 219113
GAME_NAME_ENC = "Last%20Pirates%3A%20Die%20Together"
RECENT_WINDOW = 7      # days: scan EVERY channel active in this window
STREAM_WINDOW = 7      # days of each channel's stream history to scan
DELAY = 1.0
GAME_MATCH = "last pirates"
GAME_LABEL = "Last Pirates: Die Together"
DATA = Path(__file__).parent / "data" / "sullygnome"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/148.0.0.0 Safari/537.36"),
    "Referer": "https://sullygnome.com/game/last_pirates",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

KEEP = ["channeldisplayname", "channelurl", "channellogo", "starttime",
        "startDateTime", "length", "avgviewers", "maxviewers",
        "followergain", "viewminutes"]


def get(session, url):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def all_recent_channels(session):
    """Full paginated channel list for the recent window."""
    out, start, total = [], 0, None
    while True:
        url = (f"https://sullygnome.com/api/tables/gametables/getgamechannels/"
               f"{RECENT_WINDOW}/{GAME_ID}/{GAME_NAME_ENC}/0/1/3/desc/{start}/100")
        j = get(session, url)
        if total is None:
            total = j.get("recordsTotal", 0)
        batch = j.get("data", [])
        out.extend(batch)
        start += 100
        if not batch or start >= total:
            break
        time.sleep(DELAY)
    return out


def channel_streams(session, channel_id):
    url = (f"https://sullygnome.com/api/tables/channeltables/streams/"
           f"{STREAM_WINDOW}/{channel_id}/%20/1/1/desc/0/100")
    return get(session, url).get("data", [])


def vod_link(channelurl):
    return f"https://www.twitch.tv/{channelurl}/videos?filter=archives&sort=time"


def main():
    feed = []
    with requests.Session() as s:
        s.headers.update(HEADERS)
        channels = all_recent_channels(s)
        print(f"recent {RECENT_WINDOW}d window: {len(channels)} channels to scan")
        time.sleep(DELAY)
        for i, ch in enumerate(channels, 1):
            cid, name = ch["id"], ch.get("displayname", "?")
            try:
                streams = channel_streams(s, cid)
            except Exception as e:  # noqa: BLE001
                print(f"  [{i}/{len(channels)}] {name}: ERROR {e}")
                continue
            lp = [st for st in streams
                  if GAME_MATCH in (st.get("gamesplayed") or "").lower()]
            for st in lp:
                row = {k: st.get(k) for k in KEEP}
                row["game"] = GAME_LABEL
                row["vod_channel"] = vod_link(st.get("channelurl") or name)
                feed.append(row)
            if i % 25 == 0:
                print(f"  scanned {i}/{len(channels)} … feed={len(feed)}")
            if i < len(channels):
                time.sleep(DELAY)

    # de-dup by (channel, startDateTime), newest first
    seen, uniq = set(), []
    for r in sorted(feed, key=lambda r: r.get("startDateTime") or "", reverse=True):
        key = (r["channeldisplayname"], r.get("startDateTime"))
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    (DATA / "streams_latest.json").write_text(
        json.dumps(uniq, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {len(uniq)} Last Pirates streams to streams_latest.json")
    for r in uniq[:6]:
        print(f"  {r['startDateTime']}  {r['channeldisplayname']}  peak={r['maxviewers']}")


if __name__ == "__main__":
    main()
