import time
import logging
from typing import Optional, Dict, Tuple
import redis.asyncio as aioredis
from app.core.config import settings

logger = logging.getLogger("connector_ai.redis")


class InMemoryFallbackCache:
    """Fallback cache used when Redis is unavailable during local development."""
    def __init__(self):
        self._store: Dict[str, Tuple[str, Optional[float]]] = {}

    async def get(self, key: str) -> Optional[str]:
        if key in self._store:
            val, expiry = self._store[key]
            if expiry is None or expiry > time.time():
                return val
            else:
                del self._store[key]
        return None

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        expiry = (time.time() + ex) if ex else None
        self._store[key] = (str(value), expiry)
        return True

    async def incr(self, key: str) -> int:
        val = await self.get(key)
        new_val = int(val) + 1 if val is not None else 1
        await self.set(key, str(new_val))
        return new_val

    async def expire(self, key: str, seconds: int) -> bool:
        if key in self._store:
            val, _ = self._store[key]
            self._store[key] = (val, time.time() + seconds)
            return True
        return False

    async def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    async def clear(self) -> bool:
        self._store.clear()
        return True

    async def ping(self) -> bool:
        return True


class ResilientCache:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._fallback = InMemoryFallbackCache()
        self._using_fallback = False

    async def init(self):
        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1.0,
            )
            await self._redis.ping()
            self._using_fallback = False
            logger.info("Connected to Redis successfully.")
        except Exception as e:
            self._using_fallback = True
            logger.warning(f"Redis not reachable ({e}). Using in-memory fallback cache.")

    @property
    def client(self):
        if self._using_fallback or self._redis is None:
            return self._fallback
        return self._redis


cache_service = ResilientCache()

