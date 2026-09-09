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

from ..catmatch import match_category
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
    lifecycle: bool = False  # copy discontinued flag from the provider lifecycle
    category: bool = False
    category_id: int | None = None
    mount: bool = False
    mount_value: str | None = None  # smd | tht | other
    attributes: dict[str, str] = Field(default_factory=dict)  # our_field_key -> value


_SMD_CASES = {"0201", "0402", "0603", "0805", "1206", "1210", "1812", "2010", "2220", "2512"}


def mount_guess(attrs: dict) -> str | None:
    for k in ("Mounting Style", "Termination Style", "Mounting Type", "Mounting", "Package Type"):
        v = (attrs.get(k) or "").lower()
        if "surface" in v or "smd" in v or "smt" in v:
            return "smd"
        if "through" in v or "tht" in v or "radial" in v or "axial" in v:
            return "tht"
    for k in ("Package / Case", "Case Code - in", "Case/Package", "Case Code"):
        v = (attrs.get(k) or "").strip()
        if any(c in v for c in _SMD_CASES):
            return "smd"
    return None


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
    want = body.mpn.strip().lower()
    out = []
    for r in results:
        d = r.to_dict()
        d["category_match"] = match_category(db, r.category_hint)
        d["mount_guess"] = mount_guess(r.attributes)
        d["attr_count"] = len(r.attributes)
        out.append(d)
    # exact MPN first, then richest (most attributes) first
    out.sort(key=lambda x: (0 if (x["mpn"] or "").lower() == want else 1, -x["attr_count"]))
    return {"results": out}


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_MAGIC = {
    b"\x89PNG": ("image/png", ".png"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"GIF8": ("image/gif", ".gif"),
    b"RIFF": ("image/webp", ".webp"),  # RIFF....WEBP
}


def _sniff(data: bytes) -> tuple[str, str] | None:
    for magic, ct_ext in _MAGIC.items():
        if data.startswith(magic):
            if magic == b"RIFF" and data[8:12] != b"WEBP":
                continue
            return ct_ext
    return None


def _fetch_image(url: str, referer: str | None) -> tuple:
    """-> (bytes, filename, content_type, None) or (None, None, None, reason)."""
    headers = {
        "User-Agent": _BROWSER_UA,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": referer or "https://www.mouser.com/",
    }
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True) as c:
            r = c.get(url if url.startswith("http") else "https:" + url, headers=headers)
    except httpx.HTTPError as e:
        return None, None, None, f"network error: {e}"
    if r.status_code != 200:
        return None, None, None, f"HTTP {r.status_code}"
    if len(r.content) > 6_000_000:
        return None, None, None, "image too large"
    ct = r.headers.get("content-type", "").split(";")[0].strip()
    sniff = _sniff(r.content[:16])
    if ct.startswith("image/"):
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
               "image/gif": ".gif"}.get(ct, sniff[1] if sniff else ".img")
        return r.content, f"lookup-image{ext}", ct, None
    if sniff:
        return r.content, f"lookup-image{sniff[1]}", sniff[0], None
    return None, None, None, f"not an image (content-type {ct or 'none'})"


@router.post("/api/parts/{pid}/apply-lookup")
def apply_lookup(pid: str, body: ApplyBody, db: Session = Depends(get_db)):
    part = db.get(Part, pid)
    if part is None:
        raise HTTPException(404, "part not found")
    r, ap = body.result, body.apply
    changed = []

    if ap.category and ap.category_id and db.get(Part, pid):
        from ..models import Category

        if db.get(Category, ap.category_id):
            part.category_id = ap.category_id
            changed.append("category")
    if ap.mount and ap.mount_value in ("smd", "tht", "other"):
        part.mount = ap.mount_value
        changed.append(f"mount → {ap.mount_value.upper()}")
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

    if ap.lifecycle and r.get("lifecycle"):
        lc = r["lifecycle"].lower()
        if any(s in lc for s in ("obsolete", "discontinued", "eol", "not recommended", "last time buy")):
            part.discontinued = True
            changed.append("marked discontinued")

    if ap.image and r.get("image_url"):
        data, fname, ct, reason = _fetch_image(r["image_url"], r.get("product_url"))
        if data:
            store_attachment(db, pid, fname, data, ct)
            db.flush()
            _refresh_primary(db, part)
            changed.append("image")
        else:
            changed.append(f"image skipped ({reason})")

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
