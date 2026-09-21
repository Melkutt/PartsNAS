"""BOM (bill of materials) import, matching, projects, and builds.

`POST /api/bom/parse`               multipart file=<KiCad BOM csv> -> preview,
                                     nothing saved yet
`POST /api/bom/projects`            save a reviewed/confirmed BOM as a project
`GET  /api/bom/projects`            list
`GET  /api/bom/projects/{id}`       lines + on-hand + shortage for `boards`
`DELETE /api/bom/projects/{id}`
`POST /api/bom/projects/{id}/build` deduct stock for N boards (reversible)
`POST /api/bom/builds/{id}/undo`
`GET/DELETE /api/bom/match-rules`   remembered Value+Footprint -> Part rules
`POST /api/bom/match`               already-parsed lines (e.g. read from an Interactive HTML BOM)
                                     -> the same preview as /parse
`POST/GET/DELETE /api/bom/projects/{id}/ibom`   the project's Interactive HTML BOM file (an optional
                                     board view; the project works without it)
`POST /api/bom/board/parse`         a KiCad board file (.kicad_pcb) -> what the viewer draws (nothing saved)
`POST/GET/DELETE /api/bom/projects/{id}/board`   the same, kept with the project (data/pcb/<id>.json)
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..bommatch import Matcher, part_summary, remember
from ..bomparse import parse_bom_csv
from ..kicadpcb import extract_board
from ..core.config import get_settings
from ..core.db import get_db
from ..models import BomLine, BomMatchRule, Build, Part, Project, StockEntry
from ..services import location_breakdown, location_breakdown_bulk, on_hand_map

router = APIRouter(prefix="/api/bom", tags=["bom"])


@router.post("/parse")
async def parse(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "expected a KiCad BOM export (.csv)")
    raw = await file.read()
    try:
        rows = parse_bom_csv(raw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    return {"lines": _match_rows(db, rows), "suggested_name": (file.filename.rsplit(".", 1)[0] or "BOM")}


def _match_rows(db: Session, rows: list[dict]) -> list[dict]:
    matcher = Matcher(db)
    return [
        {**r, "match": matcher.match(mpn=r.get("mpn"), value=r.get("value"),
                                     footprint=r.get("footprint"), refdes=r.get("refdes"))}
        for r in rows
    ]


class RawLine(BaseModel):
    mpn: str | None = None
    value: str | None = None
    footprint: str | None = None
    qty: float = 1
    refdes: str | None = None


class MatchIn(BaseModel):
    lines: list[RawLine] = Field(min_length=1, max_length=5000)
    suggested_name: str = "BOM"


@router.post("/match")
def match_lines(body: MatchIn, db: Session = Depends(get_db)):
    """Same preview as /parse, for a parts list that was read somewhere else - the Interactive HTML
    BOM carries one (reference, value, footprint) per component, read by the browser."""
    rows = [{"mpn": ln.mpn or "", "value": ln.value or "", "footprint": ln.footprint or "",
             "qty": ln.qty, "refdes": ln.refdes or ""} for ln in body.lines]
    return {"lines": _match_rows(db, rows), "suggested_name": body.suggested_name or "BOM"}


class LineIn(BaseModel):
    mpn: str | None = None
    value: str | None = None
    footprint: str | None = None
    qty: float = 1
    refdes: str | None = None
    part_id: str | None = None  # None = leave unresolved (fix later)
    remember: bool = False  # save this Value+Footprint -> part_id as a rule


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    notes: str | None = None
    lines: list[LineIn]


def _project_summary(db: Session, p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "notes": p.notes,
        "line_count": len(p.bom_lines),
        "has_ibom": _ibom_path(p.id).is_file(),
        "has_board": _board_path(p.id).is_file(),
        "unresolved_count": sum(1 for ln in p.bom_lines if not ln.part_id),
        "last_build": max((b.created_at.isoformat() for b in p.builds if not b.reverted), default=None),
        "created_at": p.created_at.isoformat(),
    }


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db)):
    if db.scalar(select(Project).where(Project.name == body.name)):
        raise HTTPException(409, "A project with that name already exists")
    proj = Project(name=body.name, notes=body.notes)
    db.add(proj)
    db.flush()
    for ln in body.lines:
        if ln.part_id and db.get(Part, ln.part_id) is None:
            raise HTTPException(400, f"unknown part_id {ln.part_id!r}")
        db.add(BomLine(
            project_id=proj.id, part_id=ln.part_id,
            unresolved_mpn=None if ln.part_id else (ln.mpn or None),
            value=ln.value, footprint=ln.footprint,
            qty_per_board=ln.qty, refdes=ln.refdes,
        ))
        if ln.remember and ln.part_id:
            remember(db, value=ln.value, footprint=ln.footprint, part_id=ln.part_id)
    db.commit()
    return {"id": proj.id}


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    projs = db.scalars(select(Project).order_by(Project.name)).all()
    return [_project_summary(db, p) for p in projs]


@router.get("/projects/{pid}")
def get_project(pid: int, boards: int = 1, db: Session = Depends(get_db)):
    proj = db.get(Project, pid)
    if proj is None:
        raise HTTPException(404, "project not found")
    part_ids = [ln.part_id for ln in proj.bom_lines if ln.part_id]
    on_hand = on_hand_map(db, part_ids)
    where = location_breakdown_bulk(db, part_ids)   # part id -> [{location, qty}], biggest first
    lines = []
    for ln in proj.bom_lines:
        needed = ln.qty_per_board * boards
        have = on_hand.get(ln.part_id, 0) if ln.part_id else 0
        lines.append({
            "id": ln.id,
            "part_id": ln.part_id,
            "part_name": ln.part.name if ln.part else None,
            "part_mpn": ln.part.mpn if ln.part else None,
            "part_summary": part_summary(ln.part) if ln.part else None,
            "unresolved_mpn": ln.unresolved_mpn,
            "value": ln.value,
            "footprint": ln.footprint,
            "refdes": ln.refdes,
            "qty_per_board": ln.qty_per_board,
            "needed": needed,
            "on_hand": have,
            "locations": [{"location": r["location"], "qty": r["qty"]} for r in where.get(ln.part_id, [])] if ln.part_id else [],
            "short": max(0, needed - have) if ln.part_id else None,
        })
    return {
        **_project_summary(db, proj),
        "boards": boards,
        "lines": lines,
        "builds": [
            {"id": b.id, "qty_boards": b.qty_boards, "note": b.note,
             "reverted": b.reverted, "created_at": b.created_at.isoformat()}
            for b in sorted(proj.builds, key=lambda b: b.created_at, reverse=True)
        ],
    }


@router.delete("/projects/{pid}")
def delete_project(pid: int, db: Session = Depends(get_db)):
    proj = db.get(Project, pid)
    if proj is None:
        raise HTTPException(404, "project not found")
    db.delete(proj)
    db.commit()
    _ibom_path(pid).unlink(missing_ok=True)
    _board_path(pid).unlink(missing_ok=True)
    return {"ok": True}


# ---------- the KiCad board (drawn by PartsNAS itself) ----------
BOARD_MAX_BYTES = 60 * 1024 * 1024


def _board_path(pid: int):
    return get_settings().data_dir / "pcb" / f"{pid}.json"


async def _read_board(file: UploadFile) -> dict:
    raw = await file.read(BOARD_MAX_BYTES + 1)
    if len(raw) > BOARD_MAX_BYTES:
        raise HTTPException(413, "that file is larger than 60 MB")
    try:
        return extract_board(raw.decode("utf-8-sig", errors="replace"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RecursionError as e:
        raise HTTPException(400, "that file is nested too deeply to be a KiCad board") from e


@router.post("/board/parse")
async def parse_board(file: UploadFile = File(...)):
    """The drawing model of a .kicad_pcb, for the review step (nothing is saved yet)."""
    return await _read_board(file)


@router.post("/projects/{pid}/board")
async def put_board(pid: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Attach (or replace) the project's board. Only the drawing is kept, not the original file."""
    if db.get(Project, pid) is None:
        raise HTTPException(404, "project not found")
    board = await _read_board(file)
    path = _board_path(pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(board, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "footprints": len(board["footprints"]), "bytes": path.stat().st_size}


@router.get("/projects/{pid}/board")
def get_board(pid: int):
    path = _board_path(pid)
    if not path.is_file():
        raise HTTPException(404, "no board attached to this project")
    return FileResponse(path, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.delete("/projects/{pid}/board")
def delete_board(pid: int):
    _board_path(pid).unlink(missing_ok=True)
    return {"ok": True}


# ---------- the Interactive HTML BOM (optional board view) ----------
IBOM_MAX_BYTES = 40 * 1024 * 1024


def _ibom_path(pid: int):
    return get_settings().data_dir / "ibom" / f"{pid}.html"


@router.post("/projects/{pid}/ibom")
async def put_ibom(pid: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Attach (or replace) the project's ibom.html. It is only a viewer: nothing in the project
    depends on it, so a file this cannot read never breaks the BOM itself."""
    if db.get(Project, pid) is None:
        raise HTTPException(404, "project not found")
    raw = await file.read(IBOM_MAX_BYTES + 1)
    if len(raw) > IBOM_MAX_BYTES:
        raise HTTPException(413, "that file is larger than 40 MB")
    head = raw[:4000].lower()
    if b"<html" not in head or b"pcbdata" not in raw:
        raise HTTPException(400, "that does not look like an Interactive HTML BOM (ibom.html)")
    path = _ibom_path(pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    return {"ok": True, "bytes": len(raw)}


@router.get("/projects/{pid}/ibom")
def get_ibom(pid: int):
    path = _ibom_path(pid)
    if not path.is_file():
        raise HTTPException(404, "no board view attached to this project")
    return FileResponse(path, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})


@router.delete("/projects/{pid}/ibom")
def delete_ibom(pid: int):
    _ibom_path(pid).unlink(missing_ok=True)
    return {"ok": True}


class BuildIn(BaseModel):
    boards: int = Field(gt=0)
    note: str | None = None


@router.post("/projects/{pid}/build", status_code=201)
def build_project(pid: int, body: BuildIn, db: Session = Depends(get_db)):
    proj = db.get(Project, pid)
    if proj is None:
        raise HTTPException(404, "project not found")
    build = Build(project_id=pid, qty_boards=body.boards, note=body.note)
    db.add(build)
    db.flush()
    grp = build.move_group
    for ln in proj.bom_lines:
        if not ln.part_id:
            continue
        need = int(round(ln.qty_per_board * body.boards))
        if need <= 0:
            continue
        for r in location_breakdown(db, ln.part_id):  # largest first
            if need <= 0:
                break
            take = min(need, r["qty"])
            db.add(StockEntry(part_id=ln.part_id, location_id=r["location_id"], delta=-take,
                               kind="build", move_group=grp,
                               note=f"{proj.name} x{body.boards}"))
            need -= take
        if need > 0:  # not enough on hand — record the shortfall so it's visible in history
            db.add(StockEntry(part_id=ln.part_id, location_id=None, delta=-need,
                               kind="build", move_group=grp,
                               note=f"{proj.name} x{body.boards} (shortfall)"))
    db.commit()
    return {"id": build.id}


@router.post("/builds/{bid}/undo")
def undo_build(bid: int, db: Session = Depends(get_db)):
    build = db.get(Build, bid)
    if build is None:
        raise HTTPException(404, "build not found")
    if build.reverted:
        return {"ok": True, "already": True}
    grp = build.move_group
    for e in db.scalars(select(StockEntry).where(StockEntry.move_group == grp)).all():
        db.add(StockEntry(part_id=e.part_id, location_id=e.location_id, delta=-e.delta,
                           kind="correction", move_group=f"undo-{grp}",
                           note=f"undo build #{bid}"))
    build.reverted = True
    db.commit()
    return {"ok": True}


@router.get("/match-rules")
def list_match_rules(db: Session = Depends(get_db)):
    rules = db.scalars(select(BomMatchRule).order_by(BomMatchRule.value_raw)).all()
    return [
        {"id": r.id, "value": r.value_raw, "footprint": r.footprint_raw,
         "part_id": r.part_id, "part_name": r.part.name if r.part else "(deleted part)",
         "created_at": r.created_at.isoformat()}
        for r in rules
    ]


class RulePatch(BaseModel):
    part_id: str


@router.patch("/match-rules/{rid}")
def change_match_rule(rid: int, body: RulePatch, db: Session = Depends(get_db)):
    """Point a remembered Value+Footprint at another part (the BOM does not say which voltage,
    dielectric or fuse style it means - the answer can change)."""
    r = db.get(BomMatchRule, rid)
    if r is None:
        raise HTTPException(404, "rule not found")
    part = db.get(Part, body.part_id)
    if part is None:
        raise HTTPException(400, "unknown part")
    r.part_id = part.id
    db.commit()
    return {"ok": True, "part_name": part.name}


@router.delete("/match-rules/{rid}")
def delete_match_rule(rid: int, db: Session = Depends(get_db)):
    r = db.get(BomMatchRule, rid)
    if r is None:
        raise HTTPException(404, "rule not found")
    db.delete(r)
    db.commit()
    return {"ok": True}
