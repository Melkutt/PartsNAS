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
from .services import category_path_map


def norm_value(v: str | None) -> str:
    return re.sub(r"\s+", "", (v or "")).strip().lower()


# Reference-designator prefix -> what a candidate's category path must
# mention. Sharing a footprint is not enough — a resistor and a capacitor
# both come in 0603, but they are never interchangeable, so a "C1" line
# should never even be offered a resistor as a candidate. Only prefixes
# with an unambiguous, universally-taught meaning are listed; anything
# else (a house prefix, "U" which covers every kind of IC, ...) is left
# unfiltered rather than guessed at.
_REFDES_CATEGORY: dict[str, tuple[str, ...]] = {
    "R": ("resistor",),
    "RN": ("resistor",),
    "RV": ("varistor",),
    "RT": ("thermistor",),
    "C": ("capacitor",),
    "L": ("inductor",),
    "FB": ("ferrite", "inductor"),
    "D": ("diode",),
    "LED": ("led", "diode"),
    "Q": ("transistor", "mosfet", "fet"),
    "F": ("fuse",),
    "Y": ("crystal", "oscillator"),
    "X": ("crystal", "oscillator"),
    "K": ("relay",),
    "SW": ("switch",),
    "S": ("switch",),
    "J": ("connector",),
    "P": ("connector",),
    "BT": ("battery",),
    "T": ("transformer",),
}


def _refdes_prefix(refdes: str | None) -> str | None:
    first = (refdes or "").split()[0] if (refdes or "").split() else None
    if not first:
        return None
    m = re.match(r"^([A-Za-z]+)\d", first)
    return m.group(1).upper() if m else None


# A part's real "value" (18pF, 10k, ...) usually lives in a class attribute
# named after the class (capacitance, resistance, ...), not a fixed "value"
# key, since these come from a supplier lookup's own field names. Shown to
# the user alongside a candidate so they have more than a bare MPN to judge
# a guess by — footprint matching a category means nothing on its own.
_VALUE_KEYS = ("capacitance", "resistance", "inductance", "value")
_TOL_KEYS = ("tolerance",)
_VOLT_KEYS = ("voltagerated", "voltage_rated", "ratedvoltage", "voltage")
# BJT/FET polarity — worth surfacing on its own since it's the one thing
# that decides whether a transistor is interchangeable at all, and it can
# sit under any of several supplier field names (or none — description
# text only), so this is a "does this string say so" search, not a fixed
# key lookup.
_TYPE_MARKERS = ("n-channel", "p-channel", "npn", "pnp")


def _pick_attr(attrs: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        for ak, av in attrs.items():
            if k in ak.lower() and isinstance(av, str) and av.strip():
                return av.strip()
    return None


def _pick_type_marker(attrs: dict) -> str | None:
    for av in attrs.values():
        if not isinstance(av, str):
            continue
        low = av.lower()
        if any(marker in low for marker in _TYPE_MARKERS):
            return av.strip()
    return None


def part_summary(p: Part) -> str:
    """'10k, 0603, ±5%, 50V'-style summary — enough to judge a footprint+
    value guess without opening the part. A transistor's N/P-channel or
    NPN/PNP marker, if any, leads — it's the one thing that decides
    whether it's interchangeable at all — and the generic "value" lookup is
    skipped for it, since _VALUE_KEYS' "capacitance" substring would
    otherwise just as happily grab an unrelated Ciss parametric spec."""
    attrs = p.attributes or {}
    type_marker = _pick_type_marker(attrs)
    bits = [b for b in (
        type_marker,
        None if type_marker else _pick_attr(attrs, _VALUE_KEYS),
        p.footprint_raw,
        _pick_attr(attrs, _TOL_KEYS),
        _pick_attr(attrs, _VOLT_KEYS),
    ) if b]
    return ", ".join(bits) if bits else (p.mpn or p.name)


# ---- numeric value proximity (R/L/C only — a component value is always a
# single number times an SI/RKM prefix, so "how close" has an actual
# numeric answer, unlike an MPN or a connector series name) --------------
_SI_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3,
            "k": 1e3, "K": 1e3, "M": 1e6, "g": 1e9, "G": 1e9}


def parse_component_value(raw: str | None) -> float | None:
    """"100nF" -> 1e-7, "2k2" -> 2200.0, "4R7" -> 4.7, "1000" -> 1000.0,
    None if it doesn't look like a single R/L/C-style number at all."""
    s = (raw or "").strip().replace(",", ".")
    if not s:
        return None
    s = re.sub(r"(ohms?|Ω|farads?|henr(?:y|ies)|[FH])\s*$", "", s, flags=re.I).strip()
    # RKM embedded-decimal: 2k2, 4n7, 1M5 (the SI letter stands in for the
    # decimal point)
    m = re.match(r"^(\d+)\s*([pnuµmkKMgG])\s*(\d+)$", s)
    if m:
        whole, letter, frac = m.groups()
        return float(f"{whole}.{frac}") * _SI_MULT[letter]
    # same idea with a bare "R" (ohms, no scale): 4R7, 100R
    m = re.match(r"^(\d+)\s*[Rr]\s*(\d+)?$", s)
    if m:
        whole, frac = m.groups()
        return float(f"{whole}.{frac}") if frac else float(whole)
    # plain "<number><optional SI letter>"
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([pnuµmkKMgG])?$", s)
    if m:
        num, letter = m.groups()
        return float(num) * _SI_MULT.get(letter, 1)
    return None


def part_value_number(name: str | None, attributes: dict | None) -> float | None:
    """The component value of a part as a number, or None. The `value` attribute is the source of
    truth ("1µF", "2k2"); failing that, a leading word of the name ("1n 100V X7R" -> 1n). Other
    attributes are never used: a voltage of "50" would otherwise read as a value of 50."""
    attrs = attributes or {}
    v = attrs.get("value")
    if isinstance(v, str):
        n = parse_component_value(v)
        if n is not None:
            return n
    for word in (name or "").split():
        n = parse_component_value(word)
        if n is not None:
            return n
        break  # only the first word: "Single 2-Input AND Gate" has no value, "2-Input" is not one
    return None


def same_value(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= 1e-6 * max(abs(a), abs(b), 1e-30)


def value_similarity(target: float, candidate: float) -> float:
    """1.0 = identical, falling off the further apart they are — a ratio
    of 2x (double or half) lands around 0.5, matching how a technician
    actually judges "close enough": 1k needing a stand-in is well served
    by 1k2, not by 1k5 and even less by 500R."""
    if target <= 0 or candidate <= 0:
        return 1.0 if target == candidate else 0.0
    ratio = max(target, candidate) / min(target, candidate)
    return max(0.0, 1 - (ratio - 1))


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
        self._cat_path = category_path_map(db)
        self._by_footprint: dict[str, list[Part]] = {}
        for p in self._parts:
            # a part is found under its footprint AND under the KiCad footprint you gave it - a part that
            # only has the KiCad footprint filled in used to be invisible to the matching
            buckets = {canonical_footprint(db, f) for f in (p.footprint_raw, p.kicad_footprint) if f and f.strip()}
            for b in buckets:
                self._by_footprint.setdefault(b, []).append(p)

    def _category_ok(self, p: Part, expect: tuple[str, ...] | None) -> bool:
        if not expect:
            return True  # no confident expectation (unknown/ambiguous prefix) -> don't filter
        path = self._cat_path.get(p.category_id, "").lower()
        return any(tok in path for tok in expect)

    def _suggest_category_id(self, expect: tuple[str, ...] | None) -> int | None:
        """The category to preselect when the user creates a brand-new part
        for this line — same refdes-prefix signal as _category_ok, but
        resolved to one concrete id instead of used as a filter. Tokens are
        tried in order (most specific first, e.g. "LED" tries "led" before
        the fallback "diode") and matched against a category's own name
        (not just anywhere in its path), preferring the shallowest node so
        e.g. "capacitor" lands on Capacitor itself, not some subtype."""
        if not expect:
            return None
        for tok in expect:
            best: tuple[int, int] | None = None
            for cid, path in self._cat_path.items():
                leaf = path.rsplit(" > ", 1)[-1].lower()
                if leaf == tok or leaf.startswith(tok):
                    depth = path.count(">")
                    if best is None or depth < best[1]:
                        best = (cid, depth)
            if best:
                return best[0]
        return None

    def match(self, *, mpn: str | None, value: str | None, footprint: str | None,
              refdes: str | None = None) -> dict:
        expect = _REFDES_CATEGORY.get(_refdes_prefix(refdes) or "")
        suggested_category_id = self._suggest_category_id(expect)

        mpn = (mpn or "").strip()
        if mpn:
            p = self.db.scalar(select(Part).where(func.lower(Part.mpn) == mpn.lower()))
            if p:
                return {"kind": "mpn", "part_id": p.id, "part_name": p.name,
                        "summary": part_summary(p), "score": 100, "candidates": [],
                        "suggested_category_id": suggested_category_id}

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
                    "summary": part_summary(rule.part), "score": 100, "candidates": [],
                    "suggested_category_id": suggested_category_id,
                }

        pool = [p for p in self._by_footprint.get(fnorm, []) if self._category_ok(p, expect)] if fnorm else []
        target_num = parse_component_value(value)
        scored = []
        for p in pool:
            # a category-consistent guess (refdes prefix said "resistor" and
            # this part actually lives under Resistor) starts more trusted
            # than a bare footprint-only guess (unknown/ambiguous prefix)
            score = 65 if expect else 50
            # a part's "value" (18pF, 10k, ...) usually lives in a class
            # attribute (capacitance, resistance, ...), not p.name — which,
            # for parts imported from a supplier, is often just the MPN — so
            # check every string attribute, not only the name.
            raw_values = [p.name] + [v for v in (p.attributes or {}).values() if isinstance(v, str)]
            candidates_v = [norm_value(v) for v in raw_values]

            cand_num = None
            if target_num is not None:
                cand_num = part_value_number(p.name, p.attributes)
                if cand_num is None:                      # nothing that says "value": look wider
                    for rv in raw_values:
                        n = parse_component_value(rv)
                        if n is not None:
                            cand_num = n
                            break

            if target_num is not None and cand_num is not None:
                # a real number on both sides — "how close" has an actual
                # answer (1k2 beats 1k5 beats 500R for a 1k target), so use
                # that instead of an all-or-nothing string match
                score += round(30 * value_similarity(target_num, cand_num))
            elif vnorm and vnorm in candidates_v:
                score += 30
            # a short substring ("1", "50", "100" — a tolerance or voltage
            # attribute, say) can trivially appear inside another short
            # string by coincidence, so only credit a *partial* match once
            # both sides are long enough for that to actually mean something
            elif vnorm and len(vnorm) >= 3 and any(
                len(pv) >= 3 and (vnorm in pv or pv in vnorm) for pv in candidates_v
            ):
                score += 15
            scored.append((score, p))
        scored.sort(key=lambda x: -x[0])
        if not scored:
            return {"kind": "none", "part_id": None, "part_name": None,
                    "summary": None, "score": 0, "candidates": [],
                    "suggested_category_id": suggested_category_id}
        top_score, top = scored[0]
        why = [f"package {fnorm}" if fnorm else "package"]
        if expect:
            why.append("type fits the reference designator")
        if target_num is not None and same_value(target_num, part_value_number(top.name, top.attributes)):
            why.append("same value")
        return {
            "why": why,
            "kind": "candidate",
            "part_id": top.id,
            "part_name": top.name,
            "summary": part_summary(top),
            "score": min(top_score, 95),  # a guess never claims to be certain
            "candidates": [
                {"id": p.id, "name": p.name, "summary": part_summary(p), "score": min(s, 95)}
                for s, p in scored[:5]
            ],
            "suggested_category_id": suggested_category_id,
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
