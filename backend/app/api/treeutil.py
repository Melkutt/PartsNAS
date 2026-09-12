"""Shared helpers for the two self-referential trees (Category, StorageLocation).

Kept as plain functions over an ORM class so the category and location routers
stay thin and behave identically for create / rename / move / reorder.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def build_forest(db: Session, model, extra: dict[int, dict] | None = None) -> list[dict]:
    """Return the whole tree as nested dicts, ordered by (sort_order, name)."""
    rows = db.scalars(select(model).order_by(model.sort_order, model.name)).all()
    by_parent: dict[Any, list] = {}
    for r in rows:
        by_parent.setdefault(r.parent_id, []).append(r)

    def node(r) -> dict:
        children = [node(c) for c in by_parent.get(r.id, [])]
        d = {
            "id": r.id,
            "name": r.name,
            "parent_id": r.parent_id,
            "sort_order": r.sort_order,
            "children": children,
        }
        if hasattr(r, "comment"):
            d["comment"] = r.comment
        if hasattr(r, "part_class"):
            d["part_class"] = r.part_class
        if hasattr(r, "is_unsorted"):
            d["is_unsorted"] = r.is_unsorted
        if hasattr(r, "legacy_id"):
            d["legacy_id"] = r.legacy_id
        if extra and r.id in extra:
            d.update(extra[r.id])
        # part_count rolls up: a parent shows everything under it too (e.g.
        # "Passive" = Resistor + Capacitor + ... summed all the way down),
        # and stays unset/blank when the whole subtree is empty.
        own = d.get("part_count") or 0
        total = own + sum(c.get("part_count") or 0 for c in children)
        if total:
            d["part_count"] = total
        else:
            d.pop("part_count", None)
        return d

    return [node(r) for r in by_parent.get(None, [])]


def get_or_404(db: Session, model, node_id: int):
    obj = db.get(model, node_id)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {node_id} not found")
    return obj


def descendant_ids(db: Session, model, node_id: int) -> set[int]:
    """node_id plus every id below it (used to reject cyclic moves)."""
    out = {node_id}
    frontier = {node_id}
    while frontier:
        kids = db.scalars(
            select(model.id).where(model.parent_id.in_(frontier))
        ).all()
        kids = set(kids) - out
        out |= kids
        frontier = kids
    return out


def next_sort_order(db: Session, model, parent_id: int | None) -> int:
    hi = db.scalar(
        select(func.max(model.sort_order)).where(model.parent_id.is_(parent_id))
        if parent_id is None
        else select(func.max(model.sort_order)).where(model.parent_id == parent_id)
    )
    return (hi or 0) + 1


def check_move(db: Session, model, node_id: int, new_parent_id: int | None) -> None:
    if new_parent_id is None:
        return
    if new_parent_id in descendant_ids(db, model, node_id):
        raise HTTPException(400, "Cannot move a node under itself or its own descendant")
    get_or_404(db, model, new_parent_id)
