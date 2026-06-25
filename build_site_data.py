"""
Consolidate all collector outputs (data/sullygnome/*) into a single JSON the
static dashboard reads: site/public/data.json. Run after the collectors.
"""
import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "data" / "sullygnome"
TWITCH = ROOT / "data" / "twitch"
OUT = ROOT / "site" / "public" / "data.json"

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


def merge_streams(lang_by_login):
    """Twitch-FIRST merged feed: archived VODs from Twitch (fresh, real-time) are
    the spine; SullyGnome streams graft on viewer depth (peak/avg/watch-time) when
    they match by channel + start time (±90 min). SullyGnome-only streams (VOD
    gone / archive disabled) are appended so nothing recent is lost."""
    twitch = read_json("../twitch/videos_latest.json", [])
    sully = json.loads((SRC / "streams_latest.json").read_text(encoding="utf-8")) \
        if (SRC / "streams_latest.json").exists() else []

    # index SullyGnome streams by login for time-tolerant matching
    by_login = {}
    for s in sully:
        by_login.setdefault((s.get("channelurl") or "").lower(), []).append(s)

    merged, used = [], set()
    for v in twitch:
        login = (v.get("channelurl") or "").lower()
        tv = _parse(v.get("startDateTime"))
        best, bestdiff = None, 90 * 60 + 1
        for i, s in enumerate(by_login.get(login, [])):
            if (login, i) in used:
                continue
            sv = _parse(s.get("startDateTime"))
            if tv and sv:
                d = abs((sv - tv).total_seconds())
                if d < bestdiff:
                    best, bestdiff, besti = s, d, i
        row = dict(v)
        row["language"] = LANG_NAME.get((v.get("language") or "").lower(),
                                        (v.get("language") or "").upper() or None)
        if best is not None:
            used.add((login, besti))
            row["source"] = "both"
            for k in ("avgviewers", "maxviewers", "viewminutes", "followergain"):
                if best.get(k) is not None:
                    row[k] = best[k]
            row.setdefault("starttime", best.get("starttime"))
            if not row.get("channellogo"):
                row["channellogo"] = best.get("channellogo")
        merged.append(row)

    # SullyGnome streams that matched no Twitch VOD (older / archive off)
    for login, lst in by_login.items():
        for i, s in enumerate(lst):
            if (login, i) in used:
                continue
            row = dict(s)
            row["source"] = "sullygnome"
            row["channelurl"] = login
            row["language"] = lang_by_login.get(login) or s.get("language")
            merged.append(row)

    merged.sort(key=lambda r: r.get("startDateTime") or "", reverse=True)
    return merged


def main():
    meta = read_json("run_meta.json", {})
    channels = read_channels()
    # login -> language, for tagging Twitch-only streams from the channel table
    lang_by_login = {}
    for c in channels:
        login = (c.get("twitchurl") or "").rstrip("/").rsplit("/", 1)[-1].lower()
        if login and c.get("language"):
            lang_by_login[login] = c["language"]

    streams = merge_streams(lang_by_login)
    data = {
        "generated_at": meta.get("run_at"),
        "summary": meta.get("summary", {}),
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
