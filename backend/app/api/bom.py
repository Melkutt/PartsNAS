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
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..bommatch import Matcher, remember
from ..bomparse import parse_bom_csv
from ..core.db import get_db
from ..models import BomLine, BomMatchRule, Build, Part, Project, StockEntry
from ..services import location_breakdown, on_hand_map

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

    matcher = Matcher(db)
    out = []
    for r in rows:
        m = matcher.match(mpn=r["mpn"], value=r["value"], footprint=r["footprint"])
        out.append({**r, "match": m})
    return {"lines": out, "suggested_name": (file.filename.rsplit(".", 1)[0] or "BOM")}


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
    lines = []
    for ln in proj.bom_lines:
        needed = ln.qty_per_board * boards
        have = on_hand.get(ln.part_id, 0) if ln.part_id else 0
        lines.append({
            "id": ln.id,
            "part_id": ln.part_id,
            "part_name": ln.part.name if ln.part else None,
            "part_mpn": ln.part.mpn if ln.part else None,
            "unresolved_mpn": ln.unresolved_mpn,
            "value": ln.value,
            "footprint": ln.footprint,
            "refdes": ln.refdes,
            "qty_per_board": ln.qty_per_board,
            "needed": needed,
            "on_hand": have,
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


@router.delete("/match-rules/{rid}")
def delete_match_rule(rid: int, db: Session = Depends(get_db)):
    r = db.get(BomMatchRule, rid)
    if r is None:
        raise HTTPException(404, "rule not found")
    db.delete(r)
    db.commit()
    return {"ok": True}
