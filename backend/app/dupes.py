"""Parts that share a manufacturer part number.

Nothing here deletes or merges anything: the same MPN can legitimately sit on two parts
(two packagings, a part kept in two boxes), and it is easy to forget that a part is
already in the database. So the app only points it out.

MPNs are compared with case, spaces, dashes and other punctuation ignored:
"MFR-12FTF52-3K3", "mfr12ftf52 3k3" and "MFR12FTF523K3" are the same part.
"""
from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Part

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def norm_mpn(mpn: str | None) -> str | None:
    n = _NON_ALNUM.sub("", (mpn or "").lower())
    return n or None


def _groups(db: Session) -> dict[str, list[str]]:
    by_norm: dict[str, list[str]] = defaultdict(list)
    for pid, mpn in db.execute(select(Part.id, Part.mpn)).all():
        n = norm_mpn(mpn)
        if n:
            by_norm[n].append(pid)
    return {n: ids for n, ids in by_norm.items() if len(ids) > 1}


def duplicate_counts(db: Session) -> dict[str, int]:
    """part id -> how many OTHER parts share its MPN (only parts that have any)."""
    return {pid: len(ids) - 1 for ids in _groups(db).values() for pid in ids}


def duplicate_ids(db: Session) -> set[str]:
    return {pid for ids in _groups(db).values() for pid in ids}


def parts_with_mpn(db: Session, mpn: str | None, *, exclude: str | None = None) -> list[Part]:
    """Every part whose MPN matches `mpn` (normalised), except `exclude`."""
    n = norm_mpn(mpn)
    if not n:
        return []
    rows = db.execute(select(Part.id, Part.mpn)).all()
    ids = [pid for pid, m in rows if norm_mpn(m) == n and pid != exclude]
    if not ids:
        return []
    return list(db.scalars(select(Part).where(Part.id.in_(ids)).order_by(Part.name)).all())
