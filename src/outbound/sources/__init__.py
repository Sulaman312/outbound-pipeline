"""Registry of lead sources. Config refers to sources by these names."""

from __future__ import annotations

import httpx

from outbound.config import Config
from outbound.http import ApiClient
from outbound.sources.apollo import ApolloSource
from outbound.sources.base import LeadSource, PlannedRequest, SourceOptions
from outbound.sources.google_places import GooglePlacesSource
from outbound.store import Store

SOURCES: dict[str, type[LeadSource]] = {
    ApolloSource.name: ApolloSource,
    GooglePlacesSource.name: GooglePlacesSource,
}

# How each provider expects its key. Kept here so adapters never read secrets.
_AUTH_HEADER = {
    "apollo": "X-Api-Key",
    "google_places": "X-Goog-Api-Key",
}


def build_source(
    name: str,
    config: Config,
    store: Store,
    *,
    live: bool,
    transport: httpx.BaseTransport | None = None,
) -> LeadSource:
    """Build a source. With live=False no key is read and no request can be sent."""
    cls = SOURCES[name]
    provider = config.settings.provider(name)
    headers = {"Content-Type": "application/json"}
    if live:
        headers[_AUTH_HEADER[name]] = provider.api_key()
    client = ApiClient(
        name,
        provider,
        config.settings.http,
        store,
        headers=headers,
        transport=transport if live else _BlockedTransport(),
    )
    return cls(client)


class _BlockedTransport(httpx.BaseTransport):
    """Used in dry runs: any attempt to reach the network is a bug."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"Dry run tried to call {request.url}")


__all__ = ["SOURCES", "LeadSource", "PlannedRequest", "SourceOptions", "build_source"]
