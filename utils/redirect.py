# utils/redirect.py
import httpx
from fake_useragent import UserAgent

ua = UserAgent()


async def resolve_redirects(url: str) -> tuple[str, list[str], int]:
    """Follow all redirects. Returns (final_url, chain, status_code)."""
    chain = [url]
    status = 0
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={
                "User-Agent": ua.random,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=20,
            verify=False,
        ) as client:
            resp = await client.get(url)
            status = resp.status_code
            for r in resp.history:
                u = str(r.url)
                if u not in chain:
                    chain.append(u)
            final = str(resp.url)
            if final not in chain:
                chain.append(final)
            return final, chain, status
    except Exception:
        return url, chain, status