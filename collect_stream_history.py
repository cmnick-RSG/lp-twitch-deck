"""
Gameplainer-style live capture. Snapshots LIVE Last Pirates streams from Twitch
Helix and PERSISTS them so a stream stays in the feed after it ends — carrying
the data we captured while it was live (peak viewers, followers, title, logo).
No SullyGnome needed for this; SullyGnome only deepens stats later.

State lives in state/live_history.json (committed, so it survives CI runs — that's
what makes persistence work). Each run:
  - fetch live streams (/streams?game_id) -> viewer_count, title, lang, started_at, thumb
  - fetch followers total (/channels/followers) + profile/type (/users) per broadcaster
  - upsert by stream id: peak_viewers = max over snapshots; refresh followers/title
  - streams that dropped off the live list are marked ended (kept in the store)
  - prune entries older than KEEP_DAYS

Keys from env first, then .env.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone, timedelta

import requests

GAME_ID = "350287257"
# served by Vercel + committed, so the frontend can overlay it fresh between full builds
STATE = pathlib.Path(__file__).parent / "site" / "public" / "live_history.json"
# real-time sample spine: one point per run (every ~5 min) of total live viewers +
# live channel count. This is OUR own time-series — fresh to minutes, with NO
# SullyGnome lag. The frontend stitches it onto SullyGnome's historical daily curve.
SAMPLES = pathlib.Path(__file__).parent / "site" / "public" / "live_samples.json"
KEEP_DAYS = 14
SAMPLES_KEEP_DAYS = 35


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


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def thumb(url: str) -> str:
    return (url or "").replace("{width}", "320").replace("{height}", "180")


def _run():
    e = env()
    if not e.get("TWITCH_CLIENT_ID") or not e.get("TWITCH_CLIENT_SECRET"):
        print("collect_stream_history: no Twitch keys — skipping live capture.")
        return

    tok = requests.post("https://id.twitch.tv/oauth2/token", data={
        "client_id": e["TWITCH_CLIENT_ID"], "client_secret": e["TWITCH_CLIENT_SECRET"],
        "grant_type": "client_credentials"}, timeout=15).json()["access_token"]
    HH = {"Client-ID": e["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {tok}"}

    # load persistent store, keyed by stream id
    store = {}
    if STATE.exists():
        try:
            for s in json.loads(STATE.read_text(encoding="utf-8")):
                store[s["stream_id"]] = s
        except Exception:
            store = {}

    with requests.Session() as s:
        s.headers.update(HH)
        # 1) all live streams for the game (paginated)
        live, cursor = [], None
        for _ in range(10):
            params = {"game_id": GAME_ID, "first": 100}
            if cursor:
                params["after"] = cursor
            j = s.get("https://api.twitch.tv/helix/streams", params=params, timeout=20).json()
            live.extend(j.get("data", []))
            cursor = (j.get("pagination") or {}).get("cursor")
            if not cursor:
                break

        live_ids = {v["id"] for v in live}
        uids = sorted({v["user_id"] for v in live})

        # 2) profiles (logo + partner/affiliate type), batched
        prof = {}
        for i in range(0, len(uids), 100):
            r = s.get("https://api.twitch.tv/helix/users",
                      params={"id": uids[i:i + 100]}, timeout=20).json()
            for u in r.get("data", []):
                prof[u["id"]] = u

        # 3) follower totals (one call per live broadcaster — cheap, few are live)
        follows = {}
        for uid in uids:
            try:
                rf = s.get("https://api.twitch.tv/helix/channels/followers",
                           params={"broadcaster_id": uid, "first": 1}, timeout=20).json()
                follows[uid] = rf.get("total")
            except Exception:
                follows[uid] = None

    ts = now_iso()
    # 4) upsert live streams
    for v in live:
        sid = v["id"]
        cur = v.get("viewer_count") or 0
        p = prof.get(v["user_id"], {})
        rec = store.get(sid, {})
        store[sid] = {
            "stream_id": sid,
            "user_id": v["user_id"],
            "user_login": (v.get("user_login") or "").lower(),
            "user_name": v.get("user_name"),
            "logo": p.get("profile_image_url") or rec.get("logo"),
            "broadcaster_type": p.get("broadcaster_type") or rec.get("broadcaster_type") or "",
            "title": v.get("title") or rec.get("title"),
            "language": v.get("language") or rec.get("language"),
            "thumb": thumb(v.get("thumbnail_url")) or rec.get("thumb"),
            "started_at": v.get("started_at") or rec.get("started_at"),
            "peak_viewers": max(cur, rec.get("peak_viewers") or 0),
            "last_viewers": cur,
            "followers": follows.get(v["user_id"]) if follows.get(v["user_id"]) is not None else rec.get("followers"),
            "is_live": True,
            "first_seen": rec.get("first_seen") or ts,
            "last_seen": ts,
            "ended_at": None,
        }

    # 5) mark streams that left the live list as ended (keep them)
    for sid, rec in store.items():
        if sid not in live_ids and rec.get("is_live"):
            rec["is_live"] = False
            rec["ended_at"] = rec.get("last_seen") or ts

    # 6) prune old
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    kept = []
    for rec in store.values():
        try:
            st = datetime.fromisoformat((rec.get("started_at") or "").replace("Z", "+00:00"))
            if st >= cutoff:
                kept.append(rec)
        except Exception:
            kept.append(rec)
    kept.sort(key=lambda r: r.get("started_at") or "", reverse=True)

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- real-time sample spine -------------------------------------------- #
    # Append this snapshot's totals: viewers = sum of current viewers across all
    # live streams, channels = how many are live. Cap to SAMPLES_KEEP_DAYS.
    total_viewers = sum((v.get("viewer_count") or 0) for v in live)
    sample = {"t": ts, "viewers": int(total_viewers), "channels": len(live)}
    samples = []
    if SAMPLES.exists():
        try:
            samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
        except Exception:
            samples = []
    samples.append(sample)
    scut = datetime.now(timezone.utc) - timedelta(days=SAMPLES_KEEP_DAYS)
    pruned = []
    for sm in samples:
        try:
            t = datetime.fromisoformat((sm.get("t") or "").replace("Z", "+00:00"))
            if t >= scut:
                pruned.append(sm)
        except Exception:
            pruned.append(sm)
    SAMPLES.write_text(json.dumps(pruned, ensure_ascii=False), encoding="utf-8")

    n_live = sum(1 for r in kept if r.get("is_live"))
    print(f"live_history: {len(live)} live now, {len(kept)} in store ({n_live} live, "
          f"{len(kept) - n_live} ended). sample: {sample['viewers']}v / "
          f"{sample['channels']}ch · {len(pruned)} samples kept.")


def main():
    # Twitch Helix occasionally hiccups (timeout / 5xx / rate limit). Since this runs
    # every ~5 min, retry a few times then SKIP this snapshot gracefully (exit 0) rather
    # than failing the job and emailing a false alarm — the data-branch state is untouched
    # (nothing is written until a full successful fetch), so the next run just continues.
    import time
    for attempt in range(1, 4):
        try:
            return _run()
        except Exception as ex:  # noqa: BLE001
            print(f"  collect_stream_history attempt {attempt}/3 failed: {ex}")
            if attempt < 3:
                time.sleep(4 * attempt)
    print("collect_stream_history: Twitch unreachable after retries — skipping this "
          "snapshot (state preserved, next run retries).")


if __name__ == "__main__":
    main()
