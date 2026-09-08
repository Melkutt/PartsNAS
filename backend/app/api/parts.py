"""Part CRUD + list/filter + scanner lookup.

`GET  /api/parts`                list; filters: q, category_id (+descendants),
                                 location_id, tag, mount, low_stock, limit, offset
`GET  /api/parts/ids`            just the ids matching the same filters (for
                                 "select all matching" in the bulk bar)
`GET  /api/parts/lookup?code=`   exact match on id / mpn / name — for the scanner
`GET  /api/parts/{id}`           full record + stock-by-location + category path
`POST /api/parts`                create
`PATCH /api/parts/{id}`          update
`DELETE /api/parts/{id}`         delete (stock ledger rows cascade)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Part, StockEntry, Tag
from ..services import (
    category_path,
    category_path_map,
    descendant_category_ids,
    location_breakdown,
    location_breakdown_bulk,
    on_hand_map,
    resolve_part_class,
)

router = APIRouter(prefix="/api/parts", tags=["parts"])


class PartIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mpn: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    category_id: int | None = None
    mount: str | None = None
    footprint_raw: str | None = None
    kicad_symbol: str | None = None
    kicad_footprint: str | None = None
    datasheet_url: str | None = None
    min_stock: int = 0
    notes: str | None = None
    attributes: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class PartPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    mpn: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    category_id: int | None = None
    set_category: bool = False
    mount: str | None = None
    footprint_raw: str | None = None
    kicad_symbol: str | None = None
    kicad_footprint: str | None = None
    datasheet_url: str | None = None
    min_stock: int | None = None
    notes: str | None = None
    attributes: dict | None = None
    tags: list[str] | None = None


def _filtered_query(
    db: Session,
    q: str | None,
    category_id: int | None,
    with_subcats: bool,
    location_id: int | None,
    tag: str | None,
    mount: str | None,
):
    stmt = select(Part.id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Part.name.ilike(like), Part.mpn.ilike(like), Part.description.ilike(like))
        )
    if category_id is not None:
        ids = descendant_category_ids(db, category_id) if with_subcats else {category_id}
        stmt = stmt.where(Part.category_id.in_(ids))
    if mount:
        stmt = stmt.where(Part.mount == mount)
    if tag:
        stmt = stmt.where(Part.tags.any(Tag.name == tag))
    if location_id is not None:
        sub = (
            select(StockEntry.part_id)
            .where(StockEntry.location_id == location_id)
            .group_by(StockEntry.part_id)
            .having(func.coalesce(func.sum(StockEntry.delta), 0) > 0)
        )
        stmt = stmt.where(Part.id.in_(sub))
    return stmt


def _matching_ids(db: Session, **kw) -> list[str]:
    return list(db.scalars(_filtered_query(db, **kw)).all())


@router.get("")
def list_parts(
    db: Session = Depends(get_db),
    q: str | None = None,
    category_id: int | None = None,
    with_subcats: bool = True,
    location_id: int | None = None,
    tag: str | None = None,
    mount: str | None = None,
    low_stock: bool = False,
    limit: int = Query(200, le=2000),
    offset: int = 0,
    order: str = "name",
):
    ids = _matching_ids(
        db,
        q=q,
        category_id=category_id,
        with_subcats=with_subcats,
        location_id=location_id,
        tag=tag,
        mount=mount,
    )
    onhand = on_hand_map(db, ids)
    if low_stock:
        mins = dict(db.execute(select(Part.id, Part.min_stock).where(Part.id.in_(ids))).all())
        ids = [i for i in ids if mins.get(i, 0) > 0 and onhand.get(i, 0) <= mins.get(i, 0)]

    total = len(ids)
    rows = (
        db.scalars(select(Part).where(Part.id.in_(ids))).all() if ids else []
    )
    paths = category_path_map(db)
    locs = location_breakdown_bulk(db, ids)
    out = []
    for p in rows:
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "mpn": p.mpn,
                "manufacturer": p.manufacturer,
                "category_id": p.category_id,
                "category": paths.get(p.category_id, ""),
                "mount": p.mount,
                "footprint": p.footprint_raw,
                "min_stock": p.min_stock,
                "on_hand": onhand.get(p.id, 0),
                "locations": locs.get(p.id, []),
                "tags": [t.name for t in p.tags],
                "image_path": p.image_path,
            }
        )
    key = (lambda r: r["on_hand"]) if order == "stock" else (lambda r: (r["name"] or "").lower())
    out.sort(key=key, reverse=(order == "stock"))
    return {"total": total, "count": len(out), "items": out[offset : offset + limit]}


@router.get("/ids")
def list_ids(
    db: Session = Depends(get_db),
    q: str | None = None,
    category_id: int | None = None,
    with_subcats: bool = True,
    location_id: int | None = None,
    tag: str | None = None,
    mount: str | None = None,
):
    return {
        "ids": _matching_ids(
            db,
            q=q,
            category_id=category_id,
            with_subcats=with_subcats,
            location_id=location_id,
            tag=tag,
            mount=mount,
        )
    }


@router.get("/lookup")
def lookup(code: str, db: Session = Depends(get_db)):
    """Scanner entry point: try id, then exact MPN, then exact name."""
    code = code.strip()
    if not code:
        raise HTTPException(400, "empty code")
    p = db.get(Part, code)
    if p is None:
        p = db.scalar(select(Part).where(func.lower(Part.mpn) == code.lower()))
    if p is None:
        p = db.scalar(select(Part).where(func.lower(Part.name) == code.lower()))
    if p is None:
        raise HTTPException(404, f"No part matches {code!r}")
    return {
        "id": p.id,
        "name": p.name,
        "mpn": p.mpn,
        "on_hand": on_hand_map(db, [p.id]).get(p.id, 0),
    }


@router.get("/{part_id}")
def get_part(part_id: str, db: Session = Depends(get_db)):
    p = db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "part not found")
    from ..api.images import _row as image_row
    from ..api.suppliers import _link_row

    return {
        "id": p.id,
        "name": p.name,
        "mpn": p.mpn,
        "manufacturer": p.manufacturer,
        "description": p.description,
        "category_id": p.category_id,
        "category": category_path(db, p.category_id),
        "part_class": resolve_part_class(db, p.category_id),
        "mount": p.mount,
        "footprint_raw": p.footprint_raw,
        "kicad_symbol": p.kicad_symbol,
        "kicad_footprint": p.kicad_footprint,
        "datasheet_url": p.datasheet_url,
        "image_path": p.image_path,
        "min_stock": p.min_stock,
        "notes": p.notes,
        "attributes": p.attributes or {},
        "tags": [t.name for t in p.tags],
        "on_hand": on_hand_map(db, [p.id]).get(p.id, 0),
        "stock": location_breakdown(db, p.id),
        "suppliers": [_link_row(x) for x in p.suppliers],
        "images": [image_row(a) for a in p.attachments],
        "design_note_count": len(p.design_notes),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _resolve_tags(db: Session, names: list[str]) -> list[Tag]:
    out = []
    for raw in names:
        n = raw.strip()
        if not n:
            continue
        t = db.scalar(select(Tag).where(Tag.name == n))
        if t is None:
            t = Tag(name=n)
            db.add(t)
        out.append(t)
    return out


@router.post("", status_code=201)
def create_part(body: PartIn, db: Session = Depends(get_db)):
    p = Part(
        name=body.name,
        mpn=body.mpn,
        manufacturer=body.manufacturer,
        description=body.description,
        category_id=body.category_id,
        mount=body.mount,
        footprint_raw=body.footprint_raw,
        kicad_symbol=body.kicad_symbol,
        kicad_footprint=body.kicad_footprint,
        datasheet_url=body.datasheet_url,
        min_stock=body.min_stock,
        notes=body.notes,
        attributes=body.attributes,
    )
    p.tags = _resolve_tags(db, body.tags)
    db.add(p)
    db.commit()
    return {"id": p.id}


@router.patch("/{part_id}")
def patch_part(part_id: str, body: PartPatch, db: Session = Depends(get_db)):
    p = db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "part not found")
    data = body.model_dump(exclude_unset=True)
    data.pop("set_category", None)
    if "tags" in data:
        p.tags = _resolve_tags(db, data.pop("tags") or [])
    if "category_id" in data or body.set_category:
        p.category_id = data.pop("category_id", None)
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/{part_id}")
def delete_part(part_id: str, db: Session = Depends(get_db)):
    p = db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "part not found")
    db.delete(p)
    db.commit()
    return {"ok": True}
