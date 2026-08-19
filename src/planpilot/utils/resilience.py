from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Tuple, TypeVar
import httpx
from planpilot.utils.logger import logger

# Shared cache file path — both agent process and MCP subprocess resolve to the same file
_CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_CACHE_FILE = _CACHE_DIR / "planpilot_cache.json"

T = TypeVar("T")

# Transient status codes that trigger a retry
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class CacheEntry:
    """In-memory cache entry supporting fresh and stale TTLs."""

    def __init__(self, data: Any, timestamp: float, fresh_ttl: float = 600.0, stale_ttl: float = 3600.0):
        self.data = data
        self.timestamp = timestamp
        self.fresh_ttl = fresh_ttl
        self.stale_ttl = stale_ttl

    def is_fresh(self, now: float | None = None) -> bool:
        now = now or time.time()
        return (now - self.timestamp) <= self.fresh_ttl

    def is_stale(self, now: float | None = None) -> bool:
        now = now or time.time()
        age = now - self.timestamp
        return self.fresh_ttl < age <= (self.fresh_ttl + self.stale_ttl)

    def is_expired(self, now: float | None = None) -> bool:
        now = now or time.time()
        return (now - self.timestamp) > (self.fresh_ttl + self.stale_ttl)


class ResilientCache:
    """JSON file-backed, TTL-based cache — persists across processes and restarts.

    The cache file (planpilot_cache.json) is human-readable. Both the agent
    process and the MCP subprocess resolve to the same file path, so a result
    fetched in one query is a genuine cache hit in the next.

    JSON schema per entry::

        {
          "<cache_key>": {
            "data": <any JSON-serializable value>,
            "timestamp": <unix float>,
            "fresh_ttl": <seconds float>,
            "stale_ttl": <seconds float>
          }
        }
    """

    def __init__(self, default_fresh_ttl: float = 600.0, default_stale_ttl: float = 3600.0,
                 cache_file: Path = _CACHE_FILE):
        self._cache_file = Path(cache_file)
        self.default_fresh_ttl = default_fresh_ttl
        self.default_stale_ttl = default_stale_ttl
        # In-memory mirror for backward-compat with tests that access ._store directly
        self._store: dict[str, CacheEntry] = {}

    # ------------------------------------------------------------------
    # Internal JSON helpers
    # ------------------------------------------------------------------

    def _read_json(self) -> dict[str, Any]:
        try:
            return json.loads(self._cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_json(self, db: dict[str, Any]) -> None:
        self._cache_file.write_text(
            json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> tuple[Any | None, bool]:
        """Return (data, is_stale). Returns (None, False) if missing or expired."""
        now = time.time()
        db = self._read_json()
        raw = db.get(key)
        if not raw:
            return None, False
        entry = CacheEntry(
            data=raw["data"],
            timestamp=raw["timestamp"],
            fresh_ttl=raw.get("fresh_ttl", self.default_fresh_ttl),
            stale_ttl=raw.get("stale_ttl", self.default_stale_ttl),
        )
        if entry.is_fresh(now):
            return entry.data, False
        elif entry.is_stale(now):
            return entry.data, True
        else:
            self._delete(key)
            return None, False

    def set(self, key: str, data: Any, fresh_ttl: float | None = None, stale_ttl: float | None = None) -> None:
        """Store data under key in the JSON cache file."""
        now = time.time()
        f_ttl = fresh_ttl if fresh_ttl is not None else self.default_fresh_ttl
        s_ttl = stale_ttl if stale_ttl is not None else self.default_stale_ttl
        # Keep in-memory mirror in sync
        self._store[key] = CacheEntry(data=data, timestamp=now, fresh_ttl=f_ttl, stale_ttl=s_ttl)
        try:
            db = self._read_json()
            db[key] = {"data": data, "timestamp": now, "fresh_ttl": f_ttl, "stale_ttl": s_ttl}
            self._write_json(db)
        except Exception:
            pass  # fall back to in-memory only

    def _delete(self, key: str) -> None:
        self._store.pop(key, None)
        try:
            db = self._read_json()
            db.pop(key, None)
            self._write_json(db)
        except Exception:
            pass

    def clear(self) -> None:
        """Clear all entries from both memory and the JSON file."""
        self._store.clear()
        try:
            self._write_json({})
        except Exception:
            pass


# Global cache instance for service calls
global_cache = ResilientCache()


async def http_get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 8.0,
    max_retries: int = 2,
    initial_backoff: float = 0.5,
    backoff_factor: float = 2.0,
) -> httpx.Response:
    """Perform an HTTP GET request with timeout, retries, and exponential backoff.

    Retries on:
    - httpx.TimeoutException
    - httpx.NetworkError / TransportError / ConnectError
    - HTTP status codes 429, 500, 502, 503, 504
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            logger.debug(f"HTTP GET attempt {attempt + 1}/{max_retries + 1} for '{url}'")
            resp = await client.get(url, headers=headers, params=params, timeout=timeout)

            if resp.status_code in TRANSIENT_STATUS_CODES and attempt < max_retries:
                logger.warning(
                    f"HTTP GET to '{url}' returned transient status {resp.status_code}. "
                    f"Retrying ({attempt + 1}/{max_retries})..."
                )
                backoff = initial_backoff * (backoff_factor**attempt) + random.uniform(0, 0.1)
                await asyncio.sleep(backoff)
                continue

            resp.raise_for_status()
            return resp

        except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
            last_exc = exc
            if attempt < max_retries:
                backoff = initial_backoff * (backoff_factor**attempt) + random.uniform(0, 0.1)
                logger.warning(
                    f"HTTP GET to '{url}' failed with transient error: {exc}. "
                    f"Retrying in {backoff:.2f}s (attempt {attempt + 1}/{max_retries})..."
                )
                await asyncio.sleep(backoff)
            else:
                logger.error(f"HTTP GET to '{url}' failed after {max_retries + 1} attempts: {exc}")
                raise exc
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code in TRANSIENT_STATUS_CODES and attempt < max_retries:
                backoff = initial_backoff * (backoff_factor**attempt) + random.uniform(0, 0.1)
                logger.warning(
                    f"HTTP GET to '{url}' status error {exc.response.status_code}. "
                    f"Retrying in {backoff:.2f}s..."
                )
                await asyncio.sleep(backoff)
            else:
                logger.error(f"HTTP GET to '{url}' failed with status {exc.response.status_code}")
                raise exc

    if last_exc:
        raise last_exc
    raise RuntimeError(f"HTTP GET to '{url}' failed after max retries.")


async def execute_fallback_chain(
    providers: list[tuple[str, Callable[[], Awaitable[T]]]],
    cache_key: str | None = None,
    cache: ResilientCache | None = None,
    is_valid_result: Callable[[T], bool] | None = None,
    attach_stale_note: Callable[[T], T] | None = None,
) -> tuple[T | None, str]:
    """Execute a chain of providers with fallback and stale-cache support.

    Parameters:
    - providers: List of (provider_name, async_fn) tuples to try in order.
    - cache_key: Optional cache key for checking fresh/stale cache.
    - cache: ResilientCache instance to use (defaults to global_cache).
    - is_valid_result: Callable that returns True if the provider result is non-empty/valid.
    - attach_stale_note: Callable to annotate stale cache results.

    Returns (result, provider_source_name).
    """
    cache = cache or global_cache

    # 1. Check fresh cache
    if cache_key:
        cached_data, is_stale = cache.get(cache_key)
        if cached_data is not None and not is_stale:
            logger.info(f"⚡ [CACHE HIT] Fresh cache hit for '{cache_key}'")
            return cached_data, "Fresh Cache"

    # 2. Try providers in sequence
    for name, provider_fn in providers:
        try:
            logger.info(f"Attempting primary/secondary provider '{name}' for '{cache_key or 'request'}'")
            result = await provider_fn()

            valid = is_valid_result(result) if is_valid_result else (result is not None)
            if valid:
                logger.info(f"Provider '{name}' succeeded for '{cache_key or 'request'}'")
                if cache_key:
                    cache.set(cache_key, result)
                return result, name
            else:
                logger.warning(f"Provider '{name}' returned invalid or empty data for '{cache_key or 'request'}'")
        except Exception as exc:
            logger.warning(f"Provider '{name}' failed with error: {exc}. Trying next fallback...")

    # 3. All live providers failed -> check stale cache
    if cache_key:
        cached_data, is_stale = cache.get(cache_key)
        if cached_data is not None:
            logger.info(f"⚡ [STALE CACHE HIT] All live providers failed. Returning stale cached data for '{cache_key}'")
            if attach_stale_note:
                cached_data = attach_stale_note(cached_data)
            return cached_data, "Stale Cache"

    logger.error(f"All providers and cache options failed for '{cache_key or 'request'}'")
    return None, "Unavailable"
