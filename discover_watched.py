"""Discover the streamer TABLE endpoint on the /watched page."""
import requests
from playwright.sync_api import sync_playwright

TARGET = "https://sullygnome.com/game/last_pirates/365/watched"
hits = []


def on_response(resp):
    u = resp.url
    if "/api/" in u and "statcounter" not in u:
        try:
            body = resp.text()[:300]
        except Exception:
            body = "<no body>"
        hits.append((resp.status, u, body))


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/148.0.0.0 Safari/537.36"))
    pg.on("response", on_response)
    pg.goto(TARGET, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(8000)
    b.close()

print(f"=== {len(hits)} /api/ calls ===")
for status, url, body in hits:
    tag = "  <<< TABLE" if "table" in url.lower() else ""
    print(f"\n{status}  {url}{tag}")
    if "table" in url.lower():
        print(f"   BODY: {body}")
