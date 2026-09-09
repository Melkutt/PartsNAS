"""Part images / file attachments.

`GET    /api/parts/{pid}/images`            list (url + thumb_url)
`POST   /api/parts/{pid}/images`            multipart upload (field: files, repeatable)
`PATCH  /api/parts/{pid}/images/{aid}`      {sort_order} / {kind}
`POST   /api/parts/{pid}/images/{aid}/primary`   make it the list thumbnail
`DELETE /api/parts/{pid}/images/{aid}`

Files live under DATA_DIR/images/<pid>/ ; thumbnails under DATA_DIR/thumbs/<pid>/
and are reachable at /media/<stored>. Non-image files are kept without a thumb.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.db import get_db
from ..models import Attachment, Part

router = APIRouter(tags=["images"])
settings = get_settings()
THUMB_PX = 320
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


class AttachPatch(BaseModel):
    sort_order: int | None = None
    kind: str | None = None


def _need_part(db: Session, pid: str) -> Part:
    p = db.get(Part, pid)
    if p is None:
        raise HTTPException(404, "part not found")
    return p


def _row(a: Attachment) -> dict:
    return {
        "id": a.id,
        "kind": a.kind,
        "filename": a.filename,
        "url": f"/media/{a.stored}",
        "thumb_url": f"/media/{a.thumb}" if a.thumb else None,
        "content_type": a.content_type,
        "size": a.size,
        "sort_order": a.sort_order,
    }


def _refresh_primary(db: Session, part: Part) -> None:
    first = db.scalar(
        select(Attachment)
        .where(Attachment.part_id == part.id, Attachment.kind == "image")
        .order_by(Attachment.sort_order, Attachment.id)
        .limit(1)
    )
    part.image_path = f"/media/{first.thumb or first.stored}" if first else None


@router.get("/api/parts/{pid}/images")
def list_images(pid: str, db: Session = Depends(get_db)):
    _need_part(db, pid)
    rows = db.scalars(
        select(Attachment)
        .where(Attachment.part_id == pid)
        .order_by(Attachment.sort_order, Attachment.id)
    ).all()
    return [_row(a) for a in rows]


def _next_order(db: Session, pid: str) -> int:
    return (
        db.scalar(
            select(Attachment.sort_order)
            .where(Attachment.part_id == pid)
            .order_by(Attachment.sort_order.desc())
            .limit(1)
        )
        or 0
    )


def store_attachment(
    db: Session, pid: str, filename: str, raw: bytes, content_type: str | None
) -> Attachment:
    """Write one file + (for images) a thumbnail, add the Attachment row. Caller
    commits and refreshes the primary."""
    (settings.data_dir / "images" / pid).mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "thumbs" / pid).mkdir(parents=True, exist_ok=True)
    ext = Path(filename or "").suffix.lower() or ".bin"
    key = secrets.token_hex(8)
    stored_rel = f"images/{pid}/{key}{ext}"
    (settings.data_dir / stored_rel).write_bytes(raw)
    thumb_rel = None
    kind = "image" if ext in IMAGE_EXT else ("datasheet" if ext == ".pdf" else "file")
    if kind == "image":
        try:
            im = Image.open(settings.data_dir / stored_rel)
            im.thumbnail((THUMB_PX, THUMB_PX))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            thumb_rel = f"thumbs/{pid}/{key}.jpg"
            im.save(settings.data_dir / thumb_rel, "JPEG", quality=82)
        except (UnidentifiedImageError, OSError):
            kind = "file"
    a = Attachment(
        part_id=pid, kind=kind, filename=filename or f"file{key}",
        stored=stored_rel, thumb=thumb_rel, content_type=content_type,
        size=len(raw), sort_order=_next_order(db, pid) + 1,
    )
    db.add(a)
    return a


@router.post("/api/parts/{pid}/images", status_code=201)
async def upload_images(
    pid: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db)
):
    part = _need_part(db, pid)
    made = []
    for up in files:
        raw = await up.read()
        made.append(store_attachment(db, pid, up.filename or "file", raw, up.content_type))
    db.flush()
    _refresh_primary(db, part)
    db.commit()
    return [_row(a) for a in made]


@router.post("/api/parts/{pid}/design/images", status_code=201)
async def upload_design_images(
    pid: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db)
):
    """Images for the part's Design scratchpad — kept out of the primary/product
    image pool (kind='design')."""
    part = _need_part(db, pid)
    made = []
    for i, up in enumerate(files, 1):
        raw = await up.read()
        a = store_attachment(db, pid, up.filename or f"design-{i}.png", raw, up.content_type)
        a.kind = "design"
        made.append(a)
    db.flush()
    _refresh_primary(db, part)
    db.commit()
    return [_row(a) for a in made]


@router.patch("/api/parts/{pid}/images/{aid}")
def patch_image(pid: str, aid: int, body: AttachPatch, db: Session = Depends(get_db)):
    a = db.get(Attachment, aid)
    if a is None or a.part_id != pid:
        raise HTTPException(404, "attachment not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    _refresh_primary(db, _need_part(db, pid))
    db.commit()
    return {"ok": True}


@router.post("/api/parts/{pid}/images/{aid}/primary")
def make_primary(pid: str, aid: int, db: Session = Depends(get_db)):
    part = _need_part(db, pid)
    target = db.get(Attachment, aid)
    if target is None or target.part_id != pid:
        raise HTTPException(404, "attachment not found")
    others = db.scalars(
        select(Attachment)
        .where(Attachment.part_id == pid, Attachment.id != aid)
        .order_by(Attachment.sort_order, Attachment.id)
    ).all()
    target.sort_order = 0
    for i, o in enumerate(others, 1):
        o.sort_order = i
    _refresh_primary(db, part)
    db.commit()
    return {"ok": True}


@router.delete("/api/parts/{pid}/images/{aid}")
def delete_image(pid: str, aid: int, db: Session = Depends(get_db)):
    a = db.get(Attachment, aid)
    if a is None or a.part_id != pid:
        raise HTTPException(404, "attachment not found")
    for rel in (a.stored, a.thumb):
        if rel:
            (settings.data_dir / rel).unlink(missing_ok=True)
    db.delete(a)
    db.flush()
    _refresh_primary(db, _need_part(db, pid))
    db.commit()
    return {"ok": True}
