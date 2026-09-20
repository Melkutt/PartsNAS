"""The order list: parts that have run down to (or below) their Min stock, and what has
been ordered but has not arrived yet.

`GET  /api/order`                 {items: to order, on_order: bought, waiting for delivery}
`GET  /api/order/count`           {count, out, on_order} - cheap, feeds the badge on the Order tab
`POST /api/order/mark-ordered`    {items:[{part_id, qty}], ref?} - the parts are bought
`POST /api/order/unmark-ordered`  {part_ids} - undo that
`POST /api/order/receive`         {part_id, qty, location_id?, unit_price?, update_price?, ref?}
                                  - the delivery arrived: adds the stock (and, if a price is
                                    given, records it as what was paid)

Same definition of "low" as the Parts "Low stock" filter and the red on-hand number:
min_stock > 0 and on_hand <= min_stock. A part that is on order leaves the "to order" list
(it would only be ordered twice) and shows under "on order" until it is received. Each item
carries the supplier link to buy from - the ★ preferred one, else the cheapest priced one -
so the list can be turned straight into an order (SKU + quantity).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Part, PartSupplier, StorageLocation
from ..services import category_path_map, location_breakdown, on_hand_map
from .stock import StockIn, add_entry

router = APIRouter(prefix="/api/order", tags=["order"])


def _pick_link(p: Part) -> PartSupplier | None:
    links = [x for x in p.suppliers if x.active] or list(p.suppliers)
    if not links:
        return None
    preferred = [x for x in links if x.preferred]
    if preferred:
        return preferred[0]
    priced = [x for x in links if x.unit_price is not None]
    if priced:
        return min(priced, key=lambda x: x.unit_price)
    return links[0]


def _low_parts(db: Session) -> list[tuple[Part, int]]:
    parts = db.scalars(select(Part).where(Part.min_stock > 0, Part.on_order_qty.is_(None))).all()
    onhand = on_hand_map(db, [p.id for p in parts])
    return [(p, onhand.get(p.id, 0)) for p in parts if onhand.get(p.id, 0) <= p.min_stock]


def _on_order_parts(db: Session) -> list[Part]:
    return list(db.scalars(select(Part).where(Part.on_order_qty.is_not(None), Part.on_order_qty > 0)).all())


def _supplier_block(link: PartSupplier | None) -> dict | None:
    if link is None:
        return None
    return {
        "name": link.supplier.name if link.supplier else "?",
        "sku": link.sku,
        "url": link.url,
        "unit_price": link.unit_price,    # ex VAT
        "currency": link.currency,
        "preferred": link.preferred,
    }


@router.get("/count")
def order_count(db: Session = Depends(get_db)):
    low = _low_parts(db)
    return {
        "count": len(low),
        "out": sum(1 for _, oh in low if oh <= 0),
        "on_order": len(_on_order_parts(db)),
    }


@router.get("")
def order_list(db: Session = Depends(get_db)):
    low = _low_parts(db)
    paths = category_path_map(db)
    items = []
    for p, oh in low:
        link = _pick_link(p)
        short = p.min_stock - oh
        items.append({
            "id": p.id,
            "name": p.name,
            "mpn": p.mpn,
            "manufacturer": p.manufacturer,
            "category": paths.get(p.category_id, ""),
            "datasheet_url": p.datasheet_url,
            "on_hand": oh,
            "min_stock": p.min_stock,
            "short": short,                       # how far below the minimum
            # what the qty box shows: the amount typed there last time, else how far below Min stock
            "suggested_qty": p.order_qty or max(short, 1),
            "order_qty": p.order_qty,             # None until the user has typed one
            "status": "out" if oh <= 0 else "low",
            "discontinued": p.discontinued,
            "replacement": p.replaced_by.name if p.replaced_by else (p.replacement_mpn or None),
            "supplier": _supplier_block(link),
        })
    # worst first: out of stock, then by how far under the minimum (relative), then name
    items.sort(key=lambda i: (i["status"] != "out", i["on_hand"] / i["min_stock"], (i["name"] or "").lower()))

    now = datetime.now(timezone.utc)
    ordered = []
    parts = _on_order_parts(db)
    onhand = on_hand_map(db, [p.id for p in parts])
    for p in parts:
        at = p.on_order_at
        if at is not None and at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        stock = sorted(location_breakdown(db, p.id), key=lambda r: -r["qty"])
        ordered.append({
            "id": p.id,
            "name": p.name,
            "mpn": p.mpn,
            "on_hand": onhand.get(p.id, 0),
            "qty": p.on_order_qty,
            "ordered_at": at.isoformat() if at else None,
            "days": (now - at).days if at else None,
            "ref": p.on_order_ref,
            "supplier": _supplier_block(_pick_link(p)),
            # where the delivery most likely goes: where this part already lives
            "default_location_id": stock[0]["location_id"] if stock else None,
        })
    ordered.sort(key=lambda o: (o["ordered_at"] or "", (o["name"] or "").lower()))
    return {
        "count": len(items),
        "out": sum(1 for i in items if i["status"] == "out"),
        "items": items,
        "on_order": ordered,
    }


# -- bought / received ---------------------------------------------------------------------

class OrderedLine(BaseModel):
    part_id: str
    qty: int = Field(ge=1)


class MarkOrderedIn(BaseModel):
    items: list[OrderedLine] = Field(min_length=1)
    ref: str | None = Field(default=None, max_length=120)  # your order number / note


class UnmarkIn(BaseModel):
    part_ids: list[str] = Field(min_length=1)


class ReceiveIn(BaseModel):
    part_id: str
    qty: int = Field(ge=1)
    location_id: int | None = None
    unit_price: float | None = Field(default=None, ge=0)   # what you paid per unit, ex VAT
    update_price: bool = True    # also make it the supplier price, so quotes use what you really paid
    ref: str | None = Field(default=None, max_length=120)


@router.post("/mark-ordered")
def mark_ordered(body: MarkOrderedIn, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    parts = {p.id: p for p in db.scalars(select(Part).where(Part.id.in_([i.part_id for i in body.items]))).all()}
    missing = [i.part_id for i in body.items if i.part_id not in parts]
    if missing:
        raise HTTPException(404, f"unknown part(s): {', '.join(missing)}")
    for line in body.items:
        p = parts[line.part_id]
        p.on_order_qty = line.qty
        p.on_order_at = now
        p.on_order_ref = (body.ref or "").strip() or None
        p.order_qty = line.qty  # what you typed is what you tend to buy: remember it too
    db.commit()
    return {"ok": True, "marked": len(body.items)}


@router.post("/unmark-ordered")
def unmark_ordered(body: UnmarkIn, db: Session = Depends(get_db)):
    for p in db.scalars(select(Part).where(Part.id.in_(body.part_ids))).all():
        p.on_order_qty = None
        p.on_order_at = None
        p.on_order_ref = None
    db.commit()
    return {"ok": True}


@router.post("/receive")
def receive(body: ReceiveIn, db: Session = Depends(get_db)):
    p = db.get(Part, body.part_id)
    if p is None:
        raise HTTPException(404, "part not found")
    if body.location_id is not None and db.get(StorageLocation, body.location_id) is None:
        raise HTTPException(400, "unknown location_id")
    link = _pick_link(p)
    ref = body.ref or p.on_order_ref
    # the same ledger entry as "Add stock" on the Stock tab: stock in, and (with a price) the
    # supplier link is updated to what was actually paid
    add_entry(
        p.id,
        StockIn(
            location_id=body.location_id,
            delta=body.qty,
            kind="add",
            unit_price=body.unit_price,
            currency=link.currency if link else None,
            vat_percent=link.vat_percent if link else None,
            supplier_id=link.supplier_id if link else None,
            supplier_sku=link.sku if link else None,
            link_to_part=bool(body.update_price and body.unit_price is not None),
            order_ref=ref,
            note="received from order",
        ),
        db,
    )
    p = db.get(Part, body.part_id)
    left = (p.on_order_qty or 0) - body.qty
    if left > 0:      # a partial delivery: the rest is still on its way
        p.on_order_qty = left
    else:
        p.on_order_qty = None
        p.on_order_at = None
        p.on_order_ref = None
    db.commit()
    return {"ok": True, "on_hand": on_hand_map(db, [p.id]).get(p.id, 0), "still_on_order": max(left, 0)}
