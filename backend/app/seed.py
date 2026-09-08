"""First-run seeding from the JSON files under seed/ (produced by
scripts/extract_spec.py). Safe to call on every startup: it only fills tables
that are still empty and always guarantees an "Unsorted" catch-all category.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .core.config import get_settings
from .models import Category, FootprintAlias, StorageLocation

UNSORTED_NAME = "Unsorted / Uncategorized"


def _slug(name: str) -> str:
    s = name.lower().replace("å", "a").replace("ä", "a").replace("ö", "o")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "cat"


def _load(name: str):
    path = get_settings().seed_dir / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _insert_category_tree(db: Session, nodes: list[dict], parent: Category | None, order0: int = 0):
    for i, node in enumerate(nodes):
        cat = Category(
            parent=parent,
            name=node["name"],
            slug=_slug(node["name"]),
            sort_order=order0 + i,
            comment=node.get("comment"),
        )
        db.add(cat)
        db.flush()
        kids = node.get("children") or []
        if kids:
            _insert_category_tree(db, kids, cat)


def seed_categories(db: Session) -> None:
    if db.scalar(select(Category).limit(1)):
        return
    tree = _load("categories.json") or []
    _insert_category_tree(db, tree, None)
    unsorted = db.scalar(select(Category).where(Category.name == UNSORTED_NAME))
    if not unsorted:
        unsorted = Category(
            name=UNSORTED_NAME, slug="unsorted", sort_order=999, is_unsorted=True
        )
        db.add(unsorted)
    else:
        unsorted.is_unsorted = True
    db.commit()


def seed_footprints(db: Session) -> None:
    if db.scalar(select(FootprintAlias).limit(1)):
        return
    for row in _load("footprint_aliases.json") or []:
        db.add(
            FootprintAlias(
                canonical=row["canonical"],
                aliases=row.get("aliases") or [],
                group=row.get("group"),
                kicad_footprint=row.get("kicad_footprint"),
            )
        )
    db.commit()


def seed_locations(db: Session) -> None:
    """Optional: a flat starter list from the PartsBox export, if present as
    seed/storage_locations.json ([{legacy_id, name}, ...]). The importer creates
    the rest as needed."""
    if db.scalar(select(StorageLocation).limit(1)):
        return
    for i, row in enumerate(_load("storage_locations.json") or []):
        db.add(
            StorageLocation(
                name=row["name"], legacy_id=row.get("legacy_id"), sort_order=i
            )
        )
    db.commit()


def run_all(db: Session) -> None:
    seed_categories(db)
    seed_footprints(db)
    seed_locations(db)
