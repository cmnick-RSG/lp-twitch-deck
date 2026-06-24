"""Confirm GameChannels + summary stats via plain requests (no browser)."""
import re
import requests

GAMEID = 219113
GAME = "Last%20Pirates%3A%20Die%20Together"
BASE = "https://sullygnome.com/api/charts/linecharts/getconfig"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/148.0.0.0 Safari/537.36"),
    "Referer": "https://sullygnome.com/game/last_pirates/365/summary",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

for chart in ["GameChannels", "GameViewers"]:
    url = f"{BASE}/{chart}/365/0/{GAMEID}/{GAME}/%20/%20/0/0/%20/0/"
    r = requests.get(url, headers=HEADERS, timeout=30)
    print(f"\n[{chart}] HTTP {r.status_code}")
    if r.status_code == 200:
        cfg = r.json()
        data = cfg.get("data", {})
        labels = data.get("labels", [])
        dsets = data.get("datasets", [])
        vals = dsets[0].get("data", []) if dsets else []
        print(f"   points: {len(labels)}")
        print(f"   first label: {labels[0] if labels else None}  -> {vals[0] if vals else None}")
        print(f"   last  label: {labels[-1] if labels else None}  -> {vals[-1] if vals else None}")
        nums = [v for v in vals if isinstance(v, (int, float))]
        if nums:
            print(f"   max={max(nums)}  min={min(nums)}  sum={sum(nums)}")

# Headline numbers from the summary HTML
print("\n[summary page headline numbers]")
html = requests.get("https://sullygnome.com/game/last_pirates/365/summary",
                    headers=HEADERS, timeout=30).text
for label in ["hours watched", "hours streamed", "average viewers",
              "max viewers", "streamers"]:
    m = re.search(r'([\d.,]+\s*(?:thousand|million|k|m)?)\s*</[^>]+>\s*<[^>]*>\s*' + re.escape(label),
                  html, re.I)
    print(f"   {label}: {'found pattern' if m else 'n/a (needs DOM parse)'}")
print(f"   summary html length: {len(html)}")
