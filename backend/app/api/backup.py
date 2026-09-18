"""Full PartsNAS backup — a zip that carries everything (attributes, tags,
suppliers, images, stock, design notes, replacement links).

`GET  /api/export/backup.zip?only_with_supplier=&category_id=&q=`
`POST /api/import/backup`   multipart file=<zip>, mode=merge|update|replace, dry_run

mode:
  merge   — create parts that don't exist (match id then MPN); leave existing alone
  update  — also overwrite fields / re-link suppliers+images on existing parts
  replace — like update, but first clear the existing part's attributes,
            supplier links and images ("skriva över allt")
"""
from __future__ import annotations

import io
import json
import secrets
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..core.config import get_settings
from ..core.db import get_db
from ..core.kv import get_kv, set_kv
from ..models import (
    Attachment,
    Category,
    Customer,
    DesignNote,
    DesignNoteLink,
    Part,
    PartSupplier,
    Quote,
    QuoteLine,
    Setting,
    StockEntry,
    StorageLocation,
    Supplier,
    Tag,
)
from ..providers import all_providers
from ..services import category_path_map, location_breakdown
from .images import _refresh_primary, store_attachment
from .parts import PartFilter, _query

router = APIRouter(tags=["backup"])
settings = get_settings()
FMT = "partsnas-backup"


# ---------- export ----------
def _part_record(db: Session, p: Part, paths: dict[int, str]) -> dict:
    loc = location_breakdown(db, p.id)
    return {
        "id": p.id,
        "mpn": p.mpn,
        "manufacturer": p.manufacturer,
        "name": p.name,
        "description": p.description,
        "category_id": p.category_id,
        "category_path": paths.get(p.category_id, ""),
        "part_class": None,
        "mount": p.mount,
        "footprint_raw": p.footprint_raw,
        "kicad_symbol": p.kicad_symbol,
        "kicad_footprint": p.kicad_footprint,
        "datasheet_url": p.datasheet_url,
        "min_stock": p.min_stock,
        "notes": p.notes,
        "design_doc": p.design_doc,
        "octopart_id": p.octopart_id,
        "attributes": p.attributes or {},
        "tags": [t.name for t in p.tags],
        "discontinued": p.discontinued,
        "replaced_by_mpn": p.replaced_by.mpn if p.replaced_by else None,
        "replacement_mpn": p.replacement_mpn,
        "replacement_sku": p.replacement_sku,
        "replacement_source": p.replacement_source,
        "suppliers": [
            {
                "supplier": link.supplier.name if link.supplier else None,
                "sku": link.sku,
                "url": link.url,
                "unit_price": link.unit_price,
                "currency": link.currency,
                "vat_percent": link.vat_percent,
                "active": link.active,
                "preferred": link.preferred,
                "note": link.note,
            }
            for link in p.suppliers
        ],
        "images": [
            {"id": a.id, "kind": a.kind, "filename": a.filename, "stored": a.stored,
             "content_type": a.content_type, "sort_order": a.sort_order}
            for a in p.attachments
        ],
        "stock": [{"location": r["location"], "qty": r["qty"]} for r in loc],
        "design_notes": [
            {
                "title": n.title, "condition": n.condition, "body": n.body,
                "links": [
                    {"mpn": (lk.part.mpn if lk.part else lk.mpn),
                     "label": (lk.part.name if lk.part else None),
                     "role": lk.role, "value_hint": lk.value_hint, "qty": lk.qty}
                    for lk in n.links
                ],
            }
            for n in p.design_notes
        ],
    }


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _customer_record(c: Customer) -> dict:
    return {"id": c.id, "name": c.name, "address": c.address, "org_number": c.org_number,
            "phone": c.phone, "email": c.email, "created_at": _iso(c.created_at)}


def _quote_record(q: Quote) -> dict:
    """Everything needed to rebuild a quote/invoice exactly — including lock,
    trash and invoice-date state, since invoice history is the point."""
    return {
        "id": q.id, "customer": q.customer, "customer_id": q.customer_id,
        "title": q.title, "note": q.note,
        "markup_percent": q.markup_percent, "vat_percent": q.vat_percent,
        "status": q.status, "stock_committed": q.stock_committed,
        "hide_cost": q.hide_cost, "hide_vat": q.hide_vat, "locked": q.locked,
        "created_at": _iso(q.created_at), "updated_at": _iso(q.updated_at),
        "invoiced_at": _iso(q.invoiced_at), "deleted_at": _iso(q.deleted_at),
        "lines": [
            {"part_id": ln.part_id, "line_type": ln.line_type, "description": ln.description,
             "mpn": ln.mpn, "qty": ln.qty, "unit_cost": ln.unit_cost,
             "markup_percent": ln.markup_percent, "currency": ln.currency,
             "cost_source": ln.cost_source, "note": ln.note, "sort_order": ln.sort_order}
            for ln in q.lines
        ],
    }


@router.get("/api/export/backup.zip")
def export_backup(
    db: Session = Depends(get_db),
    only_with_supplier: bool = False,
    category_id: int | None = None,
    q: str | None = None,
    include_secrets: bool = False,
):
    f = PartFilter(q=q, category_id=category_id)
    ids = list(db.scalars(_query(db, f)).all())
    if only_with_supplier:
        with_sup = {
            pid for (pid,) in db.execute(
                select(PartSupplier.part_id).where(PartSupplier.part_id.in_(ids)).distinct()
            ).all()
        }
        ids = [i for i in ids if i in with_sup]
    parts = db.scalars(select(Part).where(Part.id.in_(ids))).all() if ids else []
    paths = category_path_map(db)
    records = [_part_record(db, p, paths) for p in parts]

    # full trees so a user-made branch that has no parts yet still round-trips
    cats = [
        {"path": paths.get(c.id, c.name), "part_class": c.part_class,
         "comment": c.comment, "sort_order": c.sort_order, "is_unsorted": c.is_unsorted}
        for c in db.scalars(select(Category)).all()
    ]
    lp = {loc.id: loc for loc in db.scalars(select(StorageLocation)).all()}

    def _loc_path(loc):
        chain, seen = [], set()
        while loc and loc.id not in seen:
            seen.add(loc.id)
            chain.append(loc.name)
            loc = lp.get(loc.parent_id)
        return " > ".join(reversed(chain))

    locs = [
        {"path": _loc_path(loc), "note": loc.note, "legacy_id": loc.legacy_id}
        for loc in lp.values()
    ]

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps({
            "format": FMT, "version": 1, "app_version": __version__,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "parts": len(records), "categories": len(cats), "locations": len(locs),
            "only_with_supplier": only_with_supplier,
        }, indent=2))
        z.writestr("parts.json", json.dumps(records, ensure_ascii=False, indent=2))
        z.writestr("categories.json", json.dumps(cats, ensure_ascii=False, indent=2))
        z.writestr("locations.json", json.dumps(locs, ensure_ascii=False, indent=2))
        z.writestr("customers.json", json.dumps(
            [_customer_record(c) for c in db.scalars(select(Customer).order_by(Customer.id)).all()],
            ensure_ascii=False, indent=2))
        z.writestr("quotes.json", json.dumps(
            [_quote_record(q) for q in db.scalars(select(Quote).order_by(Quote.id)).all()],
            ensure_ascii=False, indent=2))
        logo_rel = get_kv(db, "branding:logo", None)
        z.writestr("branding.json", json.dumps({
            "logo_filename": Path(logo_rel).name if logo_rel else None,
            "footer": get_kv(db, "branding:footer", "") or "",
            "swish": get_kv(db, "branding:swish", "") or "",
        }, ensure_ascii=False, indent=2))
        if logo_rel:
            logo_src = settings.data_dir / logo_rel
            if logo_src.exists():
                z.write(logo_src, f"branding/{Path(logo_rel).name}")
        if include_secrets:
            secrets = {}
            for prov in all_providers():
                cfg = get_kv(db, f"provider:{prov.name}:config", {}) or {}
                loc = get_kv(db, f"provider:{prov.name}:locale", {}) or {}
                if cfg or loc:
                    secrets[prov.name] = {"config": cfg, "locale": loc}
            z.writestr("secrets.json", json.dumps({"providers": secrets}, indent=2))
        for p in parts:
            for a in p.attachments:
                src = settings.data_dir / a.stored
                if src.exists():
                    z.write(src, f"images/{p.id}/{a.filename}")
    bio.seek(0)
    fn = f"partsnas-backup-{datetime.now():%Y%m%d-%H%M}.zip"
    return StreamingResponse(iter([bio.getvalue()]), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{fn}"'})


# ---------- import ----------
def _resolve_category(db: Session, path: str, cache: dict) -> int | None:
    path = (path or "").strip()
    if not path:
        return None
    if path in cache:
        return cache[path]
    parent_id = None
    node = None
    for name in [s.strip() for s in path.split(">") if s.strip()]:
        node = db.scalar(
            select(Category).where(Category.parent_id.is_(parent_id), Category.name == name)
            if parent_id is None
            else select(Category).where(Category.parent_id == parent_id, Category.name == name)
        )
        if node is None:
            node = Category(name=name, slug=name.lower().replace(" ", "-"), parent_id=parent_id)
            db.add(node)
            db.flush()
            cache["_created_cats"] = cache.get("_created_cats", 0) + 1
        parent_id = node.id
    cache[path] = node.id if node else None
    return cache[path]


def _resolve_location(db: Session, path: str, cache: dict) -> int | None:
    path = (path or "").strip()
    if not path:
        return None
    if path in cache:
        return cache[path]
    parent_id = None
    node = None
    for name in [s.strip() for s in path.split(">") if s.strip()]:
        node = db.scalar(
            select(StorageLocation).where(StorageLocation.parent_id.is_(parent_id), StorageLocation.name == name)
            if parent_id is None
            else select(StorageLocation).where(StorageLocation.parent_id == parent_id, StorageLocation.name == name)
        )
        if node is None:
            node = StorageLocation(name=name, parent_id=parent_id)
            db.add(node)
            db.flush()
            cache["_created_locs"] = cache.get("_created_locs", 0) + 1
        parent_id = node.id
    cache[path] = node.id if node else None
    return cache[path]


def _supplier_by_name(db: Session, name: str | None, s: dict) -> Supplier | None:
    if not name:
        return None
    sup = db.scalar(select(Supplier).where(func.lower(Supplier.name) == name.lower()))
    if sup is None:
        sup = Supplier(name=name, sort_order=300)
        db.add(sup)
        db.flush()
        s["suppliers_created"] = s.get("suppliers_created", 0) + 1
    return sup


def _dt(s: str | None):
    return datetime.fromisoformat(s) if s else None


def _restore_customers_and_quotes(db: Session, zf: zipfile.ZipFile, mode: str, s: dict) -> None:
    """Quotes keep their original id (= the invoice number). A quote already
    present with the same id AND created_at is the same document: merge leaves
    it, update/replace overwrite it. Same id but a different created_at is some
    other document — restored under a fresh id with a warning, never clobbered."""
    s.update({"customers_created": 0, "quotes_created": 0, "quotes_updated": 0, "quotes_skipped": 0})
    names = zf.namelist()

    cust_map: dict[int, int] = {}  # id in the backup -> id here
    if "customers.json" in names:
        for cr in json.loads(zf.read("customers.json")):
            hit = db.scalar(select(Customer).where(
                func.lower(Customer.name) == (cr.get("name") or "").lower(),
                func.coalesce(Customer.org_number, "") == (cr.get("org_number") or "")))
            if hit is None:
                hit = Customer(name=cr["name"], address=cr.get("address"), org_number=cr.get("org_number"),
                               phone=cr.get("phone"), email=cr.get("email"))
                if cr.get("created_at"):
                    hit.created_at = _dt(cr["created_at"])
                db.add(hit)
                db.flush()
                s["customers_created"] += 1
            cust_map[cr["id"]] = hit.id

    if "quotes.json" not in names:
        return
    for qr in json.loads(zf.read("quotes.json")):
        existing = db.get(Quote, qr["id"])
        same = existing is not None and _iso(existing.created_at) == qr.get("created_at")
        if same and mode == "merge":
            s["quotes_skipped"] += 1
            continue
        if same:
            q = existing
            for ln in list(q.lines):
                db.delete(ln)
            db.flush()
            s["quotes_updated"] += 1
        else:
            q = Quote()
            if existing is None:
                q.id = qr["id"]
            else:
                s["warnings"].append(f"quote #{qr['id']} clashes with a different quote here — restored under a new number")
            db.add(q)
            s["quotes_created"] += 1
        for k in ("customer", "title", "note", "markup_percent", "vat_percent", "status",
                  "stock_committed", "hide_cost", "hide_vat", "locked"):
            if k in qr:
                setattr(q, k, qr[k])
        q.customer_id = cust_map.get(qr.get("customer_id"))
        q.created_at = _dt(qr.get("created_at")) or q.created_at
        q.invoiced_at = _dt(qr.get("invoiced_at"))
        q.deleted_at = _dt(qr.get("deleted_at"))
        db.flush()
        for ln in qr.get("lines") or []:
            pid = ln.get("part_id")
            if pid and db.get(Part, pid) is None:
                pid = db.scalar(select(Part.id).where(func.lower(Part.mpn) == (ln.get("mpn") or "").lower())) \
                    if ln.get("mpn") else None
            db.add(QuoteLine(
                quote_id=q.id, part_id=pid, line_type=ln.get("line_type") or "part",
                description=ln["description"], mpn=ln.get("mpn"), qty=ln.get("qty", 1),
                unit_cost=ln.get("unit_cost", 0), markup_percent=ln.get("markup_percent"),
                currency=ln.get("currency") or "SEK", cost_source=ln.get("cost_source"),
                note=ln.get("note"), sort_order=ln.get("sort_order", 0)))
        db.flush()
        q.updated_at = _dt(qr.get("updated_at")) or q.updated_at


@router.post("/api/import/backup")
async def import_backup(
    file: UploadFile = File(...),
    mode: str = Form("merge"),
    dry_run: bool = Form(True),
    db: Session = Depends(get_db),
):
    if mode not in ("merge", "update", "replace"):
        raise HTTPException(400, "mode must be merge|update|replace")
    raw = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(400, "not a zip file")
    try:
        records = json.loads(zf.read("parts.json"))
    except KeyError:
        raise HTTPException(400, "parts.json missing — not a PartsNAS backup")

    s: dict = {"created": 0, "updated": 0, "skipped": 0, "images": 0,
               "supplier_links": 0, "design_notes": 0, "creds_restored": [],
               "branding_restored": False, "warnings": []}

    if "secrets.json" in zf.namelist():
        sec = json.loads(zf.read("secrets.json")).get("providers", {})
        for name, blob in sec.items():
            if blob.get("config"):
                if not dry_run:
                    set_kv(db, f"provider:{name}:config", blob["config"])
                    set_kv(db, f"provider:{name}:token", {})
                s["creds_restored"].append(name)
            if blob.get("locale") and not dry_run:
                set_kv(db, f"provider:{name}:locale", blob["locale"])

    if "branding.json" in zf.namelist():
        br = json.loads(zf.read("branding.json"))
        if not dry_run:
            if br.get("footer") is not None:
                set_kv(db, "branding:footer", br["footer"])
            if br.get("swish") is not None:
                set_kv(db, "branding:swish", br["swish"])
            logo_name = br.get("logo_filename")
            if logo_name:
                try:
                    blob = zf.read(f"branding/{logo_name}")
                except KeyError:
                    blob = None
                if blob:
                    old = get_kv(db, "branding:logo", None)
                    if old:
                        (settings.data_dir / old).unlink(missing_ok=True)
                    rel = f"branding/logo_{secrets.token_hex(8)}{Path(logo_name).suffix}"
                    (settings.data_dir / rel).write_bytes(blob)
                    set_kv(db, "branding:logo", rel)
            s["branding_restored"] = True
    ccache: dict = {}
    lcache: dict = {}

    # recreate the whole category / location tree first — including branches that
    # have no parts yet — so a round-trip doesn't drop the user's structure
    if "categories.json" in zf.namelist():
        for cr in sorted(json.loads(zf.read("categories.json")),
                         key=lambda r: (r.get("path") or "").count(">")):
            cid = _resolve_category(db, cr.get("path"), ccache)
            node = db.get(Category, cid) if cid else None
            if node:
                if cr.get("part_class") and not node.part_class:
                    node.part_class = cr["part_class"]
                if cr.get("comment") and not node.comment:
                    node.comment = cr["comment"]
    if "locations.json" in zf.namelist():
        for lr in sorted(json.loads(zf.read("locations.json")),
                         key=lambda r: (r.get("path") or "").count(">")):
            lid = _resolve_location(db, lr.get("path"), lcache)
            node = db.get(StorageLocation, lid) if lid else None
            if node:
                if lr.get("note") and not node.note:
                    node.note = lr["note"]
                if lr.get("legacy_id") and not node.legacy_id:
                    node.legacy_id = lr["legacy_id"]

    id_by_mpn = {
        (m or "").lower(): pid
        for pid, m in db.execute(select(Part.id, Part.mpn)).all() if m
    }
    pending_replaced_by: list[tuple[str, str]] = []  # (part_id, replaced_by_mpn)

    for rec in records:
        pid = rec.get("id")
        existing = db.get(Part, pid) if pid else None
        if existing is None and rec.get("mpn"):
            hit = id_by_mpn.get(rec["mpn"].lower())
            existing = db.get(Part, hit) if hit else None

        if existing is not None and mode == "merge":
            s["skipped"] += 1
            continue

        if existing is None:
            p = Part(id=pid) if pid and db.get(Part, pid) is None else Part()
            db.add(p)
            s["created"] += 1
        else:
            p = existing
            s["updated"] += 1

        p.name = rec.get("name") or p.name or rec.get("mpn") or "part"
        p.mpn = rec.get("mpn") or p.mpn
        for k in ("manufacturer", "description", "mount", "footprint_raw", "kicad_symbol",
                  "kicad_footprint", "datasheet_url", "notes", "design_doc", "octopart_id",
                  "replacement_mpn", "replacement_sku", "replacement_source"):
            if rec.get(k) is not None:
                setattr(p, k, rec[k])
        p.min_stock = int(rec.get("min_stock") or 0)
        p.discontinued = bool(rec.get("discontinued"))
        p.category_id = _resolve_category(db, rec.get("category_path"), ccache)

        if mode == "replace":
            p.attributes = dict(rec.get("attributes") or {})
        else:
            p.attributes = {**(p.attributes or {}), **(rec.get("attributes") or {})}

        # tags
        want_tags = rec.get("tags") or []
        if want_tags:
            tags = []
            for tn in want_tags:
                t = db.scalar(select(Tag).where(Tag.name == tn)) or Tag(name=tn)
                if t.id is None:
                    db.add(t)
                tags.append(t)
            p.tags = tags
        db.flush()

        if rec.get("replaced_by_mpn"):
            pending_replaced_by.append((p.id, rec["replaced_by_mpn"]))

        # suppliers
        if mode == "replace":
            for lk in list(p.suppliers):
                db.delete(lk)
            db.flush()
        for sup_rec in rec.get("suppliers") or []:
            sup = _supplier_by_name(db, sup_rec.get("supplier"), s)
            if sup is None:
                continue
            link = db.scalar(select(PartSupplier).where(
                PartSupplier.part_id == p.id, PartSupplier.supplier_id == sup.id,
                PartSupplier.sku == (sup_rec.get("sku") or None)))
            if link is None:
                link = PartSupplier(part_id=p.id, supplier_id=sup.id, sku=sup_rec.get("sku") or None)
                db.add(link)
                s["supplier_links"] += 1
            for k in ("url", "unit_price", "currency", "vat_percent", "active", "preferred", "note"):
                if sup_rec.get(k) is not None:
                    setattr(link, k, sup_rec[k])

        # images
        if mode == "replace":
            for a in list(p.attachments):
                db.delete(a)
            db.flush()
        if not dry_run:
            have_names = {a.filename for a in p.attachments}
            for im in rec.get("images") or []:
                if im["filename"] in have_names:
                    continue
                try:
                    blob = zf.read(f"images/{rec.get('id')}/{im['filename']}")
                except KeyError:
                    s["warnings"].append(f"image missing in zip: {im['filename']}")
                    continue
                a = store_attachment(db, p.id, im["filename"], blob, im.get("content_type"))
                if im.get("kind"):
                    a.kind = im["kind"]
                s["images"] += 1
            db.flush()
            _refresh_primary(db, p)

        # stock (only for newly created parts, to avoid double-counting)
        if existing is None:
            for st in rec.get("stock") or []:
                if st.get("qty"):
                    db.add(StockEntry(
                        part_id=p.id, location_id=_resolve_location(db, st["location"], lcache),
                        delta=int(st["qty"]), kind="add", note="backup import"))

        # design notes (only when creating, or on replace)
        if existing is None or mode == "replace":
            for dn in rec.get("design_notes") or []:
                note = DesignNote(part_id=p.id, title=dn.get("title") or "note",
                                  condition=dn.get("condition"), body=dn.get("body"))
                db.add(note)
                db.flush()
                for i, lk in enumerate(dn.get("links") or []):
                    lmpn = lk.get("mpn")
                    lpid = id_by_mpn.get((lmpn or "").lower()) if lmpn else None
                    note.links.append(DesignNoteLink(
                        part_id=lpid, mpn=None if lpid else lmpn,
                        role=lk.get("role"), value_hint=lk.get("value_hint"),
                        qty=lk.get("qty") or 1, sort_order=i))
                s["design_notes"] += 1

    # second pass: replacement links now that all parts exist
    for part_id, rb_mpn in pending_replaced_by:
        target = id_by_mpn.get(rb_mpn.lower()) or db.scalar(
            select(Part.id).where(func.lower(Part.mpn) == rb_mpn.lower()))
        if target:
            pp = db.get(Part, part_id)
            if pp:
                pp.replaced_by_id = target

    _restore_customers_and_quotes(db, zf, mode, s)

    s["categories_created"] = ccache.get("_created_cats", 0)
    s["locations_created"] = lcache.get("_created_locs", 0)
    s["mode"] = mode
    s["dry_run"] = dry_run
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return s
