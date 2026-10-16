"""The Clay round trip: make the file for Clay, then read Clay's file back.

1. POST /clay/export claims the next companies and writes the file; GET .../file downloads it.
2. POST /clay/columns reads an uploaded Clay CSV and guesses which column is which.
3. POST /clay/import saves the people, using the columns the person checked.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend import db
from backend.api.deps import get_conn, get_root, icp_or_400, sentence
from backend.db import Connection
from backend.stages import enrich

router = APIRouter(prefix="/clay", tags=["clay"])


class ExportRequest(BaseModel):
    icp: str
    rows: int = enrich.DEFAULT_ROWS


@router.get("/batches")
def list_batches(conn: Annotated[Connection, Depends(get_conn)]) -> dict[str, Any]:
    return {
        "waiting": db.count_waiting_for_clay(conn),
        "batches": [dict(row) for row in db.list_batches(conn)],
    }


@router.post("/export")
def export(
    body: ExportRequest,
    conn: Annotated[Connection, Depends(get_conn)],
    root: Annotated[Path, Depends(get_root)],
) -> dict[str, Any]:
    icp_or_400(conn, body.icp)
    if body.rows < 1:
        raise HTTPException(400, "Rows must be at least 1")
    result = enrich.export_batch(conn, root, body.icp, body.rows)
    if result is None:
        raise HTTPException(
            404,
            f"Nothing from {body.icp} is waiting for Clay. Find more companies first "
            "(Find companies page).",
        )
    return {"batch_id": result.batch_id, "rows": result.rows, "file": result.path.name}


@router.get("/batches/{batch_id}/file")
def download_batch(
    batch_id: int,
    conn: Annotated[Connection, Depends(get_conn)],
    root: Annotated[Path, Depends(get_root)],
) -> FileResponse:
    batch = db.get_batch(conn, batch_id)
    clay_dir = (root / "data" / "clay").resolve()
    path = (root / str(batch["file"])).resolve() if batch else None
    if path is None or path.parent != clay_dir or not path.is_file():
        raise HTTPException(
            404, "That batch's file isn't on this computer. It was made on another laptop."
        )
    return FileResponse(path, media_type="text/csv", filename=path.name)


def _read_upload(file: UploadFile) -> tuple[list[str], list[dict[str, str]]]:
    headers, rows = enrich.read_csv(file.file.read().decode("utf-8-sig", errors="replace"))
    if not headers:
        raise HTTPException(400, "That file is empty or isn't a CSV.")
    return headers, rows


@router.post("/columns")
def columns(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    headers, rows = _read_upload(file)
    mapping = enrich.detect_columns(headers)
    return {
        "headers": headers,
        "rows": len(rows),
        "fields": [{"key": key, "label": label} for key, (label, _) in enrich.FIELDS.items()],
        "mapping": mapping,
        "missing": enrich.missing_fields(mapping),
    }


def _mapping(text: str) -> Iterator[tuple[str, str | None]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "mapping must be JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "mapping must be an object of field to column")
    for key, value in data.items():
        yield str(key), (str(value) if value else None)


@router.post("/import")
def import_file(
    conn: Annotated[Connection, Depends(get_conn)],
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str, Form()],
    account: Annotated[str | None, Form()] = None,
    credits: Annotated[float | None, Form()] = None,
) -> dict[str, Any]:
    headers, rows = _read_upload(file)
    try:
        checked = enrich.check_mapping(headers, dict(_mapping(mapping)))
    except ValueError as exc:
        raise HTTPException(400, sentence(str(exc))) from exc
    result = enrich.import_rows(conn, rows, checked, account=account or None, credits=credits)
    return {
        "summary": enrich.describe_import(conn, result, credits),
        "result": {**asdict(result), "states": dict(result.states)},
    }
