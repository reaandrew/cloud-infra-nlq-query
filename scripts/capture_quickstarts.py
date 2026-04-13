#!/usr/bin/env python3
"""
Headlessly capture a full-page screenshot of every quick-start example
in the deployed SPA. Saves PNGs to /media/psf/Home/Downloads.

Run with the API key already in the environment:
    NLQ_API_KEY=$(make api-key) ./scripts/capture_quickstarts.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = os.environ.get("NLQ_URL", "https://nlq.demos.apps.equal.expert/")
API_KEY = os.environ["NLQ_API_KEY"]
OUT_DIR = Path(os.environ.get("OUT_DIR", "/media/psf/Home/Downloads"))
VIEWPORT = {"width": 1440, "height": 1000}
COMPLETION_TIMEOUT_MS = 60_000

# Order maps the on-page tab labels and example titles to a slug used in
# the saved PNG filename. Each tuple is (level, tab_label, example_title, slug).
EXAMPLES = [
    (1, "Basics", "Resource type histogram",          "01-l1-resource-type-histogram"),
    (1, "Basics", "EC2 instances per account",        "02-l1-ec2-instances-per-account"),
    (1, "Basics", "Top accounts by resource count",   "03-l1-top-accounts"),
    (2, "JSON fields", "Largest EBS volumes",         "04-l2-largest-ebs-volumes"),
    (2, "JSON fields", "EC2 by Environment tag",      "05-l2-ec2-by-env-tag"),
    (2, "JSON fields", "Lambda runtimes",             "06-l2-lambda-runtimes"),
    (3, "Cross-resource joins", "Instance ↔ Volume",  "07-l3-instance-volume"),
    (3, "Cross-resource joins", "Lambda ↔ IAM role",  "08-l3-lambda-iam-role"),
    (3, "Cross-resource joins", "EBS volume ↔ KMS key", "09-l3-volume-kms-key"),
    (4, "Advanced", "Subnet occupancy (3-way)",       "10-l4-subnet-occupancy"),
    (4, "Advanced", "VPC inventory (4-way pivot)",    "11-l4-vpc-inventory"),
    (4, "Advanced", "Orphan KMS keys",                "12-l4-orphan-kms"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(
                viewport=VIEWPORT,
                device_scale_factor=2,  # crisper screenshots
            )
            page = ctx.new_page()

            log(f"==> opening {URL}")
            page.goto(URL, wait_until="networkidle")

            log("==> seeding API key into localStorage")
            page.evaluate(
                "key => window.localStorage.setItem('cinq-api-key', key)",
                API_KEY,
            )
            page.reload(wait_until="networkidle")

            results: list[tuple[str, str]] = []  # (slug, status)
            current_tab: str | None = None

            for idx, (level, tab_label, example_title, slug) in enumerate(EXAMPLES, start=1):
                log(f"--- [{idx:02d}/12] L{level} · {example_title}")

                # Switch tab if needed (the first example forces a click anyway)
                if current_tab != tab_label:
                    log(f"    switching to tab '{tab_label}'")
                    page.get_by_role("tab", name=tab_label).click()
                    current_tab = tab_label
                    page.wait_for_timeout(150)

                # Click the example button. Match by name (the example's title
                # appears as the accessible name of its button).
                btn = page.get_by_role("button", name=example_title, exact=False).first
                btn.click()

                # Two-step wait. The previous query's "Query complete" heading
                # is still in the DOM until the new pending state clears it,
                # so a naive wait would resolve immediately. Wait for the
                # "Running query" heading FIRST, then wait for the next
                # "Query complete" / "Query failed" heading.
                t0 = time.time()
                try:
                    page.wait_for_function(
                        """() => {
                            const h = Array.from(document.querySelectorAll('h1,h2'));
                            return h.some(e => /Running query/.test(e.textContent || ''));
                        }""",
                        timeout=10_000,
                    )
                    page.wait_for_function(
                        """() => {
                            const h = Array.from(document.querySelectorAll('h1,h2'));
                            return h.some(e => /Query complete|Query failed/.test(e.textContent || ''));
                        }""",
                        timeout=COMPLETION_TIMEOUT_MS,
                    )
                except PWTimeout:
                    log(f"    !! timeout after {COMPLETION_TIMEOUT_MS/1000:.0f}s — capturing anyway")
                    results.append((slug, "timeout"))
                else:
                    elapsed = time.time() - t0
                    state = page.evaluate(
                        """() => {
                            const h = Array.from(document.querySelectorAll('h1,h2'));
                            const m = h.find(e => /Query complete|Query failed/.test(e.textContent || ''));
                            return m ? m.textContent.trim() : 'unknown';
                        }"""
                    )
                    log(f"    {state} in {elapsed:.1f}s")
                    results.append((slug, state))

                # Let any post-state animations settle
                page.wait_for_timeout(300)

                out_path = OUT_DIR / f"{slug}.png"
                page.screenshot(path=str(out_path), full_page=True)
                log(f"    saved {out_path.name} ({out_path.stat().st_size // 1024} KB)")

                # Scroll back to top in case the next example is on a different
                # tab and we need to reach the tab strip.
                page.evaluate("() => window.scrollTo(0, 0)")
                page.wait_for_timeout(100)

            log("")
            log("==> done. summary:")
            for slug, state in results:
                log(f"  {state:<20s}  {slug}.png")

        finally:
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
