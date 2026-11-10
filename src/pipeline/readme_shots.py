"""Screenshots for the README gallery (docs/figures/readme/), taken from the built site.

Run after `make site`: serves site/ on a local port, opens each page in headless Chromium at 1280 px and saves a
1600 px wide PNG. The README links each image to the same page on GitHub Pages.
"""
from __future__ import annotations

import http.server
import io
import sys
import threading
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE, OUT = ROOT / "site", ROOT / "docs" / "figures" / "readme"
# (file, page, tab to click, text to scroll to)
SHOTS = [
    ("overview.png", "index.html", None, None),
    ("savings.png", "index.html", "Savings tracker", "How the reported figures fit together"),
    ("payment_screen.png", "index.html", "Opportunities", "Payment screen: possible duplicates"),
    ("calculator.png", "index.html", "Calculator", None),
    ("ai_layer.png", "ai.html", None, None),
    ("explorer.png", "explorer.html", None, None),
    ("catalog.png", "catalog.html", None, None),
]


def _save(png: bytes, path: Path, width: int = 1600) -> None:
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(path, optimize=True)


def main(argv=None) -> int:
    from playwright.sync_api import sync_playwright
    if not (SITE / "index.html").exists():
        print("readme_shots: build the site first (make site)", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            for name, page, tab, text in SHOTS:
                pg = b.new_page(viewport={"width": 1280, "height": 760}, device_scale_factor=2)
                pg.goto(base + page)
                pg.wait_for_timeout(15000 if page == "explorer.html" else 8000)
                if tab:
                    pg.get_by_role("tab", name=tab).click()
                    pg.wait_for_timeout(1500)
                if text:
                    pg.get_by_text(text, exact=False).first.scroll_into_view_if_needed()
                    pg.evaluate("window.scrollBy(0, -150)")
                if page == "explorer.html":
                    pg.get_by_role("button", name="Payment screen by agency").click()
                    pg.get_by_role("button", name="Run query").click()
                    pg.wait_for_timeout(5000)
                    pg.get_by_role("button", name="Run query").scroll_into_view_if_needed()
                    pg.evaluate("window.scrollBy(0, -260)")
                pg.wait_for_timeout(500)
                _save(pg.screenshot(), OUT / name)
                pg.close()
            b.close()
    finally:
        srv.shutdown()
    print(f"readme_shots: {len(SHOTS)} screenshots in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
