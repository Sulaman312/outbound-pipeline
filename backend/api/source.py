"""Finding companies for an ICP, from one or more sources.

POST /source/preview is the dry run: it reads only our database and never calls a source.
POST /source/run spends credits, and only when the body repeats the exact number of credits
the run can spend. Same rules as `outbound source --live`: key set, cap set, cap never exceeded.
Sources run one after another in the order given, all saving into the same companies table.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend import db
from backend.api.deps import get_conn, get_settings, icp_or_400, sentence
from backend.config import Settings
from backend.db import Connection
from backend.icps import Icp
from backend.sources import BY_KEY
from backend.stages import source

router = APIRouter(tags=["source"])


class SourceRequest(BaseModel):
    icp: str
    sources: list[str] = ["apollo"]
    pages: int = 1


class RunRequest(SourceRequest):
    confirm_credits: int  # must equal the most this run can spend, all sources together


def _checked(body: SourceRequest, conn: Connection) -> Icp:
    icp = icp_or_400(conn, body.icp)
    assert icp is not None
    if not body.sources:
        raise HTTPException(400, "Pick at least one source")
    unknown = [key for key in body.sources if key not in BY_KEY]
    if unknown:
        raise HTTPException(400, f"No source called {unknown[0]!r}")
    problem = source.pages_problem(body.pages)
    if problem:
        raise HTTPException(400, sentence(problem))
    return icp


def _credits(body: SourceRequest) -> int:
    return sum(source.credits_for(key, body.pages) for key in body.sources)


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
        previews.append(
            {
                "source": key,
                "label": BY_KEY[key].label,
                "text": source.describe(conn, icp, key, pages=body.pages, cap=cap),
                "credits": source.credits_for(key, body.pages),
                "problem": sentence(problem) if problem else None,
            }
        )
    return {"previews": previews, "credits": _credits(body)}


@router.post("/source/run")
def run(
    body: RunRequest,
    request: Request,
    conn: Annotated[Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    icp = _checked(body, conn)
    credits = _credits(body)
    if body.confirm_credits != credits:
        raise HTTPException(
            400, f"Tick “Spend up to {credits} credits” to confirm this run. Nothing was spent."
        )
    ready = []
    for key in body.sources:  # check every source before spending on any
        cap = source.cap_for(settings.caps, key)
        api_key = os.environ.get(BY_KEY[key].key_env, "").strip()
        problem = source.icp_problem(icp, key) or source.live_problem(key, api_key, cap)
        if problem:
            raise HTTPException(400, sentence(problem))
        ready.append((key, api_key, cap))
    runs = []
    for key, api_key, cap in ready:
        with request.app.state.new_http_client() as client:
            result = source.run_live(
                conn, icp, key, client=client, api_key=api_key, cap=cap, pages=body.pages
            )
        used = db.usage_this_month(conn, key, BY_KEY[key].cap_unit)
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
