# bypasser/sites.py
"""
Per-site handlers for 25+ shortener / gating sites.
Each async bypass(url) -> Optional[str] (destination URL).
"""
import asyncio
import re
import json
import base64
import random
from typing import Optional
from urllib.parse import urlparse, unquote, quote

import cloudscraper
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from utils.stealth import stealth_headers, new_stealth_context
from bypasser.third_party import cascade as tp_cascade


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────

def _links_from_html(html: str, exclude_hosts: list[str]) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        host = urlparse(href).netloc
        if not any(ex in host for ex in exclude_hosts):
            links.append(href)
    return links


async def _playwright_wait_and_scrape(
    url: str,
    wait_sec: float = 10,
    click_selectors: list[str] = None,
    exclude_hosts: list[str] = None,
) -> Optional[str]:
    if exclude_hosts is None:
        exclude_hosts = [urlparse(url).netloc]
    if click_selectors is None:
        click_selectors = []

    async with async_playwright() as p:
        browser, ctx = await new_stealth_context(p)
        page = await ctx.new_page()
        dest = None
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
            await asyncio.sleep(wait_sec)

            for sel in click_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        await asyncio.sleep(3)
                        break
                except Exception:
                    pass

            # Check if page navigated away
            current = page.url
            if not any(ex in current for ex in exclude_hosts):
                dest = current
            else:
                html = await page.content()
                links = _links_from_html(html, exclude_hosts)
                if links:
                    dest = links[0]
        except Exception:
            pass
        finally:
            await browser.close()
        return dest


async def _playwright_intercept_json(
    url: str,
    json_url_patterns: list[str],
    wait_sec: float = 10,
    click_selectors: list[str] = None,
) -> Optional[str]:
    """Intercept network responses matching URL patterns, extract destination."""
    if click_selectors is None:
        click_selectors = []
    captured = {}

    async with async_playwright() as p:
        browser, ctx = await new_stealth_context(p)
        page = await ctx.new_page()

        async def on_response(response):
            try:
                rurl = response.url
                if any(pat in rurl for pat in json_url_patterns):
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        body = await response.json()
                        text = json.dumps(body)
                        found = re.findall(r'https?://[^\s"\'\\<>]+', text)
                        host = urlparse(url).netloc
                        clean = [u for u in found if host not in u and len(u) > 15]
                        if clean:
                            captured["url"] = clean[0]
            except Exception:
                pass

        page.on("response", on_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
            await asyncio.sleep(wait_sec)

            for sel in click_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click()
                        await asyncio.sleep(3)
                        break
                except Exception:
                    pass

        except Exception:
            pass
        finally:
            await browser.close()
        return captured.get("url")


# ─────────────────────────────────────────────────────────
# SITE HANDLERS
# ─────────────────────────────────────────────────────────

async def bypass_just2earn(url: str) -> Optional[str]:
    result = await _playwright_intercept_json(
        url,
        json_url_patterns=["go", "link", "redirect", "unlock", "dest", "url", "api"],
        wait_sec=10,
        click_selectors=["#btn-main", ".get-link", "a.btn-success", ".btn-primary"],
    )
    if result:
        return result
    return await _playwright_wait_and_scrape(url, wait_sec=12)


async def bypass_linkvertise(url: str) -> Optional[str]:
    m = re.search(r"linkvertise\.com/(\d+)/(\S+)", url)
    if not m:
        return None
    user_id, link_id = m.group(1), m.group(2).split("?")[0]
    api = f"https://publisher.linkvertise.com/api/v1/redirect/links/{user_id}/{link_id}/target"
    try:
        async with httpx.AsyncClient(
            timeout=15, verify=False,
            headers={
                **stealth_headers(),
                "Origin": "https://linkvertise.com",
                "Referer": "https://linkvertise.com/",
            }
        ) as c:
            r = await c.get(api, follow_redirects=True)
            data = r.json()
            return (
                data.get("data", {})
                    .get("link_target", {})
                    .get("url")
            )
    except Exception:
        return None


async def bypass_ouo(url: str) -> Optional[str]:
    """
    ouo.io / ouo.press bypass.
    POST-based: get page, extract token, resubmit form.
    """
    try:
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows"}
        )
        scraper.headers.update(stealth_headers())
        resp = scraper.get(url, timeout=20)
        soup = BeautifulSoup(resp.text, "lxml")

        # Extract hidden form fields
        form = soup.find("form")
        if not form:
            return None
        data = {i["name"]: i.get("value", "") for i in form.find_all("input") if i.get("name")}
        action = form.get("action", url)

        await asyncio.sleep(random.uniform(5, 8))

        resp2 = scraper.post(action, data=data, timeout=20, allow_redirects=True)
        if resp2.url and "ouo" not in resp2.url:
            return resp2.url

        # Try extracting from response HTML
        soup2 = BeautifulSoup(resp2.text, "lxml")
        links = _links_from_html(resp2.text, ["ouo.io", "ouo.press"])
        return links[0] if links else None
    except Exception:
        return None


async def bypass_adfoc(url: str) -> Optional[str]:
    """adf.ly / adfoc.us: decode the ysmm parameter."""
    try:
        scraper = cloudscraper.create_scraper()
        scraper.headers.update(stealth_headers())
        resp = scraper.get(url, timeout=20)

        # Extract encoded URL from JS
        m = re.search(r"ysmm\s*=\s*['\"]([^'\"]+)['\"]", resp.text)
        if not m:
            m = re.search(r"var\s+a\s*=\s*['\"]([^'\"]+)['\"]", resp.text)
        if not m:
            return None

        encoded = m.group(1)

        # adf.ly uses a split-interleave XOR decode
        def decode_adfoc(s: str) -> str:
            s1, s2 = "", ""
            for i, ch in enumerate(s):
                if i % 2 == 0:
                    s1 += ch
                else:
                    s2 = ch + s2
            decoded = base64.b64decode(s1 + s2).decode("utf-8")
            # Strip the http://adf.ly/go.php?u= prefix if present
            if "go.php?u=" in decoded:
                decoded = decoded.split("go.php?u=", 1)[1]
            return unquote(decoded)

        try:
            return decode_adfoc(encoded)
        except Exception:
            return None
    except Exception:
        return None


async def bypass_shrinkme(url: str) -> Optional[str]:
    return await tp_cascade(url)


async def bypass_gplinks(url: str) -> Optional[str]:
    """gplinks.co — hit their internal API after page load."""
    result = await _playwright_intercept_json(
        url,
        json_url_patterns=["api", "go", "link", "dest", "target"],
        wait_sec=8,
        click_selectors=["#btn-main", ".get-link", ".btn-success"],
    )
    if result:
        return result
    return await tp_cascade(url)


async def bypass_bc_vc(url: str) -> Optional[str]:
    """bc.vc — old shortener, cloudscraper usually works."""
    try:
        scraper = cloudscraper.create_scraper()
        scraper.headers.update(stealth_headers())
        resp = scraper.get(url, timeout=20, allow_redirects=True)
        links = _links_from_html(resp.text, ["bc.vc"])
        if links:
            return links[0]
    except Exception:
        pass
    return await tp_cascade(url)


async def bypass_exe_io(url: str) -> Optional[str]:
    return await tp_cascade(url) or await _playwright_wait_and_scrape(url, wait_sec=10)


async def bypass_fc_lc(url: str) -> Optional[str]:
    return await tp_cascade(url) or await _playwright_wait_and_scrape(url, wait_sec=8)


async def bypass_droplink(url: str) -> Optional[str]:
    return await tp_cascade(url) or await _playwright_wait_and_scrape(url, wait_sec=10)


async def bypass_stfly(url: str) -> Optional[str]:
    return await _playwright_intercept_json(
        url,
        json_url_patterns=["go", "api", "dest", "redirect", "link"],
        wait_sec=10,
        click_selectors=["#btn-main", ".btn-success", ".get-link"],
    ) or await tp_cascade(url)


async def bypass_clk_sh(url: str) -> Optional[str]:
    return await tp_cascade(url) or await _playwright_wait_and_scrape(url, wait_sec=10)


async def bypass_short_pe(url: str) -> Optional[str]:
    return await tp_cascade(url) or await _playwright_wait_and_scrape(url, wait_sec=8)


async def bypass_za_gl(url: str) -> Optional[str]:
    try:
        scraper = cloudscraper.create_scraper()
        scraper.headers.update(stealth_headers())
        resp = scraper.get(url, timeout=20, allow_redirects=True)
        if resp.url and "za.gl" not in resp.url:
            return resp.url
        links = _links_from_html(resp.text, ["za.gl"])
        if links:
            return links[0]
    except Exception:
        pass
    return await tp_cascade(url)


async def bypass_workink(url: str) -> Optional[str]:
    return await _playwright_wait_and_scrape(
        url, wait_sec=10,
        click_selectors=["#btn-main", ".btn-success", ".btn-link", "a.btn"],
    ) or await tp_cascade(url)


async def bypass_tmearn(url: str) -> Optional[str]:
    return await _playwright_intercept_json(
        url,
        json_url_patterns=["api", "go", "link", "dest"],
        wait_sec=10,
        click_selectors=["#btn-main", ".get-link"],
    ) or await tp_cascade(url)


async def bypass_earnl(url: str) -> Optional[str]:
    return await _playwright_wait_and_scrape(url, wait_sec=10) or await tp_cascade(url)


async def bypass_link1s(url: str) -> Optional[str]:
    return await _playwright_wait_and_scrape(url, wait_sec=8) or await tp_cascade(url)


async def bypass_cpmlink(url: str) -> Optional[str]:
    return await _playwright_wait_and_scrape(url, wait_sec=10) or await tp_cascade(url)


async def bypass_shorte_st(url: str) -> Optional[str]:
    return await _playwright_intercept_json(
        url,
        json_url_patterns=["api", "dest", "url"],
        wait_sec=12,
        click_selectors=[".interstitial-continue", ".btn-continue", "#continue-btn"],
    ) or await tp_cascade(url)


async def bypass_srt_am(url: str) -> Optional[str]:
    return await tp_cascade(url) or await _playwright_wait_and_scrape(url, wait_sec=8)


async def bypass_rel_ink(url: str) -> Optional[str]:
    return await tp_cascade(url) or await _playwright_wait_and_scrape(url, wait_sec=8)


async def bypass_cutfly(url: str) -> Optional[str]:
    return await tp_cascade(url) or await _playwright_wait_and_scrape(url, wait_sec=10)


async def bypass_payskip(url: str) -> Optional[str]:
    return await _playwright_wait_and_scrape(
        url, wait_sec=12,
        click_selectors=["#btn-main", ".get-link", ".btn-success", "a[href*='http']:not([href*='payskip'])"]
    ) or await tp_cascade(url)


async def bypass_zahd(url: str) -> Optional[str]:
    return await tp_cascade(url) or await _playwright_wait_and_scrape(url, wait_sec=8)


async def bypass_social_wolvez(url: str) -> Optional[str]:
    return await _playwright_wait_and_scrape(url, wait_sec=10) or await tp_cascade(url)


# ─────────────────────────────────────────────────────────
# SITE MAP
# ─────────────────────────────────────────────────────────

SITE_MAP = {
    "just2earn.com":       bypass_just2earn,
    "linkvertise.com":     bypass_linkvertise,
    "ouo.io":              bypass_ouo,
    "ouo.press":           bypass_ouo,
    "adf.ly":              bypass_adfoc,
    "adfoc.us":            bypass_adfoc,
    "bc.vc":               bypass_bc_vc,
    "shrinkme.io":         bypass_shrinkme,
    "gplinks.co":          bypass_gplinks,
    "gplinks.in":          bypass_gplinks,
    "exe.io":              bypass_exe_io,
    "fc.lc":               bypass_fc_lc,
    "droplink.co":         bypass_droplink,
    "stfly.me":            bypass_stfly,
    "clk.sh":              bypass_clk_sh,
    "short.pe":            bypass_short_pe,
    "za.gl":               bypass_za_gl,
    "workink.co":          bypass_workink,
    "workink.cc":          bypass_workink,
    "tmearn.com":          bypass_tmearn,
    "earnl.in":            bypass_earnl,
    "link1s.com":          bypass_link1s,
    "cpmlink.net":         bypass_cpmlink,
    "shorte.st":           bypass_shorte_st,
    "sh.st":               bypass_shorte_st,
    "srt.am":              bypass_srt_am,
    "rel.ink":             bypass_rel_ink,
    "cutfly.com":          bypass_cutfly,
    "payskip.org":         bypass_payskip,
    "zahd.pw":             bypass_zahd,
    "socialwolvez.com":    bypass_social_wolvez,
}

SUPPORTED_SITES = sorted(SITE_MAP.keys())


def get_handler(url: str):
    host = urlparse(url).netloc.replace("www.", "")
    return SITE_MAP.get(host)