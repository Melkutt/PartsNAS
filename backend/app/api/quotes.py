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

from ..core.db import get_db
from ..models import Part, PartSupplier, Quote, QuoteLine, StockEntry

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


class QuoteIn(BaseModel):
    customer: str | None = None
    title: str | None = None
    markup_percent: float = 50.0
    vat_percent: float = 25.0


class QuotePatch(BaseModel):
    customer: str | None = None
    title: str | None = None
    note: str | None = None
    markup_percent: float | None = None
    vat_percent: float | None = None
    status: str | None = None


class LineIn(BaseModel):
    part_id: str | None = None
    description: str | None = None
    mpn: str | None = None
    qty: float = 1
    unit_cost: float | None = None  # override the snapshot
    note: str | None = None


class LinePatch(BaseModel):
    description: str | None = None
    qty: float | None = None
    unit_cost: float | None = None
    note: str | None = None


class BulkLine(BaseModel):
    part_id: str
    qty: float = 1


def _need(db: Session, qid: int) -> Quote:
    q = db.get(Quote, qid)
    if q is None:
        raise HTTPException(404, "quote not found")
    return q


def snapshot_cost(db: Session, part_id: str) -> tuple[float, str, str]:
    """(ex-VAT unit cost, currency, source label) for a part, at this moment."""
    links = db.scalars(
        select(PartSupplier).where(
            PartSupplier.part_id == part_id, PartSupplier.unit_price.is_not(None)
        )
    ).all()
    if links:
        best = min(
            links, key=lambda x: (0 if x.preferred else 1, x.unit_price or 1e9)
        )
        when = best.updated_at.strftime("%Y-%m-%d") if best.updated_at else ""
        return best.unit_price, best.currency, f"{best.supplier.name} {when}".strip()
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
        return entry.unit_price, entry.currency, f"last purchase {when}".strip()
    return 0.0, "SEK", "no price on file"


def _line_row(ln: QuoteLine, markup: float, vat: float) -> dict:
    sell_ex = round(ln.unit_cost * (1 + markup / 100), 4)
    return {
        "id": ln.id,
        "part_id": ln.part_id,
        "description": ln.description,
        "mpn": ln.mpn,
        "qty": ln.qty,
        "unit_cost": ln.unit_cost,
        "currency": ln.currency,
        "cost_source": ln.cost_source,
        "note": ln.note,
        "sell_unit_ex": sell_ex,
        "line_ex": round(sell_ex * ln.qty, 2),
    }


def _quote_dict(db: Session, q: Quote, full: bool) -> dict:
    lines = [_line_row(ln, q.markup_percent, q.vat_percent) for ln in q.lines]
    cost_total = round(sum(ln.unit_cost * ln.qty for ln in q.lines), 2)
    sell_ex_total = round(sum(x["line_ex"] for x in lines), 2)
    vat_amount = round(sell_ex_total * q.vat_percent / 100, 2)
    inc_total_ceil = math.ceil(sell_ex_total * (1 + q.vat_percent / 100) - 1e-9)
    d = {
        "id": q.id,
        "customer": q.customer,
        "title": q.title,
        "note": q.note,
        "markup_percent": q.markup_percent,
        "vat_percent": q.vat_percent,
        "status": q.status,
        "line_count": len(q.lines),
        "created_at": q.created_at.isoformat() if q.created_at else None,
        "totals": {
            "cost": cost_total,
            "markup": round(sell_ex_total - cost_total, 2),
            "sell_ex_vat": sell_ex_total,
            "vat": vat_amount,
            "inc_vat_ceil": inc_total_ceil,
            "currency": "SEK",
        },
    }
    if full:
        d["lines"] = lines
    return d


@router.get("")
def list_quotes(db: Session = Depends(get_db)):
    qs = db.scalars(select(Quote).order_by(Quote.id.desc())).all()
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


def _add_line(db: Session, q: Quote, part_id, description, mpn, qty, unit_cost, note):
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
        if unit_cost is None:
            unit_cost, cur, src = snapshot_cost(db, part_id)
    if unit_cost is None:
        unit_cost = 0.0
    if src is None:
        src = "manual"
    if not description:
        raise HTTPException(400, "description required for a free line")
    ln = QuoteLine(
        quote_id=q.id, part_id=part_id, description=description, mpn=mpn,
        qty=qty, unit_cost=unit_cost, currency=cur, cost_source=src, note=note,
        sort_order=order + 1,
    )
    db.add(ln)
    return ln


@router.post("/{qid}/lines", status_code=201)
def add_line(qid: int, body: LineIn, db: Session = Depends(get_db)):
    q = _need(db, qid)
    ln = _add_line(db, q, body.part_id, body.description, body.mpn, body.qty,
                   body.unit_cost, body.note)
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


@router.get("/{qid}/export.csv")
def export_csv(qid: int, db: Session = Depends(get_db)):
    q = _need(db, qid)
    d = _quote_dict(db, q, full=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Quote", q.title or f"#{q.id}", "Customer", q.customer or ""])
    w.writerow(["Markup %", q.markup_percent, "VAT %", q.vat_percent])
    w.writerow([])
    w.writerow(["MPN", "Description", "Qty", "Unit cost ex VAT", "Source",
                "Sell unit ex VAT", "Line ex VAT", "Note"])
    for ln in d["lines"]:
        w.writerow([ln["mpn"] or "", ln["description"], ln["qty"], ln["unit_cost"],
                    ln["cost_source"] or "", ln["sell_unit_ex"], ln["line_ex"], ln["note"] or ""])
    t = d["totals"]
    w.writerow([])
    w.writerow(["", "", "", "", "", "Cost", t["cost"]])
    w.writerow(["", "", "", "", "", "Markup", t["markup"]])
    w.writerow(["", "", "", "", "", "Sell ex VAT", t["sell_ex_vat"]])
    w.writerow(["", "", "", "", "", f"VAT {q.vat_percent}%", t["vat"]])
    w.writerow(["", "", "", "", "", "Total inc VAT", t["inc_vat_ceil"]])
    buf.seek(0)
    fn = f"quote-{q.id}-{datetime.now():%Y%m%d}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fn}"'})
