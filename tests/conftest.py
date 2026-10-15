import json
from pathlib import Path

import httpx
import pytest

from outbound.config import load_config
from outbound.store import Store

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def config(tmp_path):
    cfg = load_config(CONFIG_DIR)
    cfg.settings.database = tmp_path / "test.db"
    cfg.settings.exports_dir = tmp_path / "exports"
    return cfg


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "test-apollo")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-places")


class FakeApi(httpx.BaseTransport):
    """Answers requests from a queue of (status, json) per path, records every request."""

    def __init__(self, responses: dict[str, list[tuple[int, dict]]]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.requests: list[httpx.Request] = []

    def handle_request(self, request):
        self.requests.append(request)
        queue = self.responses.get(request.url.path)
        if not queue:
            return httpx.Response(200, json={})
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    def bodies(self):
        return [json.loads(r.content) for r in self.requests]
