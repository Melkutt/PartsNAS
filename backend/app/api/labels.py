"""Printable barcode / QR labels for parts.

`GET /api/parts/{id}/label.png?fmt=qr|code128` -> a PNG, rendered fully
offline (see ../labels.py). The layout/printing itself lives in the static
`frontend/label.html` page, not here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..labels import code128_png, qr_png
from ..models import Part

router = APIRouter(prefix="/api/parts", tags=["labels"])

_RENDER = {"qr": qr_png, "code128": code128_png}


@router.get("/{part_id}/label.png")
def part_label(part_id: str, fmt: str = "qr", db: Session = Depends(get_db)):
    p = db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "part not found")
    render = _RENDER.get(fmt)
    if render is None:
        raise HTTPException(400, "fmt must be 'qr' or 'code128'")
    png = render(p.id)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})
