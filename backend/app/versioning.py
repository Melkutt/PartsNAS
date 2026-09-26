"""Comparing PartsNAS version numbers ("0.8.0" < "0.10.0") - used by the update check and the snapshot restore."""
from __future__ import annotations

import re


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """(0, 8, 0) for "0.8.0" or "v0.8.0"; None when there is no number to read. A suffix ("-beta") is ignored."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", str(text or ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def compare(a: str | None, b: str | None) -> int | None:
    """-1 / 0 / 1 for a < b / a == b / a > b; None when either is not a version."""
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None:
        return None
    n = max(len(pa), len(pb))
    pa, pb = pa + (0,) * (n - len(pa)), pb + (0,) * (n - len(pb))
    return (pa > pb) - (pa < pb)
