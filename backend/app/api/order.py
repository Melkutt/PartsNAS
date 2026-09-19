"""The order list: parts that have run down to (or below) their Min stock.

`GET /api/order`         items, worst first (out of stock, then by how far below)
`GET /api/order/count`   {count, out} — cheap, feeds the badge on the Order tab

Same definition as the Parts "Low stock" filter and the red on-hand number:
min_stock > 0 and on_hand <= min_stock. Each item carries the supplier link to
buy from — the ★ preferred one, else the cheapest priced one — so the list can
be turned straight into an order (SKU + quantity).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Part, PartSupplier
from ..services import category_path_map, on_hand_map

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
    parts = db.scalars(select(Part).where(Part.min_stock > 0)).all()
    onhand = on_hand_map(db, [p.id for p in parts])
    return [(p, onhand.get(p.id, 0)) for p in parts if onhand.get(p.id, 0) <= p.min_stock]


@router.get("/count")
def order_count(db: Session = Depends(get_db)):
    low = _low_parts(db)
    return {"count": len(low), "out": sum(1 for _, oh in low if oh <= 0)}


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
            "supplier": None if link is None else {
                "name": link.supplier.name if link.supplier else "?",
                "sku": link.sku,
                "url": link.url,
                "unit_price": link.unit_price,    # ex VAT
                "currency": link.currency,
                "preferred": link.preferred,
            },
        })
    # worst first: out of stock, then by how far under the minimum (relative), then name
    items.sort(key=lambda i: (i["status"] != "out", i["on_hand"] / i["min_stock"], (i["name"] or "").lower()))
    return {"count": len(items), "out": sum(1 for i in items if i["status"] == "out"), "items": items}
