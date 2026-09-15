"""Quotes = invoice basis ("fakturaunderlag").

Pick parts + quantities for a customer job; each line snapshots the part's cost
EX VAT at add time and never moves again (only a fresh supplier-API lookup
changes the source). A markup (default 50%, editable per quote) gives the sell
price. Inc-VAT totals are rounded UP to whole units.

`GET/POST /api/quotes`                      list / create
`GET/PATCH/DELETE /api/quotes/{id}`         customer / title / note / markup / status
`POST /api/quotes/{id}/lines`              {part_id? | description, mpn?, qty, unit_cost?, note?}
`POST /api/quotes/{id}/lines/bulk`         [{part_id, qty}] — from a parts selection
`PATCH/DELETE /api/quotes/{id}/lines/{lid}`
`GET  /api/quotes/{id}/export.csv`
"""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.db import get_db
from ..models import Customer, Part, PartSupplier, Quote, QuoteLine, StockEntry
from ..services import location_breakdown

_LINE_TYPES = {"part", "labor", "fee", "shipping"}

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


class QuoteIn(BaseModel):
    customer: str | None = None
    customer_id: int | None = None
    title: str | None = None
    markup_percent: float = 50.0
    vat_percent: float = 25.0
    hide_vat: bool = False


class QuotePatch(BaseModel):
    customer: str | None = None
    customer_id: int | None = None
    title: str | None = None
    note: str | None = None
    markup_percent: float | None = None
    vat_percent: float | None = None
    status: str | None = None
    hide_cost: bool | None = None
    hide_vat: bool | None = None


class LineIn(BaseModel):
    part_id: str | None = None
    description: str | None = None
    mpn: str | None = None
    qty: float = 1
    unit_cost: float | None = None  # override the snapshot
    supplier_link_id: int | None = None  # pin the price to this PartSupplier row
    note: str | None = None
    line_type: str = "part"  # part | labor | fee


class LinePatch(BaseModel):
    description: str | None = None
    qty: float | None = None
    unit_cost: float | None = None
    markup_percent: float | None = None  # explicit null clears -> use quote markup
    note: str | None = None
    line_type: str | None = None


class BulkLine(BaseModel):
    part_id: str
    qty: float = 1


def _need(db: Session, qid: int) -> Quote:
    q = db.get(Quote, qid)
    if q is None:
        raise HTTPException(404, "quote not found")
    return q


def snapshot_from_link(db: Session, link_id: int) -> tuple[float, str, str] | None:
    link = db.get(PartSupplier, link_id)
    if link is None or link.unit_price is None:
        return None
    when = link.updated_at.strftime("%Y-%m-%d") if link.updated_at else ""
    name = link.supplier.name if link.supplier else "supplier"
    return link.unit_price, link.currency, f"{name} {when}".strip()


def snapshot_cost(db: Session, part_id: str) -> tuple[float, str, str, float]:
    """(ex-VAT unit cost, currency, source label, vat_percent) for a part, now."""
    links = db.scalars(
        select(PartSupplier).where(
            PartSupplier.part_id == part_id, PartSupplier.unit_price.is_not(None)
        )
    ).all()
    if links:
        # the ★ preferred link wins; otherwise the DEAREST price (quote conservatively)
        best = max(links, key=lambda x: (x.preferred, x.unit_price or 0))
        when = best.updated_at.strftime("%Y-%m-%d") if best.updated_at else ""
        return best.unit_price, best.currency, f"{best.supplier.name} {when}".strip(), best.vat_percent
    entry = db.scalar(
        select(StockEntry)
        .where(
            StockEntry.part_id == part_id,
            StockEntry.delta > 0,
            StockEntry.unit_price.is_not(None),
        )
        .order_by(StockEntry.id.desc())
        .limit(1)
    )
    if entry:
        when = entry.created_at.strftime("%Y-%m-%d") if entry.created_at else ""
        return entry.unit_price, entry.currency, f"last purchase {when}".strip(), entry.vat_percent
    return 0.0, "SEK", "no price on file", get_settings().default_vat_percent


def _line_row(ln: QuoteLine, quote_markup: float) -> dict:
    markup = ln.markup_percent if ln.markup_percent is not None else quote_markup
    sell_ex = round(ln.unit_cost * (1 + markup / 100), 4)
    return {
        "id": ln.id,
        "part_id": ln.part_id,
        "line_type": ln.line_type or "part",
        "description": ln.description,
        "mpn": ln.mpn,
        "qty": ln.qty,
        "unit_cost": ln.unit_cost,
        "markup_percent": ln.markup_percent,   # None => inherits the quote's
        "effective_markup": markup,
        "currency": ln.currency,
        "cost_source": ln.cost_source,
        "note": ln.note,
        "sell_unit_ex": sell_ex,
        "line_ex": round(sell_ex * ln.qty, 2),
    }


def _quote_dict(db: Session, q: Quote, full: bool) -> dict:
    lines = [_line_row(ln, q.markup_percent) for ln in q.lines]
    cost_total = round(sum(ln.unit_cost * ln.qty for ln in q.lines), 2)
    sell_ex_total = round(sum(x["line_ex"] for x in lines), 2)
    # not VAT-registered -> treat as 0% for the math, but keep the stored
    # vat_percent untouched in case VAT applies again in the future
    vat_pct = 0 if q.hide_vat else q.vat_percent
    vat_amount = round(sell_ex_total * vat_pct / 100, 2)
    inc_total_ceil = math.ceil(sell_ex_total * (1 + vat_pct / 100) - 1e-9)
    d = {
        "id": q.id,
        "customer": q.customer,
        "customer_id": q.customer_id,
        "customer_info": {
            "name": q.customer_ref.name,
            "address": q.customer_ref.address,
            "org_number": q.customer_ref.org_number,
            "phone": q.customer_ref.phone,
            "email": q.customer_ref.email,
        } if q.customer_ref else None,
        "title": q.title,
        "note": q.note,
        "markup_percent": q.markup_percent,
        "vat_percent": q.vat_percent,
        "status": q.status,
        "stock_committed": q.stock_committed,
        "hide_cost": q.hide_cost,
        "hide_vat": q.hide_vat,
        "line_count": len(q.lines),
        "created_at": q.created_at.isoformat() if q.created_at else None,
        "totals": {
            "cost": cost_total,
            "markup": round(sell_ex_total - cost_total, 2),
            "sell_ex_vat": sell_ex_total,
            "vat": vat_amount,
            "vat_percent": vat_pct,
            "inc_vat_ceil": inc_total_ceil,
            "currency": "SEK",
        },
    }
    if full:
        d["lines"] = lines
    return d


@router.get("")
def list_quotes(status: str = "open", db: Session = Depends(get_db)):
    stmt = select(Quote).order_by(Quote.id.desc())
    if status in ("open", "invoiced"):
        stmt = stmt.where(Quote.status == status)
    qs = db.scalars(stmt).all()
    return [_quote_dict(db, q, full=False) for q in qs]


@router.post("", status_code=201)
def create_quote(body: QuoteIn, db: Session = Depends(get_db)):
    q = Quote(**body.model_dump())
    db.add(q)
    db.commit()
    return {"id": q.id}


@router.get("/{qid}")
def get_quote(qid: int, db: Session = Depends(get_db)):
    return _quote_dict(db, _need(db, qid), full=True)


@router.patch("/{qid}")
def patch_quote(qid: int, body: QuotePatch, db: Session = Depends(get_db)):
    q = _need(db, qid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(q, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/{qid}")
def delete_quote(qid: int, db: Session = Depends(get_db)):
    db.delete(_need(db, qid))
    db.commit()
    return {"ok": True}


def _add_line(db: Session, q: Quote, part_id, description, mpn, qty, unit_cost, note,
              supplier_link_id=None, line_type="part"):
    if line_type not in _LINE_TYPES:
        raise HTTPException(400, f"unknown line_type {line_type!r}")
    order = (
        db.scalar(
            select(QuoteLine.sort_order)
            .where(QuoteLine.quote_id == q.id)
            .order_by(QuoteLine.sort_order.desc())
            .limit(1)
        )
        or 0
    )
    cur, src = "SEK", None
    if part_id:
        p = db.get(Part, part_id)
        if p is None:
            raise HTTPException(400, f"unknown part_id {part_id}")
        description = description or p.name
        mpn = mpn or p.mpn
        if unit_cost is None and supplier_link_id:
            picked = snapshot_from_link(db, supplier_link_id)
            if picked:
                unit_cost, cur, src = picked
        if unit_cost is None:
            unit_cost, cur, src, _vat = snapshot_cost(db, part_id)
    if unit_cost is None:
        unit_cost = 0.0
    if src is None:
        src = "manual"
    if not description:
        raise HTTPException(400, "description required for a free line")
    ln = QuoteLine(
        quote_id=q.id, part_id=part_id, description=description, mpn=mpn,
        qty=qty, unit_cost=unit_cost, currency=cur, cost_source=src, note=note,
        sort_order=order + 1, line_type=line_type,
    )
    db.add(ln)
    return ln


@router.post("/{qid}/lines", status_code=201)
def add_line(qid: int, body: LineIn, db: Session = Depends(get_db)):
    q = _need(db, qid)
    ln = _add_line(db, q, body.part_id, body.description, body.mpn, body.qty,
                   body.unit_cost, body.note, body.supplier_link_id, body.line_type)
    db.commit()
    return {"id": ln.id}


@router.post("/{qid}/lines/bulk", status_code=201)
def add_lines_bulk(qid: int, body: list[BulkLine], db: Session = Depends(get_db)):
    q = _need(db, qid)
    n = 0
    for item in body:
        _add_line(db, q, item.part_id, None, None, item.qty, None, None)
        n += 1
    db.commit()
    return {"added": n}


@router.patch("/{qid}/lines/{lid}")
def patch_line(qid: int, lid: int, body: LinePatch, db: Session = Depends(get_db)):
    ln = db.get(QuoteLine, lid)
    if ln is None or ln.quote_id != qid:
        raise HTTPException(404, "line not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(ln, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/{qid}/lines/{lid}")
def delete_line(qid: int, lid: int, db: Session = Depends(get_db)):
    ln = db.get(QuoteLine, lid)
    if ln is None or ln.quote_id != qid:
        raise HTTPException(404, "line not found")
    db.delete(ln)
    db.commit()
    return {"ok": True}


# ---- stock commit / invoice archive (both reversible) ----
def _mg(qid: int) -> str:
    return f"quote-{qid}"


@router.post("/{qid}/commit-stock")
def commit_stock(qid: int, db: Session = Depends(get_db)):
    q = _need(db, qid)
    if q.stock_committed:
        return {"ok": True, "already": True}
    grp = _mg(qid)
    moved = 0
    for ln in q.lines:
        if not ln.part_id or ln.qty <= 0:
            continue
        need = int(round(ln.qty))
        for r in location_breakdown(db, ln.part_id):  # largest first
            if need <= 0:
                break
            take = min(need, r["qty"])
            db.add(StockEntry(part_id=ln.part_id, location_id=r["location_id"],
                              delta=-take, kind="build", move_group=grp,
                              note=f"quote #{qid}"))
            need -= take
        if need > 0:  # not enough on hand — record the shortfall as a negative
            db.add(StockEntry(part_id=ln.part_id, location_id=None, delta=-need,
                              kind="build", move_group=grp, note=f"quote #{qid} (shortfall)"))
        moved += 1
    q.stock_committed = True
    db.commit()
    return {"ok": True, "lines": moved}


@router.post("/{qid}/uncommit-stock")
def uncommit_stock(qid: int, db: Session = Depends(get_db)):
    q = _need(db, qid)
    if not q.stock_committed:
        return {"ok": True, "already": True}
    grp = _mg(qid)
    for e in db.scalars(select(StockEntry).where(StockEntry.move_group == grp)).all():
        db.add(StockEntry(part_id=e.part_id, location_id=e.location_id, delta=-e.delta,
                          kind="correction", move_group=f"undo-{grp}",
                          note=f"undo quote #{qid}"))
    q.stock_committed = False
    db.commit()
    return {"ok": True}


@router.post("/{qid}/invoice")
def invoice(qid: int, commit_stock_too: bool = True, db: Session = Depends(get_db)):
    q = _need(db, qid)
    if commit_stock_too and not q.stock_committed:
        commit_stock(qid, db)
        q = _need(db, qid)
    q.status = "invoiced"
    db.commit()
    return {"ok": True}


@router.post("/{qid}/unarchive")
def unarchive(qid: int, db: Session = Depends(get_db)):
    q = _need(db, qid)
    q.status = "open"
    db.commit()
    return {"ok": True}


@router.get("/{qid}/export.xlsx")
def export_xlsx(qid: int, db: Session = Depends(get_db)):
    import openpyxl

    q = _need(db, qid)
    d = _quote_dict(db, q, full=True)
    hide = q.hide_cost
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quote"
    ws.append([q.title or f"Quote #{q.id}"])
    ws.append(["Customer", q.customer or ""])
    t = d["totals"]
    info_row = []
    if not hide:
        info_row += ["Markup %", q.markup_percent]
    if not q.hide_vat:
        info_row += ["VAT %", t["vat_percent"]]
    info_row += ["Status", q.status]
    ws.append(info_row)
    ws.append([])
    head = ["MPN", "Description", "Qty", "Sell unit ex VAT", "Line ex VAT", "Note"] if hide else \
        ["MPN", "Description", "Qty", "Unit cost ex VAT", "Markup %",
         "Source", "Sell unit ex VAT", "Line ex VAT", "Note"]
    ws.append(head)
    for ln in d["lines"]:
        row = [ln["mpn"] or "", ln["description"], ln["qty"]]
        if not hide:
            row += [ln["unit_cost"], ln["effective_markup"], ln["cost_source"] or ""]
        row += [ln["sell_unit_ex"], ln["line_ex"], ln["note"] or ""]
        ws.append(row)
    ws.append([])
    totals = []
    if not hide:
        totals += [("Cost", t["cost"]), ("Markup", t["markup"])]
    totals.append(("Sell ex VAT", t["sell_ex_vat"]))
    if not q.hide_vat:
        totals += [(f"VAT {t['vat_percent']}%", t["vat"]), ("Total inc VAT", t["inc_vat_ceil"])]
    label_col = 6 if hide else 8  # F vs H, matching the shorter/longer header row
    for label, val in totals:
        ws.append([""] * (label_col - 1) + [label, val])
    widths = [16, 40, 6, 16, 14, 24] if hide else [16, 40, 6, 16, 10, 22, 16, 14, 24]
    for i, colw in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = colw
    bio = io.BytesIO()
    wb.save(bio)
    fn = f"quote-{q.id}-{datetime.now():%Y%m%d}.xlsx"
    return StreamingResponse(
        iter([bio.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )


@router.get("/{qid}/export.csv")
def export_csv(qid: int, db: Session = Depends(get_db)):
    q = _need(db, qid)
    d = _quote_dict(db, q, full=True)
    hide = q.hide_cost
    t = d["totals"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Quote", q.title or f"#{q.id}", "Customer", q.customer or ""])
    info_row = []
    if not hide:
        info_row += ["Markup %", q.markup_percent]
    if not q.hide_vat:
        info_row += ["VAT %", t["vat_percent"]]
    w.writerow(info_row)
    w.writerow([])
    if hide:
        w.writerow(["MPN", "Description", "Qty", "Sell unit ex VAT", "Line ex VAT", "Note"])
        for ln in d["lines"]:
            w.writerow([ln["mpn"] or "", ln["description"], ln["qty"],
                        ln["sell_unit_ex"], ln["line_ex"], ln["note"] or ""])
    else:
        w.writerow(["MPN", "Description", "Qty", "Unit cost ex VAT", "Source",
                    "Sell unit ex VAT", "Line ex VAT", "Note"])
        for ln in d["lines"]:
            w.writerow([ln["mpn"] or "", ln["description"], ln["qty"], ln["unit_cost"],
                        ln["cost_source"] or "", ln["sell_unit_ex"], ln["line_ex"], ln["note"] or ""])
    w.writerow([])
    label_col = 4 if hide else 6
    pad = [""] * (label_col - 1)
    if not hide:
        w.writerow(pad + ["Cost", t["cost"]])
        w.writerow(pad + ["Markup", t["markup"]])
    w.writerow(pad + ["Sell ex VAT", t["sell_ex_vat"]])
    if not q.hide_vat:
        w.writerow(pad + [f"VAT {t['vat_percent']}%", t["vat"]])
        w.writerow(pad + ["Total inc VAT", t["inc_vat_ceil"]])
    buf.seek(0)
    fn = f"quote-{q.id}-{datetime.now():%Y%m%d}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fn}"'})
