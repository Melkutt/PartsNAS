"""Mouser Search API v1 — https://www.mouser.se/api-hub/

Needs a free API key (per-key country/currency is set on Mouser's side; a .se key
returns SEK prices ex VAT). Set it as env PARTSNAS_MOUSER_API_KEY or in Settings.

Endpoint used: POST /api/v1/search/partnumber?apiKey=KEY
  body {"SearchByPartRequest": {"mouserPartNumber": "<mpn>", "partSearchOptions": ""}}
The `mouserPartNumber` field matches both Mouser and manufacturer part numbers.
Gentle limits: 10 req/min, 1000 req/day (see safety.py).
"""
from __future__ import annotations

import os
import re

from sqlalchemy.orm import Session

from ..core.kv import get_kv
from ..textparse import canon_tempchar, metric_first
from .base import PriceBreak, Provider, ProviderError, ProviderResult
from .safety import cache_get, cache_put, guarded_request

API = "https://api.mouser.com/api/v1/search/partnumber"
PER_MIN = 10
PER_DAY = 1000
_price_re = re.compile(r"[-+]?\d[\d\s.,]*")


class MouserProvider(Provider):
    name = "mouser"
    label = "Mouser"
    website = "https://www.mouser.se"

    def api_key(self, db: Session) -> str | None:
        return os.environ.get("PARTSNAS_MOUSER_API_KEY") or (
            get_kv(db, "provider:mouser:config", {}) or {}
        ).get("api_key")

    def configured(self, db: Session) -> bool:
        return bool(self.api_key(db))

    def search(self, db: Session, mpn: str) -> list[ProviderResult]:
        mpn = mpn.strip()
        if not mpn:
            raise ProviderError("empty MPN")
        cached = cache_get(self.name, mpn)
        if cached is not None:
            return [_from_dict(r) for r in cached]

        key = self.api_key(db)
        if not key:
            raise ProviderError("Mouser API key not configured")
        payload = {
            "SearchByPartRequest": {"mouserPartNumber": mpn, "partSearchOptions": ""}
        }
        data = guarded_request(
            db, self.name,
            method="POST", url=f"{API}?apiKey={key}", json=payload,
            per_min=PER_MIN, per_day=PER_DAY,
        )
        errs = data.get("Errors") or []
        if errs:
            raise ProviderError("; ".join(e.get("Message", str(e)) for e in errs))
        parts = ((data.get("SearchResults") or {}).get("Parts")) or []
        results = [_parse_part(p) for p in parts if p.get("ManufacturerPartNumber")]
        # prefer an exact MPN match first
        results.sort(key=lambda r: 0 if r.mpn.lower() == mpn.lower() else 1)
        cache_put(self.name, mpn, [r.to_dict() for r in results])
        return results


def _num(s: str) -> float | None:
    m = _price_re.search(s or "")
    if not m:
        return None
    raw = m.group(0).strip().replace(" ", "")
    if "," in raw and "." in raw:  # 1.234,56 -> 1234.56
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:  # 0,84 -> 0.84
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


_DESC_RULES = [
    ("Capacitance", re.compile(r"\b(\d+(?:\.\d+)?\s?[pnuµ]?F)\b", re.I)),
    ("Resistance", re.compile(r"\b(\d+(?:\.\d+)?\s?[kKMR]?\s?(?:OHM|OHMS|Ω))\b", re.I)),
    ("Inductance", re.compile(r"\b(\d+(?:\.\d+)?\s?[pnuµm]?H)\b", re.I)),
    ("Voltage Rating", re.compile(r"\b(\d+(?:\.\d+)?\s?V(?:DC|AC)?)\b", re.I)),
    ("Tolerance", re.compile(r"(±?\s?\d+(?:\.\d+)?\s?%)")),
    ("Power Rating", re.compile(r"\b(\d+/\d+\s?W|\d+(?:\.\d+)?\s?W)\b", re.I)),
    ("Dielectric", re.compile(r"\b(X7R|X5R|X6S|X8R|C0G|NP0|NPO|Y5V|Z5U|Z7T)\b", re.I)),
    ("ESR", re.compile(r"\b(\d+(?:\.\d+)?\s?m?(?:OHM|OHMS|Ω))\s*ESR\b", re.I)),
    ("Ripple Current", re.compile(r"\b(\d+(?:\.\d+)?\s?m?A)\s*(?:RMS|RIPPLE)\b", re.I)),
    ("Current Rating", re.compile(r"\b(\d+(?:\.\d+)?\s?m?A)\b", re.I)),
    ("Operating Temperature", re.compile(
        r"(-?\d+\s?°?C?\s*(?:~|to)\s*\+?\d+\s?°?C)", re.I)),
    ("Lead Spacing", re.compile(r"\b(\d+(?:\.\d+)?\s?mm)\s*(?:pitch|lead spacing|LS)\b", re.I)),
    ("Size / Dimension", re.compile(r"(\d+(?:\.\d+)?\s?[xX×]\s?\d+(?:\.\d+)?\s?mm)", re.I)),
    ("Package / Case", re.compile(r"\b(0201|0402|0603|0805|1206|1210|1812|2010|2220|2512)\b")),
    ("Series", re.compile(r"\bSeries\s*[:=]?\s*([A-Za-z0-9\-]+)\b")),
]


def _augment_from_description(attrs: dict, desc: str) -> None:
    """Mouser's ProductAttributes is often a short subset — pull whatever we can
    out of the description string to fill the gaps. Better too much than too little."""
    if not desc:
        return
    for name, rx in _DESC_RULES:
        if name in attrs:
            continue
        m = rx.search(desc)
        if m:
            attrs[name] = m.group(1).strip()


def _parse_part(p: dict) -> ProviderResult:
    breaks = []
    for b in p.get("PriceBreaks") or []:
        price = _num(b.get("Price", ""))
        if price is not None:
            breaks.append(PriceBreak(qty=int(b.get("Quantity") or 1), ex_vat=price,
                                     currency=b.get("Currency") or "SEK"))
    attrs = {}
    for a in p.get("ProductAttributes") or []:
        n, v = a.get("AttributeName"), a.get("AttributeValue")
        if n and v:
            attrs[n] = metric_first(v)
    _augment_from_description(attrs, p.get("Description") or "")
    for k in ("Dielectric", "Temperature Coefficient", "Temperature Characteristics"):
        if k in attrs:
            attrs[k] = canon_tempchar(attrs[k]) or attrs[k]
    stock = p.get("AvailabilityInStock")
    return ProviderResult(
        provider="mouser",
        mpn=p.get("ManufacturerPartNumber", ""),
        manufacturer=p.get("Manufacturer"),
        description=p.get("Description"),
        datasheet_url=p.get("DataSheetUrl") or None,
        image_url=p.get("ImagePath") or None,
        product_url=p.get("ProductDetailUrl") or None,
        sku=p.get("MouserPartNumber") or None,
        category_hint=p.get("Category") or None,
        lifecycle=p.get("LifecycleStatus") or None,
        in_stock=int(stock) if str(stock).isdigit() else None,
        attributes=attrs,
        price_breaks=breaks,
    )


def _from_dict(r: dict) -> ProviderResult:
    return ProviderResult(
        provider=r.get("provider", "mouser"),
        mpn=r.get("mpn", ""),
        manufacturer=r.get("manufacturer"),
        description=r.get("description"),
        datasheet_url=r.get("datasheet_url"),
        image_url=r.get("image_url"),
        product_url=r.get("product_url"),
        sku=r.get("sku"),
        category_hint=r.get("category_hint"),
        lifecycle=r.get("lifecycle"),
        in_stock=r.get("in_stock"),
        attributes=r.get("attributes") or {},
        price_breaks=[PriceBreak(**b) for b in (r.get("price_breaks") or [])],
    )
