"""VAT helpers. Prices are stored EX VAT everywhere; the UI shows both.

Business rule: the *inc-VAT* figure is presented with no decimals, rounded UP
(179.1 -> 180). The ex-VAT figure keeps its decimals.
"""
from __future__ import annotations

import math


def with_vat(ex: float | None, vat_percent: float) -> float | None:
    if ex is None:
        return None
    return round(ex * (1 + (vat_percent or 0) / 100), 4)


def with_vat_ceil(ex: float | None, vat_percent: float) -> int | None:
    if ex is None:
        return None
    return math.ceil(ex * (1 + (vat_percent or 0) / 100) - 1e-9)


def strip_vat(inc: float | None, vat_percent: float) -> float | None:
    if inc is None:
        return None
    return round(inc / (1 + (vat_percent or 0) / 100), 4)


def price_block(ex: float | None, vat_percent: float, currency: str) -> dict:
    return {
        "ex_vat": ex,
        "inc_vat": with_vat(ex, vat_percent),
        "inc_vat_ceil": with_vat_ceil(ex, vat_percent),
        "vat_percent": vat_percent,
        "currency": currency,
    }
