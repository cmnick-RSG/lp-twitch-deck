"""Validate Twitch Helix keys: app token -> game_id -> currently-live streams."""
import pathlib
import requests

env = {}
for line in pathlib.Path(".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

CID = env["TWITCH_CLIENT_ID"]
SECRET = env["TWITCH_CLIENT_SECRET"]
GAME = "Last Pirates: Die Together"

# 1) app access token (client credentials)
tok = requests.post("https://id.twitch.tv/oauth2/token", data={
    "client_id": CID, "client_secret": SECRET,
    "grant_type": "client_credentials"}, timeout=20)
print("token HTTP", tok.status_code)
token = tok.json().get("access_token")
print("  got token:", "yes" if token else "NO ->", tok.json() if not token else "")
H = {"Client-ID": CID, "Authorization": f"Bearer {token}"}

# 2) Twitch game_id (NOT SullyGnome's 219113)
g = requests.get("https://api.twitch.tv/helix/games",
                 params={"name": GAME}, headers=H, timeout=20).json()
gid = g["data"][0]["id"] if g.get("data") else None
print("\nTwitch game_id for", GAME, "=", gid)
print("  box art:", g["data"][0].get("box_art_url") if g.get("data") else "n/a")

# 3) currently LIVE streams of the game
s = requests.get("https://api.twitch.tv/helix/streams",
                 params={"game_id": gid, "first": 100}, headers=H, timeout=20).json()
live = s.get("data", [])
print(f"\nLIVE right now: {len(live)} stream(s)")
for st in sorted(live, key=lambda x: x.get("viewer_count", 0), reverse=True)[:10]:
    print(f"  {st['user_name']:<22} {st['viewer_count']:>6} viewers  "
          f"[{st.get('language')}]  started {st.get('started_at')}")
