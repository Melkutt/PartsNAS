"""BOM-line -> Part matching for the BOM importer.

Priority, per line:
  1. exact MPN (if the BOM has an MPN column and it matches a part exactly)
  2. a remembered Value+Footprint rule (confirmed once before, see BomMatchRule)
  3. best-scoring candidate among parts sharing the (canonical) footprint,
     scored by how well the value also matches
  4. nothing

Only 1 and 2 are ever auto-applied without the user ticking anything — a
"candidate" is always just a suggestion with a confidence score, never
silently treated as correct. Confirming one (via the import review UI)
creates a rule for #2, keyed on the exact normalised value, so a
placeholder part with no value yet (or a different value/voltage) never
inherits it.
"""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import BomMatchRule, FootprintAlias, Part


def norm_value(v: str | None) -> str:
    return re.sub(r"\s+", "", (v or "")).strip().lower()


# A handful of common KiCad footprint-library naming conventions, matched
# against the part after `Library:` is stripped, on top of whatever's in
# FootprintAlias (which already covers our own facet/seed vocabulary).
_CANON_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b0201\b", re.I), "0201"),
    (re.compile(r"\b0402\b", re.I), "0402"),
    (re.compile(r"\b0603\b", re.I), "0603"),
    (re.compile(r"\b0805\b", re.I), "0805"),
    (re.compile(r"\b1206\b", re.I), "1206"),
    (re.compile(r"\b1210\b", re.I), "1210"),
    (re.compile(r"\b1812\b", re.I), "1812"),
    (re.compile(r"\b2010\b", re.I), "2010"),
    (re.compile(r"\b2220\b", re.I), "2220"),
    (re.compile(r"\b2512\b", re.I), "2512"),
    (re.compile(r"sot-?23-?5|sot-?323", re.I), "SOT-23-5"),
    (re.compile(r"sot-?23-?3|\bsot-?23\b(?!-)", re.I), "SOT-23-3"),
    (re.compile(r"sot-?89", re.I), "SOT-89"),
    (re.compile(r"soic-?8\b", re.I), "SOIC-8"),
    (re.compile(r"soic-?14\b", re.I), "SOIC-14"),
    (re.compile(r"soic-?16\b", re.I), "SOIC-16"),
    (re.compile(r"tssop-?(\d+)", re.I), "TSSOP"),
    (re.compile(r"qfn-?(\d+)|dfn-?(\d+)", re.I), "QFN"),
    (re.compile(r"to-?220", re.I), "TO-220"),
    (re.compile(r"to-?92", re.I), "TO-92"),
    (re.compile(r"to-?252|d-?pak", re.I), "TO-252"),
    (re.compile(r"sod-?123", re.I), "SOD-123"),
    (re.compile(r"sod-?323", re.I), "SOD-323"),
]


def canonical_footprint(db: Session, raw: str | None) -> str:
    """Best-effort canonical bucket for a raw footprint string, whether it
    came from KiCad ("Resistor_SMD:R_0603_1608Metric") or our own data
    ("0603 (1608 Metric)"). Falls back to the normalised raw string when
    nothing matches, so two identical-but-unrecognised footprints still
    bucket together even if we don't have a nice name for them."""
    fp = (raw or "").strip()
    if ":" in fp:
        fp = fp.split(":", 1)[1]
    fp_low = fp.lower()
    for rx, canon in _CANON_PATTERNS:
        if rx.search(fp_low):
            return canon
    for fa in db.scalars(select(FootprintAlias)).all():
        candidates = [fa.canonical, *(fa.aliases or [])]
        if fa.kicad_footprint:
            candidates.append(fa.kicad_footprint)
        for alias in candidates:
            if alias and alias.lower() in fp_low:
                return fa.canonical
    return re.sub(r"\s+", " ", fp_low).strip()


class Matcher:
    """Loads parts/rules once, then scores many BOM lines cheaply."""

    def __init__(self, db: Session):
        self.db = db
        self._parts = db.scalars(select(Part)).all()
        self._by_footprint: dict[str, list[Part]] = {}
        for p in self._parts:
            if not p.footprint_raw:
                continue
            self._by_footprint.setdefault(canonical_footprint(db, p.footprint_raw), []).append(p)

    def match(self, *, mpn: str | None, value: str | None, footprint: str | None) -> dict:
        mpn = (mpn or "").strip()
        if mpn:
            p = self.db.scalar(select(Part).where(func.lower(Part.mpn) == mpn.lower()))
            if p:
                return {"kind": "mpn", "part_id": p.id, "part_name": p.name, "score": 100, "candidates": []}

        vnorm = norm_value(value)
        fnorm = canonical_footprint(self.db, footprint)
        if vnorm and fnorm:
            rule = self.db.scalar(
                select(BomMatchRule).where(
                    BomMatchRule.value_norm == vnorm, BomMatchRule.footprint_norm == fnorm
                )
            )
            if rule and rule.part:
                return {
                    "kind": "remembered", "part_id": rule.part_id, "part_name": rule.part.name,
                    "score": 100, "candidates": [],
                }

        pool = self._by_footprint.get(fnorm, []) if fnorm else []
        scored = []
        for p in pool:
            score = 55
            # a part's "value" (18pF, 10k, ...) usually lives in a class
            # attribute (capacitance, resistance, ...), not p.name — which,
            # for parts imported from a supplier, is often just the MPN — so
            # check every string attribute, not only the name.
            candidates_v = [norm_value(p.name)] + [
                norm_value(v) for v in (p.attributes or {}).values() if isinstance(v, str)
            ]
            if vnorm and vnorm in candidates_v:
                score += 40
            # a short substring ("1", "50", "100" — a tolerance or voltage
            # attribute, say) can trivially appear inside another short
            # string by coincidence, so only credit a *partial* match once
            # both sides are long enough for that to actually mean something
            elif vnorm and len(vnorm) >= 3 and any(
                len(pv) >= 3 and (vnorm in pv or pv in vnorm) for pv in candidates_v
            ):
                score += 20
            scored.append((score, p))
        scored.sort(key=lambda x: -x[0])
        if not scored:
            return {"kind": "none", "part_id": None, "part_name": None, "score": 0, "candidates": []}
        top_score, top = scored[0]
        return {
            "kind": "candidate",
            "part_id": top.id,
            "part_name": top.name,
            "score": min(top_score, 95),  # a guess never claims to be certain
            "candidates": [
                {"id": p.id, "name": p.name, "score": min(s, 95)} for s, p in scored[:5]
            ],
        }


def remember(db: Session, *, value: str | None, footprint: str | None, part_id: str) -> None:
    vnorm, fnorm = norm_value(value), canonical_footprint(db, footprint)
    if not vnorm or not fnorm:
        return  # nothing stable enough to key a rule on
    rule = db.scalar(
        select(BomMatchRule).where(
            BomMatchRule.value_norm == vnorm, BomMatchRule.footprint_norm == fnorm
        )
    )
    if rule:
        rule.part_id = part_id
    else:
        db.add(BomMatchRule(
            value_norm=vnorm, footprint_norm=fnorm,
            value_raw=(value or "").strip(), footprint_raw=(footprint or "").strip(),
            part_id=part_id,
        ))
