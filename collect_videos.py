"""
Twitch-FIRST recent-streams feed. Pulls recently-ended broadcasts straight from
Twitch Helix `/videos?game_id=...&type=archive&sort=time` — no SullyGnome lag.
Each archived VOD == a stream that just ended, with title, view_count, duration,
thumbnail and a real Twitch link, fresh to minutes ago.

Twitch gives recency + the VOD (link/views/thumb/title/language); it does NOT
give live viewer stats (peak/avg). SullyGnome fills those in later via the merge
in build_site_data.py. So: Twitch = "what just happened", SullyGnome = depth.

Writes data/twitch/videos_latest.json. Keys from env first, then .env.
"""
from __future__ import annotations

import json
import pathlib
import re
import time

import requests

GAME_ID = "350287257"  # Twitch's Last Pirates: Die Together (NOT SullyGnome's 219113)
OUT = pathlib.Path(__file__).parent / "data" / "twitch"
MAX_PAGES = 6          # up to ~600 most-recent VODs; LP has far fewer in practice
PAGE = 100
DELAY = 0.4            # polite pause between pages

_DUR = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")


def env():
    import os
    d = dict(os.environ)
    p = pathlib.Path(".env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                d.setdefault(k.strip(), v.strip())
    return d


def duration_minutes(s: str) -> int:
    """'2h43m35s' -> minutes (rounded)."""
    m = _DUR.fullmatch((s or "").strip())
    if not m:
        return 0
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return round(h * 60 + mi + se / 60)


def thumb(url: str) -> str:
    return (url or "").replace("%{width}", "320").replace("%{height}", "180") \
        .replace("{width}", "320").replace("{height}", "180")


def main():
    e = env()
    if not e.get("TWITCH_CLIENT_ID") or not e.get("TWITCH_CLIENT_SECRET"):
        print("collect_videos: no Twitch keys (env/.env) — skipping Twitch feed.")
        return

    tok = requests.post("https://id.twitch.tv/oauth2/token", data={
        "client_id": e["TWITCH_CLIENT_ID"], "client_secret": e["TWITCH_CLIENT_SECRET"],
        "grant_type": "client_credentials"}, timeout=15).json()["access_token"]
    HH = {"Client-ID": e["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {tok}"}

    # 1) paginate recent archived VODs for the game, newest first
    raw, cursor = [], None
    with requests.Session() as s:
        s.headers.update(HH)
        for _ in range(MAX_PAGES):
            params = {"game_id": GAME_ID, "type": "archive",
                      "sort": "time", "first": PAGE}
            if cursor:
                params["after"] = cursor
            j = s.get("https://api.twitch.tv/helix/videos",
                      params=params, timeout=20).json()
            batch = j.get("data", [])
            raw.extend(batch)
            cursor = (j.get("pagination") or {}).get("cursor")
            if not batch or not cursor:
                break
            time.sleep(DELAY)

        # 2) resolve channel logos (profile images) by user_id, batched
        logos = {}
        ids = sorted({v["user_id"] for v in raw if v.get("user_id")})
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            r = s.get("https://api.twitch.tv/helix/users",
                      params={"id": chunk}, timeout=20).json()
            for u in r.get("data", []):
                logos[u["id"]] = u.get("profile_image_url")

        # 2b) follower totals per channel (app token works for /channels/followers)
        follows = {}
        for uid in ids:
            try:
                rf = s.get("https://api.twitch.tv/helix/channels/followers",
                           params={"broadcaster_id": uid, "first": 1}, timeout=20).json()
                follows[uid] = rf.get("total")
            except Exception:
                follows[uid] = None

    feed = []
    for v in raw:
        feed.append({
            "source": "twitch",
            "video_id": v.get("id"),
            "stream_id": v.get("stream_id"),
            "channeldisplayname": v.get("user_name"),
            "channelurl": (v.get("user_login") or "").lower(),
            "channellogo": logos.get(v.get("user_id")),
            "followers": follows.get(v.get("user_id")),
            "title": v.get("title"),
            "language": v.get("language"),
            "startDateTime": v.get("created_at"),
            "published_at": v.get("published_at"),
            "length": duration_minutes(v.get("duration")),
            "vod_url": v.get("url"),
            "vod_views": v.get("view_count"),
            "vod_duration": v.get("duration"),
            "vod_thumb": thumb(v.get("thumbnail_url")),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "videos_latest.json").write_text(
        json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(feed)} Twitch archived streams to twitch/videos_latest.json")
    for v in feed[:6]:
        print(f"  {v['startDateTime']}  {(v['channeldisplayname'] or '?'):20.20}  "
              f"views={v['vod_views']:>6}  {v['vod_duration']:>9}  | {(v['title'] or '')[:36]}")


if __name__ == "__main__":
    main()
