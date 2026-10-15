"""http.py: retries and when not to retry."""

from __future__ import annotations

import httpx
import pytest

from outbound.http import HttpError, send


def client_with(*steps: object) -> tuple[httpx.Client, list[int]]:
    """Each step is a status code to answer with, or an exception to raise."""
    queue = list(steps)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        step = queue.pop(0)
        if isinstance(step, Exception):
            raise step
        headers = {"Retry-After": "7"} if step == 503 else {}
        return httpx.Response(step, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_retries_rate_limit_then_succeeds() -> None:
    client, calls = client_with(429, 429, 200)
    waits: list[float] = []
    response = send(client, "POST", "https://api.example.com/x", sleep=waits.append)
    assert response.status_code == 200
    assert len(calls) == 3
    assert waits == [1.0, 2.0]


def test_honours_retry_after() -> None:
    client, _ = client_with(503, 200)
    waits: list[float] = []
    send(client, "GET", "https://api.example.com/x", sleep=waits.append)
    assert waits == [7.0]


def test_gives_up_and_returns_last_response() -> None:
    client, calls = client_with(429, 429, 429, 429)
    response = send(client, "GET", "https://api.example.com/x", sleep=lambda s: None)
    assert response.status_code == 429
    assert len(calls) == 4


def test_client_errors_are_not_retried() -> None:
    client, calls = client_with(400)
    assert send(client, "GET", "https://api.example.com/x", sleep=lambda s: None).status_code == 400
    assert len(calls) == 1


def test_connect_errors_are_retried() -> None:
    client, calls = client_with(httpx.ConnectError("down"), 200)
    assert send(client, "GET", "https://api.example.com/x", sleep=lambda s: None).status_code == 200
    assert len(calls) == 2


def test_connect_errors_give_up() -> None:
    client, _ = client_with(*[httpx.ConnectError("down")] * 4)
    with pytest.raises(HttpError, match="could not connect"):
        send(client, "GET", "https://api.example.com/x", sleep=lambda s: None)


def test_read_timeout_is_not_retried() -> None:
    # the request may already have been charged, so don't send it twice
    client, calls = client_with(httpx.ReadTimeout("slow"), 200)
    with pytest.raises(HttpError, match="request failed"):
        send(client, "GET", "https://api.example.com/x", sleep=lambda s: None)
    assert len(calls) == 1
