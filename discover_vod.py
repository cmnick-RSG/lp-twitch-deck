"""Thoroughly hunt for a real Twitch VOD link across SullyGnome stream + channel pages."""
import re
from playwright.sync_api import sync_playwright


def dump(pg, label):
    html = pg.content()
    hrefs = pg.eval_on_selector_all(
        "a", "els=>Array.from(new Set(els.map(e=>e.getAttribute('href')).filter(Boolean)))")
    tw = [h for h in hrefs if "twitch.tv" in h]
    vids = set(re.findall(r'videos/\d+', html)) | set(re.findall(r'\bv\d{9,}\b', html))
    print(f"\n[{label}] title={pg.title()!r} hrefs={len(hrefs)}")
    print("  twitch hrefs:", tw[:10] or "none")
    print("  video patterns:", list(vids)[:10] or "none")
    # any element mentioning 'VOD'/'watch'
    txt = pg.inner_text("body")
    for kw in ["videos/", "twitch.tv/videos", "VOD", "Watch"]:
        if kw.lower() in txt.lower():
            print(f"  body mentions {kw!r}")


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/148.0.0.0 Safari/537.36"))
    api = []
    pg.on("response", lambda r: api.append(r.url)
          if "/api/" in r.url and "statcounter" not in r.url else None)

    pg.goto("https://sullygnome.com/channel/stream/319216438880",
            wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(6000)
    dump(pg, "stream page")
    print("  api:", [u.split("sullygnome.com")[-1] for u in api][:8] or "none")

    # channel streams listing page
    pg.goto("https://sullygnome.com/channel/kestayrt/14/streams",
            wait_until="domcontentloaded", timeout=60000)
    for _ in range(5):
        pg.mouse.wheel(0, 4000); pg.wait_for_timeout(700)
    pg.wait_for_timeout(3000)
    dump(pg, "channel streams page")
    b.close()
