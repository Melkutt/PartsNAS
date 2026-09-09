"""Digi-Key Product Information API v4 — https://developer.digikey.com/

Unlike Mouser, this one returns a full `Parameters` list (Core Processor,
Program Memory Size, Voltage - Supply, Number of I/O, Speed, ...).

Auth is 2-legged OAuth (client_credentials) — no browser redirect:
  POST https://api.digikey.com/v1/oauth2/token
       grant_type=client_credentials&client_id=..&client_secret=..
  -> {access_token, expires_in ~600}
The token is cached in Setting `provider:digikey:token`.

Creds: env PARTSNAS_DIGIKEY_CLIENT_ID / PARTSNAS_DIGIKEY_CLIENT_SECRET, else the
Setting `provider:digikey:config` {client_id, client_secret}. Locale is fixed to
SE / SEK / en for now (Setting `provider:digikey:locale` can override).
"""
from __future__ import annotations

import os
import time

import httpx
from sqlalchemy.orm import Session

from ..core.kv import get_kv, set_kv
from ..textparse import canon_tempchar
from .base import PriceBreak, Provider, ProviderError, ProviderResult
from .safety import UA, cache_get, cache_put, guarded_request

TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"
PER_MIN = 20
PER_DAY = 1000


class DigiKeyProvider(Provider):
    name = "digikey"
    label = "Digi-Key"
    website = "https://www.digikey.se"
    cred_fields = ["client_id", "client_secret"]

    def _creds(self, db: Session) -> tuple[str | None, str | None]:
        cfg = get_kv(db, "provider:digikey:config", {}) or {}
        cid = os.environ.get("PARTSNAS_DIGIKEY_CLIENT_ID") or cfg.get("client_id")
        sec = os.environ.get("PARTSNAS_DIGIKEY_CLIENT_SECRET") or cfg.get("client_secret")
        return cid, sec

    def configured(self, db: Session) -> bool:
        return all(self._creds(db))

    def _locale(self, db: Session) -> dict:
        loc = get_kv(db, "provider:digikey:locale", {}) or {}
        return {
            "site": loc.get("site", "SE"),
            "language": loc.get("language", "en"),
            "currency": loc.get("currency", "SEK"),
        }

    def _token(self, db: Session) -> str:
        tok = get_kv(db, "provider:digikey:token", {}) or {}
        if tok.get("access_token") and tok.get("expires_at", 0) - 30 > time.time():
            return tok["access_token"]
        cid, sec = self._creds(db)
        if not (cid and sec):
            raise ProviderError("Digi-Key client id / secret not configured")
        try:
            with httpx.Client(timeout=15.0) as c:
                r = c.post(
                    TOKEN_URL,
                    data={"grant_type": "client_credentials", "client_id": cid, "client_secret": sec},
                    headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.HTTPError as e:
            raise ProviderError(f"Digi-Key token request failed: {e}")
        if r.status_code != 200:
            raise ProviderError(
                f"Digi-Key auth failed (HTTP {r.status_code}) — check client id / secret "
                f"and that Product Information V4 is added to the app"
            )
        j = r.json()
        set_kv(db, "provider:digikey:token", {
            "access_token": j["access_token"],
            "expires_at": time.time() + int(j.get("expires_in", 600)),
        })
        return j["access_token"]

    def search(self, db: Session, mpn: str) -> list[ProviderResult]:
        mpn = mpn.strip()
        if not mpn:
            raise ProviderError("empty MPN")
        cached = cache_get(self.name, mpn)
        if cached is not None:
            return [_from_dict(r) for r in cached]

        loc = self._locale(db)
        token = self._token(db)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-DIGIKEY-Client-Id": self._creds(db)[0],
            "X-DIGIKEY-Locale-Site": loc["site"],
            "X-DIGIKEY-Locale-Language": loc["language"],
            "X-DIGIKEY-Locale-Currency": loc["currency"],
            "Content-Type": "application/json",
        }
        body = {"Keywords": mpn, "Limit": 10, "Offset": 0}
        data = guarded_request(
            db, self.name, method="POST", url=SEARCH_URL, json=body, headers=headers,
            per_min=PER_MIN, per_day=PER_DAY,
        )
        products = data.get("Products") or []
        results = [_parse_product(p, loc["currency"]) for p in products]
        want = mpn.lower()
        results.sort(key=lambda r: (0 if (r.mpn or "").lower() == want else 1, -len(r.attributes)))
        cache_put(self.name, mpn, [r.to_dict() for r in results])
        return results


def _txt(v):
    if isinstance(v, dict):
        return v.get("Name") or v.get("Value") or v.get("ProductDescription") or v.get("Status")
    return v


def _parse_product(p: dict, currency: str) -> ProviderResult:
    desc = p.get("Description") or {}
    if isinstance(desc, dict):
        description = desc.get("ProductDescription") or desc.get("DetailedDescription")
    else:
        description = desc

    attrs: dict[str, str] = {}
    for prm in p.get("Parameters") or []:
        name = prm.get("ParameterText") or prm.get("Parameter")
        val = prm.get("ValueText") or prm.get("Value")
        if name and val not in (None, "", "-"):
            attrs[name] = str(val)
    for k in ("Temperature Coefficient", "Dielectric", "Temperature Characteristics"):
        if k in attrs:
            attrs[k] = canon_tempchar(attrs[k]) or attrs[k]
    if p.get("Series") and _txt(p["Series"]):
        attrs.setdefault("Series", _txt(p["Series"]))

    # price + Digi-Key P/N live on the variations
    breaks: list[PriceBreak] = []
    sku = None
    for var in p.get("ProductVariations") or []:
        sku = sku or var.get("DigiKeyProductNumber")
        for sp in var.get("StandardPricing") or []:
            price = sp.get("UnitPrice")
            if price is not None:
                breaks.append(PriceBreak(qty=int(sp.get("BreakQuantity") or 1),
                                         ex_vat=float(price), currency=currency))
    if not breaks and p.get("UnitPrice"):
        breaks.append(PriceBreak(qty=1, ex_vat=float(p["UnitPrice"]), currency=currency))
    breaks.sort(key=lambda b: b.qty)

    status = p.get("ProductStatus") or {}
    life = _txt(status)
    if p.get("EndOfLife"):
        life = "End of Life"
    elif p.get("Discontinued"):
        life = "Discontinued"
    cat = p.get("Category") or {}
    cat_hint = _txt(cat)
    return ProviderResult(
        provider="digikey",
        mpn=p.get("ManufacturerProductNumber") or p.get("ManufacturerPartNumber") or "",
        manufacturer=_txt(p.get("Manufacturer")),
        description=description,
        datasheet_url=p.get("DatasheetUrl") or None,
        image_url=p.get("PhotoUrl") or p.get("PrimaryPhoto") or None,
        product_url=p.get("ProductUrl") or None,
        sku=sku,
        category_hint=cat_hint or None,
        lifecycle=life or None,
        in_stock=p.get("QuantityAvailable"),
        attributes=attrs,
        price_breaks=breaks,
    )


def _from_dict(r: dict) -> ProviderResult:
    return ProviderResult(
        provider=r.get("provider", "digikey"),
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
