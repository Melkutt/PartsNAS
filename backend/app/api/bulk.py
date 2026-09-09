"""Bulk edits with one-click undo.

`POST /api/bulk`               {ids | filter, action, params}
`POST /api/bulk/{op_id}/undo`  revert a previous bulk op
`GET  /api/bulk`               recent bulk ops (for an undo list)

actions:
  move_category   params.category_id       -> Part.category_id
  add_tag         params.tag               -> add a tag to each part
  remove_tag      params.tag
  set_min_stock   params.min_stock
  move_stock      params.to_location_id [, params.from_location_id]
                  moves on-hand quantity into one location (ledger entries,
                  one move_group); undo writes compensating entries
  delete          (no undo)
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import BulkOp, Part, StockEntry, StorageLocation, Tag
from ..services import location_breakdown_bulk
from .parts import PartFilter, _query

router = APIRouter(prefix="/api/bulk", tags=["bulk"])

UNDOABLE = {"move_category", "add_tag", "remove_tag", "set_min_stock", "move_stock"}


class BulkBody(BaseModel):
    ids: list[str] | None = None
    filter: dict | None = None
    action: str
    params: dict = Field(default_factory=dict)


def _target_ids(db: Session, body: BulkBody) -> list[str]:
    if body.ids:
        return list(dict.fromkeys(body.ids))
    if body.filter is not None:
        d = body.filter
        f = PartFilter(
            q=d.get("q"),
            category_id=d.get("category_id"),
            with_subcats=d.get("with_subcats", True),
            location_ids=_aslist(d.get("location_id")),
            mounts=_aslist(d.get("mount")),
            footprints=_aslist(d.get("footprint")),
            manufacturers=_aslist(d.get("manufacturer")),
            tags=_aslist(d.get("tag")),
            in_stock=d.get("in_stock"),
            attrs=_aslist(d.get("attr")),
        )
        return list(db.scalars(_query(db, f)).all())
    raise HTTPException(400, "provide ids or filter")


def _aslist(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _tag(db: Session, name: str) -> Tag:
    t = db.scalar(select(Tag).where(Tag.name == name.strip()))
    if t is None:
        t = Tag(name=name.strip())
        db.add(t)
        db.flush()
    return t


@router.post("")
def run_bulk(body: BulkBody, db: Session = Depends(get_db)):
    ids = _target_ids(db, body)
    if not ids:
        return {"affected": 0, "op_id": None}
    parts = db.scalars(select(Part).where(Part.id.in_(ids))).all()
    p = body.params
    op = BulkOp(kind=body.action, summary="", undo={})

    if body.action == "move_category":
        cat_id = p.get("category_id")
        op.undo = {"kind": "move_category", "before": {x.id: x.category_id for x in parts}}
        for x in parts:
            x.category_id = cat_id
        op.summary = f"Moved {len(parts)} part(s) to category #{cat_id}"

    elif body.action == "set_min_stock":
        val = int(p.get("min_stock", 0))
        op.undo = {"kind": "set_min_stock", "before": {x.id: x.min_stock for x in parts}}
        for x in parts:
            x.min_stock = val
        op.summary = f"Set min stock = {val} on {len(parts)} part(s)"

    elif body.action in ("add_tag", "remove_tag"):
        name = (p.get("tag") or "").strip()
        if not name:
            raise HTTPException(400, "params.tag required")
        tag = _tag(db, name)
        changed = []
        for x in parts:
            has = tag in x.tags
            if body.action == "add_tag" and not has:
                x.tags.append(tag)
                changed.append(x.id)
            elif body.action == "remove_tag" and has:
                x.tags.remove(tag)
                changed.append(x.id)
        op.undo = {"kind": body.action, "tag": name, "changed": changed}
        op.summary = f"{body.action.replace('_', ' ')} '{name}' on {len(changed)} part(s)"

    elif body.action == "move_stock":
        to_id = p.get("to_location_id")
        if to_id is None or db.get(StorageLocation, to_id) is None:
            raise HTTPException(400, "params.to_location_id invalid")
        from_id = p.get("from_location_id")  # optional
        group = secrets.token_hex(6)
        breakdown = location_breakdown_bulk(db, ids)
        moved_parts = 0
        for pid in ids:
            for row in breakdown.get(pid, []):
                if row["qty"] <= 0 or row["location_id"] == to_id:
                    continue
                if from_id is not None and row["location_id"] != from_id:
                    continue
                db.add(
                    StockEntry(
                        part_id=pid, location_id=row["location_id"], delta=-row["qty"],
                        kind="move", move_group=group, note="bulk move",
                    )
                )
                db.add(
                    StockEntry(
                        part_id=pid, location_id=to_id, delta=row["qty"],
                        kind="move", move_group=group, note="bulk move",
                    )
                )
            moved_parts += 1
        op.undo = {"kind": "move_stock", "move_group": group}
        dest = db.get(StorageLocation, to_id)
        op.summary = f"Moved stock of {moved_parts} part(s) to {dest.name}"

    elif body.action == "delete":
        n = len(parts)
        for x in parts:
            db.delete(x)
        db.commit()
        return {"affected": n, "op_id": None}  # not undoable

    else:
        raise HTTPException(400, f"unknown action {body.action!r}")

    db.add(op)
    db.commit()
    return {"affected": len(ids), "op_id": op.id, "summary": op.summary}


@router.get("")
def recent_ops(db: Session = Depends(get_db), limit: int = 20):
    ops = db.scalars(select(BulkOp).order_by(BulkOp.id.desc()).limit(limit)).all()
    return [
        {
            "id": o.id,
            "kind": o.kind,
            "summary": o.summary,
            "undone": o.undone,
            "undoable": o.kind in UNDOABLE and not o.undone,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in ops
    ]


@router.post("/{op_id}/undo")
def undo_op(op_id: int, db: Session = Depends(get_db)):
    op = db.get(BulkOp, op_id)
    if op is None:
        raise HTTPException(404, "op not found")
    if op.undone:
        raise HTTPException(409, "already undone")
    u = op.undo or {}
    kind = u.get("kind")

    if kind in ("move_category", "set_min_stock"):
        field = "category_id" if kind == "move_category" else "min_stock"
        for pid, val in (u.get("before") or {}).items():
            part = db.get(Part, pid)
            if part is not None:
                setattr(part, field, val)

    elif kind in ("add_tag", "remove_tag"):
        tag = db.scalar(select(Tag).where(Tag.name == u.get("tag")))
        if tag is not None:
            for pid in u.get("changed") or []:
                part = db.get(Part, pid)
                if part is None:
                    continue
                if kind == "add_tag" and tag in part.tags:
                    part.tags.remove(tag)
                elif kind == "remove_tag" and tag not in part.tags:
                    part.tags.append(tag)

    elif kind == "move_stock":
        group = u.get("move_group")
        entries = db.scalars(
            select(StockEntry).where(StockEntry.move_group == group)
        ).all()
        for e in entries:
            db.add(
                StockEntry(
                    part_id=e.part_id, location_id=e.location_id, delta=-e.delta,
                    kind="correction", move_group=f"undo-{group}", note="undo bulk move",
                )
            )
    else:
        raise HTTPException(400, "this op cannot be undone")

    op.undone = True
    db.commit()
    return {"ok": True}
