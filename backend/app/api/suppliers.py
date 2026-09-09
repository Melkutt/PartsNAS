"""Suppliers (master list) and per-part supplier links.

`GET/POST /api/suppliers`            list / add a supplier
`PATCH/DELETE /api/suppliers/{id}`   edit / remove (blocked while referenced)
`GET  /api/parts/{pid}/suppliers`    links for one part (price shown ex + inc VAT)
`POST /api/parts/{pid}/suppliers`    add a link {supplier_id, sku?, url?, price?, ...}
`PATCH/DELETE /api/parts/{pid}/suppliers/{lid}`
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.kv import get_kv
from ..models import Part, PartSupplier, StockEntry, Supplier
from ..money import price_block, strip_vat
from ..providers import all_providers
from ..providers.base import ProviderBlocked, ProviderError

router = APIRouter(tags=["suppliers"])


class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    website: str | None = None
    country: str | None = None


class SupplierPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    website: str | None = None
    country: str | None = None


class LinkIn(BaseModel):
    supplier_id: int
    sku: str | None = None
    url: str | None = None
    price: float | None = None
    price_includes_vat: bool = False
    vat_percent: float = 25.0
    currency: str = "SEK"
    active: bool = True
    preferred: bool = False
    note: str | None = None


class LinkPatch(BaseModel):
    sku: str | None = None
    url: str | None = None
    price: float | None = None
    price_includes_vat: bool = False
    vat_percent: float | None = None
    currency: str | None = None
    active: bool | None = None
    preferred: bool | None = None
    note: str | None = None


def _supplier_row(s: Supplier) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "website": s.website,
        "country": s.country,
        "builtin": s.builtin,
    }


@router.get("/api/suppliers")
def list_suppliers(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Supplier).order_by(Supplier.sort_order, Supplier.name)
    ).all()
    used = {
        sid
        for (sid,) in db.execute(
            select(PartSupplier.supplier_id).distinct()
        ).all()
    } | {
        sid
        for (sid,) in db.execute(
            select(StockEntry.supplier_id).where(StockEntry.supplier_id.is_not(None)).distinct()
        ).all()
    }
    return [{**_supplier_row(s), "in_use": s.id in used} for s in rows]


@router.post("/api/suppliers", status_code=201)
def add_supplier(body: SupplierIn, db: Session = Depends(get_db)):
    if db.scalar(select(Supplier).where(func.lower(Supplier.name) == body.name.lower())):
        raise HTTPException(409, "a supplier with that name already exists")
    s = Supplier(name=body.name, website=body.website, country=body.country, sort_order=200)
    db.add(s)
    db.commit()
    return {"id": s.id}


@router.patch("/api/suppliers/{sid}")
def patch_supplier(sid: int, body: SupplierPatch, db: Session = Depends(get_db)):
    s = db.get(Supplier, sid)
    if s is None:
        raise HTTPException(404, "supplier not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/api/suppliers/{sid}")
def delete_supplier(sid: int, db: Session = Depends(get_db)):
    s = db.get(Supplier, sid)
    if s is None:
        raise HTTPException(404, "supplier not found")
    n = db.scalar(
        select(func.count()).select_from(PartSupplier).where(PartSupplier.supplier_id == sid)
    )
    if n:
        raise HTTPException(409, f"supplier is linked to {n} part(s); unlink first")
    db.delete(s)
    db.commit()
    return {"ok": True}


# ---- per-part links ----
def _need_part(db: Session, pid: str) -> Part:
    p = db.get(Part, pid)
    if p is None:
        raise HTTPException(404, "part not found")
    return p


def _link_row(link: PartSupplier) -> dict:
    return {
        "id": link.id,
        "supplier_id": link.supplier_id,
        "supplier": link.supplier.name if link.supplier else "?",
        "sku": link.sku,
        "url": link.url,
        "active": link.active,
        "preferred": link.preferred,
        "note": link.note,
        "price": price_block(link.unit_price, link.vat_percent, link.currency),
        "updated_at": link.updated_at.isoformat() if link.updated_at else None,
    }


@router.get("/api/parts/{pid}/cost")
def cost_options(pid: str, db: Session = Depends(get_db)):
    """Which supplier prices could feed a quote line. `auto_link_id` is what the
    quote picks if you don't choose: the ★ preferred link, else the DEAREST."""
    _need_part(db, pid)
    links = db.scalars(
        select(PartSupplier).where(
            PartSupplier.part_id == pid, PartSupplier.unit_price.is_not(None)
        )
    ).all()
    opts = [
        {
            "link_id": x.id,
            "supplier": x.supplier.name if x.supplier else "?",
            "sku": x.sku,
            "unit_price": x.unit_price,
            "currency": x.currency,
            "preferred": x.preferred,
        }
        for x in links
    ]
    has_pref = any(o["preferred"] for o in opts)
    auto = None
    if opts:
        auto = max(links, key=lambda x: (x.preferred, x.unit_price or 0)).id
    return {"options": opts, "auto_link_id": auto, "has_preferred": has_pref}


@router.post("/api/parts/{pid}/refresh-prices")
def refresh_prices(pid: str, db: Session = Depends(get_db)):
    """Query every configured + price-enabled provider for this part's MPN and
    upsert one supplier link per provider. Uses the disk cache, so a recent
    lookup costs no request. Explicit user action only."""
    part = _need_part(db, pid)
    if not part.mpn:
        raise HTTPException(400, "part has no MPN to look up")
    updated: list[dict] = []
    errors: list[dict] = []
    for prov in all_providers():
        if not prov.configured(db):
            continue
        if not get_kv(db, f"provider:{prov.name}:price_enabled", True):
            continue
        try:
            results = prov.search(db, part.mpn)
        except (ProviderBlocked, ProviderError) as e:
            errors.append({"provider": prov.label, "error": str(e)})
            continue
        up = results[0].unit_price() if results else None
        if up is None:
            errors.append({"provider": prov.label, "error": "no match" if not results else "no price"})
            continue
        r = results[0]
        sup = db.scalar(select(Supplier).where(func.lower(Supplier.name) == prov.label.lower()))
        if sup is None:
            sup = Supplier(name=prov.label, sort_order=100)
            db.add(sup)
            db.flush()
        link = db.scalar(select(PartSupplier).where(
            PartSupplier.part_id == pid, PartSupplier.supplier_id == sup.id))
        if link is None:
            link = PartSupplier(part_id=pid, supplier_id=sup.id)
            db.add(link)
        link.sku = r.sku or link.sku
        link.url = r.product_url or link.url
        link.unit_price = up.ex_vat
        link.currency = up.currency
        updated.append({"provider": prov.label, "price": up.ex_vat, "currency": up.currency})
    db.commit()
    return {"updated": updated, "errors": errors}


@router.get("/api/parts/{pid}/suppliers")
def part_suppliers(pid: str, db: Session = Depends(get_db)):
    _need_part(db, pid)
    links = db.scalars(
        select(PartSupplier).where(PartSupplier.part_id == pid).order_by(
            PartSupplier.preferred.desc(), PartSupplier.id
        )
    ).all()
    return [_link_row(x) for x in links]


@router.post("/api/parts/{pid}/suppliers", status_code=201)
def add_link(pid: str, body: LinkIn, db: Session = Depends(get_db)):
    _need_part(db, pid)
    if db.get(Supplier, body.supplier_id) is None:
        raise HTTPException(400, "unknown supplier_id")
    ex = strip_vat(body.price, body.vat_percent) if body.price_includes_vat else body.price
    if body.preferred:
        for other in db.scalars(
            select(PartSupplier).where(PartSupplier.part_id == pid)
        ).all():
            other.preferred = False
    link = PartSupplier(
        part_id=pid,
        supplier_id=body.supplier_id,
        sku=body.sku or None,
        url=body.url or None,
        unit_price=ex,
        currency=body.currency,
        vat_percent=body.vat_percent,
        active=body.active,
        preferred=body.preferred,
        note=body.note or None,
    )
    db.add(link)
    db.commit()
    return {"id": link.id}


@router.patch("/api/parts/{pid}/suppliers/{lid}")
def patch_link(pid: str, lid: int, body: LinkPatch, db: Session = Depends(get_db)):
    link = db.get(PartSupplier, lid)
    if link is None or link.part_id != pid:
        raise HTTPException(404, "link not found")
    data = body.model_dump(exclude_unset=True)
    inc = data.pop("price_includes_vat", False)
    if "vat_percent" in data and data["vat_percent"] is not None:
        link.vat_percent = data.pop("vat_percent")
    if "price" in data:
        price = data.pop("price")
        link.unit_price = strip_vat(price, link.vat_percent) if inc else price
    if data.get("preferred"):
        for other in db.scalars(
            select(PartSupplier).where(
                PartSupplier.part_id == pid, PartSupplier.id != lid
            )
        ).all():
            other.preferred = False
    for k, v in data.items():
        setattr(link, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/api/parts/{pid}/suppliers/{lid}")
def delete_link(pid: str, lid: int, db: Session = Depends(get_db)):
    link = db.get(PartSupplier, lid)
    if link is None or link.part_id != pid:
        raise HTTPException(404, "link not found")
    db.delete(link)
    db.commit()
    return {"ok": True}
