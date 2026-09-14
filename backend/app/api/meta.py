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
from ..models import Category, Part
from ..partschema import part_class_schema
from ..services import category_class_map, category_path_map, descendant_category_ids

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
    category_id: int
    selected: list[FacetEntry]


def _facet_store(db: Session) -> dict:
    """`facets:visible` -> {str(category_id): [{id,label}, ...]}. Defensively
    resets a pre-per-category flat-list value (only ever same-session test data,
    never real user configuration) instead of trying to migrate it."""
    store = get_kv(db, "facets:visible", {})
    return store if isinstance(store, dict) else {}


def _available_attrs_for_category(db: Session, category_id: int) -> list[dict]:
    """Non-bool schema fields + real unmapped attribute keys, scoped to the
    part classes actually in play under this category (not the whole DB) —
    same idea as parts.py's /facets endpoint, just anchored to one subtree."""
    schema = part_class_schema()
    ids = descendant_category_ids(db, category_id)
    ccmap = category_class_map(db)
    classes = {ccmap.get(cid) for cid in ids} - {None}
    attrs: dict[str, dict] = {}
    for cls in classes:
        for f in schema.get(cls, {}).get("fields", []):
            if f["type"] == "bool" or f["key"] in attrs:
                continue
            attrs[f["key"]] = {"key": f["key"], "label": f["label"], "unit": f.get("unit")}
    seen_keys: set[str] = set()
    for (a,) in db.execute(select(Part.attributes).where(Part.category_id.in_(ids))).all():
        seen_keys |= set((a or {}).keys())
    for key in sorted(seen_keys):
        if key not in attrs and _KEY_RE.match(key):
            attrs[key] = {"key": key, "label": key.replace("_", " "), "unit": None}
    return sorted(attrs.values(), key=lambda a: a["label"].lower())


@router.get("/facet-config")
def get_facet_config(category_id: int | None = None, db: Session = Depends(get_db)):
    """Filter groups a Parts-view category has customized, plus what it could
    add. "All categories" / Unsorted / Locations mode never pass a category_id
    (or pass Unsorted's) and always render unrestricted — see parts.js."""
    cat = db.get(Category, category_id) if category_id is not None else None
    editable = cat is not None and not cat.is_unsorted
    if not editable:
        return {"selected": [], "editable": False, "available": {"builtins": _BUILTIN_FACETS, "attrs": []}}
    store = _facet_store(db)
    return {
        "selected": store.get(str(category_id), []),
        "editable": True,
        "available": {
            "builtins": _BUILTIN_FACETS,
            "attrs": _available_attrs_for_category(db, category_id),
        },
    }


@router.put("/facet-config")
def put_facet_config(body: FacetConfig, db: Session = Depends(get_db)):
    cat = db.get(Category, body.category_id)
    if cat is None:
        raise HTTPException(404, "category not found")
    if cat.is_unsorted:
        raise HTTPException(400, "Unsorted always shows every filter and can't be customized")
    builtin_ids = {b["id"] for b in _BUILTIN_FACETS}
    out = []
    for e in body.selected:
        if e.id not in builtin_ids and not (e.id.startswith("attr:") and _KEY_RE.match(e.id[5:])):
            raise HTTPException(400, f"unknown facet id {e.id!r}")
        out.append({"id": e.id, "label": (e.label or "").strip() or None})
    store = _facet_store(db)
    if out:
        store[str(body.category_id)] = out
    else:
        store.pop(str(body.category_id), None)
    set_kv(db, "facets:visible", store)
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
