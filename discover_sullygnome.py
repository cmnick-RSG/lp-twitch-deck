"""
Discovery v5: capture FULL chart endpoint URLs via browser, then immediately
re-fetch each one with plain `requests` (NO browser) to prove the runtime
collector needs no browser. Dump the GameChannels data points.
"""
import json
import requests
from playwright.sync_api import sync_playwright

full_urls = []


def on_response(resp):
    if "/api/charts/" in resp.url:
        full_urls.append(resp.url)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.0.0 Safari/537.36")
    )
    page.on("response", on_response)
    page.goto("https://sullygnome.com/game/last_pirates/365/summary",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    browser.close()

# unique, keep first of each chart type
uniq = {}
for u in full_urls:
    key = u.split("getconfig/")[1].split("/")[0] if "getconfig/" in u else u
    uniq.setdefault(key, u)

print("=== FULL chart endpoint URLs discovered ===")
for k, u in uniq.items():
    print(f"\n[{k}]\n{u}")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/148.0.0.0 Safari/537.36"),
    "Referer": "https://sullygnome.com/game/last_pirates/365/summary",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

print("\n\n=== Re-fetching each WITHOUT browser (plain requests) ===")
for k, u in uniq.items():
    try:
        r = requests.get(u, headers=HEADERS, timeout=30)
        ok = r.status_code == 200
        print(f"\n[{k}] HTTP {r.status_code}  ({len(r.content)} bytes)")
        if ok and "GameChannels" in k:
            cfg = r.json()
            data = cfg.get("data", {})
            labels = data.get("labels", [])
            dsets = data.get("datasets", [])
            print(f"   labels: {len(labels)} points; first={labels[:2]} last={labels[-2:]}")
            if dsets:
                vals = dsets[0].get("data", [])
                print(f"   dataset[0]: {len(vals)} values; sample={vals[:5]} ... {vals[-3:]}")
    except Exception as e:
        print(f"[{k}] ERROR: {e}")
