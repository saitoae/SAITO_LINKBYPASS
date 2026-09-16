# utils/cache.py
"""
Thread-safe in-memory LRU cache with TTL.
Key = URL, Value = bypass result dict.
"""
import time
from collections import OrderedDict
from threading import Lock
from config import CACHE_TTL, CACHE_MAX_SIZE


class TTLLRUCache:
    def __init__(self, maxsize: int = CACHE_MAX_SIZE, ttl: int = CACHE_TTL):
        self.maxsize = maxsize
        self.ttl = ttl
        self._store: OrderedDict = OrderedDict()
        self._lock = Lock()
        self.hits = 0
        self.misses = 0
        self.total_requests = 0

    def get(self, key: str):
        with self._lock:
            self.total_requests += 1
            if key not in self._store:
                self.misses += 1
                return None
            value, ts = self._store[key]
            if time.time() - ts > self.ttl:
                del self._store[key]
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value):
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, time.time())
            if len(self._store) > self.maxsize:
                self._store.popitem(last=False)

    def clear(self):
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0
            self.total_requests = 0

    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._store),
                "maxsize": self.maxsize,
                "hits": self.hits,
                "misses": self.misses,
                "total_requests": self.total_requests,
                "hit_rate": round(self.hits / self.total_requests * 100, 2) if self.total_requests else 0,
                "ttl_seconds": self.ttl,
            }


cache = TTLLRUCache()