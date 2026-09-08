"""Design notes — reusable "when you build with part X, use these" hints.

Anchored to one part; each note has a condition (e.g. "Vout=5V", "fsw=400kHz"),
a free-text explanation, and links to companion parts with a role/value hint.
The list endpoint is searchable across anchor, condition, body and companions.

`GET    /api/design-notes?q=&part_id=`   searchable list
`POST   /api/design-notes`               {part_id, title, condition?, body?, links:[...]}
`GET    /api/design-notes/{id}`
`PATCH  /api/design-notes/{id}`          same shape; links replace the set when given
`DELETE /api/design-notes/{id}`
`GET    /api/parts/{pid}/design-notes`   notes anchored to a part + notes referencing it
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..core.db import get_db
from ..models import DesignNote, DesignNoteLink, Part

router = APIRouter(tags=["design-notes"])


class LinkIn(BaseModel):
    part_id: str | None = None
    role: str | None = None
    value_hint: str | None = None
    mpn: str | None = None
    qty: float = 1


class NoteIn(BaseModel):
    part_id: str
    title: str = Field(min_length=1, max_length=160)
    condition: str | None = None
    body: str | None = None
    links: list[LinkIn] = Field(default_factory=list)


class NotePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    condition: str | None = None
    body: str | None = None
    links: list[LinkIn] | None = None


def _link_row(db: Session, lk: DesignNoteLink) -> dict:
    p = lk.part
    return {
        "id": lk.id,
        "part_id": lk.part_id,
        "part_name": p.name if p else None,
        "part_mpn": p.mpn if p else None,
        "on_hand": _on_hand(db, lk.part_id) if lk.part_id else None,
        "role": lk.role,
        "value_hint": lk.value_hint,
        "mpn": lk.mpn,
        "qty": lk.qty,
    }


def _on_hand(db: Session, pid: str) -> int:
    from ..services import on_hand_map

    return on_hand_map(db, [pid]).get(pid, 0)


def _note_row(db: Session, n: DesignNote, *, full: bool = False) -> dict:
    row = {
        "id": n.id,
        "part_id": n.part_id,
        "anchor_name": n.part.name if n.part else None,
        "anchor_mpn": n.part.mpn if n.part else None,
        "title": n.title,
        "condition": n.condition,
        "body": n.body,
        "link_count": len(n.links),
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }
    if full:
        row["links"] = [_link_row(db, lk) for lk in n.links]
    else:
        row["links"] = [
            {"role": lk.role, "value_hint": lk.value_hint,
             "label": (lk.part.name if lk.part else lk.mpn) or "?"}
            for lk in n.links
        ]
    return row


def _apply_links(db: Session, note: DesignNote, links: list[LinkIn]) -> None:
    note.links.clear()
    db.flush()
    for i, lk in enumerate(links):
        note.links.append(
            DesignNoteLink(
                part_id=lk.part_id or None,
                role=lk.role or None,
                value_hint=lk.value_hint or None,
                mpn=lk.mpn or None,
                qty=lk.qty or 1,
                sort_order=i,
            )
        )


@router.get("/api/design-notes")
def list_notes(q: str | None = None, part_id: str | None = None, db: Session = Depends(get_db)):
    stmt = (
        select(DesignNote)
        .options(selectinload(DesignNote.links).selectinload(DesignNoteLink.part),
                 selectinload(DesignNote.part))
        .order_by(DesignNote.updated_at.desc())
    )
    if part_id:
        stmt = stmt.where(DesignNote.part_id == part_id)
    notes = db.scalars(stmt).all()
    if q:
        ql = q.strip().lower()

        def hit(n: DesignNote) -> bool:
            hay = [n.title, n.condition, n.body,
                   n.part.name if n.part else None,
                   n.part.mpn if n.part else None]
            for lk in n.links:
                hay += [lk.role, lk.value_hint, lk.mpn,
                        lk.part.name if lk.part else None,
                        lk.part.mpn if lk.part else None]
            return any(h and ql in h.lower() for h in hay)

        notes = [n for n in notes if hit(n)]
    return [_note_row(db, n) for n in notes]


@router.post("/api/design-notes", status_code=201)
def create_note(body: NoteIn, db: Session = Depends(get_db)):
    if db.get(Part, body.part_id) is None:
        raise HTTPException(400, "unknown part_id (anchor)")
    n = DesignNote(
        part_id=body.part_id, title=body.title,
        condition=body.condition or None, body=body.body or None,
    )
    db.add(n)
    db.flush()
    _apply_links(db, n, body.links)
    db.commit()
    return {"id": n.id}


@router.get("/api/design-notes/{nid}")
def get_note(nid: int, db: Session = Depends(get_db)):
    n = db.get(DesignNote, nid)
    if n is None:
        raise HTTPException(404, "note not found")
    return _note_row(db, n, full=True)


@router.patch("/api/design-notes/{nid}")
def patch_note(nid: int, body: NotePatch, db: Session = Depends(get_db)):
    n = db.get(DesignNote, nid)
    if n is None:
        raise HTTPException(404, "note not found")
    data = body.model_dump(exclude_unset=True)
    links = data.pop("links", None)
    for k, v in data.items():
        setattr(n, k, v or None)
    if links is not None:
        _apply_links(db, n, [LinkIn(**lk) for lk in links])
    db.commit()
    return {"ok": True}


@router.delete("/api/design-notes/{nid}")
def delete_note(nid: int, db: Session = Depends(get_db)):
    n = db.get(DesignNote, nid)
    if n is None:
        raise HTTPException(404, "note not found")
    db.delete(n)
    db.commit()
    return {"ok": True}


@router.get("/api/parts/{pid}/design-notes")
def part_notes(pid: str, db: Session = Depends(get_db)):
    if db.get(Part, pid) is None:
        raise HTTPException(404, "part not found")
    anchored = db.scalars(
        select(DesignNote)
        .options(selectinload(DesignNote.links).selectinload(DesignNoteLink.part),
                 selectinload(DesignNote.part))
        .where(DesignNote.part_id == pid)
    ).all()
    ref_ids = db.scalars(
        select(DesignNoteLink.note_id).where(DesignNoteLink.part_id == pid).distinct()
    ).all()
    referenced = (
        db.scalars(
            select(DesignNote)
            .options(selectinload(DesignNote.links).selectinload(DesignNoteLink.part),
                     selectinload(DesignNote.part))
            .where(DesignNote.id.in_(ref_ids), DesignNote.part_id != pid)
        ).all()
        if ref_ids
        else []
    )
    return {
        "anchored": [_note_row(db, n, full=True) for n in anchored],
        "referenced_by": [_note_row(db, n) for n in referenced],
    }
