"""Tests for the resilience system (retries, timeouts, caching, and fallback chains)."""

import asyncio
import time
import pytest
import httpx
from planpilot.utils.resilience import (
    CacheEntry,
    ResilientCache,
    execute_fallback_chain,
    http_get_with_retry,
)


@pytest.mark.asyncio
async def test_resilient_cache_fresh_and_stale():
    cache = ResilientCache(default_fresh_ttl=0.2, default_stale_ttl=0.4)
    cache.set("test_key", {"data": "ok"})

    # 1. Fresh hit
    data, is_stale = cache.get("test_key")
    assert data == {"data": "ok"}
    assert is_stale is False

    # 2. Stale hit after fresh_ttl expires
    await asyncio.sleep(0.25)
    data, is_stale = cache.get("test_key")
    assert data == {"data": "ok"}
    assert is_stale is True

    # 3. Completely expired (0.25 + 0.45 = 0.70s > 0.60s TTL)
    await asyncio.sleep(0.45)
    data, is_stale = cache.get("test_key")
    assert data is None
    assert is_stale is False


@pytest.mark.asyncio
async def test_http_get_with_retry_success():
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await http_get_with_retry(client, "https://api.example.com/test", max_retries=1)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_http_get_with_retry_transient_failure_then_success():
    attempts = 0

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, json={"status": "recovered"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await http_get_with_retry(
            client, "https://api.example.com/retry", max_retries=2, initial_backoff=0.01
        )
        assert attempts == 2
        assert resp.status_code == 200
        assert resp.json() == {"status": "recovered"}


@pytest.mark.asyncio
async def test_http_get_with_retry_timeout():
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Connection timed out")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.TimeoutException):
            await http_get_with_retry(
                client, "https://api.example.com/timeout", max_retries=1, initial_backoff=0.01
            )


@pytest.mark.asyncio
async def test_fallback_chain_primary_success():
    cache = ResilientCache()

    async def primary():
        return {"data": "primary"}

    async def secondary():
        return {"data": "secondary"}

    providers = [("Primary", primary), ("Secondary", secondary)]
    res, src = await execute_fallback_chain(providers, cache_key="chain_1", cache=cache)
    assert res == {"data": "primary"}
    assert src == "Primary"


@pytest.mark.asyncio
async def test_fallback_chain_primary_fails_secondary_succeeds():
    cache = ResilientCache()

    async def primary():
        raise RuntimeError("Primary down")

    async def secondary():
        return {"data": "secondary"}

    providers = [("Primary", primary), ("Secondary", secondary)]
    res, src = await execute_fallback_chain(providers, cache_key="chain_2", cache=cache)
    assert res == {"data": "secondary"}
    assert src == "Secondary"


@pytest.mark.asyncio
async def test_fallback_chain_all_fail_returns_stale_cache():
    cache = ResilientCache(default_fresh_ttl=0.1, default_stale_ttl=1.0)
    cache.set("chain_3", {"data": "old_cached"})
    await asyncio.sleep(0.15)  # Make it stale

    async def primary():
        raise RuntimeError("Primary down")

    async def secondary():
        return None

    providers = [("Primary", primary), ("Secondary", secondary)]

    def annotate(d):
        d_copy = dict(d)
        d_copy["stale"] = True
        return d_copy

    res, src = await execute_fallback_chain(
        providers, cache_key="chain_3", cache=cache, attach_stale_note=annotate
    )
    assert res == {"data": "old_cached", "stale": True}
    assert src == "Stale Cache"


@pytest.mark.asyncio
async def test_fallback_chain_all_fail_no_cache():
    cache = ResilientCache()

    async def primary():
        raise RuntimeError("Primary down")

    providers = [("Primary", primary)]
    res, src = await execute_fallback_chain(providers, cache_key="chain_4", cache=cache)
    assert res is None
    assert src == "Unavailable"
