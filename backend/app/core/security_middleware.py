from __future__ import annotations

import logging
from typing import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.config.settings import settings

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies security headers to all HTTP responses to protect against MIME-confusion,
    clickjacking, drive-by framing, and unauthorized resource embedding.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)

        # Content-type sniffing prevention
        response.headers.setdefault("X-Content-Type-Options", "nosniff")

        # Frame protection: prevent clickjacking
        response.headers.setdefault("X-Frame-Options", "DENY")

        # Referrer leakage prevention
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

        # Browser permissions control: restrict hardware/sensors
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), camera=(), microphone=(self)",
        )

        # Cross-domain policy restrictions
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")

        # API-safe Content-Security-Policy: disallow framing and execution on API responses
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )

        # HTTP Strict Transport Security (HSTS) when enabled or in production
        if settings.enable_hsts or settings.environment.lower() == "production":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        return response


class RequestSizeLimitMiddleware:
    """
    Pure ASGI middleware enforcing maximum incoming request body size limits.
    Rejects oversized payloads with HTTP 413 before loading unbounded data into memory.
    """

    def __init__(self, app: ASGIApp, max_body_size: int | None = None) -> None:
        self.app = app
        self.max_body_size = (
            max_body_size if max_body_size is not None else settings.max_request_body_bytes
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length_header = headers.get(b"content-length")

        if content_length_header:
            try:
                content_length = int(content_length_header.decode("latin1"))
                if content_length > self.max_body_size:
                    logger.warning(
                        "Payload too large (Content-Length: %d > %d max)",
                        content_length,
                        self.max_body_size,
                    )
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "payload_too_large",
                                "message": f"Request body exceeds maximum allowed size of {self.max_body_size} bytes.",
                            }
                        },
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        total_received = 0

        async def limited_receive() -> Message:
            nonlocal total_received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                total_received += len(body)
                if total_received > self.max_body_size:
                    logger.warning(
                        "Streaming payload exceeded size limit: %d > %d bytes",
                        total_received,
                        self.max_body_size,
                    )
                    raise PayloadTooLargeException()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except PayloadTooLargeException:
            response = JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": f"Request body exceeds maximum allowed size of {self.max_body_size} bytes.",
                    }
                },
            )
            await response(scope, receive, send)


class PayloadTooLargeException(Exception):
    """Internal sentinel exception when streaming body exceeds maximum allowed bytes."""
    pass

