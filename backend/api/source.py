"""Segments, and finding companies through Apollo.

POST /source/preview is the dry run: it reads only our database and never calls Apollo.
POST /source/run spends credits, and only when the body repeats the exact number of credits
the run can spend. Same rules as `outbound source --live`: key set, cap set, cap never exceeded.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend import db
from backend.api.deps import get_conn, get_segments, get_settings, segment_or_400, sentence
from backend.config import Segment, Settings
from backend.db import Connection
from backend.stages import source

router = APIRouter(tags=["source"])


class SourceRequest(BaseModel):
    segment: str
    pages: int = 1


class RunRequest(SourceRequest):
    confirm_credits: int  # must equal the most this run can spend


@router.get("/segments")
def list_segments(
    conn: Annotated[Connection, Depends(get_conn)],
    segments: Annotated[dict[str, Segment], Depends(get_segments)],
) -> list[dict[str, Any]]:
    saved = db.count_companies(conn)
    return [
        {
            **asdict(segment),
            "saved": saved.get(key, 0),
            "waiting_for_clay": db.count_waiting_for_clay(conn, key),
        }
        for key, segment in sorted(segments.items())
    ]


def _checked(body: SourceRequest, segments: dict[str, Segment]) -> Segment:
    segment = segment_or_400(segments, body.segment)
    assert segment is not None
    problem = source.pages_problem(body.pages)
    if problem:
        raise HTTPException(400, sentence(problem))
    return segment


def _apollo_cap(settings: Settings) -> int | None:
    return settings.caps.get("apollo", {}).get("credits")


@router.post("/source/preview")
def preview(
    body: SourceRequest,
    conn: Annotated[Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
    segments: Annotated[dict[str, Segment], Depends(get_segments)],
) -> dict[str, Any]:
    segment = _checked(body, segments)
    cap = _apollo_cap(settings)
    return {
        "text": source.describe(conn, segment, pages=body.pages, cap=cap),
        "credits": source.credits_for(body.pages),
        "problem": source.live_problem(os.environ.get("APOLLO_API_KEY", "").strip(), cap),
    }


@router.post("/source/run")
def run(
    body: RunRequest,
    request: Request,
    conn: Annotated[Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
    segments: Annotated[dict[str, Segment], Depends(get_segments)],
) -> dict[str, Any]:
    segment = _checked(body, segments)
    credits = source.credits_for(body.pages)
    if body.confirm_credits != credits:
        raise HTTPException(
            400, f"Tick “Spend up to {credits} credits” to confirm this run. Nothing was spent."
        )
    api_key = os.environ.get("APOLLO_API_KEY", "").strip()
    cap = _apollo_cap(settings)
    problem = source.live_problem(api_key, cap)
    if problem:
        raise HTTPException(400, problem)
    assert cap is not None
    with request.app.state.new_http_client() as client:
        result = source.run_live(
            conn, segment, client=client, api_key=api_key, cap=cap, pages=body.pages
        )
    used = db.usage_this_month(conn, source.PROVIDER, source.UNIT)
    return {
        "summary": source.summarize(result, used=used, cap=cap),
        "result": asdict(result),
        "used": used,
        "cap": cap,
    }
