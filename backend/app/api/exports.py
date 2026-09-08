"""Export endpoints.

`GET /api/export/parts.csv`   all parts + on-hand + per-location breakdown + tags
`GET /api/export/parts.xlsx`  same, as a workbook
"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Part
from ..services import category_path_map, location_breakdown_bulk, on_hand_map

router = APIRouter(prefix="/api/export", tags=["export"])

COLUMNS = [
    "id", "mpn", "manufacturer", "name", "description", "category", "mount",
    "footprint", "kicad_symbol", "kicad_footprint", "datasheet_url",
    "min_stock", "on_hand", "locations", "tags", "notes", "created_at",
]


def _rows(db: Session) -> list[list]:
    parts = db.scalars(select(Part).order_by(Part.name)).all()
    ids = [p.id for p in parts]
    paths = category_path_map(db)
    onhand = on_hand_map(db, ids)
    locs = location_breakdown_bulk(db, ids)
    out = []
    for p in parts:
        loc_str = "; ".join(f"{r['location']}:{r['qty']}" for r in locs.get(p.id, []))
        out.append(
            [
                p.id, p.mpn or "", p.manufacturer or "", p.name, p.description or "",
                paths.get(p.category_id, ""), p.mount or "", p.footprint_raw or "",
                p.kicad_symbol or "", p.kicad_footprint or "", p.datasheet_url or "",
                p.min_stock, onhand.get(p.id, 0), loc_str,
                ", ".join(t.name for t in p.tags), (p.notes or "").replace("\n", " "),
                p.created_at.isoformat() if p.created_at else "",
            ]
        )
    return out


@router.get("/parts.csv")
def parts_csv(db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    w.writerows(_rows(db))
    buf.seek(0)
    fname = f"partsnas-parts-{datetime.now():%Y%m%d}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/parts.xlsx")
def parts_xlsx(db: Session = Depends(get_db)):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Parts"
    ws.append(COLUMNS)
    for row in _rows(db):
        ws.append(row)
    for i, col in enumerate(COLUMNS, 1):
        ws.column_dimensions[chr(64 + i) if i <= 26 else "A"].width = max(12, len(col) + 2)
    bio = io.BytesIO()
    wb.save(bio)
    fname = f"partsnas-parts-{datetime.now():%Y%m%d}.xlsx"
    return Response(
        content=bio.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
