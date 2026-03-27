from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("INTEL_UI_BASE_URL", "http://127.0.0.1:8768")


@dataclass
class PageResult:
    name: str
    url: str
    title: str
    h1: str
    mode_buttons: int
    map_present: int
    sections: int
    metrics: int
    doc_width: int
    inner_width: int


def _inspect_page(page, *, name: str, url: str, map_selector: str, sections_selector: str, metrics_selector: str) -> PageResult:
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(2_500)
    overflow = page.evaluate("() => ({inner: window.innerWidth, doc: document.documentElement.scrollWidth})")
    return PageResult(
        name=name,
        url=url,
        title=page.title(),
        h1=page.locator("h1").first.inner_text() if page.locator("h1").count() else "",
        mode_buttons=page.locator(".intel-map-mode-button").count(),
        map_present=page.locator(map_selector).count(),
        sections=page.locator(sections_selector).count(),
        metrics=page.locator(metrics_selector).count(),
        doc_width=overflow["doc"],
        inner_width=overflow["inner"],
    )


def main() -> int:
    results: list[PageResult] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        desktop = browser.new_page(viewport={"width": 1440, "height": 1200})
        mobile = browser.new_page(viewport={"width": 390, "height": 844})

        results.append(
            _inspect_page(
                desktop,
                name="blanga_austin_desktop",
                url=f"{BASE_URL}/blanga/austin",
                map_selector="#client-view-map-canvas",
                sections_selector="#client-view-sections .client-section-panel",
                metrics_selector="#client-view-metrics .intel-card",
            )
        )
        results.append(
            _inspect_page(
                desktop,
                name="intel_austin_desktop",
                url=f"{BASE_URL}/intel?region=austin_tx",
                map_selector="#intel-map-canvas",
                sections_selector="#brief-grid .intel-card",
                metrics_selector="#client-view-grid .intel-card",
            )
        )
        results.append(
            _inspect_page(
                mobile,
                name="blanga_austin_mobile",
                url=f"{BASE_URL}/blanga/austin",
                map_selector="#client-view-map-canvas",
                sections_selector="#client-view-sections .client-section-panel",
                metrics_selector="#client-view-metrics .intel-card",
            )
        )
        browser.close()

    failures: list[str] = []
    for result in results:
        if result.map_present < 1:
            failures.append(f"{result.name}: map missing")
        if result.sections < 1:
            failures.append(f"{result.name}: sections missing")
        if result.doc_width > result.inner_width + 2:
            failures.append(f"{result.name}: horizontal overflow {result.doc_width}>{result.inner_width}")

    print(json.dumps({"base_url": BASE_URL, "results": [asdict(item) for item in results], "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
