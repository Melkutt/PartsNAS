"""Look a part up at a supplier and (optionally) copy fields onto it.

`GET  /api/lookup/providers`            which providers are usable right now
`POST /api/lookup`                      {mpn, provider} -> normalized results
`POST /api/parts/{id}/apply-lookup`     {result, apply:{...}} -> write chosen bits

Only ever called from the "Look up" button. Results are disk-cached (see
providers/safety.py), so re-opening the dialog costs no request.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Part, PartSupplier, Supplier
from ..providers import all_providers, get_provider
from ..providers.base import ProviderBlocked, ProviderError
from ..providers.safety import UA
from .images import _refresh_primary, store_attachment

router = APIRouter(tags=["lookup"])


class LookupBody(BaseModel):
    mpn: str
    provider: str


class ApplyBlock(BaseModel):
    manufacturer: bool = False
    description: bool = False
    datasheet: bool = False
    image: bool = False
    supplier: bool = False
    attributes: dict[str, str] = Field(default_factory=dict)  # our_field_key -> value


class ApplyBody(BaseModel):
    result: dict
    apply: ApplyBlock


@router.get("/api/lookup/providers")
def providers(db: Session = Depends(get_db)):
    return [
        {"name": p.name, "label": p.label, "configured": p.configured(db)}
        for p in all_providers()
    ]


@router.post("/api/lookup")
def do_lookup(body: LookupBody, db: Session = Depends(get_db)):
    p = get_provider(body.provider)
    if p is None:
        raise HTTPException(404, "unknown provider")
    if not p.configured(db):
        raise HTTPException(400, f"{p.label} has no API key configured (Settings)")
    try:
        results = p.search(db, body.mpn)
    except ProviderBlocked as e:
        raise HTTPException(429, str(e))
    except ProviderError as e:
        raise HTTPException(400, str(e))
    return {"results": [r.to_dict() for r in results]}


def _fetch_image(url: str) -> tuple[bytes, str, str] | None:
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as c:
            r = c.get(url, headers={"User-Agent": UA})
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
            return None
        if len(r.content) > 6_000_000:
            return None
        ct = r.headers["content-type"].split(";")[0]
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
               "image/gif": ".gif"}.get(ct, ".img")
        return r.content, f"mouser-image{ext}", ct
    except httpx.HTTPError:
        return None


@router.post("/api/parts/{pid}/apply-lookup")
def apply_lookup(pid: str, body: ApplyBody, db: Session = Depends(get_db)):
    part = db.get(Part, pid)
    if part is None:
        raise HTTPException(404, "part not found")
    r, ap = body.result, body.apply
    changed = []

    if ap.manufacturer and r.get("manufacturer"):
        part.manufacturer = r["manufacturer"]
        changed.append("manufacturer")
    if ap.description and r.get("description"):
        part.description = r["description"]
        changed.append("description")
    if ap.datasheet and r.get("datasheet_url"):
        part.datasheet_url = r["datasheet_url"]
        changed.append("datasheet_url")
    if ap.attributes:
        attrs = dict(part.attributes or {})
        attrs.update({k: v for k, v in ap.attributes.items() if v not in (None, "")})
        part.attributes = attrs
        changed.append(f"{len(ap.attributes)} attribute(s)")

    if ap.image and r.get("image_url"):
        got = _fetch_image(r["image_url"])
        if got:
            store_attachment(db, pid, got[1], got[0], got[2])
            db.flush()
            _refresh_primary(db, part)
            changed.append("image")
        else:
            changed.append("image (fetch failed)")

    if ap.supplier:
        sup = db.scalar(
            select(Supplier).where(Supplier.name == (r.get("provider") or "").title())
        ) or db.scalar(select(Supplier).where(Supplier.name == "Mouser"))
        if sup:
            up = r.get("unit_price") or {}
            link = db.scalar(
                select(PartSupplier).where(
                    PartSupplier.part_id == pid,
                    PartSupplier.supplier_id == sup.id,
                    PartSupplier.sku == (r.get("sku") or None),
                )
            )
            if link is None:
                link = PartSupplier(part_id=pid, supplier_id=sup.id, sku=r.get("sku") or None)
                db.add(link)
            link.url = r.get("product_url") or link.url
            if up.get("ex_vat") is not None:
                link.unit_price = up["ex_vat"]
                link.currency = up.get("currency") or "SEK"
            changed.append(f"{sup.name} supplier link")

    db.commit()
    return {"ok": True, "changed": changed}
