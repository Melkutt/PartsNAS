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
from ..models import Part, PartSupplier, StockEntry, StorageLocation, Supplier
from ..money import price_block, strip_vat
from ..services import location_breakdown

router = APIRouter(prefix="/api/parts", tags=["stock"])

KINDS = {"add", "remove", "count", "correction", "move"}


class StockIn(BaseModel):
    location_id: int | None = None
    delta: int
    kind: str = "add"
    unit_price: float | None = None  # price per unit as typed
    price_includes_vat: bool = False
    vat_percent: float = 25.0
    currency: str = "SEK"
    supplier_id: int | None = None
    supplier_sku: str | None = None
    link_to_part: bool = True  # also upsert the part<->supplier link
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
                "price": price_block(e.unit_price, e.vat_percent, e.currency),
                "supplier": e.supplier,
                "supplier_id": e.supplier_id,
                "supplier_sku": e.supplier_sku,
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

    sup = db.get(Supplier, body.supplier_id) if body.supplier_id else None
    if body.supplier_id and sup is None:
        raise HTTPException(400, "unknown supplier_id")
    ex_price = (
        strip_vat(body.unit_price, body.vat_percent)
        if body.price_includes_vat
        else body.unit_price
    )

    e = StockEntry(
        part_id=part_id,
        location_id=body.location_id,
        delta=body.delta,
        kind=body.kind,
        unit_price=ex_price,
        vat_percent=body.vat_percent,
        currency=body.currency,
        supplier=sup.name if sup else None,
        supplier_id=sup.id if sup else None,
        supplier_sku=body.supplier_sku or None,
        order_ref=body.order_ref,
        note=body.note,
    )
    db.add(e)

    # keep the part<->supplier catalogue in sync with what we actually buy
    if sup and body.link_to_part and body.delta > 0:
        link = db.scalar(
            select(PartSupplier).where(
                PartSupplier.part_id == part_id,
                PartSupplier.supplier_id == sup.id,
                PartSupplier.sku == (body.supplier_sku or None),
            )
        )
        if link is None:
            link = PartSupplier(
                part_id=part_id, supplier_id=sup.id, sku=body.supplier_sku or None
            )
            db.add(link)
        if ex_price is not None:
            link.unit_price = ex_price
            link.vat_percent = body.vat_percent
            link.currency = body.currency

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
