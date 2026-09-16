# bypasser/third_party.py
"""
Third-party bypass cascade:
  bypass.vip → bypass.city → bypass.pm → 12ft.io → archive.ph
"""
import httpx
from typing import Optional
from utils.stealth import stealth_headers

BYPASS_VIP  = "https://bypass.vip/bypass?url={}"
BYPASS_CITY = "https://api.bypass.city/bypass?url={}"
BYPASS_PM   = "https://bypass.pm/bypass?url={}"
TWELVE_FT   = "https://12ft.io/proxy?q={}"
ARCHIVE_PH  = "https://archive.ph/newest/{}"


async def _get_json(url: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(
            timeout=25, verify=False,
            headers=stealth_headers(),
            follow_redirects=True,
        ) as c:
            r = await c.get(url)
            return r.json()
    except Exception:
        return None


async def _get_text(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(
            timeout=25, verify=False,
            headers=stealth_headers(),
            follow_redirects=True,
        ) as c:
            r = await c.get(url)
            return r.text if r.status_code == 200 else None
    except Exception:
        return None


def _extract_dest(data: dict) -> Optional[str]:
    """Pull destination from any third-party API response shape."""
    for key in ["destination", "result", "url", "bypass", "link", "target", "dest"]:
        if v := data.get(key):
            if isinstance(v, str) and v.startswith("http"):
                return v
    return None


async def bypass_vip(url: str) -> Optional[str]:
    data = await _get_json(BYPASS_VIP.format(url))
    return _extract_dest(data) if data else None


async def bypass_city(url: str) -> Optional[str]:
    data = await _get_json(BYPASS_CITY.format(url))
    return _extract_dest(data) if data else None


async def bypass_pm(url: str) -> Optional[str]:
    data = await _get_json(BYPASS_PM.format(url))
    return _extract_dest(data) if data else None


async def twelve_ft(url: str) -> Optional[str]:
    """Strip paywall via 12ft.io. Returns clean HTML or None."""
    return await _get_text(TWELVE_FT.format(url))


async def archive_ph(url: str) -> Optional[str]:
    """Grab latest archive.ph snapshot."""
    return await _get_text(ARCHIVE_PH.format(url))


async def cascade(url: str) -> Optional[str]:
    """Run all third-party services in order, return first hit."""
    for fn in [bypass_vip, bypass_city, bypass_pm]:
        result = await fn(url)
        if result:
            return result
    return None