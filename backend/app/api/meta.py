"""Static / derived metadata the frontend needs.

`GET /api/meta/part-classes`   per-class field schemas (base + *_extra overlay)
`GET /api/meta/attr-values`    distinct values already used for each attribute key,
                               so the edit form can offer them as a datalist
"""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Part
from ..partschema import part_class_schema

router = APIRouter(prefix="/api/meta", tags=["meta"])

_num = re.compile(r"^-?\d+(\.\d+)?$")
_cache: dict = {"t": 0, "v": None}


@router.get("/part-classes")
def part_classes():
    return part_class_schema()


def _sort_key(v: str):
    return (0, float(v)) if _num.match(v) else (1, v.lower())


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
