# utils/captcha.py
"""
2captcha.com solver — hCaptcha, reCAPTCHA v2/v3, Cloudflare Turnstile.
Falls back gracefully if no API key set.
"""
import asyncio
import httpx
from typing import Optional
from config import TWOCAPTCHA_KEY


class CaptchaSolver:
    BASE = "https://2captcha.com"
    POLL_INTERVAL = 5
    MAX_WAIT = 120

    def __init__(self, api_key: str = TWOCAPTCHA_KEY):
        self.key = api_key

    def _available(self) -> bool:
        return bool(self.key and self.key != "your_2captcha_api_key")

    async def _submit(self, params: dict) -> Optional[str]:
        params["key"] = self.key
        params["json"] = 1
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(f"{self.BASE}/in.php", data=params)
                data = r.json()
                if data.get("status") == 1:
                    return str(data["request"])
        except Exception:
            pass
        return None

    async def _poll(self, task_id: str) -> Optional[str]:
        waited = 0
        async with httpx.AsyncClient(timeout=20) as c:
            while waited < self.MAX_WAIT:
                await asyncio.sleep(self.POLL_INTERVAL)
                waited += self.POLL_INTERVAL
                try:
                    r = await c.get(f"{self.BASE}/res.php", params={
                        "key": self.key,
                        "action": "get",
                        "id": task_id,
                        "json": 1,
                    })
                    data = r.json()
                    if data.get("status") == 1:
                        return data["request"]
                    if data.get("request") == "ERROR_CAPTCHA_UNSOLVABLE":
                        return None
                except Exception:
                    pass
        return None

    async def solve_hcaptcha(self, sitekey: str, url: str) -> Optional[str]:
        if not self._available():
            return None
        task_id = await self._submit({
            "method": "hcaptcha",
            "sitekey": sitekey,
            "pageurl": url,
        })
        if not task_id:
            return None
        return await self._poll(task_id)

    async def solve_recaptcha_v2(self, sitekey: str, url: str) -> Optional[str]:
        if not self._available():
            return None
        task_id = await self._submit({
            "method": "userrecaptcha",
            "googlekey": sitekey,
            "pageurl": url,
        })
        if not task_id:
            return None
        return await self._poll(task_id)

    async def solve_recaptcha_v3(
        self, sitekey: str, url: str,
        action: str = "verify", min_score: float = 0.3
    ) -> Optional[str]:
        if not self._available():
            return None
        task_id = await self._submit({
            "method": "userrecaptcha",
            "version": "v3",
            "googlekey": sitekey,
            "pageurl": url,
            "action": action,
            "min_score": min_score,
        })
        if not task_id:
            return None
        return await self._poll(task_id)

    async def solve_turnstile(self, sitekey: str, url: str) -> Optional[str]:
        if not self._available():
            return None
        task_id = await self._submit({
            "method": "turnstile",
            "sitekey": sitekey,
            "pageurl": url,
        })
        if not task_id:
            return None
        return await self._poll(task_id)


solver = CaptchaSolver()