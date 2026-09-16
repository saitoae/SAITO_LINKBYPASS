# bypasser/engine.py
"""
Master bypass orchestrator.
Order:
  1. Cache hit
  2. Redirect chain resolve
  3. Site-specific handler (if known)
  4. Third-party cascade (bypass.vip → .city → .pm)
  5. Cloudscraper (CF JS challenge)
  6. Playwright stealth + captcha solve
  7. DDoS-Guard Playwright
  8. 12ft.io / archive.ph paywall strip
"""
import time
from typing import Optional

import cloudscraper
from playwright.async_api import async_playwright

from utils.cache import cache
from utils.redirect import resolve_redirects
from utils.stealth import stealth_headers, new_stealth_context
from bypasser.third_party import cascade as tp_cascade, twelve_ft, archive_ph
from bypasser.cloudflare import (
    fetch_cloudscraper, playwright_cf_bypass, ddosguard_bypass
)
from bypasser.sites import get_handler, SUPPORTED_SITES
from bs4 import BeautifulSoup


PAYWALL_SIGNALS = [
    "subscribe to continue", "subscription required", "sign in to read",
    "create a free account", "unlimited access", "premium content",
    "member-only", "you've reached your", "reading limit",
]

DDOSGUARD_SIGNALS = ["ddos-guard", "__ddg", "_ddgid"]
CF_SIGNALS = ["cloudflare", "cf-browser-verification", "checking your browser"]


def _is_paywalled(html: str) -> bool:
    lower = html.lower()
    return any(s in lower for s in PAYWALL_SIGNALS)


def _is_cf(html: str) -> bool:
    lower = html.lower()
    return any(s in lower for s in CF_SIGNALS)


def _is_ddosguard(html: str) -> bool:
    lower = html.lower()
    return any(s in lower for s in DDOSGUARD_SIGNALS)


def _needs_js(html: str) -> bool:
    lower = html.lower()
    return (
        "enable javascript" in lower
        or "<noscript>" in lower
        or len(html.strip()) < 1500
    )


def _extract_external_links(html: str, host: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and host not in href:
            links.append(href)
    return links


async def bypass(url: str) -> dict:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    start = time.monotonic()

    # ── 1. Cache ──────────────────────────────────────────────
    cached = cache.get(url)
    if cached:
        cached["from_cache"] = True
        return cached

    # ── 2. Redirect resolve ───────────────────────────────────
    final_url, chain, status = await resolve_redirects(url)
    host = final_url.split("/")[2].replace("www.", "")

    destination: Optional[str] = None
    strategy = "unknown"

    # ── 3. Site-specific handler ──────────────────────────────
    handler = get_handler(final_url)
    if handler:
        destination = await handler(final_url)
        strategy = f"site:{host}"

    # ── 4. Third-party cascade ────────────────────────────────
    if not destination:
        destination = await tp_cascade(final_url)
        if destination:
            strategy = "third-party-api"

    # ── 5. Cloudscraper (CF JS / IUAM) ───────────────────────
    if not destination:
        html, resolved, status = fetch_cloudscraper(final_url)
        if html and not _is_cf(html) and not _needs_js(html):
            links = _extract_external_links(html, host)
            if links:
                destination = links[0]
                strategy = "cloudscraper"
            elif resolved and host not in resolved:
                destination = resolved
                strategy = "cloudscraper-redirect"
        elif html and _is_cf(html):
            # ── 6. Playwright CF bypass ───────────────────────
            pw_html, pw_url = await playwright_cf_bypass(final_url)
            if pw_html:
                if pw_url and host not in pw_url:
                    destination = pw_url
                    strategy = "playwright-cf"
                else:
                    links = _extract_external_links(pw_html, host)
                    if links:
                        destination = links[0]
                        strategy = "playwright-cf-dom"
        elif html and _is_ddosguard(html):
            # ── 7. DDoS-Guard bypass ──────────────────────────
            dg_html, dg_url = await ddosguard_bypass(final_url)
            if dg_html:
                if dg_url and host not in dg_url:
                    destination = dg_url
                    strategy = "ddosguard"
                else:
                    links = _extract_external_links(dg_html, host)
                    if links:
                        destination = links[0]
                        strategy = "ddosguard-dom"

    # ── 8. Playwright generic stealth fallback ────────────────
    if not destination:
        async with async_playwright() as p_:
            browser, ctx = await new_stealth_context(p_)
            page = await ctx.new_page()
            try:
                await page.goto(final_url, wait_until="networkidle", timeout=35_000)
                import asyncio
                await asyncio.sleep(8)
                pw_url = page.url
                if host not in pw_url:
                    destination = pw_url
                    strategy = "playwright-generic"
                else:
                    pw_html = await page.content()
                    links = _extract_external_links(pw_html, host)
                    if links:
                        destination = links[0]
                        strategy = "playwright-dom"
            except Exception:
                pass
            finally:
                await browser.close()

    # ── 9. Paywall strip fallback (12ft / archive.ph) ─────────
    if not destination:
        tf = await twelve_ft(final_url)
        if tf and not _is_paywalled(tf):
            strategy = "12ft-paywall"
            # Just return the 12ft proxy URL as destination
            destination = f"https://12ft.io/proxy?q={final_url}"

    if not destination:
        strategy = "archive.ph-fallback"
        destination = f"https://archive.ph/newest/{final_url}"

    elapsed = round(time.monotonic() - start, 2)

    result = {
        "original_url": url,
        "resolved_url": final_url,
        "destination":  destination,
        "redirect_chain": chain,
        "strategy": strategy,
        "status_code": status,
        "success": bool(
            destination
            and "12ft.io" not in destination
            and "archive.ph" not in destination
        ),
        "elapsed_seconds": elapsed,
        "from_cache": False,
    }

    if result["success"]:
        cache.set(url, result)

    return result