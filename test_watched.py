"""Pull ALL channels in ONE polite request (no browser, no pagination hammering)."""
import requests

# .../{days}/{gameid}/{name}/0/1/{sortcol}/{sortdir}/{start}/{length}
URL = ("https://sullygnome.com/api/tables/gametables/getgamechannels/"
       "365/219113/Last%20Pirates%3A%20Die%20Together/0/1/3/desc/0/2000")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/148.0.0.0 Safari/537.36"),
    "Referer": "https://sullygnome.com/game/last_pirates/365/watched",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

r = requests.get(URL, headers=HEADERS, timeout=30)
print("HTTP", r.status_code)
j = r.json()
rows = j.get("data", [])
print("recordsTotal:", j.get("recordsTotal"), "| rows returned in ONE request:", len(rows))
print("\nColumns:", list(rows[0].keys()) if rows else None)
print("\nTop 5 channels by view-minutes:")
for row in rows[:5]:
    print(f"  {row.get('rownum'):>4}  {row.get('displayname') or row.get('twitchname','?'):<22} "
          f"watch_min={row.get('viewminutes'):>9}  stream_min={row.get('streamedminutes'):>6} "
          f"max_v={row.get('maxviewers'):>5}  lang={row.get('language','?')}")
