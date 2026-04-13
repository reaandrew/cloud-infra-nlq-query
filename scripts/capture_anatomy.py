#!/usr/bin/env python3
"""
Capture per-component screenshots of the SPA for the "How it works"
documentation page.

Picks the Level 3 "Instance ↔ Volume" quick-start as the showcase
because it exercises:
  - retrieval of two related resource types
  - a generated WITH-CTE join over the JSON columns
  - a populated results table (rows actually return)

Saves PNGs to BOTH /media/psf/Home/Downloads/anatomy/ (the user's
local copy) AND web/public/docs/anatomy/ (bundled into the SPA).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Locator, Page

URL = os.environ.get("NLQ_URL", "https://nlq.demos.apps.equal.expert/")
API_KEY = os.environ["NLQ_API_KEY"]

OUT_DIRS = [
    Path("/media/psf/Home/Downloads/anatomy"),
    Path(__file__).resolve().parent.parent / "web" / "public" / "docs" / "anatomy",
]
VIEWPORT = {"width": 1440, "height": 1000}

SHOWCASE_EXAMPLE = "Instance ↔ Volume"


def log(msg: str) -> None:
    print(msg, flush=True)


def save_element(loc: Locator, name: str) -> None:
    for d in OUT_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        path = d / name
        loc.screenshot(path=str(path))
        log(f"    wrote {path}")


def save_full_page(page: Page, name: str) -> None:
    for d in OUT_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        path = d / name
        page.screenshot(path=str(path), full_page=True)
        log(f"    wrote {path}")


def wait_for_heading(page: Page, *needles: str, timeout_ms: int = 60_000) -> str:
    needle_re = "|".join(needles)
    page.wait_for_function(
        f"""() => {{
            const h = Array.from(document.querySelectorAll('h1,h2'));
            return h.some(e => /{needle_re}/.test(e.textContent || ''));
        }}""",
        timeout=timeout_ms,
    )
    return page.evaluate(
        f"""() => {{
            const h = Array.from(document.querySelectorAll('h1,h2'));
            const m = h.find(e => /{needle_re}/.test(e.textContent || ''));
            return m ? m.textContent.trim() : '';
        }}"""
    )


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
            page = ctx.new_page()

            log(f"==> opening {URL}")
            page.goto(URL, wait_until="networkidle")

            log("==> seeding API key into localStorage")
            page.evaluate(
                "key => window.localStorage.setItem('cinq-api-key', key)",
                API_KEY,
            )
            page.reload(wait_until="networkidle")

            log("==> moving to the Cross-resource joins tab so the L3 example is on screen")
            page.get_by_role("tab", name="Cross-resource joins").click()
            page.wait_for_timeout(200)

            # --- empty-state component shots ---
            log("==> capturing empty-state crops")

            save_element(page.locator("header").first, "01-header.png")
            save_element(page.locator("header + div").first, "02-phase-banner.png")
            save_element(page.locator("form").first, "03-question-form.png")
            save_element(page.locator("[role='tablist']").first, "04-quick-start-tabs.png")
            save_element(
                page.get_by_role("button", name=SHOWCASE_EXAMPLE).first,
                "05-example-item.png",
            )

            log(f"==> clicking the '{SHOWCASE_EXAMPLE}' example")
            page.get_by_role("button", name=SHOWCASE_EXAMPLE).first.click()

            # --- mid-flight progress panel shot ---
            # Wait for the "Running query" heading then catch a frame around the
            # midpoint of the synthetic timeline (~3-4s in) so multiple stages
            # are visibly in flight.
            log("==> waiting for the running state")
            page.wait_for_function(
                """() => {
                    const h = Array.from(document.querySelectorAll('h1,h2'));
                    return h.some(e => /Running query/.test(e.textContent || ''));
                }""",
                timeout=10_000,
            )
            page.wait_for_timeout(3500)
            log("==> capturing in-flight progress panel")
            save_element(
                page.locator("[aria-label='Query progress']").first,
                "06-progress-running.png",
            )

            # --- completed state shots ---
            log("==> waiting for completion")
            t0 = time.time()
            state = wait_for_heading(page, "Query complete", "Query failed")
            elapsed = time.time() - t0
            log(f"    {state} (after a further {elapsed:.1f}s)")
            page.wait_for_timeout(400)  # let the result panel paint

            log("==> capturing completed state crops")
            save_element(
                page.locator("[aria-label='Query progress']").first,
                "07-progress-complete.png",
            )
            save_element(
                page.locator("[aria-labelledby='sql-heading']").first,
                "08-generated-sql.png",
            )
            save_element(
                page.locator("[aria-labelledby='schemas-heading']").first,
                "09-retrieved-schemas.png",
            )
            save_element(
                page.locator("[aria-labelledby='results-heading']").first,
                "10-results-table.png",
            )

            log("==> capturing the full completed page (cover image)")
            save_full_page(page, "00-full-page.png")

            log("")
            log("==> done")
        finally:
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
