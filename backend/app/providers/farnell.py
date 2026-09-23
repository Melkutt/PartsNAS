"""Farnell / element14 (Premier Farnell) Product Search API — https://partner.element14.com/

One flat GET, no request signing (unlike TME) — the API key is just a query parameter:
  https://api.element14.com/catalog/products
    ?term=manuPartNum:<mpn>
    &storeInfo.id=<region, e.g. "uk.farnell.com">   (also fixes the currency)
    &resultsSettings.responseGroup=large,prices,inventory
    &resultsSettings.numberOfResults=10
    &callInfo.responseDataFormat=JSON
    &callInfo.apiKey=<key>

Creds: env PARTSNAS_FARNELL_API_KEY, else Setting `provider:farnell:config` {api_key} (the key
from your Partner Portal account -> "View API Key"). Store region defaults to "uk.farnell.com"
(GBP); override via Setting `provider:farnell:locale` {store, currency}. element14 runs several
regional storefronts (uk.farnell.com, de.farnell.com, newark.com for the US, ...) each with its
own currency and stock, so pick the one you actually buy from.

NOTE: like TME originally, this has not been exercised against a live account. The endpoint,
query parameter names and `term=manuPartNum:` syntax are confirmed from element14's own docs and
their Swagger definition; the response field names below (translatedManufacturerPartNumber,
displayName, brandName, sku, prices[].from/to/cost, datasheets[].url, inv...) are the ones
consistently used across element14's docs and third-party client libraries, but not checked
against a real response — read defensively (`.get(...)` everywhere), so a wrong name only means
a thinner result, never a crash. element14 doesn't return parametric specs the way Mouser/
Digi-Key do, so `attributes` is filled the same way Mouser's own listing is: guessed out of the
description text (`textparse.guess_attrs_from_description`, shared with mouser.py).
"""
from __future__ import annotations

import os

from sqlalchemy.orm import Session

from ..core.kv import get_kv
from ..textparse import canon_tempchar, guess_attrs_from_description, metric_first
from .base import PriceBreak, Provider, ProviderError, ProviderResult
from .safety import cache_get, cache_put, guarded_request

BASE = "https://api.element14.com/catalog/products"
PER_MIN = 15
PER_DAY = 1000


class FarnellProvider(Provider):
    name = "farnell"
    label = "Farnell"
    website = "https://www.farnell.com"
    cred_fields = ["api_key"]

    def _key(self, db: Session) -> str | None:
        return os.environ.get("PARTSNAS_FARNELL_API_KEY") or (
            get_kv(db, "provider:farnell:config", {}) or {}
        ).get("api_key")

    def configured(self, db: Session) -> bool:
        return bool(self._key(db))

    def _locale(self, db: Session) -> dict:
        loc = get_kv(db, "provider:farnell:locale", {}) or {}
        return {"store": loc.get("store", "uk.farnell.com"), "currency": loc.get("currency", "GBP")}

    def search(self, db: Session, mpn: str) -> list[ProviderResult]:
        mpn = mpn.strip()
        if not mpn:
            raise ProviderError("empty MPN")
        cached = cache_get(self.name, mpn)
        if cached is not None:
            return [_from_dict(r) for r in cached]

        key = self._key(db)
        if not key:
            raise ProviderError("Farnell API key not configured")
        loc = self._locale(db)
        params = {
            "term": f"manuPartNum:{mpn}",
            "storeInfo.id": loc["store"],
            "resultsSettings.offset": 0,
            "resultsSettings.numberOfResults": 10,
            "resultsSettings.responseGroup": "large,prices,inventory",
            "callInfo.responseDataFormat": "JSON",
            "callInfo.apiKey": key,
        }
        data = guarded_request(db, self.name, method="GET", url=BASE, params=params, per_min=PER_MIN, per_day=PER_DAY)
        # the wrapper key differs by which kind of search was made ("manufacturerPartNumberSearchReturn"
        # for term=manuPartNum:..., "keywordSearchReturn" for a plain keyword term) - accept either
        wrapper = (data.get("manufacturerPartNumberSearchReturn") or data.get("keywordSearchReturn")
                   or data.get("premierFarnellPartNumberReturn") or {})
        rows = wrapper.get("products") or []
        results = [_parse_product(r, loc["currency"]) for r in rows]
        results.sort(key=lambda r: 0 if r.mpn.lower() == mpn.lower() else 1)
        cache_put(self.name, mpn, [r.to_dict() for r in results])
        return results


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_product(p: dict, currency: str) -> ProviderResult:
    breaks: list[PriceBreak] = []
    for pb in p.get("prices") or []:
        cost = _num(pb.get("cost"))
        if cost is not None:
            breaks.append(PriceBreak(qty=int(pb.get("from") or 1), ex_vat=cost, currency=p.get("currency") or currency))
    breaks.sort(key=lambda b: b.qty)

    desc = p.get("displayName") or p.get("longDescription")
    attrs: dict[str, str] = {}
    for k, v in (p.get("attributes") or {}).items() if isinstance(p.get("attributes"), dict) else []:
        if v:
            attrs[str(k)] = metric_first(str(v))
    guess_attrs_from_description(attrs, desc)
    for k in ("Dielectric", "Temperature Coefficient", "Temperature Characteristics"):
        if k in attrs:
            attrs[k] = canon_tempchar(attrs[k]) or attrs[k]

    datasheet = None
    for d in p.get("datasheets") or []:
        if isinstance(d, dict) and d.get("url"):
            datasheet = d["url"]
            break

    # element14's image path scheme isn't confirmed against a live response, so only a field that
    # is ALREADY a full URL is used - a guessed CDN path could point at a broken/wrong image
    image = None
    img = p.get("image")
    if isinstance(img, dict):
        img = img.get("url") or img.get("baseName")
    if isinstance(img, str) and img.startswith(("http://", "https://")):
        image = img

    stock = None
    inv = p.get("inv") or {}
    if isinstance(inv, dict):
        for k in ("quantity", "stockLevel", "stockQty", "level"):
            v = inv.get(k)
            if isinstance(v, (int, float)) or str(v).isdigit():
                stock = int(v)
                break

    return ProviderResult(
        provider="farnell",
        mpn=p.get("translatedManufacturerPartNumber") or p.get("manufacturerPartNumber") or "",
        manufacturer=p.get("brandName") or p.get("vendorName"),
        description=desc,
        datasheet_url=datasheet,
        image_url=image,
        product_url=p.get("productUrl") or None,
        sku=p.get("sku") or None,
        category_hint=None,
        lifecycle=p.get("productStatus") or None,
        in_stock=stock,
        attributes=attrs,
        price_breaks=breaks,
    )


def _from_dict(r: dict) -> ProviderResult:
    return ProviderResult(
        provider=r.get("provider", "farnell"),
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
