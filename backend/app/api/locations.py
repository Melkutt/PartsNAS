"""Storage-location tree endpoints. Mirrors categories.py; the tree can be as deep
as you like (Cabinet > Row > Box > Compartment).

`GET  /api/locations`          nested tree (+ distinct part count currently stored)
`POST /api/locations`          create {name, parent_id?, note?}
`PATCH /api/locations/{id}`    rename / move / reorder / note
`DELETE /api/locations/{id}`   delete; children reparent, stock entries keep history
                               with location_id = NULL (shown as "Unknown location")
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import StockEntry, StorageLocation
from .treeutil import build_forest, check_move, get_or_404, move_sibling, next_sort_order

router = APIRouter(prefix="/api/locations", tags=["locations"])


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: int | None = None
    note: str | None = None


class LocationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: int | None = None
    set_parent: bool = False
    note: str | None = None
    sort_order: int | None = None


def _stored_counts(db: Session) -> dict[int, dict]:
    """Distinct parts with non-zero on-hand quantity per location."""
    q = (
        select(StockEntry.location_id, StockEntry.part_id, func.sum(StockEntry.delta))
        .group_by(StockEntry.location_id, StockEntry.part_id)
    )
    tally: dict[int, int] = {}
    for loc_id, _part, qty in db.execute(q).all():
        if loc_id is not None and (qty or 0) > 0:
            tally[loc_id] = tally.get(loc_id, 0) + 1
    return {k: {"part_count": v} for k, v in tally.items()}


@router.get("")
def list_locations(db: Session = Depends(get_db)):
    return build_forest(db, StorageLocation, extra=_stored_counts(db))


@router.post("", status_code=201)
def create_location(body: LocationCreate, db: Session = Depends(get_db)):
    if body.parent_id is not None:
        get_or_404(db, StorageLocation, body.parent_id)
    dup = db.scalar(
        select(StorageLocation).where(
            StorageLocation.parent_id.is_(body.parent_id)
            if body.parent_id is None
            else StorageLocation.parent_id == body.parent_id,
            StorageLocation.name == body.name,
        )
    )
    if dup:
        raise HTTPException(409, "A sibling location with that name already exists")
    loc = StorageLocation(
        name=body.name,
        parent_id=body.parent_id,
        note=body.note,
        sort_order=next_sort_order(db, StorageLocation, body.parent_id),
    )
    db.add(loc)
    db.commit()
    return {"id": loc.id}


@router.patch("/{loc_id}")
def patch_location(loc_id: int, body: LocationPatch, db: Session = Depends(get_db)):
    loc = get_or_404(db, StorageLocation, loc_id)
    if body.name is not None:
        loc.name = body.name
    if body.note is not None:
        loc.note = body.note or None
    if body.sort_order is not None:
        loc.sort_order = body.sort_order
    if body.set_parent or body.parent_id is not None:
        check_move(db, StorageLocation, loc_id, body.parent_id)
        loc.parent_id = body.parent_id
    db.commit()
    return {"ok": True}


class MoveIn(BaseModel):
    direction: str      # "up" | "down": one step among the siblings


@router.post("/{loc_id}/move")
def move_location(loc_id: int, body: MoveIn, db: Session = Depends(get_db)):
    """Reorder: one step up or down among the locations with the same parent."""
    return {"position": move_sibling(db, StorageLocation, loc_id, body.direction)}


@router.delete("/{loc_id}")
def delete_location(loc_id: int, db: Session = Depends(get_db)):
    loc = get_or_404(db, StorageLocation, loc_id)
    fallback = loc.parent_id  # may be None -> becomes a root
    db.execute(
        StorageLocation.__table__.update()
        .where(StorageLocation.parent_id == loc_id)
        .values(parent_id=fallback)
    )
    # stock_entry.location_id is ON DELETE SET NULL -> history preserved
    db.delete(loc)
    db.commit()
    return {"ok": True}
