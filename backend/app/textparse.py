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


# a number as written in a description: "18", "0.18" or ".18" (the leading zero is often
# dropped, and "\b" would then start the match after the dot and read .18 as 18)
_NUM = r"(?:\d+(?:\.\d+)?|\.\d+)"

# distributors' own attribute lists are often a short subset of what the description string
# says - shared by every provider parser (Mouser, Farnell, ...) that wants to fill the gaps
DESC_RULES = [
    ("Capacitance", re.compile(rf"(?<![\w.])({_NUM}\s?[pnuµ]?F)\b", re.I)),
    ("Resistance", re.compile(rf"(?<![\w.])({_NUM}\s?[kKMR]?\s?(?:OHM|OHMS|Ω))\b", re.I)),
    ("Inductance", re.compile(rf"(?<![\w.])({_NUM}\s?[pnuµm]?H)\b", re.I)),
    ("Voltage Rating", re.compile(r"\b(\d+(?:\.\d+)?\s?V(?:DC|AC)?)\b", re.I)),
    ("Tolerance", re.compile(r"(±?\s?\d+(?:\.\d+)?\s?%)")),
    ("Power Rating", re.compile(rf"(?<![\w.])(\d+/\d+\s?W|{_NUM}\s?W)\b", re.I)),
    ("Dielectric", re.compile(r"\b(X7R|X5R|X6S|X8R|C0G|NP0|NPO|Y5V|Z5U|Z7T)\b", re.I)),
    ("ESR", re.compile(r"\b(\d+(?:\.\d+)?\s?m?(?:OHM|OHMS|Ω))\s*ESR\b", re.I)),
    ("Ripple Current", re.compile(r"\b(\d+(?:\.\d+)?\s?m?A)\s*(?:RMS|RIPPLE)\b", re.I)),
    ("Current Rating", re.compile(r"\b(\d+(?:\.\d+)?\s?m?A)\b", re.I)),
    ("Operating Temperature", re.compile(
        r"(-?\d+\s?°?C?\s*(?:~|to)\s*\+?\d+\s?°?C)", re.I)),
    ("Lead Spacing", re.compile(r"\b(\d+(?:\.\d+)?\s?mm)\s*(?:pitch|lead spacing|LS)\b", re.I)),
    ("Size / Dimension", re.compile(r"(\d+(?:\.\d+)?\s?[xX×]\s?\d+(?:\.\d+)?\s?mm)", re.I)),
    ("Package / Case", re.compile(r"\b(0201|0402|0603|0805|1206|1210|1812|2010|2220|2512)\b")),
    ("Series", re.compile(r"\bSeries\s*[:=]?\s*([A-Za-z0-9\-]+)\b")),
]


def guess_attrs_from_description(attrs: dict, desc: str | None) -> None:
    """Fill gaps in `attrs` (in place) from a free-text product description, without
    overwriting anything already there. Better too much than too little."""
    if not desc:
        return
    for name, rx in DESC_RULES:
        if name in attrs:
            continue
        m = rx.search(desc)
        if m:
            attrs[name] = m.group(1).strip()
