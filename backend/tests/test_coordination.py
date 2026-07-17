"""Tests for Redis-backed session lease ownership semantics."""

import asyncio

import pytest

from app.services.coordination import SessionLease, SessionLockManager


class FakeRedis:
    def __init__(self):
        self.values = {"lock:session:test": "owner"}

    async def set(self, key, value, *, nx, px):
        assert nx is True
        assert px > 0
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script, key_count, key, *args):
        assert key_count == 1
        token = args[0]
        if self.values.get(key) != token:
            return 0
        if "pexpire" in script:
            return 1
        del self.values[key]
        return 1


@pytest.mark.asyncio
async def test_session_lease_only_releases_its_own_lock():
    redis = FakeRedis()
    wrong = SessionLease(redis, "lock:session:test", "other", 60)
    await wrong.release()
    assert redis.values["lock:session:test"] == "owner"

    owned = SessionLease(redis, "lock:session:test", "owner", 60)
    owned.start_renewal()
    await asyncio.sleep(0)
    await owned.release()
    assert "lock:session:test" not in redis.values


@pytest.mark.asyncio
async def test_session_lock_manager_acquires_only_one_lease():
    redis = FakeRedis()
    redis.values.clear()
    manager = SessionLockManager("redis://unused")
    manager._redis = redis

    lease = await manager.acquire("test")
    assert lease is not None
    assert await manager.acquire("test") is None

    await lease.release()
