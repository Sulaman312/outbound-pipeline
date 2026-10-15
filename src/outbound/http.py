"""One HTTP client for every provider: retries, pacing, and the budget guard.

Adapters never call httpx directly. Going through `ApiClient` means every
provider gets the same behaviour on 429/5xx, and no adapter can spend past a
monthly cap by accident: the cap is checked before each request and the usage
is recorded the moment a request is sent.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from outbound.config import HttpSettings, ProviderSettings
from outbound.errors import BudgetExceededError, ProviderError
from outbound.store import Store

log = logging.getLogger(__name__)

_RETRY_STATUSES = {429, 500, 502, 503, 504}


def current_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


class ApiClient:
    def __init__(
        self,
        provider: str,
        settings: ProviderSettings,
        http: HttpSettings,
        store: Store,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.provider = provider
        self.settings = settings
        self.http = http
        self.store = store
        self._sleep = sleep
        self._last_request = 0.0
        self._client = httpx.Client(
            base_url=settings.base_url or "",
            headers=headers or {},
            timeout=http.timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def remaining_budget(self) -> int | None:
        cap = self.settings.monthly_request_cap
        if cap is None:
            return None
        return max(0, cap - self.store.usage(self.provider, current_month()))

    def post(self, path: str, json: dict[str, Any], headers: dict[str, str] | None = None) -> dict:
        return self._request("POST", path, json=json, headers=headers)

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return self._request("GET", path, params=params)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        for attempt in range(self.http.max_retries + 1):
            self._check_budget()
            self._pace()
            response = self._client.request(method, path, **kwargs)
            self.store.add_usage(self.provider, current_month())

            if response.status_code < 400:
                return response.json()
            if response.status_code in _RETRY_STATUSES and attempt < self.http.max_retries:
                wait = self._retry_after(response) or self.http.backoff_seconds * 2**attempt
                log.warning(
                    "%s HTTP %s, retrying in %.0fs", self.provider, response.status_code, wait
                )
                self._sleep(wait)
                continue
            raise ProviderError(self.provider, response.status_code, response.text)
        raise AssertionError("unreachable")

    def _check_budget(self) -> None:
        remaining = self.remaining_budget()
        if remaining is not None and remaining <= 0:
            raise BudgetExceededError(
                f"{self.provider}: monthly cap of {self.settings.monthly_request_cap} "
                f"requests reached for {current_month()}"
            )

    def _pace(self) -> None:
        gap = self.settings.min_seconds_between_requests
        if gap:
            wait = self._last_request + gap - time.monotonic()
            if wait > 0:
                self._sleep(wait)
        self._last_request = time.monotonic()

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("retry-after")
        try:
            return float(value) if value else None
        except ValueError:
            return None
