"""Find the per-STREAM table endpoint: read channel nav links + probe streams tab."""
from playwright.sync_api import sync_playwright

hits = []
links = []


def on_response(resp):
    u = resp.url
    if "/api/tables/" in u:
        try:
            body = resp.text()[:500]
        except Exception:
            body = "<no body>"
        hits.append((resp.status, u, body))


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/148.0.0.0 Safari/537.36"))
    pg.on("response", on_response)
    pg.goto("https://sullygnome.com/channel/smii7y/365",
            wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    links = pg.eval_on_selector_all(
        "a[href*='/channel/']",
        "els => Array.from(new Set(els.map(e => e.getAttribute('href'))))")
    # probe the streams sub-page
    for sub in ["streams", "365/streams"]:
        try:
            pg.goto(f"https://sullygnome.com/channel/smii7y/{sub}",
                    wait_until="domcontentloaded", timeout=60000)
            for _ in range(5):
                pg.mouse.wheel(0, 4000)
                pg.wait_for_timeout(800)
            pg.wait_for_timeout(2500)
        except Exception as e:
            print("probe err", sub, e)
    b.close()

print("=== channel nav links ===")
for l in sorted(set(links)):
    print("  ", l)
print(f"\n=== {len(hits)} /api/tables/ calls ===")
for status, url, body in hits:
    print(f"\n{status}  {url}")
    print(f"   BODY: {body}")
