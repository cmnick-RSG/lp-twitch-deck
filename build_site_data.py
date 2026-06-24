"""
Consolidate all collector outputs (data/sullygnome/*) into a single JSON the
static dashboard reads: site/public/data.json. Run after the collectors.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "data" / "sullygnome"
OUT = ROOT / "site" / "public" / "data.json"

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


def main():
    meta = read_json("run_meta.json", {})
    data = {
        "generated_at": meta.get("run_at"),
        "summary": meta.get("summary", {}),
        "languages": read_json("languages_latest.json", {}),
        "channels": read_channels(),
        "timeseries": {
            "channels": read_ts("channels"),
            "viewers": read_ts("viewers"),
            "viewerratio": read_ts("viewerratio"),
        },
        "streams": read_json("streams_latest.json", []),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"  channels={len(data['channels'])} "
          f"streams={len(data['streams'])} "
          f"ts_points={len(data['timeseries']['channels'])} "
          f"langs={len(data['languages'])}")


if __name__ == "__main__":
    main()
