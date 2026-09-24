"""Names for KiCad's libraries: which symbol and footprint a part goes by in KiCad.

The KiCad HTTP library (api/kicad.py) hands KiCad a part's data, but the drawing itself comes from KiCad's
own libraries, so each part must say WHICH symbol ("Device:C") and footprint ("Capacitor_SMD:C_0603_1608Metric")
to use. Only parts that name both are "ready" and shown to KiCad.

Passives follow KiCad's standard naming exactly, so for those the names can be worked out from the category and
the package size ("0603"). Anything else (ICs, connectors, ...) has to be named by hand on the part.
"""
from __future__ import annotations

import re

# imperial size code -> the metric code KiCad puts in its footprint names
METRIC = {"0201": "0603", "0402": "1005", "0603": "1608", "0805": "2012", "1008": "2520", "1206": "3216",
          "1210": "3225", "1812": "4532", "2010": "5025", "2512": "6332"}
_SIZE = re.compile(r"(?<![0-9.])(0201|0402|0603|0805|1008|1206|1210|1812|2010|2512)(?![0-9])")

# kind -> (path must contain, leaf categories, symbol, footprint library, footprint prefix, reference, sizes KiCad has)
_KINDS = {
    "resistor": ("resistor", {"thin film", "thick film", "metal film", "carbon film"}, "Device:R",
                 "Resistor_SMD", "R", "R", {"0201", "0402", "0603", "0805", "1206", "1210", "1812", "2010", "2512"}),
    "capacitor": ("capacitor", {"ceramic"}, "Device:C", "Capacitor_SMD", "C", "C",
                  {"0201", "0402", "0603", "0805", "1206", "1210", "1812"}),
    "inductor": ("inductor", {"shielded", "unshielded"}, "Device:L", "Inductor_SMD", "L", "L",
                 {"0201", "0402", "0603", "0805", "1008", "1206", "1210", "1812"}),
    "led": ("led", {"led"}, "Device:LED", "LED_SMD", "LED", "D", {"0201", "0402", "0603", "0805", "1206", "1210"}),
}


# the hand-solder pad variants KiCad's own libraries have (names checked against kicad.github.io/footprints);
# a couple of sizes have two, so each is a list
_HAND = {
    "Capacitor_SMD": {
        "0201": ["0.64x0.40"], "0402": ["0.74x0.62"], "0603": ["1.08x0.95"], "0805": ["1.18x1.45"],
        "1206": ["1.33x1.80"], "1210": ["1.33x2.70"], "1812": ["1.57x3.40"]},
    "Resistor_SMD": {
        "0201": ["0.64x0.40"], "0402": ["0.72x0.64"], "0603": ["0.98x0.95"], "0805": ["1.20x1.40"],
        "1206": ["1.30x1.75"], "1210": ["1.30x2.65"], "1812": ["1.30x3.40"], "2010": ["1.40x2.65"], "2512": ["1.40x3.35"]},
    "Inductor_SMD": {
        "0201": ["0.64x0.40"], "0402": ["0.77x0.64"], "0603": ["1.05x0.95"], "0805": ["1.05x1.20", "1.15x1.40"],
        "1008": ["1.43x2.20"], "1206": ["1.22x1.90", "1.42x1.75"], "1210": ["1.42x2.65"], "1812": ["1.30x3.40"]},
    "LED_SMD": {
        "0201": ["0.64x0.40"], "0402": ["0.77x0.64"], "0603": ["1.05x0.95"], "0805": ["1.15x1.40"],
        "1206": ["1.42x1.75"], "1210": ["1.42x2.65"]},
}
_BASE = re.compile(r"^([^:]+):(.*?Metric)(?:_Pad.*)?$")


def split_footprints(text: str | None) -> list[str]:
    """One footprint per line (commas and semicolons work too), blanks dropped, each once."""
    seen: dict[str, None] = {}
    for part in re.split(r"[\n,;]+", text or ""):
        part = part.strip()
        if part:
            seen.setdefault(part)
    return list(seen)


def footprint_filters(default: str | None, alts: list[str]) -> list[str]:
    """What KiCad's footprint chooser should offer for a part: the named alternatives, and every pad variant of
    the default's package (`Capacitor_SMD:C_0603_1608Metric*` also finds ..._Pad1.08x0.95mm_HandSolder)."""
    out: list[str] = []
    for fp in [default, *alts]:
        m = _BASE.match(fp or "")
        if m:
            out.append(f"{m.group(1)}:{m.group(2)}*")
    out += [a for a in alts if a not in out]
    return list(dict.fromkeys(out))


def is_named(symbol: str | None, footprint: str | None) -> bool:
    """A part KiCad can use: both names carry their library ("Device:C", "Capacitor_SMD:C_0603_1608Metric")."""
    return bool(symbol and ":" in symbol and footprint and ":" in footprint)


def suggest_names(category_path: str | None, footprint_raw: str | None, prefer: str = "standard") -> dict | None:
    """{"symbol", "footprint", "reference", "alts"} for a standard SMD passive, worked out from the category
    ("Passive > Capacitor > Ceramic") and the package size in the footprint text; None when not one.
    `prefer` picks the default footprint - "standard" pads or "hand" (hand-solder pads); the other kind is
    offered as an alternative, so both are one click away in KiCad."""
    if not category_path or not footprint_raw:
        return None
    segs = [s.strip().lower() for s in category_path.split(">")]
    leaf = segs[-1]
    m = _SIZE.search(footprint_raw)
    if not m:
        return None
    size = m.group(1)
    for kind, (must, leaves, symbol, lib, prefix, ref, sizes) in _KINDS.items():
        if must in segs and leaf in leaves and size in sizes:
            std = f"{lib}:{prefix}_{size}_{METRIC[size]}Metric"
            hand = [f"{std.split(':')[0]}:{prefix}_{size}_{METRIC[size]}Metric_Pad{w}mm_HandSolder"
                    for w in _HAND.get(lib, {}).get(size, [])]
            options = [*hand, std] if prefer == "hand" and hand else [std, *hand]
            return {"symbol": symbol, "footprint": options[0], "reference": ref, "alts": options[1:]}
    return None


def reference_for(symbol: str | None) -> str | None:
    """The reference letter KiCad gives a standard symbol (only the ones this file knows)."""
    for _kind, (_m, _l, sym, _lib, _p, ref, _s) in _KINDS.items():
        if symbol == sym:
            return ref
    return None
