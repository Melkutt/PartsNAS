"""VAT helpers. Prices are stored EX VAT everywhere; the UI shows both."""
from __future__ import annotations


def with_vat(ex: float | None, vat_percent: float) -> float | None:
    if ex is None:
        return None
    return round(ex * (1 + (vat_percent or 0) / 100), 4)


def strip_vat(inc: float | None, vat_percent: float) -> float | None:
    if inc is None:
        return None
    return round(inc / (1 + (vat_percent or 0) / 100), 4)


def price_block(ex: float | None, vat_percent: float, currency: str) -> dict:
    return {
        "ex_vat": ex,
        "inc_vat": with_vat(ex, vat_percent),
        "vat_percent": vat_percent,
        "currency": currency,
    }
