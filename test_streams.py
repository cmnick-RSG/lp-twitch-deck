"""Verify per-stream table via plain requests (no browser) for a channel, 365d."""
import requests

CH_ID = 717780  # SMii7Y
URL = (f"https://sullygnome.com/api/tables/channeltables/streams/"
       f"365/{CH_ID}/%20/1/1/desc/0/100")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/148.0.0.0 Safari/537.36"),
    "Referer": "https://sullygnome.com/channel/smii7y/365",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}
r = requests.get(URL, headers=HEADERS, timeout=30)
print("HTTP", r.status_code)
j = r.json()
rows = j.get("data", [])
print("recordsTotal:", j.get("recordsTotal"), "| returned:", len(rows))
print("columns:", list(rows[0].keys()) if rows else None)
print("\nlast 365d streams (first 6):")
for s in rows[:6]:
    game = (s.get("gamesplayed") or "").split("|")[0]
    print(f"  {s.get('starttime'):<32} len={s.get('length'):>4}m "
          f"avg={s.get('avgviewers'):>5} peak={s.get('maxviewers'):>5} "
          f"+f={s.get('followergain'):>5}  game={game}")
