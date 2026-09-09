"""Static / derived metadata the frontend needs.

`GET /api/meta/part-classes`   per-class field schemas (base + *_extra overlay)
`GET /api/meta/attr-values`    distinct values already used for each attribute key
`GET/PUT /api/meta/attr-rules` user-defined attribute-text -> category rules
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
from ..core.kv import set_kv
from ..models import Part
from ..partschema import part_class_schema
from ..services import category_path_map

router = APIRouter(prefix="/api/meta", tags=["meta"])

_num = re.compile(r"^-?\d+(\.\d+)?$")
_cache: dict = {"t": 0, "v": None}


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
