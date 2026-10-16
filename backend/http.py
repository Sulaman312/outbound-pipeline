"""The one place that sends HTTP requests: timeouts, and retries on rate limits and server errors.

Provider clients pass in an httpx.Client, so tests can swap in a fake transport.
Dry runs never get here.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

TIMEOUT_SECONDS = 30.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_WAIT_SECONDS = 60.0


class HttpError(Exception):
    """The request never got a response (network down, couldn't connect)."""


def new_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_SECONDS)


def _wait_seconds(attempt: int, retry_after: str | None) -> float:
    if retry_after and retry_after.strip().isdigit():
        return min(float(retry_after), MAX_WAIT_SECONDS)
    return float(2**attempt)  # 1, 2, 4 ...


def send(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: list[tuple[str, str]] | None = None,
    json: Any = None,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """Send a request and return the response, whatever its status.

    Retries a 429 or 5xx response, and a failure to connect. It doesn't retry a timeout after
    the request was sent, because the provider may already have charged for it.
    """
    for attempt in range(retries + 1):
        try:
            response = client.request(method, url, headers=headers, params=params, json=json)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if attempt == retries:
                raise HttpError(f"could not connect: {exc}") from exc
            sleep(_wait_seconds(attempt, None))
            continue
        except httpx.TransportError as exc:
            raise HttpError(f"request failed: {exc}") from exc
        if response.status_code in RETRY_STATUSES and attempt < retries:
            sleep(_wait_seconds(attempt, response.headers.get("Retry-After")))
            continue
        return response
    raise AssertionError("unreachable")
