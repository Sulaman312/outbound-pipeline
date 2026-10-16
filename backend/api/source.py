"""Finding companies for an ICP, from one or more sources.

POST /source/preview is the dry run: it reads only our database and never calls a source.
POST /source/run spends, and only when the body repeats, for every source picked, the exact
amount that source can spend (its own tick box on the page): key set, cap set, cap never
exceeded. Sources run in the order of backend/sources.py
(Apollo, then Google Maps), all saving into the same companies table.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.api.deps import get_conn, get_settings, icp_or_400, sentence
from backend.config import Settings
from backend.db import Connection
from backend.icps import Icp
from backend.sources import BY_KEY, SOURCES
from backend.stages import source

router = APIRouter(tags=["source"])


class SourceRequest(BaseModel):
    icp: str
    sources: list[str] = ["apollo"]
    pages: int = 1


class RunRequest(SourceRequest):
    confirm: dict[str, int]  # per source: must equal the most that source can spend


def _checked(body: SourceRequest, conn: Connection) -> Icp:
    icp = icp_or_400(conn, body.icp)
    assert icp is not None
    if not body.sources:
        raise HTTPException(400, "Pick at least one source")
    unknown = [key for key in body.sources if key not in BY_KEY]
    if unknown:
        raise HTTPException(400, f"No source called {unknown[0]!r}")
    body.sources = [s.key for s in SOURCES if s.key in body.sources]  # always Apollo first
    problem = source.pages_problem(body.pages)
    if problem:
        raise HTTPException(400, sentence(problem))
    return icp


def confirm_label(key: str, amount: int) -> str:
    """The words on the tick box, like "Spend up to 6 Google Maps requests"."""
    info = BY_KEY[key]
    label = f"Spend up to {amount} {info.label} {info.cap_unit}"
    if key == source.GOOGLE:
        label += " (free up to 1,000 a month)"
    return label


@router.post("/source/preview")
def preview(
    body: SourceRequest,
    conn: Annotated[Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    icp = _checked(body, conn)
    previews = []
    for key in body.sources:
        cap = source.cap_for(settings.caps, key)
        problem = source.icp_problem(icp, key)
        if problem is None:
            api_key = os.environ.get(BY_KEY[key].key_env, "").strip()
            problem = source.live_problem(key, api_key, cap)
        amount = source.credits_for(conn, icp, key, body.pages)
        previews.append(
            {
                "source": key,
                "label": BY_KEY[key].label,
                "text": source.describe(conn, icp, key, pages=body.pages, cap=cap),
                "credits": amount,
                "confirm_label": confirm_label(key, amount),
                "problem": sentence(problem) if problem else None,
            }
        )
    return {"previews": previews}


@router.post("/source/run")
def run(
    body: RunRequest,
    request: Request,
    conn: Annotated[Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    icp = _checked(body, conn)
    ready = []
    for key in body.sources:  # check every source, and its own tick box, before spending
        cap = source.cap_for(settings.caps, key)
        api_key = os.environ.get(BY_KEY[key].key_env, "").strip()
        problem = source.icp_problem(icp, key) or source.live_problem(key, api_key, cap)
        if problem:
            raise HTTPException(400, sentence(problem))
        amount = source.credits_for(conn, icp, key, body.pages)
        if body.confirm.get(key) != amount:
            raise HTTPException(
                400, f"Tick “{confirm_label(key, amount)}” to confirm. Nothing was spent."
            )
        ready.append((key, api_key, cap))
    runs = []
    for key, api_key, cap in ready:
        with request.app.state.new_http_client() as client:
            result = source.run_live(
                conn, icp, key, client=client, api_key=api_key, cap=cap, pages=body.pages
            )
        used = source.used_this_month(conn, key)
        runs.append(
            {
                "source": key,
                "label": BY_KEY[key].label,
                "summary": source.summarize(result, used=used, cap=cap),
                "result": asdict(result),
                "used": used,
                "cap": cap,
            }
        )
    return {"runs": runs}
