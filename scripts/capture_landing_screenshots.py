#!/usr/bin/env python3
"""Capture real app screenshots for the landing page hero."""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:2026"
OUT_DIR = Path(__file__).resolve().parents[1] / "server" / "static" / "landing"
VIEWPORT = {"width": 1440, "height": 960}
CLIP_WIDTH = 900
CLIP_HEIGHT = 820


def login_demo(page) -> None:
    page.goto(f"{BASE}/login?demo=1", wait_until="networkidle")
    page.fill("#login-identifier", "demo")
    page.fill("#login-password", "demo123!")
    page.click('button[type="submit"]:has-text("Sign in")')
    page.wait_for_url("**/login/2fa**", timeout=15000)
    page.fill('input[name="code"]', "456789")
    page.click('button[type="submit"]:has-text("Continue")')
    page.wait_for_url("**/portal**", timeout=15000)


def dismiss_overlays(page) -> None:
    page.evaluate(
        """() => {
            document.querySelectorAll('.modal.show, .modal-backdrop').forEach(el => el.remove());
            document.querySelectorAll('#flash-container .alert').forEach(el => el.remove());
        }"""
    )


def wait_for_map(page, selector: str = ".leaflet-tile, .pw-map-frame") -> None:
    try:
        page.wait_for_selector(selector, timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(3000)


def screenshot_app(page, name: str) -> None:
    dismiss_overlays(page)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(400)
    page.screenshot(
        path=OUT_DIR / f"{name}.png",
        clip={
            "x": 0,
            "y": 0,
            "width": min(CLIP_WIDTH, VIEWPORT["width"]),
            "height": min(CLIP_HEIGHT, VIEWPORT["height"]),
        },
    )
    print(f"Saved {OUT_DIR / f'{name}.png'}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=2,
            color_scheme="dark",
        )
        page = context.new_page()

        login_demo(page)

        page.goto(
            f"{BASE}/portal/find-parking?"
            "q=Piata+Universitatii%2C+Bucharest&lat=44.4358&lng=26.1025",
            wait_until="domcontentloaded",
        )
        wait_for_map(page)
        screenshot_app(page, "app-find-parking")

        page.goto(f"{BASE}/portal", wait_until="domcontentloaded")
        wait_for_map(page, "#portal-map, .portal-map-frame")
        screenshot_app(page, "app-portal")

        browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
