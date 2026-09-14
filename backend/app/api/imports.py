"""File import endpoints.

`POST /api/import/partsbox`      multipart: file=<xlsx>, dry_run=<bool>
`POST /api/import/mouser-order`  multipart: file=<xls|xlsx>, dry_run=<bool>
`POST /api/import/kit-list`      multipart: file=<xlsx|xls|csv>, dry_run=<bool>
    dry_run=true  -> parse and report what would happen, change nothing
    dry_run=false -> apply
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..importers import kit_list, mouser_order, partsbox

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/partsbox")
async def import_partsbox(
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "expected a .xlsx PartsBox export")
    data = await file.read()
    tmp = Path(tempfile.gettempdir()) / f"partsnas-import-{file.filename}"
    tmp.write_bytes(data)
    try:
        return partsbox.run(db, tmp, commit=not dry_run)
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/mouser-order")
async def import_mouser_order(
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith((".xls", ".xlsx")):
        raise HTTPException(400, "expected a Mouser order-history export (.xls or .xlsx)")
    data = await file.read()
    tmp = Path(tempfile.gettempdir()) / f"partsnas-import-{file.filename}"
    tmp.write_bytes(data)
    try:
        return mouser_order.run(db, tmp, commit=not dry_run)
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/kit-list")
async def import_kit_list(
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith((".xls", ".xlsx", ".csv")):
        raise HTTPException(400, "expected a vendor kit-list export (.xls, .xlsx or .csv)")
    data = await file.read()
    tmp = Path(tempfile.gettempdir()) / f"partsnas-import-{file.filename}"
    tmp.write_bytes(data)
    try:
        return kit_list.run(db, tmp, commit=not dry_run)
    finally:
        tmp.unlink(missing_ok=True)
