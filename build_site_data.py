"""
Consolidate all collector outputs (data/sullygnome/*) into a single JSON the
static dashboard reads: site/public/data.json. Run after the collectors.
"""
import csv
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "data" / "sullygnome"
TWITCH = ROOT / "data" / "twitch"
STATE = ROOT / "site" / "public" / "live_history.json"
ROSTER = ROOT / "site" / "public" / "roster.json"
OUT = ROOT / "site" / "public" / "data.json"

_DUR = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")

# Twitch BCP-47 language codes -> readable names (LP's actual audience + common)
LANG_NAME = {
    "en": "English", "es": "Spanish", "pt": "Portuguese", "ru": "Russian",
    "fr": "French", "de": "German", "it": "Italian", "pl": "Polish",
    "tr": "Turkish", "th": "Thai", "zh": "Chinese", "ja": "Japanese",
    "ko": "Korean", "ar": "Arabic", "uk": "Ukrainian", "nl": "Dutch",
    "cs": "Czech", "hu": "Hungarian", "fi": "Finnish", "el": "Greek",
    "sv": "Swedish", "da": "Danish", "no": "Norwegian", "ro": "Romanian",
    "id": "Indonesian", "vi": "Vietnamese", "hi": "Hindi", "fil": "Filipino",
    "tl": "Filipino", "bg": "Bulgarian", "sk": "Slovak", "ca": "Catalan",
}

NUM = {"rownum", "viewminutes", "streamedminutes", "maxviewers",
       "avgviewers", "followers", "followersgained"}


def read_channels():
    rows = []
    with (SRC / "channels_latest.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k in list(r):
                if k in NUM:
                    try:
                        r[k] = int(r[k])
                    except (ValueError, TypeError):
                        r[k] = 0
            r["partner"] = str(r.get("partner")).lower() == "true"
            rows.append(r)
    return rows


def read_ts(name):
    p = SRC / f"timeseries_{name}.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return [{"date": x["date"], "value": float(x["value"] or 0)}
                for x in csv.DictReader(f)]


def read_json(name, default):
    p = SRC / name
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return default


def read_hourly(name):
    p = SRC / f"hourly_{name}.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return [{"t": x["t"], "v": float(x["v"] or 0)} for x in csv.DictReader(f)]


def _parse(ts):
    try:
        return datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except Exception:
        return None


def _dur_min(s):
    m = _DUR.fullmatch((s or "").strip())
    if not m:
        return None
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return round(h * 60 + mi + se / 60) or None


def _langname(code_or_name):
    if not code_or_name:
        return None
    return LANG_NAME.get(code_or_name.lower(), code_or_name if len(code_or_name) > 3 else code_or_name.upper())


def merge_streams(lang_by_login):
    """Gameplainer-style merged feed from THREE sources, all keyed by channel+time:
      1) live_history (our own Twitch live snapshots) — the spine. Streams appear the
         moment they're live and STAY after ending, carrying captured peak viewers +
         followers. No SullyGnome wait.
      2) Twitch /videos — attaches real VOD url/views/duration/thumbnail.
      3) SullyGnome — grafts deeper stats (avg, watch-minutes, follower gain) once it
         has processed the stream.
    Records not seen live still appear from (2)/(3) so nothing recent is lost."""
    history = []
    if STATE.exists():
        try:
            history = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            history = []
    twitch = read_json("../twitch/videos_latest.json", [])
    sully = json.loads((SRC / "streams_latest.json").read_text(encoding="utf-8")) \
        if (SRC / "streams_latest.json").exists() else []

    recs = []                       # unified records
    index = {}                      # login -> list of (rec, parsed_start)

    def add(rec):
        recs.append(rec)
        index.setdefault(rec["channelurl"], []).append((rec, _parse(rec.get("startDateTime"))))

    def match(login, iso, used_key):
        t = _parse(iso)
        best, bestdiff = None, 90 * 60 + 1
        for rec, rt in index.get(login, []):
            if rec.get(used_key):
                continue
            if t and rt:
                d = abs((rt - t).total_seconds())
                if d < bestdiff:
                    best, bestdiff = rec, d
        return best

    # 1) spine: our captured live/ended streams
    for h in history:
        login = (h.get("user_login") or "").lower()
        ended_len = None
        st, en = _parse(h.get("started_at")), _parse(h.get("ended_at"))
        if st and en:
            ended_len = max(1, round((en - st).total_seconds() / 60))
        add({
            "source": "live" if h.get("is_live") else "ended",
            "is_live": bool(h.get("is_live")),
            "stream_id": h.get("stream_id"),
            "channeldisplayname": h.get("user_name"),
            "channelurl": login,
            "channellogo": h.get("logo"),
            "title": h.get("title"),
            "language": _langname(h.get("language")),
            "startDateTime": h.get("started_at"),
            "peak_viewers": h.get("peak_viewers"),
            "viewer_count": h.get("last_viewers") if h.get("is_live") else None,
            "followers": h.get("followers"),
            "partner": (h.get("broadcaster_type") == "partner"),
            "length": ended_len,
            "vod_thumb": h.get("thumb"),
        })

    # 2) Twitch VODs — attach to a matching record, else add as VOD-only
    for v in twitch:
        login = (v.get("channelurl") or "").lower()
        rec = match(login, v.get("startDateTime"), "_vod")
        if rec is not None:
            rec["_vod"] = True
            rec["vod_url"] = v.get("vod_url")
            rec["vod_views"] = v.get("vod_views")
            rec["vod_duration"] = v.get("vod_duration")
            if v.get("vod_thumb"):
                rec["vod_thumb"] = v["vod_thumb"]
            if not rec.get("length"):
                rec["length"] = _dur_min(v.get("vod_duration"))
            if not rec.get("title"):
                rec["title"] = v.get("title")
            if rec.get("followers") is None and v.get("followers") is not None:
                rec["followers"] = v.get("followers")
        else:
            add({
                "source": "twitch", "is_live": False,
                "channeldisplayname": v.get("channeldisplayname"),
                "channelurl": login, "channellogo": v.get("channellogo"),
                "title": v.get("title"), "language": _langname(v.get("language")),
                "startDateTime": v.get("startDateTime"),
                "length": _dur_min(v.get("vod_duration")),
                "followers": v.get("followers"),
                "vod_url": v.get("vod_url"), "vod_views": v.get("vod_views"),
                "vod_duration": v.get("vod_duration"), "vod_thumb": v.get("vod_thumb"),
                "_vod": True,
            })

    # 3) SullyGnome — graft depth onto a match, else add as SullyGnome-only
    for sst in sully:
        login = (sst.get("channelurl") or "").lower()
        rec = match(login, sst.get("startDateTime"), "_sully")
        if rec is not None:
            rec["_sully"] = True
            for k in ("avgviewers", "maxviewers", "viewminutes", "followergain"):
                if sst.get(k) is not None:
                    rec[k] = sst[k]
            if not rec.get("length") and sst.get("length"):
                rec["length"] = sst["length"]
            if rec.get("followers") is None and sst.get("followers") is not None:
                rec["followers"] = sst.get("followers")
            # carry the VOD enrich_helix found per-channel (e.g. a stream Twitch filed
            # under a different game category) onto the record if it lacks one
            if not rec.get("vod_url") and sst.get("vod_url"):
                rec["vod_url"] = sst.get("vod_url")
                rec["vod_views"] = sst.get("vod_views")
                rec["vod_duration"] = sst.get("vod_duration")
                if sst.get("vod_thumb"):
                    rec["vod_thumb"] = sst["vod_thumb"]
        else:
            add({
                "source": "sullygnome", "is_live": False, "_sully": True,
                "channeldisplayname": sst.get("channeldisplayname"),
                "channelurl": login, "channellogo": sst.get("channellogo"),
                "language": lang_by_login.get(login) or sst.get("language"),
                "startDateTime": sst.get("startDateTime"),
                "length": sst.get("length"),
                "avgviewers": sst.get("avgviewers"), "maxviewers": sst.get("maxviewers"),
                "viewminutes": sst.get("viewminutes"), "followergain": sst.get("followergain"),
                "followers": sst.get("followers"),
                # VOD link/views/duration/thumbnail from enrich_helix (per-channel match)
                "vod_url": sst.get("vod_url"), "vod_views": sst.get("vod_views"),
                "vod_duration": sst.get("vod_duration"), "vod_thumb": sst.get("vod_thumb"),
            })

    for r in recs:
        r.pop("_vod", None)
        r.pop("_sully", None)
    # live first, then newest by start time
    recs.sort(key=lambda r: (r.get("is_live", False), r.get("startDateTime") or ""), reverse=True)
    return recs


def _login_of(c):
    """Universal channel key = lowercase Twitch login (works across all sources)."""
    url = (c.get("twitchurl") or c.get("channelurl") or "")
    if "/" in url:
        url = url.rstrip("/").rsplit("/", 1)[-1]
    return (url or c.get("user_login") or "").lower()


def update_roster(channels, history, streams, run_date):
    """Persist a CUMULATIVE roster of every Twitch login we have EVER seen stream
    Last Pirates, across all sources and all runs. This is the TRUE all-time unique
    streamer count — it only grows. We do NOT trust SullyGnome's 365-day table total
    for this: that window is a stale snapshot (~1076) and is actually LOWER than the
    90-day total, so it never reflects new streamers. The roster fixes that."""
    roster = {}
    if ROSTER.exists():
        try:
            j = json.loads(ROSTER.read_text(encoding="utf-8"))
            roster = j.get("logins", j) if isinstance(j, dict) else {}
        except Exception:
            roster = {}
    before = len(roster)
    for src in (channels, history, streams):
        for c in src or []:
            login = _login_of(c)
            if login and login not in roster:
                roster[login] = run_date
    ROSTER.write_text(json.dumps({"updated": run_date, "logins": roster},
                                 ensure_ascii=False), encoding="utf-8")
    added = len(roster) - before
    print(f"  roster: {len(roster)} all-time unique streamers (+{added} new this run)")
    return roster


def main():
    meta = read_json("run_meta.json", {})
    channels = read_channels()
    # merge all-time per-channel LP meta (total streams + last stream date),
    # refreshed in batches by collect_channel_meta.py into channel_meta.json
    cmeta = {}
    mp = ROOT / "site" / "public" / "channel_meta.json"
    if mp.exists():
        try:
            cmeta = json.loads(mp.read_text(encoding="utf-8")).get("channels", {})
        except Exception:
            cmeta = {}
    for c in channels:
        m = cmeta.get(_login_of(c))
        if m:
            c["total_streams"] = m.get("n")
            c["last_stream"] = m.get("last")
    # login -> language, for tagging Twitch-only streams from the channel table
    lang_by_login = {}
    for c in channels:
        login = (c.get("twitchurl") or "").rstrip("/").rsplit("/", 1)[-1].lower()
        if login and c.get("language"):
            lang_by_login[login] = c["language"]

    streams = merge_streams(lang_by_login)

    # TRUE all-time unique streamers via a cumulative, self-owned roster (not the
    # stale SullyGnome 365 window). Overrides the frozen total_streamers headline.
    run_date = (meta.get("run_at") or "")[:10]
    roster = update_roster(channels, [], streams, run_date)
    summary = dict(meta.get("summary", {}))
    summary["total_streamers"] = max(len(roster), summary.get("total_streamers", 0))
    summary["roster_count"] = len(roster)

    data = {
        "generated_at": meta.get("run_at"),
        "summary": summary,
        "windows": read_json("windows.json", {}),
        "languages": read_json("languages_latest.json", {}),
        "channels": channels,
        "timeseries": {
            "channels": read_ts("channels"),
            "viewers": read_ts("viewers"),
            "viewerratio": read_ts("viewerratio"),
        },
        "hourly": {
            "viewers": read_hourly("viewers"),
            "channels": read_hourly("channels"),
        },
        "streams": streams,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    src = {}
    for s in streams:
        src[s.get("source", "?")] = src.get(s.get("source", "?"), 0) + 1
    print(f"Wrote {OUT}")
    print(f"  channels={len(channels)} streams={len(streams)} {src} "
          f"ts_points={len(data['timeseries']['channels'])} langs={len(data['languages'])}")


if __name__ == "__main__":
    main()
