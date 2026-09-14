"""Static / derived metadata the frontend needs.

`GET /api/meta/part-classes`     per-class field schemas (base + *_extra overlay)
`GET /api/meta/attr-values`      distinct values already used for each attribute key
`GET/PUT /api/meta/attr-rules`   user-defined attribute-text -> category rules
`GET/PUT /api/meta/facet-config` user-picked, ordered, optionally-renamed set of
                                 filter groups shown in the Parts view sidebar
"""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..catmatch import builtin_attr_rules, custom_attr_rules
from ..core.db import get_db
from ..core.kv import get_kv, set_kv
from ..models import Part
from ..partschema import part_class_schema
from ..services import category_path_map

router = APIRouter(prefix="/api/meta", tags=["meta"])

_num = re.compile(r"^-?\d+(\.\d+)?$")
_cache: dict = {"t": 0, "v": None}

_KEY_RE = re.compile(r"^[a-z0-9_]+$")
_BUILTIN_FACETS = [
    {"id": "mount", "label": "Mount"},
    {"id": "footprint", "label": "Footprint"},
    {"id": "manufacturer", "label": "Manufacturer"},
    {"id": "location", "label": "Location"},
    {"id": "tags", "label": "Tags"},
    {"id": "in_stock", "label": "Stock"},
]


@router.get("/part-classes")
def part_classes():
    return part_class_schema()


def _sort_key(v: str):
    return (0, float(v)) if _num.match(v) else (1, v.lower())


class AttrRule(BaseModel):
    pattern: str
    regex: bool = False
    category_id: int
    note: str = ""


class AttrRules(BaseModel):
    rules: list[AttrRule]


@router.get("/attr-rules")
def get_attr_rules(db: Session = Depends(get_db)):
    paths = category_path_map(db)
    rules = []
    for r in custom_attr_rules(db):
        rules.append({**r, "category_path": paths.get(r.get("category_id"), "?")})
    return {"rules": rules, "builtin": builtin_attr_rules()}


@router.put("/attr-rules")
def put_attr_rules(body: AttrRules, db: Session = Depends(get_db)):
    paths = category_path_map(db)
    out = []
    for r in body.rules:
        pat = r.pattern.strip()
        if not pat:
            continue
        if r.category_id not in paths:
            raise HTTPException(400, f"unknown category_id {r.category_id}")
        if r.regex:
            try:
                re.compile(pat)
            except re.error as e:
                raise HTTPException(400, f"bad regex {pat!r}: {e}")
        out.append({
            "pattern": pat, "regex": r.regex,
            "category_id": r.category_id, "category_path": paths[r.category_id],
            "note": r.note.strip(),
        })
    set_kv(db, "catmatch:attr_rules", out)
    return {"ok": True, "count": len(out)}


class FacetEntry(BaseModel):
    id: str
    label: str | None = None


class FacetConfig(BaseModel):
    selected: list[FacetEntry]


@router.get("/facet-config")
def get_facet_config(db: Session = Depends(get_db)):
    schema = part_class_schema()
    attrs: dict[str, dict] = {}
    for cls in schema.values():
        for f in cls.get("fields", []):
            if f["type"] == "bool" or f["key"] in attrs:
                continue
            attrs[f["key"]] = {"key": f["key"], "label": f["label"], "unit": f.get("unit")}
    seen_keys: set[str] = set()
    for (a,) in db.execute(select(Part.attributes)).all():
        seen_keys |= set((a or {}).keys())
    for key in sorted(seen_keys):
        if key not in attrs and _KEY_RE.match(key):
            attrs[key] = {"key": key, "label": key.replace("_", " "), "unit": None}
    return {
        "selected": get_kv(db, "facets:visible", []),
        "available": {
            "builtins": _BUILTIN_FACETS,
            "attrs": sorted(attrs.values(), key=lambda a: a["label"].lower()),
        },
    }


@router.put("/facet-config")
def put_facet_config(body: FacetConfig, db: Session = Depends(get_db)):
    builtin_ids = {b["id"] for b in _BUILTIN_FACETS}
    out = []
    for e in body.selected:
        if e.id not in builtin_ids and not (e.id.startswith("attr:") and _KEY_RE.match(e.id[5:])):
            raise HTTPException(400, f"unknown facet id {e.id!r}")
        out.append({"id": e.id, "label": (e.label or "").strip() or None})
    set_kv(db, "facets:visible", out)
    return {"ok": True, "count": len(out)}


@router.get("/attr-values")
def attr_values(db: Session = Depends(get_db)):
    if _cache["v"] is not None and time.time() - _cache["t"] < 30:
        return _cache["v"]
    seen: dict[str, set] = {}
    for (attrs,) in db.execute(select(Part.attributes)).all():
        for k, v in (attrs or {}).items():
            if v in (None, "", True, False):
                continue
            seen.setdefault(k, set()).add(str(v))
    out = {k: sorted(vs, key=_sort_key) for k, vs in seen.items()}
    _cache.update(t=time.time(), v=out)
    return out
