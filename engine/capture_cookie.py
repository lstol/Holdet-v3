"""
engine/siv/capture_cookie.py — Automated cookie capture via Playwright

Logs into holdet.dk using HOLDET_EMAIL and HOLDET_PASSWORD from .env,
captures the full session cookie (Better Auth + AWS ALB), and writes it to
HOLDET_COOKIE in .env. Run this whenever the cookie expires (401/403 errors).

Usage:
    python engine/siv/capture_cookie.py

Requirements:
    pip install playwright
    python -m playwright install chromium
"""

import re
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def update_env_cookie(cookie_value: str, env_path: Path) -> None:
    content = env_path.read_text()
    content = re.sub(r"HOLDET_COOKIE=.*\n?", "", content)
    content = content.rstrip() + f"\nHOLDET_COOKIE={cookie_value}\n"
    env_path.write_text(content)


def capture_cookie() -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright not installed. Run: pip install playwright && python -m playwright install chromium")

    env = dotenv_values(ROOT / ".env")
    email = env.get("HOLDET_EMAIL", "")
    password = env.get("HOLDET_PASSWORD", "")

    if not email or not password:
        sys.exit("HOLDET_EMAIL and HOLDET_PASSWORD must be set in .env")

    print("Launching browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        print("Loading login page...")
        page.goto("https://www.holdet.dk/da/login", timeout=30000)

        # Dismiss cookie consent
        try:
            page.wait_for_selector(
                "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll", timeout=5000
            )
            page.click("#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll")
            page.wait_for_timeout(500)
        except Exception:
            pass

        # Click the login button in the header
        log_ind_btn = page.wait_for_selector(
            'a:has-text("Log ind"), button:has-text("Log ind")', timeout=8000
        )
        log_ind_btn.click()
        page.wait_for_timeout(1000)

        # Step 1: enter email
        print("Entering email...")
        email_input = page.wait_for_selector(
            'input[type="email"], input[placeholder*="mail" i]', timeout=8000
        )
        email_input.fill(email)
        email_input.press("Enter")
        page.wait_for_timeout(2000)

        # Step 2: enter password
        print("Entering password...")
        password_input = page.wait_for_selector('input[type="password"]', timeout=8000)
        password_input.fill(password)
        password_input.press("Enter")
        page.wait_for_timeout(3000)

        # Navigate to the API domain to pick up the nexus `session` cookie
        page.goto(
            "https://nexus-app-fantasy-fargate.holdet.dk/da/giro-d-italia-2026/me/fantasyteams/6796783",
            timeout=30000,
        )
        try:
            page.wait_for_selector(
                "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll", timeout=3000
            )
            page.click("#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll")
        except Exception:
            pass
        page.wait_for_load_state("networkidle", timeout=20000)
        page.wait_for_timeout(2000)

        # Collect all cookies, preferring the nexus domain for duplicates
        all_cookies = context.cookies(
            ["https://www.holdet.dk", "https://nexus-app-fantasy-fargate.holdet.dk"]
        )
        cookie_dict: dict[str, str] = {}
        for c in all_cookies:
            # Keep nexus-domain cookies over www for same names
            if c["name"] not in cookie_dict or "nexus" in c["domain"]:
                cookie_dict[c["name"]] = c["value"]

        browser.close()

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
    return cookie_str


def verify_cookie(cookie_str: str) -> int:
    import requests

    r = requests.get(
        "https://nexus-app-fantasy-fargate.holdet.dk/api/games/612/players",
        headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    return r.status_code


def main():
    env_path = ROOT / ".env"
    if not env_path.exists():
        sys.exit(f".env not found at {env_path}. Copy .env.example and fill in credentials.")

    cookie_str = capture_cookie()

    print("Verifying cookie against API...")
    status = verify_cookie(cookie_str)
    if status == 200:
        update_env_cookie(cookie_str, env_path)
        names = [part.split("=")[0] for part in cookie_str.split("; ") if "=" in part]
        print(f"✓ Cookie valid. Saved to .env (cookies: {names})")
    else:
        print(f"✗ API returned {status} — login may have failed. Cookie NOT saved.")
        sys.exit(1)


if __name__ == "__main__":
    main()
