"""
Local helper: write site/public/live.json with currently-live Last Pirates
streams (Twitch Helix). Reads keys from .env. On Vercel the real-time source is
the /api/live serverless function; this file is a fallback for local preview.
"""
import json
import pathlib
import requests

TWITCH_GAME_ID = "350287257"
GAME_NAME = "Last Pirates: Die Together"
OUT = pathlib.Path(__file__).parent / "site" / "public" / "live.json"


def env():
    d = {}
    for line in pathlib.Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def main():
    e = env()
    tok = requests.post("https://id.twitch.tv/oauth2/token", data={
        "client_id": e["TWITCH_CLIENT_ID"],
        "client_secret": e["TWITCH_CLIENT_SECRET"],
        "grant_type": "client_credentials"}, timeout=15).json()["access_token"]
    H = {"Client-ID": e["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {tok}"}
    live, cursor = [], None
    while True:
        p = {"game_id": TWITCH_GAME_ID, "first": 100}
        if cursor:
            p["after"] = cursor
        j = requests.get("https://api.twitch.tv/helix/streams",
                         params=p, headers=H, timeout=15).json()
        for s in j.get("data", []):
            live.append({
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
    live.sort(key=lambda x: x["viewer_count"], reverse=True)
    OUT.write_text(json.dumps(
        {"game": GAME_NAME, "count": len(live), "live": live},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(live)} live stream(s) to {OUT}")
    for s in live[:10]:
        print(f"  {s['user_name']:<22} {s['viewer_count']:>5} viewers [{s['language']}]")


if __name__ == "__main__":
    main()
