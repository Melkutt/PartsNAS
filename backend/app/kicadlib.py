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


def is_named(symbol: str | None, footprint: str | None) -> bool:
    """A part KiCad can use: both names carry their library ("Device:C", "Capacitor_SMD:C_0603_1608Metric")."""
    return bool(symbol and ":" in symbol and footprint and ":" in footprint)


def suggest_names(category_path: str | None, footprint_raw: str | None) -> dict | None:
    """{"symbol", "footprint", "reference"} for a standard SMD passive, worked out from the category
    ("Passive > Capacitor > Ceramic") and the package size in the footprint text; None when not one."""
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
            return {"symbol": symbol, "footprint": f"{lib}:{prefix}_{size}_{METRIC[size]}Metric", "reference": ref}
    return None


def reference_for(symbol: str | None) -> str | None:
    """The reference letter KiCad gives a standard symbol (only the ones this file knows)."""
    for _kind, (_m, _l, sym, _lib, _p, ref, _s) in _KINDS.items():
        if symbol == sym:
            return ref
    return None
