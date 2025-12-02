"""
Cache decorator for API endpoints to prevent duplicate Discord API calls
"""
import functools
import time
from typing import Any, Callable, Optional

# Simple in-memory cache
_cache: dict[str, tuple[Any, float]] = {}
_DEFAULT_TTL = 30  # 30 seconds


def _build_cache_key_parts(func_name: str, args: tuple, kwargs: dict) -> list[str]:
    """Build cache key parts from function arguments."""
    parts = [func_name]

    # Add positional args to key
    for arg in args:
        if isinstance(arg, (str, int, float, bool)):
            parts.append(str(arg))

    # Add keyword args to key
    for k, v in sorted(kwargs.items()):
        if isinstance(v, (str, int, float, bool)):
            parts.append(f"{k}={v}")

    return parts


def _get_cached_value(cache_key: str, ttl: int) -> tuple[Any, bool]:
    """Get value from cache if valid, return (value, is_valid)."""
    if cache_key not in _cache:
        return None, False

    cached_value, cached_time = _cache[cache_key]
    if time.time() - cached_time < ttl:
        return cached_value, True

    # Expired, remove from cache
    del _cache[cache_key]
    return None, False


def cache_endpoint(ttl: int = _DEFAULT_TTL, key_prefix: str = ""):
    """
    Cache decorator for async functions.

    Args:
        ttl: Time to live in seconds
        key_prefix: Prefix for cache key

    Usage:
        @cache_endpoint(ttl=60, key_prefix="channels")
        async def get_channels(server_id: int):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key from function name and arguments
            func_name = key_prefix or func.__name__
            cache_key_parts = _build_cache_key_parts(func_name, args, kwargs)
            cache_key = ":".join(cache_key_parts)

            # Check cache
            cached_value, is_valid = _get_cached_value(cache_key, ttl)
            if is_valid:
                return cached_value

            # Execute function
            result = await func(*args, **kwargs)

            # Store in cache
            _cache[cache_key] = (result, time.time())

            return result

        return wrapper
    return decorator


def invalidate_cache(pattern: Optional[str] = None):
    """
    Invalidate cache entries.

    Args:
        pattern: If provided, only invalidate keys containing this pattern.
                 If None, clear entire cache.
    """
    if pattern is None:
        _cache.clear()
    else:
        keys_to_delete = [k for k in _cache.keys() if pattern in k]
        for key in keys_to_delete:
            del _cache[key]


def get_cache_stats() -> dict:
    """Get cache statistics."""
    return {
        "size": len(_cache),
        "keys": list(_cache.keys()),
    }
