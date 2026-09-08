"""Category tree endpoints.

`GET  /api/categories`            nested tree (+ direct part counts)
`POST /api/categories`            create {name, parent_id?, part_class?}
`PATCH /api/categories/{id}`      rename / move / set part_class / reorder
`DELETE /api/categories/{id}`     delete; parts + children go to parent or Unsorted
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Category, Part
from .treeutil import build_forest, check_move, get_or_404, next_sort_order

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: int | None = None
    part_class: str | None = None


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: int | None = None
    set_parent: bool = False  # PATCH {parent_id:null, set_parent:true} => move to root
    part_class: str | None = None
    sort_order: int | None = None


def _part_counts(db: Session) -> dict[int, dict]:
    rows = db.execute(
        select(Part.category_id, func.count()).group_by(Part.category_id)
    ).all()
    return {cid: {"part_count": n} for cid, n in rows if cid is not None}


def _unsorted(db: Session) -> Category:
    cat = db.scalar(select(Category).where(Category.is_unsorted.is_(True)))
    if cat is None:  # should never happen after seeding
        cat = Category(name="Unsorted / Uncategorized", slug="unsorted", is_unsorted=True)
        db.add(cat)
        db.flush()
    return cat


@router.get("")
def list_categories(db: Session = Depends(get_db)):
    return build_forest(db, Category, extra=_part_counts(db))


@router.post("", status_code=201)
def create_category(body: CategoryCreate, db: Session = Depends(get_db)):
    if body.parent_id is not None:
        get_or_404(db, Category, body.parent_id)
    dup = db.scalar(
        select(Category).where(
            Category.parent_id.is_(body.parent_id)
            if body.parent_id is None
            else Category.parent_id == body.parent_id,
            Category.name == body.name,
        )
    )
    if dup:
        raise HTTPException(409, "A sibling category with that name already exists")
    cat = Category(
        name=body.name,
        slug=body.name.lower().replace(" ", "-"),
        parent_id=body.parent_id,
        part_class=body.part_class,
        sort_order=next_sort_order(db, Category, body.parent_id),
    )
    db.add(cat)
    db.commit()
    return {"id": cat.id}


@router.patch("/{cat_id}")
def patch_category(cat_id: int, body: CategoryPatch, db: Session = Depends(get_db)):
    cat = get_or_404(db, Category, cat_id)
    if body.name is not None:
        cat.name = body.name
    if body.part_class is not None:
        cat.part_class = body.part_class or None
    if body.sort_order is not None:
        cat.sort_order = body.sort_order
    if body.set_parent or body.parent_id is not None:
        check_move(db, Category, cat_id, body.parent_id)
        cat.parent_id = body.parent_id
    db.commit()
    return {"ok": True}


@router.delete("/{cat_id}")
def delete_category(cat_id: int, db: Session = Depends(get_db)):
    cat = get_or_404(db, Category, cat_id)
    if cat.is_unsorted:
        raise HTTPException(400, "The Unsorted category cannot be deleted")
    fallback_id = cat.parent_id or _unsorted(db).id
    db.execute(
        Category.__table__.update()
        .where(Category.parent_id == cat_id)
        .values(parent_id=fallback_id)
    )
    db.execute(
        Part.__table__.update().where(Part.category_id == cat_id).values(category_id=fallback_id)
    )
    db.delete(cat)
    db.commit()
    return {"ok": True, "moved_to": fallback_id}
