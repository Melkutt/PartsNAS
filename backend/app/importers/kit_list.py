"""Import a vendor "sample kit contents" spreadsheet (.xlsx/.xls/.csv) —
the table format KEMET and others print on their kit datasheets: Part
Number, Case Size, Capacitance/Resistance/Inductance, Tolerance, Rated
Voltage, Thickness, Dielectric, Quantity. Columns are matched by header
name, not position, and only a Part Number column is required — the rest
degrade gracefully if a particular kit's sheet doesn't have them (e.g. a
resistor kit has no "Dielectric" column).

Every row becomes a new Part under Unsorted (existing MPNs are left
completely alone — no attribute/stock changes — since a kit list has no
natural per-row identity to dedupe against on re-import, unlike an order
history's order+line number).

`run(db, path, commit)` returns a summary dict; with commit=False it
rolls back (same convention as importers/partsbox.py).
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Category, Part, StockEntry

_HEADER_SYNONYMS: dict[str, list[str]] = {
    "mpn": ["kemet part number", "mfr part number", "mfr. part number", "manufacturer part number",
            "part number", "mpn", "vendor part number"],
    "case_size": ["case size", "case size (eia/metric)", "package", "footprint"],
    "value": ["capacitance", "resistance", "inductance", "value"],
    "tolerance": ["cap tolerance", "cap tolerance (%)", "tolerance", "tolerance (%)"],
    "voltage": ["rated voltage", "rated voltage (vdc)", "voltage"],
    "thickness": ["t thickness", "t thickness (mm)", "thickness"],
    "dielectric": ["dielectric", "temperature coefficient", "tempco"],
    "qty": ["quantity", "qty"],
}


def _norm_header(h) -> str:
    return " ".join(str(h or "").strip().lower().split())


def _detect_columns(header: list) -> dict[str, int]:
    low = [_norm_header(c) for c in header]
    out: dict[str, int] = {}
    for key, names in _HEADER_SYNONYMS.items():
        for i, h in enumerate(low):
            if h in names:
                out[key] = i
                break
    return out


def _load_rows(path: str | Path) -> list[list]:
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        import csv

        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f))
    if suffix == ".xls":
        import xlrd

        wb = xlrd.open_workbook(str(path))
        sh = wb.sheet_by_index(0)
        return [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    return [list(row) for row in wb.worksheets[0].iter_rows(values_only=True)]


def _s(v) -> str:
    if v in (None, ""):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def run(db: Session, path: str | Path, commit: bool = False) -> dict:
    rows = _load_rows(path)
    summary = {"created": 0, "already_exists": 0, "skipped_no_mpn": 0,
               "warnings": [], "committed": commit}
    if not rows:
        summary["warnings"].append("empty file")
        return summary

    cols = _detect_columns(rows[0])
    if "mpn" not in cols:
        summary["warnings"].append(
            "Couldn't find a part-number column — expected a vendor kit-list export "
            "(Part Number, Case Size, Capacitance/Resistance, Tolerance, Voltage, ...)"
        )
        return summary

    unsorted_cat = db.scalar(select(Category).where(Category.is_unsorted.is_(True)))

    def get(row: list, key: str) -> str:
        i = cols.get(key)
        return _s(row[i]) if i is not None and i < len(row) else ""

    for row in rows[1:]:
        if not any(_s(c) for c in row):
            continue
        mpn = get(row, "mpn")
        if not mpn:
            summary["skipped_no_mpn"] += 1
            continue

        if db.scalar(select(Part).where(func.lower(Part.mpn) == mpn.lower())):
            summary["already_exists"] += 1
            continue

        case_size = get(row, "case_size")
        footprint = case_size.split("/", 1)[0].strip() if case_size else None
        # keys match the class schema (seed/part_classes.json +
        # part_classes_extra.json) exactly, not made-up names — a
        # near-miss key (e.g. "voltagerated" instead of the schema's
        # "voltage") shows up as its own separate "Additional parameters"
        # entry and facet, duplicating the real field instead of filling it.
        attrs = {}
        if v := get(row, "value"):
            attrs["value"] = v  # capacitor/resistor/inductor "value" field
        if v := get(row, "tolerance"):
            attrs["tolerance"] = v
        if v := get(row, "voltage"):
            attrs["voltage"] = v  # "Voltage (max)"
        if v := get(row, "thickness"):
            attrs["body_height"] = v.split("±")[0].strip()  # "0.80 ±0.07" -> "0.80"
        if v := get(row, "dielectric"):
            attrs["tempchar"] = v  # C0G/X7R/X5R -> "Temperature characteristic"

        part = Part(
            name=mpn, mpn=mpn, footprint_raw=footprint or None,
            category_id=unsorted_cat.id if unsorted_cat else None,
            attributes=attrs,
        )
        db.add(part)
        db.flush()
        summary["created"] += 1

        qty_s = get(row, "qty")
        try:
            qty = int(float(qty_s)) if qty_s else 0
        except ValueError:
            qty = 0
        if qty > 0:
            db.add(StockEntry(part_id=part.id, delta=qty, kind="add", note="kit list import"))

    if commit:
        db.commit()
    else:
        db.rollback()
    return summary
