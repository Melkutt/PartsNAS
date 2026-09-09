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


_CLASS_LABELS = {"fuse": "Fuse"}


@lru_cache
def part_class_schema() -> dict:
    d = get_settings().seed_dir
    base = json.loads((d / "part_classes.json").read_text(encoding="utf-8"))
    extra_p = d / "part_classes_extra.json"
    if not extra_p.exists():
        return base
    extra = json.loads(extra_p.read_text(encoding="utf-8"))
    shared = extra.pop("_shared", [])
    for cid, fields in extra.items():
        cls = base.setdefault(
            cid, {"id": cid, "label": _CLASS_LABELS.get(cid, cid.replace("_", " ").title()), "fields": []}
        )
        cls["fields"] = _merge(cls["fields"], fields)  # extra overrides base on key collision
    for cls in base.values():
        cls["fields"] = _merge(cls["fields"], shared)  # shared appended if missing
    return base


def _merge(base_fields: list[dict], extra_fields: list[dict]) -> list[dict]:
    by_key = {f["key"]: f for f in extra_fields}
    seen: set[str] = set()
    out: list[dict] = []
    for bf in base_fields:
        out.append(by_key.get(bf["key"], bf))
        seen.add(bf["key"])
    for f in extra_fields:
        if f["key"] not in seen:
            out.append(f)
    return out


def fields_for(class_id: str | None) -> list[dict]:
    if not class_id:
        return []
    return part_class_schema().get(class_id, {}).get("fields", [])
