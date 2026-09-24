"""KiCad HTTP library (KiCad 8+): KiCad's symbol chooser asks PartsNAS for parts.

`GET /api/kicad/v1/`                          {categories, parts} (KiCad only checks that the keys exist)
`GET /api/kicad/v1/categories.json`           [{id, name, description}] - categories that hold ready parts
`GET /api/kicad/v1/parts/category/{id}.json`  [{id, name, description}]
`GET /api/kicad/v1/parts/{id}.json`           one part: symbolIdStr + fields (value, footprint, datasheet, MPN ...)
`GET /api/kicad/suggest`                      names that can be worked out for standard passives (preview)
`POST /api/kicad/apply`                       {ids: [...]} fill in those names (only where a part has none)

Only READY parts are shown to KiCad: those whose KiCad symbol and footprint both name their library
(see kicadlib.is_named). No token: like the rest of PartsNAS it is meant for a trusted home network.
All values are strings, as the KiCad specification requires.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..bommatch import _VALUE_KEYS, _pick_attr, part_summary
from ..core.db import get_db
from ..kicadlib import is_named, reference_for, suggest_names
from ..models import Part
from ..services import category_path_map

router = APIRouter(prefix="/api/kicad", tags=["kicad"])


def _ready(db: Session) -> list[Part]:
    parts = db.scalars(select(Part).where(Part.kicad_symbol.is_not(None), Part.kicad_footprint.is_not(None))).all()
    return [p for p in parts if is_named(p.kicad_symbol, p.kicad_footprint)]


def _cat_name(paths: dict[int, str], cid: int | None) -> str:
    return (paths.get(cid) or "Uncategorized").replace(" > ", "/")


@router.get("/v1/")
def root():
    return {"categories": "", "parts": ""}


@router.get("/v1/categories.json")
def categories(db: Session = Depends(get_db)):
    paths = category_path_map(db)
    ids = sorted({p.category_id for p in _ready(db)}, key=lambda i: _cat_name(paths, i))
    return [{"id": str(i if i is not None else 0), "name": _cat_name(paths, i),
             "description": _cat_name(paths, i)} for i in ids]


@router.get("/v1/parts/category/{cid}.json")
def parts_in_category(cid: int, db: Session = Depends(get_db)):
    want = None if cid == 0 else cid
    return [{"id": p.id, "name": p.name, "description": part_summary(p)}
            for p in sorted(_ready(db), key=lambda p: (p.name or "").lower()) if p.category_id == want]


@router.get("/v1/parts/{pid}.json")
def one_part(pid: str, db: Session = Depends(get_db)):
    p = db.get(Part, pid)
    if p is None or not is_named(p.kicad_symbol, p.kicad_footprint):
        raise HTTPException(404, "part not found, or it has no KiCad symbol and footprint yet")
    attrs = p.attributes or {}
    fields: dict[str, dict] = {
        "value": {"value": _pick_attr(attrs, _VALUE_KEYS) or p.name},
        "footprint": {"value": p.kicad_footprint, "visible": "False"},
        "datasheet": {"value": (p.datasheet_url or "~").strip(), "visible": "False"},
    }
    ref = reference_for(p.kicad_symbol)
    if ref:
        fields["reference"] = {"value": ref}
    if p.mpn:
        fields["MPN"] = {"value": p.mpn, "visible": "False"}
    if p.manufacturer:
        fields["Manufacturer"] = {"value": p.manufacturer, "visible": "False"}
    return {"id": p.id, "name": p.name, "symbolIdStr": p.kicad_symbol, "description": part_summary(p),
            "fields": fields}


# ---- names for standard passives (Parts -> "KiCad names...") -----------------------------------

def _proposals(db: Session) -> tuple[list[dict], int, int]:
    """(proposals, ready count, parts with nothing to suggest). A proposal only ever fills what is EMPTY."""
    paths = category_path_map(db)
    proposals: list[dict] = []
    ready = other = 0
    for p in db.scalars(select(Part)).all():
        if is_named(p.kicad_symbol, p.kicad_footprint):
            ready += 1
            continue
        s = suggest_names(paths.get(p.category_id), p.footprint_raw)
        symbol = None if (p.kicad_symbol or "").strip() else s and s["symbol"]
        footprint = None if (p.kicad_footprint or "").strip() else s and s["footprint"]
        if s and (symbol or footprint):
            proposals.append({"id": p.id, "name": p.name, "category": _cat_name(paths, p.category_id),
                              "footprint_raw": p.footprint_raw, "symbol": symbol, "footprint": footprint})
        else:
            other += 1
    proposals.sort(key=lambda x: (x["category"], x["name"].lower()))
    return proposals, ready, other


@router.get("/suggest")
def suggest(db: Session = Depends(get_db)):
    proposals, ready, other = _proposals(db)
    return {"ready": ready, "proposals": proposals, "other": other}


class ApplyIn(BaseModel):
    ids: list[str]


@router.post("/apply")
def apply(body: ApplyIn, db: Session = Depends(get_db)):
    """Fill in the suggested names for these parts. Only empty fields are written - a name you typed yourself
    is never replaced."""
    proposals, _ready_n, _other = _proposals(db)
    want = set(body.ids)
    n = 0
    for pr in proposals:
        if pr["id"] not in want:
            continue
        p = db.get(Part, pr["id"])
        if pr["symbol"]:
            p.kicad_symbol = pr["symbol"]
        if pr["footprint"]:
            p.kicad_footprint = pr["footprint"]
        n += 1
    db.commit()
    return {"updated": n}
