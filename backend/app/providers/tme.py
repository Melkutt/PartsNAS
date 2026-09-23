"""TME (Transfer Multisort Elektronik) API — https://developers.tme.eu/

Base URL `https://api.tme.eu/`, POST only, one JSON action per call:
  https://api.tme.eu/Products/Search.json       SearchPlain=<text> -> matching Symbols
  https://api.tme.eu/Products/GetProducts.json  SymbolList[]=<symbol> -> descriptions
  https://api.tme.eu/Products/GetPrices.json    SymbolList[]=<symbol> -> price breaks
  https://api.tme.eu/Products/GetParameters.json SymbolList[]=<symbol> -> technical parameters
A lookup here is 4 requests (worth it once: the result is disk-cached for two weeks same as
every other provider), so `search()` keeps the candidate list short before the follow-up calls.

Auth is TME's own HMAC-SHA1 scheme (their manual: "similar to ... OAuth 1.0a"): every request
parameter (Token plus the action's own params, NOT the signature itself) is percent-encoded;
the encoded pairs are sorted and joined with "&" (RFC 5849 3.4.1.3.2 — sorted *after* encoding,
so a bracket like `SymbolList[0]` sorts where its escaped form `%5B` would); that string, and
the request URL, are themselves percent-encoded again and joined as `POST&<url>&<params>`. The
HMAC-SHA1 of that base string is keyed with the Application Secret **alone** — unlike OAuth
1.0a's `consumer_secret&token_secret`, TME has no second secret, and their own manual describes
the key only as "assigned to the application" (no trailing "&" mentioned or needed) — base64-
encoded, sent back as the `ApiSignature` form field. (An earlier version of this file used an
OAuth-style `secret + "&"` key by analogy; a real account got back `E_INVALID_SIGNATURE` with
it, which is what pinned this down.) See `_sign()` below.

Creds: env PARTSNAS_TME_TOKEN / PARTSNAS_TME_SECRET, else Setting `provider:tme:config`
{token, secret} (the "Token" and "Application Secret" from developers.tme.eu -> your app's
Applications tab). Country / Language / Currency default to SE / EN / SEK, like Mouser and
Digi-Key here; override via Setting `provider:tme:locale`.

NOTE: the Search/GetParameters field names below (ProductList, ParameterList, ...) follow
TME's published examples and community client libraries, but this provider has not yet been
exercised against a live account — everything is read defensively (`.get(...)`, never raises
on an unexpected shape), so a wrong field name only means a thinner result, not a crash. First
real "Look up" from a part with an MPN will show whether anything needs adjusting.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from urllib.parse import quote

from sqlalchemy.orm import Session

from ..core.kv import get_kv
from ..textparse import canon_tempchar, metric_first
from .base import PriceBreak, Provider, ProviderError, ProviderResult
from .safety import cache_get, cache_put, guarded_request

BASE = "https://api.tme.eu"
PER_MIN = 6      # a lookup is 4 requests; kept low so one click never bursts more than TME expects
PER_DAY = 500


def _quote(s: str) -> str:
    return quote(str(s), safe="~")  # RFC 3986: everything but unreserved chars is encoded


def _flatten(params: dict) -> dict[str, str]:
    """SymbolList=[a, b] -> {"SymbolList[0]": a, "SymbolList[1]": b}; everything else as-is."""
    out: dict[str, str] = {}
    for k, v in params.items():
        if isinstance(v, (list, tuple)):
            for i, item in enumerate(v):
                out[f"{k}[{i}]"] = str(item)
        elif v is not None:
            out[k] = str(v)
    return out


def _sign(method: str, url: str, params: dict[str, str], secret: str) -> str:
    encoded = sorted((_quote(k), _quote(v)) for k, v in params.items())  # sort AFTER encoding (RFC 5849)
    param_str = "&".join(f"{k}={v}" for k, v in encoded)
    base_str = f"{method.upper()}&{_quote(url)}&{_quote(param_str)}"
    digest = hmac.new(secret.encode(), base_str.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


class TMEProvider(Provider):
    name = "tme"
    label = "TME"
    website = "https://www.tme.eu"
    cred_fields = ["token", "secret"]

    def _creds(self, db: Session) -> tuple[str | None, str | None]:
        cfg = get_kv(db, "provider:tme:config", {}) or {}
        token = os.environ.get("PARTSNAS_TME_TOKEN") or cfg.get("token")
        secret = os.environ.get("PARTSNAS_TME_SECRET") or cfg.get("secret")
        return token, secret

    def configured(self, db: Session) -> bool:
        return all(self._creds(db))

    def _locale(self, db: Session) -> dict:
        loc = get_kv(db, "provider:tme:locale", {}) or {}
        return {
            "country": loc.get("country", "SE"),
            "language": loc.get("language", "EN"),
            "currency": loc.get("currency", "SEK"),
        }

    def _call(self, db: Session, action: str, params: dict) -> dict:
        token, secret = self._creds(db)
        if not (token and secret):
            raise ProviderError("TME token / application secret not configured")
        url = f"{BASE}/{action}.json"
        flat = _flatten({"Token": token, **params})
        flat["ApiSignature"] = _sign("POST", url, flat, secret)
        data = guarded_request(
            db, self.name, method="POST", url=url, data=flat,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            per_min=PER_MIN, per_day=PER_DAY,
        )
        if str(data.get("Status", "OK")).upper() not in ("OK", ""):
            raise ProviderError(f"TME: {data.get('Status')} — {data.get('Data', {}).get('Message', '')}".strip(" —"))
        return data.get("Data") or {}

    def search(self, db: Session, mpn: str) -> list[ProviderResult]:
        mpn = mpn.strip()
        if not mpn:
            raise ProviderError("empty MPN")
        cached = cache_get(self.name, mpn)
        if cached is not None:
            return [_from_dict(r) for r in cached]

        loc = self._locale(db)
        found = self._call(db, "Products/Search", {
            "SearchPlain": mpn, "Country": loc["country"], "Language": loc["language"],
        })
        rows = found.get("ProductList") or found.get("Products") or []
        symbols = [r.get("Symbol") for r in rows if r.get("Symbol")][:10]
        if not symbols:
            cache_put(self.name, mpn, [])
            return []

        by_symbol: dict[str, dict] = {r.get("Symbol"): dict(r) for r in rows if r.get("Symbol")}
        try:
            details = self._call(db, "Products/GetProducts", {
                "SymbolList": symbols, "Country": loc["country"], "Language": loc["language"],
            })
            for r in details.get("ProductList") or []:
                if r.get("Symbol") in by_symbol:
                    by_symbol[r["Symbol"]].update(r)
        except ProviderError:
            pass  # Search's own fields are already enough for a usable (if thinner) result
        try:
            prices = self._call(db, "Products/GetPrices", {
                "SymbolList": symbols, "Country": loc["country"], "Currency": loc["currency"], "Language": loc["language"],
            })
            price_by_symbol = {r.get("Symbol"): r.get("PriceList") or [] for r in prices.get("ProductList") or []}
        except ProviderError:
            price_by_symbol = {}
        try:
            params = self._call(db, "Products/GetParameters", {"SymbolList": symbols, "Language": loc["language"]})
            attrs_by_symbol = {r.get("Symbol"): r.get("ParameterList") or [] for r in params.get("ProductList") or []}
        except ProviderError:
            attrs_by_symbol = {}

        results = [
            _parse_product(by_symbol[sym], price_by_symbol.get(sym) or [], attrs_by_symbol.get(sym) or [], loc["currency"])
            for sym in symbols
        ]
        results.sort(key=lambda r: 0 if r.mpn.lower() == mpn.lower() else 1)
        cache_put(self.name, mpn, [r.to_dict() for r in results])
        return results


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_product(p: dict, price_list: list, param_list: list, currency: str) -> ProviderResult:
    breaks: list[PriceBreak] = []
    for pb in price_list:
        amount, price = _num(pb.get("Amount")), _num(pb.get("PriceValue") or pb.get("PriceBase"))
        if price is not None:
            breaks.append(PriceBreak(qty=int(amount or 1), ex_vat=price, currency=currency))
    breaks.sort(key=lambda b: b.qty)

    attrs: dict[str, str] = {}
    for prm in param_list:
        name = prm.get("ParameterName") or prm.get("Name")
        val = prm.get("ParameterValue") or prm.get("Value")
        if name and val:
            attrs[name] = metric_first(str(val)) or str(val)
    for k in ("Dielectric", "Temperature Coefficient", "Temperature Characteristics"):
        if k in attrs:
            attrs[k] = canon_tempchar(attrs[k]) or attrs[k]

    photo = p.get("Photo") or p.get("Image") or None
    if photo and photo.startswith("//"):
        photo = "https:" + photo
    return ProviderResult(
        provider="tme",
        mpn=p.get("OriginalSymbol") or p.get("Symbol") or "",
        manufacturer=p.get("Producer") or p.get("Manufacturer"),
        description=p.get("Description") or p.get("OriginalDescription"),
        datasheet_url=p.get("DocumentUrl") or p.get("Datasheet") or None,
        image_url=photo,
        product_url=p.get("ProductInformationPage") or p.get("ProductUrl") or None,
        sku=p.get("Symbol") or None,
        category_hint=p.get("Category") or p.get("CategoryName") or None,
        lifecycle=None,
        in_stock=int(p["InStock"]) if str(p.get("InStock", "")).isdigit() else None,
        attributes=attrs,
        price_breaks=breaks,
    )


def _from_dict(r: dict) -> ProviderResult:
    return ProviderResult(
        provider=r.get("provider", "tme"),
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
