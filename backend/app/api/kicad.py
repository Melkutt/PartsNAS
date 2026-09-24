"""KiCad HTTP library (KiCad 8+): KiCad's symbol chooser asks PartsNAS for parts.

`GET /api/kicad/v1/`                          {categories, parts} (KiCad only checks that the keys exist)
`GET /api/kicad/v1/categories.json`           [{id, name, description}] - categories that hold ready parts
`GET /api/kicad/v1/parts/category/{id}.json`  [{id, name, description}]
`GET /api/kicad/v1/parts/{id}.json`           one part: symbolIdStr + fields (value, footprint, datasheet, MPN ...)
`GET /api/kicad/suggest?prefer=`              names that can be worked out for standard passives (preview)
`POST /api/kicad/apply`                       {ids: [...], prefer} fill in those names (only where a part has none)

Only READY parts are shown to KiCad: those whose KiCad symbol and footprint both name their library
(see kicadlib.is_named). No token: like the rest of PartsNAS it is meant for a trusted home network.
All values are strings, as the KiCad specification requires.

A part can have several footprints (`Part.kicad_footprint` is the default, `kicad_footprint_alts` the others,
one per line). Each other footprint is ALSO listed as an entry of its own ("<name> · <footprint>", id
"<part id>~<n>"), so which one to use is decided when the part is placed; every entry also carries
`footprint_filters`, so KiCad's footprint chooser offers the alternatives (and every pad variant of the
default's package) later too.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..bommatch import _VALUE_KEYS, _pick_attr, part_summary
from ..core.db import get_db
from ..kicadlib import footprint_filters, is_named, reference_for, split_footprints, suggest_names
from ..kicadrules import all_rules, default_rules, match_rule, package_texts, save_user_rules, user_rules
from ..models import Part
from ..services import category_path_map, descendant_category_ids

router = APIRouter(prefix="/api/kicad", tags=["kicad"])


def _ready(db: Session) -> list[Part]:
    parts = db.scalars(select(Part).where(Part.kicad_symbol.is_not(None), Part.kicad_footprint.is_not(None))).all()
    return [p for p in parts if is_named(p.kicad_symbol, p.kicad_footprint)]


def _alts(p: Part) -> list[str]:
    """The other footprints of a part (only ones that name their library), never the default again."""
    return [f for f in split_footprints(p.kicad_footprint_alts) if ":" in f and f != p.kicad_footprint]


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
    out = []
    for p in sorted(_ready(db), key=lambda p: (p.name or "").lower()):
        if p.category_id != want:
            continue
        out.append({"id": p.id, "name": p.name, "description": part_summary(p)})
        for n, alt in enumerate(_alts(p), start=1):
            out.append({"id": f"{p.id}~{n}", "name": f"{p.name} · {alt.split(':', 1)[1]}", "description": part_summary(p)})
    return out


@router.get("/v1/parts/{pid}.json")
def one_part(pid: str, db: Session = Depends(get_db)):
    base, _, variant = pid.partition("~")
    p = db.get(Part, base)
    if p is None or not is_named(p.kicad_symbol, p.kicad_footprint):
        raise HTTPException(404, "part not found, or it has no KiCad symbol and footprint yet")
    alts = _alts(p)
    footprint, name = p.kicad_footprint, p.name
    if variant:
        if not variant.isdigit() or not 1 <= int(variant) <= len(alts):
            raise HTTPException(404, "no such footprint variant")
        footprint = alts[int(variant) - 1]
        name = f"{p.name} · {footprint.split(':', 1)[1]}"
    attrs = p.attributes or {}
    fields: dict[str, dict] = {
        "value": {"value": _pick_attr(attrs, _VALUE_KEYS) or p.name},
        "footprint": {"value": footprint, "visible": "False"},
        "datasheet": {"value": (p.datasheet_url or "~").strip(), "visible": "False"},
    }
    ref = reference_for(p.kicad_symbol)
    if ref:
        fields["reference"] = {"value": ref}
    if p.mpn:
        fields["MPN"] = {"value": p.mpn, "visible": "False"}
    if p.manufacturer:
        fields["Manufacturer"] = {"value": p.manufacturer, "visible": "False"}
    out = {"id": pid, "name": name, "symbolIdStr": p.kicad_symbol, "description": part_summary(p), "fields": fields}
    filters = footprint_filters(p.kicad_footprint, alts)
    if filters:
        out["footprint_filters"] = filters
    return out


# ---- names for standard passives (Parts -> "KiCad names...") -----------------------------------

def _proposals(db: Session, prefer: str = "standard", category_id: int | None = None) -> tuple[list[dict], int, int]:
    """(proposals, ready count, parts with nothing to suggest) - for one category and everything below it, or
    all parts. A proposal only ever fills what is EMPTY: the default footprint and the alternatives are filled
    separately, and the alternatives only when the part's footprint is the one suggested here (a footprint typed
    by hand is not second-guessed). Standard SMD passives are named from category + package size, everything
    else from the footprint rules (`assumed` ones are proposed, but unticked)."""
    paths = category_path_map(db)
    rules = all_rules(db)
    scope = descendant_category_ids(db, category_id) if category_id else None
    proposals: list[dict] = []
    ready = other = 0
    for p in db.scalars(select(Part)).all():
        if scope is not None and p.category_id not in scope:
            continue
        s = suggest_names(paths.get(p.category_id), p.footprint_raw, prefer)
        symbol = footprint = None
        alts: list[str] = []
        rule = None
        assumed = False
        if s:
            symbol = None if (p.kicad_symbol or "").strip() else s["symbol"]
            footprint = None if (p.kicad_footprint or "").strip() else s["footprint"]
            options = [s["footprint"], *s["alts"]]
            ours = footprint is not None or (p.kicad_footprint or "") in options
            if ours and not (p.kicad_footprint_alts or "").strip():
                keep = footprint or p.kicad_footprint
                alts = [o for o in options if o != keep]
        else:
            have = (p.kicad_footprint or "").strip()
            hit = match_rule(rules, package_texts(p.attributes, p.footprint_raw), paths.get(p.category_id))
            if hit and not have:
                footprint, rule, assumed = hit["footprint"], hit["rule"], hit["assumed"]
            elif hit and ":" not in have and hit["footprint"].split(":", 1)[1] == have:
                # the right footprint typed without its library: only the library is missing, so add it
                footprint, rule, assumed = hit["footprint"], f"{hit['rule']} (adds the library)", hit["assumed"]
        named = is_named(p.kicad_symbol, p.kicad_footprint)
        ready += named
        if symbol or footprint or alts:
            proposals.append({"id": p.id, "name": p.name, "category": _cat_name(paths, p.category_id),
                              "footprint_raw": p.footprint_raw, "symbol": symbol, "footprint": footprint, "alts": alts,
                              "rule": rule, "assumed": assumed,
                              "package": " | ".join(t for t in package_texts(p.attributes, None).values() if t)})
        elif not named:
            other += 1
    proposals.sort(key=lambda x: (x["category"], x["name"].lower()))
    return proposals, ready, other


def _prefer(value: str) -> str:
    return "hand" if value == "hand" else "standard"


@router.get("/suggest")
def suggest(prefer: str = "standard", category_id: int | None = None, db: Session = Depends(get_db)):
    proposals, ready, other = _proposals(db, _prefer(prefer), category_id)
    paths = category_path_map(db)
    return {"ready": ready, "proposals": proposals, "other": other,
            "scope": _cat_name(paths, category_id) if category_id else None}


class ApplyIn(BaseModel):
    ids: list[str]
    prefer: str = "standard"      # "hand": hand-solder pads are the default footprint, the standard ones an alternative
    category_id: int | None = None


@router.post("/apply")
def apply(body: ApplyIn, db: Session = Depends(get_db)):
    """Fill in the suggested names for these parts. Only empty fields are written - a name you have typed yourself
    is never replaced."""
    proposals, _ready_n, _other = _proposals(db, _prefer(body.prefer), body.category_id)
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
        if pr["alts"]:
            p.kicad_footprint_alts = "\n".join(pr["alts"])
        n += 1
    db.commit()
    return {"updated": n}


# ---- the footprint rules (Settings) ------------------------------------------------------------

class RulesIn(BaseModel):
    rules: list[dict]


@router.get("/rules")
def get_rules(db: Session = Depends(get_db)):
    """`user`: your own rules (tried first), `defaults`: the built-in ones (read only)."""
    return {"user": user_rules(db), "defaults": default_rules()}


@router.put("/rules")
def put_rules(body: RulesIn, db: Session = Depends(get_db)):
    try:
        return {"user": save_user_rules(db, body.rules)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
