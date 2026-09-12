"""Printable barcode / QR labels for parts.

`GET /api/parts/{id}/label.png?fmt=qr|code128&h=<mm>` -> a PNG, rendered
fully offline (see ../labels.py). The layout/printing itself lives in
`frontend/label.html` (bulk) and the part detail's Label tab (single part).

`h` (code128 only, ignored for qr — a QR's size is width-driven, stretching
it would break scanning) asks the barcode to be drawn at roughly that total
height in mm to start with, so the frontend's CSS-level fit to the user's
chosen box is a small final adjustment rather than a large stretch of a
fixed-proportion image — much crisper at the extremes (e.g. a short numeric
code, which python-barcode would otherwise render nearly square).

The encoded payload is the part's MPN when it has one (recognisable, and
what you'd want to scan back into e.g. the "New part" MPN field), else the
part's own id. `GET /api/parts/lookup?code=` tries id, then MPN, then name,
so either payload always resolves straight back to this part.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..labels import code128_png, qr_png
from ..models import Part

router = APIRouter(prefix="/api/parts", tags=["labels"])


@router.get("/{part_id}/label.png")
def part_label(part_id: str, fmt: str = "qr", h: float | None = None, db: Session = Depends(get_db)):
    p = db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "part not found")
    payload = p.mpn or p.id
    if fmt == "qr":
        png = qr_png(payload)
    elif fmt == "code128":
        png = code128_png(payload, target_height_mm=h)
    else:
        raise HTTPException(400, "fmt must be 'qr' or 'code128'")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})
