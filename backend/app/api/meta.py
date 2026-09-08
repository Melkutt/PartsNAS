"""Static metadata the frontend needs: the per-class field schemas."""
from __future__ import annotations

import json
from functools import lru_cache

from fastapi import APIRouter

from ..core.config import get_settings

router = APIRouter(prefix="/api/meta", tags=["meta"])


@lru_cache
def _part_classes() -> dict:
    p = get_settings().seed_dir / "part_classes.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


@router.get("/part-classes")
def part_classes():
    return _part_classes()
