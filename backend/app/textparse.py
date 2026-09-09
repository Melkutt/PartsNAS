"""Small text helpers shared by the provider parsers and the lookup router."""
from __future__ import annotations

import re

_RANGE = re.compile(
    r"([-+]?\d+(?:\.\d+)?)\s*°?\s*C?\s*(?:~|to|\.\.\.?|–|—|-)\s*([-+]?\d+(?:\.\d+)?)\s*°?\s*C?",
    re.I,
)


def split_range(s: str | None) -> tuple[str, str] | None:
    """'-55°C ~ +125°C' / '-40 to 85' -> ('-55', '125'). None if not a range."""
    if not s:
        return None
    m = _RANGE.search(s)
    if not m:
        return None
    lo, hi = m.group(1).lstrip("+"), m.group(2).lstrip("+")
    return lo, hi


_METRIC_PAREN = re.compile(r"^(.*?)\s*\(([^()]*mm[^()]*)\)\s*$", re.I)


def metric_first(v: str | None) -> str | None:
    """Distributors write dims imperial-first: '0.240" L x ... (6.10mm x ...)'.
    Swap so the mm figure leads: '6.10mm x ... (0.240" L x ...)'."""
    if not v or '"' not in v:
        return v
    m = _METRIC_PAREN.match(v)
    if not m:
        return v
    outer, inner = m.group(1).strip(), m.group(2).strip()
    if '"' in outer and "mm" not in outer.lower():
        return f"{inner} ({outer})"
    return v


# Mouser sometimes writes both C0G and NP0; some makers treat them as identical.
def canon_tempchar(v: str | None) -> str | None:
    if not v:
        return v
    u = v.upper().replace(" ", "")
    if "C0G" in u or "NP0" in u or "NPO" in u:
        return "C0G (NP0)"
    for code in ("X8R", "X7R", "X6S", "X5R", "Y5V", "Z5U", "Z7T"):
        if code in u:
            return code
    return v
