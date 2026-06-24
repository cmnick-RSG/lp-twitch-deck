"""Verify English UI + fresh streams feed; screenshot the streams tab."""
from playwright.sync_api import sync_playwright

errors = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1200, "height": 950})
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.goto("http://127.0.0.1:8123/", wait_until="networkidle", timeout=30000)
    pg.wait_for_timeout(1200)
    nav = pg.eval_on_selector_all("nav button", "e=>e.map(x=>x.textContent)")
    pg.click("nav button:has-text('Newest streams')")
    pg.wait_for_timeout(800)
    first = pg.text_content("#streams .row .name")
    pg.screenshot(path="site_streams.png")
    b.close()

print("NAV:", nav)
print("first stream row:", " ".join((first or "").split()))
print("page errors:", errors if errors else "none")
