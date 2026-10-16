"""The local web app: the JSON routes under /api, and the built screens from ui/dist.

There is no login, so it only listens on 127.0.0.1 (see `outbound serve`) and refuses requests
that come from another website (Host or Origin not this computer).
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint

from backend.api import clay, companies, leads, overview, source, suppression
from backend.config import ConfigError, load_env
from backend.http import new_client

UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"
LOCAL_HOSTS = ("127.0.0.1", "localhost")

log = logging.getLogger("outbound")


async def _local_origin_only(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Refuse a change sent by a page from another site (a browser always sends Origin then)."""
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD") and origin:
        if urlparse(origin).hostname not in LOCAL_HOSTS:
            return JSONResponse({"detail": "Requests from other websites are refused."}, 403)
    return await call_next(request)


async def _config_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": f"Config error: {exc}"}, 500)


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unexpected error on %s %s", request.method, request.url.path)
    return JSONResponse(
        {"detail": f"Something went wrong ({type(exc).__name__}). The terminal shows details."},
        500,
    )


def create_app(root: Path, *, ui_dist: Path = UI_DIST) -> FastAPI:
    """The app for the project folder `root`. Serves ui_dist at / when it has been built."""
    load_env(root / ".env")
    app = FastAPI(
        title="Arsuno outbound",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.root = root
    app.state.new_http_client = new_client  # tests swap in a fake Apollo
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(LOCAL_HOSTS))
    app.middleware("http")(_local_origin_only)
    app.add_exception_handler(ConfigError, _config_error)
    app.add_exception_handler(Exception, _unexpected_error)
    for module in (overview, source, companies, clay, leads, suppression):
        app.include_router(module.router, prefix="/api")
    if (ui_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=ui_dist, html=True), name="ui")
    return app
