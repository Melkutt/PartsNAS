"""Part CRUD + list/filter + scanner lookup.

`GET  /api/parts`                list; filters: q, category_id (+descendants),
                                 location_id, tag, mount, low_stock, limit, offset
`GET  /api/parts/ids`            just the ids matching the same filters (for
                                 "select all matching" in the bulk bar)
`GET  /api/parts/lookup?code=`   exact match on id / mpn / name — for the scanner
`GET  /api/parts/{id}`           full record + stock-by-location + category path
`POST /api/parts`                create
`PATCH /api/parts/{id}`          update
`DELETE /api/parts/{id}`         delete (stock ledger rows cascade)
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..bommatch import parse_component_value, part_value_number, same_value
from ..dupes import duplicate_counts, duplicate_ids, norm_mpn, parts_with_mpn
from ..models import Category, Part, StockEntry, Tag
from ..partschema import fields_for, part_class_schema
from ..kicadrules import auto_footprint
from ..services import (
    category_class_map,
    category_path,
    category_path_map,
    descendant_category_ids,
    location_breakdown,
    location_breakdown_bulk,
    on_hand_map,
    resolve_part_class,
    unit_cost_map,
)

router = APIRouter(prefix="/api/parts", tags=["parts"])

_KEY_RE = re.compile(r"^[a-z0-9_]+$")


class PartIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mpn: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    category_id: int | None = None
    mount: str | None = None
    footprint_raw: str | None = None
    kicad_symbol: str | None = None
    kicad_footprint: str | None = None
    kicad_footprint_alts: str | None = None
    datasheet_url: str | None = None
    min_stock: int = 0
    notes: str | None = None
    attributes: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class PartPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    mpn: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    category_id: int | None = None
    set_category: bool = False
    mount: str | None = None
    footprint_raw: str | None = None
    kicad_symbol: str | None = None
    kicad_footprint: str | None = None
    kicad_footprint_alts: str | None = None
    datasheet_url: str | None = None
    min_stock: int | None = None
    order_qty: int | None = Field(default=None, ge=1)  # null clears it
    notes: str | None = None
    design_doc: str | None = None
    attributes: dict | None = None
    tags: list[str] | None = None
    discontinued: bool | None = None
    replaced_by_id: str | None = None
    set_replaced_by: bool = False
    replacement_mpn: str | None = None
    replacement_sku: str | None = None
    replacement_source: str | None = None


@dataclass
class PartFilter:
    q: str | None = None
    category_id: int | None = None
    with_subcats: bool = True
    location_ids: list[int] = field(default_factory=list)
    mounts: list[str] = field(default_factory=list)
    footprints: list[str] = field(default_factory=list)
    manufacturers: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    in_stock: str | None = None  # "yes" | "no"
    datasheet: str | None = None  # "yes" | "no" - has a datasheet URL or not
    attrs: list[str] = field(default_factory=list)  # "key:value"
    low_stock: bool = False
    no_category: bool = False
    duplicates: bool = False  # only parts that share their MPN with another part
    value_eq: str | None = None  # only parts whose component value equals this ("1u" = 1uF = 1000nF)

    def attr_groups(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for raw in self.attrs:
            if ":" not in raw:
                continue
            k, v = raw.split(":", 1)
            if _KEY_RE.match(k):
                groups.setdefault(k, []).append(v)
        return groups


def _query(db: Session, f: PartFilter, *, exclude: str | None = None):
    """Ids matching the filter. `exclude` drops one dimension so a facet group
    doesn't shrink its own counts."""
    stmt = select(Part.id)
    if f.q:
        like = f"%{f.q.strip()}%"
        stmt = stmt.where(
            or_(Part.name.ilike(like), Part.mpn.ilike(like), Part.description.ilike(like))
        )
    if f.category_id is not None:
        ids = descendant_category_ids(db, f.category_id) if f.with_subcats else {f.category_id}
        stmt = stmt.where(Part.category_id.in_(ids))
    if f.no_category:
        unsorted = db.scalar(select(Category.id).where(Category.is_unsorted.is_(True)))
        stmt = stmt.where(or_(Part.category_id.is_(None), Part.category_id == unsorted))
    if f.mounts and exclude != "mount":
        # "" is the Unknown/unset bucket from the facet - IN doesn't match
        # NULL, so it needs its own OR'd condition
        real = [m for m in f.mounts if m]
        conds = []
        if real:
            conds.append(Part.mount.in_(real))
        if "" in f.mounts:
            conds.append(Part.mount.is_(None))
        stmt = stmt.where(or_(*conds))
    if f.footprints and exclude != "footprint":
        # "" = the Unknown bucket: parts with no footprint (NULL or blank)
        real = [x for x in f.footprints if x]
        conds = []
        if real:
            conds.append(Part.footprint_raw.in_(real))
        if "" in f.footprints:
            conds.append(or_(Part.footprint_raw.is_(None), func.trim(Part.footprint_raw) == ""))
        stmt = stmt.where(or_(*conds))
    if f.datasheet and exclude != "datasheet":
        has = func.length(func.trim(func.coalesce(Part.datasheet_url, ""))) > 0
        stmt = stmt.where(has if f.datasheet == "yes" else ~has)
    if f.manufacturers and exclude != "manufacturer":
        stmt = stmt.where(Part.manufacturer.in_(f.manufacturers))
    if f.tags and exclude != "tags":
        for t in f.tags:
            stmt = stmt.where(Part.tags.any(Tag.name == t))
    if f.location_ids and exclude != "location":
        sub = (
            select(StockEntry.part_id)
            .where(StockEntry.location_id.in_(f.location_ids))
            .group_by(StockEntry.part_id)
            .having(func.coalesce(func.sum(StockEntry.delta), 0) > 0)
        )
        stmt = stmt.where(Part.id.in_(sub))
    if f.in_stock and exclude != "in_stock":
        sub = (
            select(StockEntry.part_id)
            .group_by(StockEntry.part_id)
            .having(func.coalesce(func.sum(StockEntry.delta), 0) > 0)
        )
        stmt = stmt.where(Part.id.in_(sub) if f.in_stock == "yes" else Part.id.not_in(sub))
    for key, values in f.attr_groups().items():
        if exclude == f"attr:{key}":
            continue
        col = func.json_extract(Part.attributes, f'$."{key}"')
        stmt = stmt.where(or_(*[col == v for v in values]))
    return stmt


def _matching_ids(db: Session, f: PartFilter) -> list[str]:
    ids = list(db.scalars(_query(db, f)).all())
    if f.low_stock:
        onhand = on_hand_map(db, ids)
        mins = dict(db.execute(select(Part.id, Part.min_stock).where(Part.id.in_(ids))).all())
        ids = [i for i in ids if mins.get(i, 0) > 0 and onhand.get(i, 0) <= mins.get(i, 0)]
    if f.duplicates:
        dup = duplicate_ids(db)
        ids = [i for i in ids if i in dup]
    target = parse_component_value(f.value_eq) if f.value_eq else None
    if target is not None and ids:
        # by NUMBER, not by text: "1u" must not find "100nF" just because its description says "0.1uF"
        rows = db.execute(select(Part.id, Part.name, Part.attributes).where(Part.id.in_(ids))).all()
        ids = [pid for pid, name, attrs in rows if same_value(target, part_value_number(name, attrs))]
    elif f.value_eq and ids:
        # not a number ("TestPoint_2Pole", "USB4085-GF-A", "SMA"): match the text in the name, MPN or value,
        # rather than quietly not filtering at all while the list claims it is filtered
        needle = f.value_eq.strip().lower()
        rows = db.execute(select(Part.id, Part.name, Part.mpn, Part.attributes).where(Part.id.in_(ids))).all()
        ids = [pid for pid, name, mpn, attrs in rows
               if needle in (name or "").lower() or needle in (mpn or "").lower()
               or needle in str((attrs or {}).get("value", "")).lower()]
    return ids


def _filter_params(
    q: str | None = None,
    category_id: int | None = None,
    with_subcats: bool = True,
    location_id: list[int] = Query(default=[]),
    mount: list[str] = Query(default=[]),
    footprint: list[str] = Query(default=[]),
    manufacturer: list[str] = Query(default=[]),
    tag: list[str] = Query(default=[]),
    in_stock: str | None = None,
    datasheet: str | None = None,
    attr: list[str] = Query(default=[]),
    low_stock: bool = False,
    no_category: bool = False,
    duplicates: bool = False,
    value_eq: str | None = None,
) -> PartFilter:
    return PartFilter(
        q=q, category_id=category_id, with_subcats=with_subcats,
        location_ids=location_id, mounts=mount, footprints=footprint,
        manufacturers=manufacturer, tags=tag, in_stock=in_stock, datasheet=datasheet, attrs=attr,
        low_stock=low_stock, no_category=no_category, duplicates=duplicates, value_eq=value_eq,
    )


@router.get("")
def list_parts(
    db: Session = Depends(get_db),
    f: PartFilter = Depends(_filter_params),
    limit: int = Query(200, le=2000),
    offset: int = 0,
    order: str = "name",
):
    ids = _matching_ids(db, f)
    onhand = on_hand_map(db, ids)
    total = len(ids)
    rows = db.scalars(select(Part).where(Part.id.in_(ids))).all() if ids else []
    paths = category_path_map(db)
    locs = location_breakdown_bulk(db, ids)
    dups = duplicate_counts(db)
    costs = unit_cost_map(db, ids)
    out = [
        {
            "id": p.id,
            "name": p.name,
            "mpn": p.mpn,
            "manufacturer": p.manufacturer,
            "category_id": p.category_id,
            "category": paths.get(p.category_id, ""),
            "mount": p.mount,
            "footprint": p.footprint_raw,
            "min_stock": p.min_stock,
            "on_hand": onhand.get(p.id, 0),
            "locations": locs.get(p.id, []),
            "tags": [t.name for t in p.tags],
            "image_path": p.image_path,
            "datasheet_url": p.datasheet_url,
            "discontinued": p.discontinued,
            "dup": dups.get(p.id, 0),  # other parts with the same MPN
            "unit_price": costs[p.id][0] if p.id in costs else None,   # ex VAT, as a quote would price it
            "currency": costs[p.id][1] if p.id in costs else None,
            "replacement": (
                p.replaced_by.name if p.replaced_by else (p.replacement_mpn or None)
            ),
        }
        for p in rows
    ]
    key = (lambda r: r["on_hand"]) if order == "stock" else (lambda r: (r["name"] or "").lower())
    out.sort(key=key, reverse=(order == "stock"))
    return {"total": total, "count": len(out), "items": out[offset : offset + limit]}


@router.get("/ids")
def list_ids(db: Session = Depends(get_db), f: PartFilter = Depends(_filter_params)):
    return {"ids": _matching_ids(db, f)}


@router.get("/facets")
def facets(db: Session = Depends(get_db), f: PartFilter = Depends(_filter_params)):
    """Available filter values + counts for the current selection. Each group is
    counted with every *other* active filter applied but not its own, so options
    stay meaningful while multi-selecting."""
    cat_class = category_class_map(db)
    schema = part_class_schema()

    active_attrs = f.attr_groups()
    _sets: dict = {}

    def parts_for(exclude: str | None):
        # An attribute facet only drops its OWN filter, so for every attribute that
        # isn't being filtered the result is the same set as "no exclusion". There
        # are hundreds of attribute keys, and each used to re-run the query and
        # reload every Part row (~3 s on 330 parts); compute each distinct set once.
        if exclude and exclude.startswith("attr:") and exclude[5:] not in active_attrs:
            exclude = None
        if exclude not in _sets:
            ids = list(db.scalars(_query(db, f, exclude=exclude)).all())
            _sets[exclude] = db.scalars(select(Part).where(Part.id.in_(ids))).all() if ids else []
        return _sets[exclude]

    def count(field_get, exclude, include_empty=False):
        c = Counter()
        empty = 0
        for p in parts_for(exclude):
            v = field_get(p)
            if v in (None, ""):
                empty += 1
            else:
                c[str(v)] += 1
        opts = [{"value": k, "count": n} for k, n in c.most_common()]
        # "" is the sentinel for "not set" - always last, not folded into the
        # count-order above, so it doesn't get lost among the real values
        if include_empty and empty:
            opts.append({"value": "", "count": empty})
        return opts

    result: dict = {
        "mount": count(lambda p: p.mount, "mount", include_empty=True),
        "footprint": count(lambda p: p.footprint_raw if (p.footprint_raw or "").strip() else None, "footprint", include_empty=True),
        "manufacturer": count(lambda p: p.manufacturer, "manufacturer"),
    }

    # location facet
    loc_parts = parts_for("location")
    loc_counts = location_breakdown_bulk(db, [p.id for p in loc_parts])
    lc = Counter()
    for rows in loc_counts.values():
        for r in rows:
            lc[r["location"]] += 1
    result["location"] = [{"value": k, "count": n, "id": None} for k, n in lc.most_common()]
    # attach ids where we can
    name_id = {r["location"]: r["location_id"] for rows in loc_counts.values() for r in rows}
    for opt in result["location"]:
        opt["id"] = name_id.get(opt["value"])

    # tags facet
    tag_parts = parts_for("tags")
    tc = Counter()
    for p in tag_parts:
        for t in p.tags:
            tc[t.name] += 1
    result["tags"] = [{"value": k, "count": n} for k, n in tc.most_common()]

    # in-stock facet
    isp = parts_for("in_stock")
    oh = on_hand_map(db, [p.id for p in isp])
    yes = sum(1 for p in isp if oh.get(p.id, 0) > 0)
    result["in_stock"] = [
        {"value": "yes", "count": yes},
        {"value": "no", "count": len(isp) - yes},
    ]

    # datasheet facet: is there a datasheet URL at all (finds the ones you forgot)
    dsp = parts_for("datasheet")
    has_ds = sum(1 for p in dsp if (p.datasheet_url or "").strip())
    result["datasheet"] = [
        {"value": "yes", "count": has_ds},
        {"value": "no", "count": len(dsp) - has_ds},
    ]

    # which classes are in play -> their parameter fields
    if f.category_id is not None:
        classes = {resolve_part_class(db, f.category_id)} - {None}
    else:
        classes = {cat_class.get(p.category_id) for p in parts_for(None)} - {None}
    attr_facets: dict = {}
    for cls in sorted(classes):  # a set's order changes per process; a shared key's label must not
        for fdef in schema.get(cls, {}).get("fields", []):
            key = fdef["key"]
            if key in attr_facets or not _KEY_RE.match(key) or fdef["type"] == "bool":
                continue
            opts = count(lambda p, k=key: (p.attributes or {}).get(k), f"attr:{key}")
            if opts:
                attr_facets[key] = {
                    "label": fdef["label"],
                    "unit": fdef.get("unit"),
                    "options": opts,
                }
    # every OTHER attribute key present in the data (e.g. copied from a lookup and
    # not mapped to a class field) becomes a filter too — nothing is unfilterable
    seen_keys: set[str] = set()
    for p in parts_for(None):
        seen_keys |= set((p.attributes or {}).keys())
    for key in sorted(seen_keys):
        if key in attr_facets or not _KEY_RE.match(key):
            continue
        opts = count(lambda p, k=key: (p.attributes or {}).get(k), f"attr:{key}")
        if opts:
            attr_facets[key] = {
                "label": key.replace("_", " "),
                "unit": None,
                "options": opts,
                "unmapped": True,
            }
    result["attributes"] = attr_facets
    return result


def _dup_row(db: Session, p: Part, paths: dict) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "mpn": p.mpn,
        "manufacturer": p.manufacturer,
        "category": paths.get(p.category_id, ""),
        "on_hand": on_hand_map(db, [p.id]).get(p.id, 0),
    }


@router.get("/check-mpn")
def check_mpn(mpn: str, exclude: str | None = None, db: Session = Depends(get_db)):
    """Parts that already carry this MPN (punctuation / case ignored) - for the New part
    form and MPN edits, so a part that was forgotten about gets noticed. Only reports."""
    paths = category_path_map(db)
    return {"matches": [_dup_row(db, p, paths) for p in parts_with_mpn(db, mpn, exclude=exclude)]}


@router.get("/duplicates")
def duplicates(db: Session = Depends(get_db)):
    """Every group of parts that share an MPN."""
    paths = category_path_map(db)
    groups: dict[str, list[Part]] = {}
    for p in db.scalars(select(Part).order_by(Part.name)).all():
        n = norm_mpn(p.mpn)
        if n:
            groups.setdefault(n, []).append(p)
    out = [
        {"mpn": ps[0].mpn, "parts": [_dup_row(db, p, paths) for p in ps]}
        for ps in groups.values() if len(ps) > 1
    ]
    out.sort(key=lambda g: (g["mpn"] or "").lower())
    return {"count": len(out), "groups": out}


@router.get("/lookup")
def lookup(code: str, db: Session = Depends(get_db)):
    """Scanner entry point: try id, then exact MPN, then exact name."""
    code = code.strip()
    if not code:
        raise HTTPException(400, "empty code")
    p = db.get(Part, code)
    if p is None:
        p = db.scalar(select(Part).where(func.lower(Part.mpn) == code.lower()))
    if p is None:
        p = db.scalar(select(Part).where(func.lower(Part.name) == code.lower()))
    if p is None:
        raise HTTPException(404, f"No part matches {code!r}")
    return {
        "id": p.id,
        "name": p.name,
        "mpn": p.mpn,
        "on_hand": on_hand_map(db, [p.id]).get(p.id, 0),
    }


@router.get("/{part_id}")
def get_part(part_id: str, db: Session = Depends(get_db)):
    p = db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "part not found")
    from ..api.images import _row as image_row
    from ..api.suppliers import _link_row

    return {
        "id": p.id,
        "name": p.name,
        "mpn": p.mpn,
        "manufacturer": p.manufacturer,
        "description": p.description,
        "category_id": p.category_id,
        "category": category_path(db, p.category_id),
        "part_class": resolve_part_class(db, p.category_id),
        "mount": p.mount,
        "footprint_raw": p.footprint_raw,
        "kicad_symbol": p.kicad_symbol,
        "kicad_footprint": p.kicad_footprint,
        "kicad_footprint_alts": p.kicad_footprint_alts,
        "datasheet_url": p.datasheet_url,
        "image_path": p.image_path,
        "min_stock": p.min_stock,
        "notes": p.notes,
        "design_doc": p.design_doc,
        "attributes": p.attributes or {},
        "tags": [t.name for t in p.tags],
        "on_hand": on_hand_map(db, [p.id]).get(p.id, 0),
        "stock": location_breakdown(db, p.id),
        "suppliers": [_link_row(x) for x in p.suppliers],
        "images": [image_row(a) for a in p.attachments],
        "design_note_count": len(p.design_notes),
        "on_order": (
            {"qty": p.on_order_qty, "at": p.on_order_at.isoformat() if p.on_order_at else None, "ref": p.on_order_ref}
            if p.on_order_qty else None
        ),
        "same_mpn": [_dup_row(db, x, category_path_map(db)) for x in parts_with_mpn(db, p.mpn, exclude=p.id)],
        "discontinued": p.discontinued,
        "replaced_by": (
            {
                "id": p.replaced_by.id,
                "name": p.replaced_by.name,
                "mpn": p.replaced_by.mpn,
                "on_hand": on_hand_map(db, [p.replaced_by.id]).get(p.replaced_by.id, 0),
            }
            if p.replaced_by
            else None
        ),
        "replacement_mpn": p.replacement_mpn,
        "replacement_sku": p.replacement_sku,
        "replacement_source": p.replacement_source,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _resolve_tags(db: Session, names: list[str]) -> list[Tag]:
    out = []
    for raw in names:
        n = raw.strip()
        if not n:
            continue
        t = db.scalar(select(Tag).where(Tag.name == n))
        if t is None:
            t = Tag(name=n)
            db.add(t)
        out.append(t)
    return out


@router.post("", status_code=201)
def create_part(body: PartIn, db: Session = Depends(get_db)):
    p = Part(
        name=body.name,
        mpn=body.mpn,
        manufacturer=body.manufacturer,
        description=body.description,
        category_id=body.category_id,
        mount=body.mount,
        footprint_raw=body.footprint_raw,
        kicad_symbol=body.kicad_symbol,
        kicad_footprint=body.kicad_footprint,
        kicad_footprint_alts=body.kicad_footprint_alts,
        datasheet_url=body.datasheet_url,
        min_stock=body.min_stock,
        notes=body.notes,
        attributes=body.attributes,
    )
    p.tags = _resolve_tags(db, body.tags)
    auto_footprint(db, p)        # a KiCad footprint straight away, when a rule is certain of it
    db.add(p)
    db.commit()
    return {"id": p.id}


@router.patch("/{part_id}")
def patch_part(part_id: str, body: PartPatch, db: Session = Depends(get_db)):
    p = db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "part not found")
    data = body.model_dump(exclude_unset=True)
    data.pop("set_category", None)
    data.pop("set_replaced_by", None)
    if "tags" in data:
        p.tags = _resolve_tags(db, data.pop("tags") or [])
    if "category_id" in data or body.set_category:
        p.category_id = data.pop("category_id", None)
    if "replaced_by_id" in data or body.set_replaced_by:
        rid = data.pop("replaced_by_id", None)
        if rid == part_id:
            raise HTTPException(400, "a part cannot replace itself")
        p.replaced_by_id = rid
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/{part_id}")
def delete_part(part_id: str, db: Session = Depends(get_db)):
    p = db.get(Part, part_id)
    if p is None:
        raise HTTPException(404, "part not found")
    db.delete(p)
    db.commit()
    return {"ok": True}
