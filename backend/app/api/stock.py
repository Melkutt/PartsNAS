"""Per-part stock ledger.

`GET  /api/parts/{id}/stock`     history (newest first) + per-location totals
`POST /api/parts/{id}/stock`     append one entry
                                 {location_id, delta, kind, unit_price?, note?}
`POST /api/parts/{id}/stock/move`  {from_location_id, to_location_id, qty}

Quantities are never edited in place; a correction is another entry.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Part, StockEntry, StorageLocation
from ..services import location_breakdown

router = APIRouter(prefix="/api/parts", tags=["stock"])

KINDS = {"add", "remove", "count", "correction", "move"}


class StockIn(BaseModel):
    location_id: int | None = None
    delta: int
    kind: str = "add"
    unit_price: float | None = None
    currency: str = "SEK"
    supplier: str | None = None
    order_ref: str | None = None
    note: str | None = None


class MoveIn(BaseModel):
    from_location_id: int | None = None
    to_location_id: int
    qty: int


def _need_part(db: Session, part_id: str) -> Part:
    p = db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "part not found")
    return p


@router.get("/{part_id}/stock")
def history(part_id: str, db: Session = Depends(get_db)):
    _need_part(db, part_id)
    rows = db.scalars(
        select(StockEntry)
        .where(StockEntry.part_id == part_id)
        .order_by(StockEntry.id.desc())
    ).all()
    names = dict(db.execute(select(StorageLocation.id, StorageLocation.name)).all())
    return {
        "by_location": location_breakdown(db, part_id),
        "entries": [
            {
                "id": e.id,
                "delta": e.delta,
                "kind": e.kind,
                "location_id": e.location_id,
                "location": names.get(e.location_id, "Unknown location")
                if e.location_id
                else "Unknown location",
                "unit_price": e.unit_price,
                "currency": e.currency,
                "supplier": e.supplier,
                "order_ref": e.order_ref,
                "note": e.note,
                "move_group": e.move_group,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ],
    }


@router.post("/{part_id}/stock", status_code=201)
def add_entry(part_id: str, body: StockIn, db: Session = Depends(get_db)):
    _need_part(db, part_id)
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(KINDS)}")
    if body.location_id is not None and db.get(StorageLocation, body.location_id) is None:
        raise HTTPException(400, "unknown location_id")
    e = StockEntry(
        part_id=part_id,
        location_id=body.location_id,
        delta=body.delta,
        kind=body.kind,
        unit_price=body.unit_price,
        currency=body.currency,
        supplier=body.supplier,
        order_ref=body.order_ref,
        note=body.note,
    )
    db.add(e)
    db.commit()
    return {"id": e.id}


@router.post("/{part_id}/stock/move", status_code=201)
def move(part_id: str, body: MoveIn, db: Session = Depends(get_db)):
    _need_part(db, part_id)
    if body.qty <= 0:
        raise HTTPException(400, "qty must be positive")
    if db.get(StorageLocation, body.to_location_id) is None:
        raise HTTPException(400, "unknown to_location_id")
    group = secrets.token_hex(6)
    db.add(
        StockEntry(
            part_id=part_id, location_id=body.from_location_id, delta=-body.qty,
            kind="move", move_group=group, note="move",
        )
    )
    db.add(
        StockEntry(
            part_id=part_id, location_id=body.to_location_id, delta=body.qty,
            kind="move", move_group=group, note="move",
        )
    )
    db.commit()
    return {"move_group": group}
