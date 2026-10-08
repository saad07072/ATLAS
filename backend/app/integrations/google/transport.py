from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.integrations.google.errors import GoogleIntegrationError


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        ...


class UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request = Request(
            url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status_code=response.status,
                    body=response.read(),
                )
        except HTTPError as exc:
            return HttpResponse(
                status_code=exc.code,
                body=exc.read(),
            )
        except (URLError, TimeoutError, OSError) as exc:
            raise GoogleIntegrationError(
                "network_error",
                "The Google service could not be reached. Please try again.",
            ) from None
