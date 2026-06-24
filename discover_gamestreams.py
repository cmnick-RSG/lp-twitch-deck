"""Inspect the Last Pirates game landing page: final URL, nav links, ALL api calls."""
from playwright.sync_api import sync_playwright

api = []


def on_response(resp):
    u = resp.url
    if "/api/" in u and "statcounter" not in u:
        try:
            body = resp.text()[:250]
        except Exception:
            body = ""
        api.append((resp.status, u, body))


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/148.0.0.0 Safari/537.36"))
    pg.on("response", on_response)
    pg.goto("https://sullygnome.com/game/last_pirates",
            wait_until="domcontentloaded", timeout=60000)
    for _ in range(8):
        pg.mouse.wheel(0, 4000)
        pg.wait_for_timeout(800)
    pg.wait_for_timeout(3000)
    final_url = pg.url
    links = pg.eval_on_selector_all(
        "a[href*='/game/last_pirates']",
        "els => Array.from(new Set(els.map(e => e.getAttribute('href'))))")
    b.close()

print("FINAL URL:", final_url)
print("\n=== game nav links ===")
for l in sorted(set(links)):
    print("  ", l)
print(f"\n=== {len(api)} /api/ calls ===")
for status, url, body in api:
    kind = "TABLE" if "/tables/" in url else "chart"
    print(f"[{kind}] {status}  {url[:120]}")
    if kind == "TABLE":
        print(f"    {body}")
