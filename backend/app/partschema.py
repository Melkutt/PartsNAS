"""The per-class parameter schema = seed/part_classes.json with the hand-kept
seed/part_classes_extra.json merged on top (extra dimensions the spec workbook
didn't cover: lead pitch, body W/H, radial/axial mounting, ...).

extract_spec.py regenerates the base file from the Swedish workbook; put anything
new in the *_extra.json overlay so a regen doesn't wipe it.
"""
from __future__ import annotations

import json
from functools import lru_cache

from .core.config import get_settings


@lru_cache
def part_class_schema() -> dict:
    d = get_settings().seed_dir
    base = json.loads((d / "part_classes.json").read_text(encoding="utf-8"))
    extra_p = d / "part_classes_extra.json"
    if extra_p.exists():
        extra = json.loads(extra_p.read_text(encoding="utf-8"))
        for cid, fields in extra.items():
            cls = base.setdefault(cid, {"id": cid, "label": cid, "fields": []})
            have = {f["key"] for f in cls["fields"]}
            for f in fields:
                if f["key"] not in have:
                    cls["fields"].append(f)
    return base


def fields_for(class_id: str | None) -> list[dict]:
    if not class_id:
        return []
    return part_class_schema().get(class_id, {}).get("fields", [])
