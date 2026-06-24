"""
Enrich the SullyGnome streams feed with real Twitch VOD data via Helix:
real VOD url, view_count, thumbnail, duration — matched by broadcast time.
VODs expire on Twitch, so this only fills recent streams (which is the point:
capture the link + thumbnail + views while they still exist).

Reads/writes data/sullygnome/streams_latest.json. Keys from .env.
"""
import json
import pathlib
from datetime import datetime, timezone
import requests

DATA = pathlib.Path(__file__).parent / "data" / "sullygnome"
STREAMS = DATA / "streams_latest.json"
MATCH_MIN = 90  # match a VOD to a stream if start times within N minutes


def env():
    import os
    d = dict(os.environ)  # CI: secrets come from environment
    p = pathlib.Path(".env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1); d.setdefault(k.strip(), v.strip())
    return d


def parse(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    e = env()
    if not e.get("TWITCH_CLIENT_ID") or not e.get("TWITCH_CLIENT_SECRET"):
        print("enrich_helix: no Twitch keys (env/.env) — skipping VOD enrichment.")
        return
    tok = requests.post("https://id.twitch.tv/oauth2/token", data={
        "client_id": e["TWITCH_CLIENT_ID"], "client_secret": e["TWITCH_CLIENT_SECRET"],
        "grant_type": "client_credentials"}, timeout=15).json()["access_token"]
    HH = {"Client-ID": e["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {tok}"}

    streams = json.loads(STREAMS.read_text(encoding="utf-8"))
    logins = sorted({(s.get("channelurl") or "").lower() for s in streams if s.get("channelurl")})

    # 1) logins -> user_id (batch 100)
    uid = {}
    for i in range(0, len(logins), 100):
        chunk = logins[i:i + 100]
        r = requests.get("https://api.twitch.tv/helix/users",
                         params={"login": chunk}, headers=HH, timeout=20).json()
        for u in r.get("data", []):
            uid[u["login"].lower()] = u["id"]

    # 2) per user -> archive videos
    vids = {}
    for login, id_ in uid.items():
        try:
            r = requests.get("https://api.twitch.tv/helix/videos",
                             params={"user_id": id_, "type": "archive", "first": 30},
                             headers=HH, timeout=20).json()
            vids[login] = r.get("data", [])
        except Exception:
            vids[login] = []

    # 3) match each stream to a VOD by start time
    enriched = 0
    for s in streams:
        login = (s.get("channelurl") or "").lower()
        st = parse(s.get("startDateTime"))
        best, bestdiff = None, MATCH_MIN * 60 + 1
        for v in vids.get(login, []):
            cv = parse(v.get("created_at"))
            if not (st and cv):
                continue
            diff = abs((cv - st).total_seconds())
            if diff < bestdiff:
                best, bestdiff = v, diff
        if best:
            s["vod_url"] = best.get("url")
            s["vod_views"] = best.get("view_count")
            s["vod_duration"] = best.get("duration")
            s["vod_thumb"] = (best.get("thumbnail_url") or "") \
                .replace("%{width}", "320").replace("%{height}", "180") \
                .replace("{width}", "320").replace("{height}", "180")
            enriched += 1

    STREAMS.write_text(json.dumps(streams, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"enriched {enriched}/{len(streams)} streams with live Twitch VOD data "
          f"({len(uid)} channels resolved)")


if __name__ == "__main__":
    main()
