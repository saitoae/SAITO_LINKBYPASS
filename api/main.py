# api/main.py
"""
FastAPI — REST endpoints with per-IP rate limiting.
"""
import asyncio
import time
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bypasser.engine import bypass as run_bypass
from bypasser.sites import SUPPORTED_SITES
from utils.cache import cache
from config import RATE_LIMIT_PER_MIN, ADMIN_IDS

app = FastAPI(
    title="🔓 AllBypass API",
    description="Universal link bypass — 25+ sites, CF, DDoS-Guard, captcha auto-solve.",
    version="3.0.0",
    docs_url="/",
    redoc_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Per-IP rate limiter ───────────────────────────────────────────────────────
_rate_buckets: dict[str, list[float]] = defaultdict(list)

def check_rate(ip: str) -> bool:
    now = time.time()
    bucket = _rate_buckets[ip]
    bucket[:] = [t for t in bucket if now - t < 60]
    if len(bucket) >= RATE_LIMIT_PER_MIN:
        return False
    bucket.append(now)
    return True


# ── Models ────────────────────────────────────────────────────────────────────

class BypassReq(BaseModel):
    url: str

class BatchReq(BaseModel):
    urls: list[str]
    max_concurrent: int = 5


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/bypass")
async def bypass_post(req: BypassReq, request: Request):
    ip = request.client.host
    if not check_rate(ip):
        raise HTTPException(429, f"Rate limit: {RATE_LIMIT_PER_MIN} req/min")
    result = await run_bypass(req.url)
    return JSONResponse(result)


@app.get("/bypass")
async def bypass_get(url: str = Query(...), request: Request = None):
    ip = request.client.host if request else "unknown"
    if not check_rate(ip):
        raise HTTPException(429, f"Rate limit: {RATE_LIMIT_PER_MIN} req/min")
    result = await run_bypass(url)
    return JSONResponse(result)


@app.post("/batch")
async def batch_bypass(req: BatchReq, request: Request):
    ip = request.client.host
    if not check_rate(ip):
        raise HTTPException(429, "Rate limit exceeded")
    if len(req.urls) > 20:
        raise HTTPException(400, "Max 20 URLs per batch")

    sem = asyncio.Semaphore(min(req.max_concurrent, 5))

    async def _guarded(url):
        async with sem:
            return await run_bypass(url)

    results = await asyncio.gather(*[_guarded(u) for u in req.urls])
    return JSONResponse({"results": results, "count": len(results)})


@app.get("/supported")
async def supported():
    return {"sites": SUPPORTED_SITES, "count": len(SUPPORTED_SITES)}


@app.get("/cache/stats")
async def cache_stats():
    return JSONResponse(cache.stats())


@app.delete("/cache/clear")
async def cache_clear(admin_key: str = Query(...)):
    # Simple admin key check — match first admin ID as string
    if str(admin_key) not in [str(i) for i in ADMIN_IDS]:
        raise HTTPException(403, "Unauthorized")
    cache.clear()
    return {"status": "cleared"}


@app.get("/health")
async def health():
    return {"status": "alive", "version": "3.0.0", "sig": "6767"}