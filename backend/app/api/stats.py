"""Overall inventory facts, shown on the About tab.

`GET /api/stats` -> part/stock counts, inventory value (cost basis and sale
value at the standard markup, each ex/inc VAT), and lifetime logged labor hours.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Part, QuoteLine
from ..money import with_vat
from ..services import on_hand_map
from .quotes import snapshot_cost

router = APIRouter(prefix="/api/stats", tags=["stats"])

# There's no per-part markup outside a Quote — use the same default every new
# Quote starts at (Quote.markup_percent), so "sale value" means "if this
# inventory were quoted out today at the standard markup".
_DEFAULT_MARKUP = 50.0


@router.get("")
def get_stats(db: Session = Depends(get_db)):
    total_parts = db.scalar(select(func.count(Part.id))) or 0

    oh = on_hand_map(db)
    total_stock_units = sum(oh.values())

    cost_ex = 0.0
    cost_inc = 0.0
    for part_id, qty in oh.items():
        if qty <= 0:
            continue
        unit_cost, _currency, _source, vat_percent = snapshot_cost(db, part_id)
        cost_ex += unit_cost * qty
        cost_inc += (with_vat(unit_cost, vat_percent) or 0.0) * qty

    # markup is one flat multiplier, so applying it to the already-summed
    # totals is exactly equal to summing each part's own sale value
    sale_ex = cost_ex * (1 + _DEFAULT_MARKUP / 100)
    sale_inc = cost_inc * (1 + _DEFAULT_MARKUP / 100)

    total_labor_hours = db.scalar(
        select(func.coalesce(func.sum(QuoteLine.qty), 0))
        .where(QuoteLine.line_type == "labor")
    ) or 0

    return {
        "total_parts": total_parts,
        "total_stock_units": total_stock_units,
        "inventory_cost_ex_vat": round(cost_ex, 2),
        "inventory_cost_inc_vat": round(cost_inc, 2),
        "inventory_sale_ex_vat": round(sale_ex, 2),
        "inventory_sale_inc_vat": round(sale_inc, 2),
        "markup_percent_used": _DEFAULT_MARKUP,
        "total_labor_hours": total_labor_hours,
        "currency": "SEK",
    }
