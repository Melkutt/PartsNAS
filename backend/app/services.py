"""Shared read helpers over the model (stock math, tree paths).

Kept separate from the routers so parts / stock / export all compute on-hand and
category paths the same way.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Category, Part, PartSupplier, StockEntry, StorageLocation


def on_hand_map(db: Session, part_ids: list[str] | None = None) -> dict[str, int]:
    """part_id -> total quantity on hand (SUM of ledger deltas)."""
    q = select(StockEntry.part_id, func.coalesce(func.sum(StockEntry.delta), 0)).group_by(
        StockEntry.part_id
    )
    if part_ids is not None:
        if not part_ids:
            return {}
        q = q.where(StockEntry.part_id.in_(part_ids))
    return {pid: int(total) for pid, total in db.execute(q).all()}


def location_breakdown(db: Session, part_id: str) -> list[dict]:
    """Per-location quantity for one part, zero rows dropped."""
    q = (
        select(StockEntry.location_id, func.sum(StockEntry.delta))
        .where(StockEntry.part_id == part_id)
        .group_by(StockEntry.location_id)
    )
    rows = db.execute(q).all()
    names = dict(
        db.execute(
            select(StorageLocation.id, StorageLocation.name).where(
                StorageLocation.id.in_([lid for lid, _ in rows if lid is not None])
            )
        ).all()
    )
    out = []
    for lid, qty in rows:
        qty = int(qty or 0)
        if qty == 0:
            continue
        out.append(
            {
                "location_id": lid,
                "location": names.get(lid, "Unknown location") if lid else "Unknown location",
                "qty": qty,
            }
        )
    out.sort(key=lambda r: (-r["qty"], r["location"]))
    return out


def location_breakdown_bulk(db: Session, part_ids: list[str]) -> dict[str, list[dict]]:
    if not part_ids:
        return {}
    q = (
        select(StockEntry.part_id, StockEntry.location_id, func.sum(StockEntry.delta))
        .where(StockEntry.part_id.in_(part_ids))
        .group_by(StockEntry.part_id, StockEntry.location_id)
    )
    rows = db.execute(q).all()
    loc_ids = {lid for _, lid, _ in rows if lid is not None}
    names = dict(
        db.execute(
            select(StorageLocation.id, StorageLocation.name).where(
                StorageLocation.id.in_(loc_ids)
            )
        ).all()
    )
    acc: dict[str, list[dict]] = defaultdict(list)
    for pid, lid, qty in rows:
        qty = int(qty or 0)
        if qty == 0:
            continue
        acc[pid].append(
            {"location_id": lid, "location": names.get(lid, "Unknown location"), "qty": qty}
        )
    for lst in acc.values():
        lst.sort(key=lambda r: (-r["qty"], r["location"]))
    return acc


def resolve_part_class(db: Session, cat_id: int | None) -> str | None:
    """Nearest-ancestor `part_class` for a category."""
    seen: set[int] = set()
    cur = db.get(Category, cat_id) if cat_id else None
    while cur and cur.id not in seen:
        if cur.part_class:
            return cur.part_class
        seen.add(cur.id)
        cur = cur.parent
    return None


def category_class_map(db: Session) -> dict[int, str | None]:
    """Every category id -> its resolved part_class (one pass, no recursion cost)."""
    rows = db.execute(select(Category.id, Category.parent_id, Category.part_class)).all()
    own = {i: c for i, _p, c in rows}
    parent = {i: p for i, p, _c in rows}

    def resolve(i: int) -> str | None:
        seen: set[int] = set()
        while i is not None and i not in seen:
            if own.get(i):
                return own[i]
            seen.add(i)
            i = parent.get(i)
        return None

    return {i: resolve(i) for i in own}


def category_path(db: Session, cat_id: int | None) -> str:
    """'Passive > Resistor > Thick film' for one category id."""
    if cat_id is None:
        return ""
    parts: list[str] = []
    seen: set[int] = set()
    cur = db.get(Category, cat_id)
    while cur and cur.id not in seen:
        seen.add(cur.id)
        parts.append(cur.name)
        cur = cur.parent
    return " > ".join(reversed(parts))


def category_path_map(db: Session) -> dict[int, str]:
    """id -> full path, for every category (one query)."""
    rows = db.execute(select(Category.id, Category.name, Category.parent_id)).all()
    name = {i: n for i, n, _ in rows}
    parent = {i: p for i, _, p in rows}

    def path(i: int) -> str:
        chain: list[str] = []
        seen: set[int] = set()
        while i is not None and i not in seen:
            seen.add(i)
            chain.append(name.get(i, "?"))
            i = parent.get(i)
        return " > ".join(reversed(chain))

    return {i: path(i) for i in name}


def descendant_category_ids(db: Session, cat_id: int) -> set[int]:
    out = {cat_id}
    frontier = {cat_id}
    while frontier:
        kids = set(
            db.scalars(select(Category.id).where(Category.parent_id.in_(frontier))).all()
        )
        kids -= out
        out |= kids
        frontier = kids
    return out


def unit_cost_map(db: Session, part_ids: list[str]) -> dict[str, tuple[float, str, float]]:
    """part_id -> (ex-VAT unit cost, currency, vat_percent) for the parts that have a price on file, else absent.

    The same rule a quote uses (quotes.snapshot_cost): the preferred supplier link wins, otherwise the dearest
    priced link; a part with no priced link falls back to its most recent priced purchase."""
    if not part_ids:
        return {}
    out: dict[str, tuple[float, str, float]] = {}
    best: dict[str, PartSupplier] = {}
    for link in db.scalars(select(PartSupplier).where(PartSupplier.part_id.in_(part_ids), PartSupplier.unit_price.is_not(None))):
        cur = best.get(link.part_id)
        if cur is None or (link.preferred, link.unit_price or 0) > (cur.preferred, cur.unit_price or 0):
            best[link.part_id] = link
    for pid, link in best.items():
        if link.unit_price and link.unit_price > 0:
            out[pid] = (link.unit_price, link.currency, link.vat_percent)
    rest = [pid for pid in part_ids if pid not in out]
    if rest:
        for e in db.scalars(
            select(StockEntry)
            .where(StockEntry.part_id.in_(rest), StockEntry.delta > 0, StockEntry.unit_price.is_not(None))
            .order_by(StockEntry.id.desc())
        ):
            if e.part_id not in out and e.unit_price and e.unit_price > 0:
                out[e.part_id] = (e.unit_price, e.currency, e.vat_percent)
    return out
