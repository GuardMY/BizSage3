"""Redis-backed coordination primitives shared by all API instances."""

from __future__ import annotations

import asyncio
import logging
import secrets

from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger(__name__)

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class SessionLease:
    """One renewable Redis lease for a diagnosis session."""

    def __init__(self, redis: Redis, key: str, token: str, ttl_seconds: int) -> None:
        self._redis = redis
        self._key = key
        self._token = token
        self._ttl_ms = ttl_seconds * 1000
        self._renew_task: asyncio.Task[None] | None = None
        self._released = False

    def start_renewal(self) -> None:
        self._renew_task = asyncio.create_task(
            self._renew_loop(),
            name=f"session-lease:{self._key}",
        )

    async def _renew_loop(self) -> None:
        interval = max(self._ttl_ms / 3000, 1.0)
        try:
            while True:
                await asyncio.sleep(interval)
                renewed = await self._redis.eval(
                    _RENEW_SCRIPT,
                    1,
                    self._key,
                    self._token,
                    self._ttl_ms,
                )
                if not renewed:
                    logger.warning("Session lease was lost: %s", self._key)
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to renew session lease: %s", self._key)

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._renew_task is not None:
            self._renew_task.cancel()
            await asyncio.gather(self._renew_task, return_exceptions=True)
        try:
            await self._redis.eval(
                _RELEASE_SCRIPT,
                1,
                self._key,
                self._token,
            )
        except Exception:
            logger.exception("Failed to release session lease: %s", self._key)


class SessionLockManager:
    """Acquire non-blocking, renewable session leases from Redis."""

    def __init__(self, redis_url: str = settings.redis_url) -> None:
        self._redis_url = redis_url
        self._redis: Redis | None = None

    async def startup(self) -> None:
        if self._redis is None:
            self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        await self._redis.ping()

    async def shutdown(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def acquire(self, session_id: str) -> SessionLease | None:
        if self._redis is None:
            await self.startup()
        assert self._redis is not None
        key = f"lock:session:{session_id}"
        token = secrets.token_urlsafe(32)
        acquired = await self._redis.set(
            key,
            token,
            nx=True,
            px=settings.session_lock_ttl_seconds * 1000,
        )
        if not acquired:
            return None
        lease = SessionLease(
            self._redis,
            key,
            token,
            settings.session_lock_ttl_seconds,
        )
        lease.start_renewal()
        return lease

    async def ping(self) -> bool:
        if self._redis is None:
            return False
        return bool(await self._redis.ping())


session_lock_manager = SessionLockManager()
