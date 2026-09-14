"""Import a Mouser order-history export ("My Account -> Order History ->
Download", .xls or .xlsx).

Columns are matched by header name, not position — Mouser's export varies
with the account's language (Swedish shown below, English also handled)
and which columns the customer chose to include:

    Mouser nr / Mouser Part #          -> supplier SKU (PartSupplier link)
    Tillverk: Nr. / Mfr. Part Number   -> MPN (matches an existing part, or
                                           creates a new one under Unsorted)
    Beskr / Description                -> Part.description, if not already set
    Kundens artikelnummer / Customer # -> Part.notes (the free-text project
                                           reference typed in at checkout)
    Ordermängd / Order Qty             -> an "add" stock entry
    Rad nr. / Line # (+ the order number in column A) -> StockEntry.order_ref,
        so re-importing the same file a second time is a no-op rather than
        double-counting stock.

`run(db, path, commit)` returns a summary dict; with commit=False it rolls
back (same convention as importers/partsbox.py). Price columns are read by
Mouser as "155,83 kr" — SEK, but not clearly ex- or inc-VAT for a historical
order — so they're deliberately not imported; add supplier pricing later
via "Look up specs" or a manual entry instead.
"""
from __future__ import annotations

from pathlib import Path

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Category, Part, PartSupplier, StockEntry, Supplier

# Compared after _norm_header() strips trailing punctuation from both sides
# (Mouser's actual header is "Tillverk: Nr.:" — the colons after "Tillverk"
# and at the very end are both just export formatting, not part of the
# label), so these are written without any trailing ":"/".".
_HEADER_SYNONYMS: dict[str, list[str]] = {
    "mpn": ["tillverk: nr", "mfr no", "mfr part #", "mfr part number",
            "manufacturer part number", "manufacturer part no"],
    "mouser_sku": ["mouser nr", "mouser #", "mouser part #", "mouser part number"],
    "description": ["beskr", "description", "desc"],
    "customer_ref": ["kundens artikelnummer", "customer #", "cust #", "customer part number"],
    "qty": ["ordermängd", "order qty", "quantity"],
    "order_no": ["säljorder nr", "sales order #", "sales order no"],
    "line_no": ["rad nr", "line #", "line no"],
}


def _norm_header(h) -> str:
    s = str(h or "").strip().lower()
    s = re.sub(r"[\s:.]+$", "", s)  # trailing "Tillverk: Nr.:" punctuation, etc.
    return re.sub(r"\s+", " ", s)


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
    """Legacy .xls (Mouser's default) via xlrd, modern .xlsx via openpyxl —
    Mouser's export picker offers either."""
    if str(path).lower().endswith(".xls"):
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
    summary = {
        "created": 0, "updated": 0, "stock_entries": 0, "supplier_links": 0,
        "skipped_no_mpn": 0, "already_imported": 0, "warnings": [], "committed": commit,
    }
    if not rows:
        summary["warnings"].append("empty file")
        return summary

    cols = _detect_columns(rows[0])
    if "mpn" not in cols:
        summary["warnings"].append(
            "Couldn't find a manufacturer part number column — expected a Mouser order-history export"
        )
        return summary
    if "mouser_sku" not in cols:
        summary["warnings"].append("no Mouser article-number column found — supplier links skipped")

    mouser = db.scalar(select(Supplier).where(Supplier.name == "Mouser"))
    if mouser is None:
        summary["warnings"].append('no "Mouser" supplier in the database — supplier links skipped')
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

        order_ref = f"{get(row, 'order_no') or '?'}-{get(row, 'line_no') or '?'}"
        if db.scalar(select(StockEntry).where(StockEntry.order_ref == order_ref)):
            summary["already_imported"] += 1
            continue

        desc = get(row, "description")
        ref = get(row, "customer_ref")
        mouser_sku = get(row, "mouser_sku")
        qty_s = get(row, "qty")
        try:
            qty = int(float(qty_s)) if qty_s else 0
        except ValueError:
            qty = 0

        part = db.scalar(select(Part).where(func.lower(Part.mpn) == mpn.lower()))
        if part is None:
            part = Part(
                name=mpn, mpn=mpn, description=desc or None, notes=ref or None,
                category_id=unsorted_cat.id if unsorted_cat else None,
            )
            db.add(part)
            db.flush()
            summary["created"] += 1
        else:
            summary["updated"] += 1
            if desc and not part.description:
                part.description = desc
            if ref and (not part.notes or ref not in part.notes):
                part.notes = f"{part.notes}\n{ref}" if part.notes else ref

        if qty > 0:
            db.add(StockEntry(part_id=part.id, delta=qty, kind="add", order_ref=order_ref,
                               note=f"Mouser order {get(row, 'order_no') or '?'}"))
            summary["stock_entries"] += 1

        if mouser and mouser_sku:
            link = db.scalar(select(PartSupplier).where(
                PartSupplier.part_id == part.id, PartSupplier.supplier_id == mouser.id,
                PartSupplier.sku == mouser_sku,
            ))
            if link is None:
                db.add(PartSupplier(part_id=part.id, supplier_id=mouser.id, sku=mouser_sku))
                summary["supplier_links"] += 1

    if commit:
        db.commit()
    else:
        db.rollback()
    return summary
