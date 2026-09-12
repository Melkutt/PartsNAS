"""Parse a KiCad BOM export (CSV).

KiCad's schematic-editor "Export BOM" dialog lets the user pick which
fields become columns, so there's no one fixed header — this matches by
common header names instead. Works with both a "grouped" export (one row
per distinct Value+Footprint+MPN, a Qty column, multiple designators in
Reference) and a flat one (one row per component); either way the result
here is grouped by (MPN, Value, Footprint) so the review table shows one
line per distinct part-to-buy, not one per designator.
"""
from __future__ import annotations

import csv
import io
import re
from collections import OrderedDict

_HEADER_SYNONYMS: dict[str, list[str]] = {
    "refdes": ["reference", "references", "refdes", "ref des", "designator", "designators", "refs"],
    "value": ["value"],
    "footprint": ["footprint", "footprints", "package"],
    "qty": ["qty", "quantity", "count", "qnty", "qty per pcb"],
    "mpn": [
        "mpn", "manufacturer part number", "manufacturer part no", "manufacturer part no.",
        "mfr part #", "mfr part number", "mfr.part#", "part number", "part#",
    ],
}


def _detect_columns(header: list[str]) -> dict[str, int]:
    low = [h.strip().lower() for h in header]
    out: dict[str, int] = {}
    for key, names in _HEADER_SYNONYMS.items():
        for i, h in enumerate(low):
            if h in names:
                out[key] = i
                break
    return out


def parse_bom_csv(raw: bytes) -> list[dict]:
    # utf-8-sig: KiCad commonly writes a BOM (byte-order mark) on the file.
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    cols = _detect_columns(rows[0])
    if "refdes" not in cols or "value" not in cols:
        raise ValueError(
            "Couldn't find Reference/Value columns — expected a KiCad BOM export (CSV)"
        )

    grouped: OrderedDict[tuple[str, str, str], dict] = OrderedDict()
    for row in rows[1:]:
        if not any((c or "").strip() for c in row):
            continue

        def get(key: str) -> str:
            i = cols.get(key)
            return row[i].strip() if i is not None and i < len(row) else ""

        refs = [r for r in re.split(r"[,\s]+", get("refdes")) if r]
        mpn, value, footprint = get("mpn"), get("value"), get("footprint")
        qty_field = get("qty")
        try:
            qty = float(qty_field) if qty_field else float(len(refs) or 1)
        except ValueError:
            qty = float(len(refs) or 1)

        key = (mpn.lower(), value.lower(), footprint.lower())
        if key in grouped:
            grouped[key]["refdes"].extend(refs)
            grouped[key]["qty"] += qty
        else:
            grouped[key] = {"mpn": mpn, "value": value, "footprint": footprint,
                             "qty": qty, "refdes": refs}

    return [
        {
            "mpn": g["mpn"] or None,
            "value": g["value"],
            "footprint": g["footprint"],
            "qty": g["qty"],
            "refdes": " ".join(g["refdes"]),
        }
        for g in grouped.values()
    ]
