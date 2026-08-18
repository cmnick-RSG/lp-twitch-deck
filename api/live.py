"""
Vercel serverless function: GET /api/live
Returns Last Pirates streams that are LIVE on Twitch right now (real-time via
Helix). Reads TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET from environment.

This is the "as fast as possible" tier — a stream shows up within ~1 min of
going live, every time the dashboard is opened.
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler

import requests

TWITCH_GAME_ID = "350287257"          # Last Pirates: Die Together (Twitch id)
GAME_NAME = "Last Pirates: Die Together"

_token = {"value": None, "exp": 0}    # cached across warm invocations


def app_token():
    if _token["value"] and time.time() < _token["exp"] - 60:
        return _token["value"]
    r = requests.post("https://id.twitch.tv/oauth2/token", data={
        "client_id": os.environ["TWITCH_CLIENT_ID"],
        "client_secret": os.environ["TWITCH_CLIENT_SECRET"],
        "grant_type": "client_credentials"}, timeout=15)
    r.raise_for_status()
    j = r.json()
    _token["value"] = j["access_token"]
    _token["exp"] = time.time() + j.get("expires_in", 3600)
    return _token["value"]


def fetch_live():
    headers = {"Client-ID": os.environ["TWITCH_CLIENT_ID"],
               "Authorization": f"Bearer {app_token()}"}
    live, cursor, pages = [], None, 0
    while pages < 20:                 # guard: reshuffling can keep handing cursors
        pages += 1
        params = {"game_id": TWITCH_GAME_ID, "first": 100}
        if cursor:
            params["after"] = cursor
        r = requests.get("https://api.twitch.tv/helix/streams",
                         params=params, headers=headers, timeout=15)
        r.raise_for_status()
        j = r.json()
        for s in j.get("data", []):
            live.append({
                "user_id": s.get("user_id"),
                "user_name": s.get("user_name"),
                "user_login": s.get("user_login"),
                "viewer_count": s.get("viewer_count", 0),
                "title": s.get("title", ""),
                "language": s.get("language"),
                "started_at": s.get("started_at"),
                "thumbnail": (s.get("thumbnail_url") or "")
                .replace("{width}", "320").replace("{height}", "180"),
            })
        cursor = j.get("pagination", {}).get("cursor")
        if not cursor:
            break
    # Helix can hand back the same stream on two pages: the result set reshuffles
    # between paged requests (channels going live, viewer counts reordering), so a
    # channel already returned slides onto the next page too. Very visible on a
    # launch-day category. Dedupe by user_id, keeping the highest count seen.
    # Done BEFORE the follower loop so duplicates don't cost extra requests too.
    by_user = {}
    for s in live:
        uid = s.get("user_id") or s.get("user_login")
        if uid not in by_user or s["viewer_count"] > by_user[uid]["viewer_count"]:
            by_user[uid] = s
    live = list(by_user.values())
    # follower totals per live channel (works with an app token; few are live → cheap)
    for s in live:
        s["followers"] = None
        if s.get("user_id"):
            try:
                rf = requests.get("https://api.twitch.tv/helix/channels/followers",
                                  params={"broadcaster_id": s["user_id"], "first": 1},
                                  headers=headers, timeout=15)
                if rf.status_code == 200:
                    s["followers"] = rf.json().get("total")
            except Exception:  # noqa: BLE001
                pass
    live.sort(key=lambda x: x["viewer_count"], reverse=True)
    return {"game": GAME_NAME, "game_id": TWITCH_GAME_ID,
            "count": len(live), "live": live}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            payload = fetch_live()
            code = 200
        except Exception as e:  # noqa: BLE001
            payload = {"error": str(e), "live": [], "count": 0}
            code = 500
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "s-maxage=60, stale-while-revalidate=120")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
