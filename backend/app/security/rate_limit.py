from __future__ import annotations

import logging
import math
import re
import threading
import time
from typing import Callable
from uuid import UUID

from fastapi import Depends, Request, Response

from backend.app.config.settings import settings
from backend.app.core.exceptions import ApplicationError
from backend.app.security.identity import get_optional_authenticated_user_id

logger = logging.getLogger(__name__)


class RateLimitConfig:
    def __init__(self, requests: int, window_seconds: int) -> None:
        if requests <= 0:
            raise ValueError("Rate limit requests must be positive.")
        if window_seconds <= 0:
            raise ValueError("Rate limit window must be positive.")
        self.requests = requests
        self.window_seconds = window_seconds

    def __repr__(self) -> str:
        return f"<RateLimitConfig {self.requests}/{self.window_seconds}s>"


def parse_rate_limit(rate_limit_str: str) -> RateLimitConfig:
    """
    Parses rate limit strings such as:
    - "10/minute", "10/min", "10/m"
    - "5/second", "5/s"
    - "100/hour", "100/h"
    - "1000/day", "1000/d"
    - "10/60" (10 requests per 60 seconds)
    """
    cleaned = rate_limit_str.strip().lower()
    match = re.match(r"^(\d+)\s*/\s*([a-z0-9_]+)$", cleaned)
    if not match:
        raise ValueError(f"Invalid rate limit format: '{rate_limit_str}'. Expected format like '10/minute'.")

    requests = int(match.group(1))
    unit = match.group(2)

    if unit.isdigit():
        window_seconds = int(unit)
    elif unit in {"s", "sec", "second", "seconds"}:
        window_seconds = 1
    elif unit in {"m", "min", "minute", "minutes"}:
        window_seconds = 60
    elif unit in {"h", "hr", "hour", "hours"}:
        window_seconds = 3600
    elif unit in {"d", "day", "days"}:
        window_seconds = 86400
    else:
        raise ValueError(f"Unknown time unit '{unit}' in rate limit '{rate_limit_str}'.")

    return RateLimitConfig(requests=requests, window_seconds=window_seconds)


class InMemoryRateLimiter:
    """
    Thread-safe in-memory sliding-window log rate limiter.
    
    LIMITATION NOTICE:
    This rate limiter operates in-memory for the current Python process.
    In multi-worker deployments (e.g., multiple Uvicorn workers or containers),
    limits are enforced independently per process and will reset on process restart.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, list[float]] = {}
        self._last_cleanup: float = time.monotonic()

    def check(
        self,
        key: str,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> tuple[bool, int, int, int]:
        """
        Evaluates whether a request with the given key is allowed.
        Returns:
            allowed: bool
            remaining: int (remaining allowed requests in current window)
            reset_seconds: int (seconds until the window resets)
            retry_after: int (seconds caller should wait before retrying)
        """
        current_time = time.monotonic() if now is None else now

        with self._lock:
            # Periodic cleanup of completely stale keys every 60 seconds
            if current_time - self._last_cleanup > 60.0:
                self._prune_stale_keys(current_time)
                self._last_cleanup = current_time

            timestamps = self._events.get(key, [])
            cutoff = current_time - window_seconds
            valid_timestamps = [t for t in timestamps if t > cutoff]

            if len(valid_timestamps) >= limit:
                # Limit exceeded
                oldest_in_window = valid_timestamps[0]
                retry_after = max(1, math.ceil(oldest_in_window + window_seconds - current_time))
                reset_seconds = retry_after
                self._events[key] = valid_timestamps
                return False, 0, reset_seconds, retry_after

            # Request allowed: record this timestamp
            valid_timestamps.append(current_time)
            self._events[key] = valid_timestamps
            remaining = max(0, limit - len(valid_timestamps))
            reset_seconds = window_seconds
            return True, remaining, reset_seconds, 0

    def _prune_stale_keys(self, current_time: float) -> None:
        """Removes keys with no recent events to prevent memory unbounded growth."""
        keys_to_delete = []
        for key, timestamps in self._events.items():
            # If no event in the last 2 hours, drop key
            if not timestamps or (current_time - timestamps[-1] > 7200.0):
                keys_to_delete.append(key)
        for key in keys_to_delete:
            del self._events[key]

    def reset(self) -> None:
        """Clears all stored rate limit history. Used primarily in test suites."""
        with self._lock:
            self._events.clear()


# Global in-memory rate limiter instance
rate_limiter_instance = InMemoryRateLimiter()


def resolve_client_identity(
    request: Request,
    user_id: UUID | None = None,
) -> str:
    """
    Resolves client identity for rate limiting:
    - If user is authenticated, uses verified user ID: 'user:<user_id>'.
    - If unauthenticated, uses client IP: 'ip:<client_ip>'.
      X-Forwarded-For is only parsed if trust_proxy_headers is explicitly True
      AND the immediate client host is in trusted_proxies.
    """
    if user_id is not None:
        return f"user:{user_id}"

    client_host = request.client.host if request.client else "unknown"

    if settings.trust_proxy_headers and client_host in settings.trusted_proxies:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Parse the first (original client) IP in the chain
            first_ip = forwarded_for.split(",")[0].strip()
            if first_ip:
                return f"ip:{first_ip}"

    return f"ip:{client_host}"


def create_rate_limit_dependency(
    category: str,
    limit_override: str | None = None,
) -> Callable[..., None]:
    """
    Creates a FastAPI dependency that evaluates rate limits for incoming requests.
    Stops unauthorized execution BEFORE reaching handlers, tools, or LLM providers.
    """

    async def rate_limit_dependency(
        request: Request,
        response: Response,
        user_id: UUID | None = Depends(get_optional_authenticated_user_id),
    ) -> None:
        if not settings.rate_limit_enabled:
            return

        # Determine configured limit string
        limit_str = limit_override
        if not limit_str:
            if category == "chat":
                limit_str = settings.rate_limit_chat
            elif category == "workflows":
                limit_str = settings.rate_limit_workflows
            elif category == "confirmations":
                limit_str = settings.rate_limit_confirmations
            elif category == "oauth":
                limit_str = settings.rate_limit_oauth
            elif user_id is not None:
                limit_str = settings.rate_limit_authenticated_default
            else:
                limit_str = settings.rate_limit_unauthenticated_default

        try:
            config = parse_rate_limit(limit_str)
        except ValueError:
            logger.warning("Invalid rate limit '%s' configured for category '%s'. Falling back to 60/minute.", limit_str, category)
            config = RateLimitConfig(requests=60, window_seconds=60)

        identity = resolve_client_identity(request, user_id=user_id)
        rate_key = f"{category}:{identity}"

        allowed, remaining, reset_seconds, retry_after = rate_limiter_instance.check(
            key=rate_key,
            limit=config.requests,
            window_seconds=config.window_seconds,
        )

        if not allowed:
            logger.warning(
                "Rate limit exceeded for %s on %s %s. Limit: %d/%ds. Retry-After: %ds",
                rate_key,
                request.method,
                request.url.path,
                config.requests,
                config.window_seconds,
                retry_after,
            )
            raise ApplicationError(
                f"Rate limit exceeded for {category}. Please try again in {retry_after} seconds.",
                code="rate_limit_exceeded",
                status_code=429,
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(config.requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_seconds),
                },
            )

        # Attach informational rate limit headers on allowed responses
        response.headers["X-RateLimit-Limit"] = str(config.requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_seconds)

    return rate_limit_dependency


# Pre-configured route dependencies
rate_limit_chat = create_rate_limit_dependency("chat")
rate_limit_workflows = create_rate_limit_dependency("workflows")
rate_limit_confirmations = create_rate_limit_dependency("confirmations")
rate_limit_oauth = create_rate_limit_dependency("oauth")
rate_limit_general = create_rate_limit_dependency("general")

