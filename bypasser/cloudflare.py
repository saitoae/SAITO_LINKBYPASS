# bypasser/cloudflare.py
"""
Cloudflare UAM / Bot Fight Mode / DDoS-Guard bypass.
Layer 1: cloudscraper (handles CF JS challenge + IUAM)
Layer 2: Playwright stealth + Turnstile auto-solve via 2captcha
Layer 3: Playwright stealth with full FP mask + behavior sim
"""
import asyncio
import random
import time
import re
from typing import Optional, Tuple

import cloudscraper
from playwright.async_api import async_playwright

from utils.stealth import stealth_headers, new_stealth_context, STEALTH_JS
from utils.captcha import solver


# ── Cloudscraper (CF JS challenge) ─────────────────────────────────────────────

def fetch_cloudscraper(url: str) -> Tuple[Optional[str], Optional[str], int]:
    """
    Returns (html, final_url, status_code).
    Handles CF JS challenge, IUAM, and basic bot detection.
    """
    try:
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False},
            delay=4,
        )
        scraper.headers.update(stealth_headers())
        time.sleep(random.uniform(0.8, 2.0))
        resp = scraper.get(url, timeout=30, allow_redirects=True)
        return resp.text, resp.url, resp.status_code
    except Exception:
        return None, None, 0


# ── CF Turnstile detect + solve ────────────────────────────────────────────────

def _detect_turnstile(html: str) -> Optional[str]:
    """Extract Turnstile sitekey from page HTML."""
    m = re.search(r'data-sitekey=["\']([0-9A-Za-z_\-]+)["\']', html)
    return m.group(1) if m else None


def _detect_hcaptcha(html: str) -> Optional[str]:
    m = re.search(r'data-sitekey=["\']([0-9a-f\-]{36})["\']', html)
    return m.group(1) if m else None


def _detect_recaptcha(html: str) -> Optional[str]:
    m = re.search(r'data-sitekey=["\']([0-9A-Za-z_\-]{40,})["\']', html)
    return m.group(1) if m else None


# ── Playwright full stealth bypass ─────────────────────────────────────────────

async def playwright_cf_bypass(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Full Playwright stealth pass.
    - Detects Turnstile/hCaptcha/reCAPTCHA
    - Submits to 2captcha if key set
    - Injects token and continues
    - Returns (html, final_url)
    """
    async with async_playwright() as p:
        browser, ctx = await new_stealth_context(p, headless=True)
        page = await ctx.new_page()
        html = None
        final_url = None

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40_000)

            # Human-like random mouse movements
            for _ in range(random.randint(2, 5)):
                await page.mouse.move(
                    random.randint(100, 1800),
                    random.randint(100, 900),
                )
                await asyncio.sleep(random.uniform(0.1, 0.5))

            # Wait for CF challenge to potentially clear
            await asyncio.sleep(random.uniform(4, 7))

            page_html = await page.content()

            # Detect and solve captcha
            captcha_token = None
            sitekey = _detect_turnstile(page_html)
            if sitekey:
                captcha_token = await solver.solve_turnstile(sitekey, url)
                if captcha_token:
                    await page.evaluate(f"""
                        document.querySelector('[name="cf-turnstile-response"]').value = '{captcha_token}';
                        document.querySelector('form').submit();
                    """)
                    await asyncio.sleep(4)

            if not captcha_token:
                sitekey = _detect_hcaptcha(page_html)
                if sitekey:
                    captcha_token = await solver.solve_hcaptcha(sitekey, url)
                    if captcha_token:
                        await page.evaluate(f"""
                            document.querySelector('[name="h-captcha-response"]').value = '{captcha_token}';
                            try {{ hcaptcha.execute(); }} catch(e) {{}}
                            document.querySelector('form').submit();
                        """)
                        await asyncio.sleep(4)

            if not captcha_token:
                sitekey = _detect_recaptcha(page_html)
                if sitekey:
                    captcha_token = await solver.solve_recaptcha_v2(sitekey, url)
                    if captcha_token:
                        await page.evaluate(f"""
                            document.getElementById('g-recaptcha-response').value = '{captcha_token}';
                            document.querySelector('form').submit();
                        """)
                        await asyncio.sleep(4)

            # Final wait for post-challenge content
            await asyncio.sleep(random.uniform(2, 4))
            html = await page.content()
            final_url = page.url

        except Exception:
            pass
        finally:
            await browser.close()

        return html, final_url


# ── DDoS-Guard bypass ──────────────────────────────────────────────────────────

async def ddosguard_bypass(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    DDoS-Guard uses JS cookie challenge.
    Playwright renders the challenge JS and gets the cookie, then re-fetches.
    """
    async with async_playwright() as p:
        browser, ctx = await new_stealth_context(p, headless=True)
        page = await ctx.new_page()
        html = None
        final_url = None
        try:
            # First pass — trigger challenge
            await page.goto(url, wait_until="networkidle", timeout=35_000)
            await asyncio.sleep(6)
            # Second pass — cookies should be set now
            await page.reload(wait_until="networkidle", timeout=30_000)
            await asyncio.sleep(3)
            html = await page.content()
            final_url = page.url
        except Exception:
            pass
        finally:
            await browser.close()
        return html, final_url