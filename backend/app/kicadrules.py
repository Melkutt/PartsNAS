"""Rules that turn a part's package text into a KiCad footprint (IC / transistor / diode packages).

A rule is `{"id", "when": {"case", "device", "raw"}, "scope"?, "footprint", "assumed"?}`. `when` holds regular
expressions (case-insensitive) that must ALL match: `case` is the supplier's *Package / Case*, `device` its
*Supplier Device Package*, `raw` the part's own Footprint text. `scope` is a word the category path must contain.
`assumed` marks a rule that only guesses the common variant (proposed unticked). The first rule that matches wins;
the user's own rules (Settings) come before the built-in ones in `seed/kicad_footprint_rules.json`.

Also here: turning a supplier's "8-SOIC" into the footprint text people write ("SOIC-8").
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from .core.kv import get_kv, set_kv

_SEED = Path(__file__).resolve().parent.parent.parent / "seed" / "kicad_footprint_rules.json"
_KEY = "kicad:footprint_rules"
_FIELDS = ("case", "device", "raw")


@lru_cache(maxsize=1)
def default_rules() -> list[dict]:
    try:
        return json.loads(_SEED.read_text(encoding="utf-8"))["rules"]
    except (OSError, ValueError, KeyError):
        return []


def user_rules(db: Session) -> list[dict]:
    return get_kv(db, _KEY, []) or []


def all_rules(db: Session) -> list[dict]:
    return [*user_rules(db), *default_rules()]


def validate_rule(rule: dict) -> dict:
    """A cleaned copy of a user rule, or ValueError saying what is wrong with it."""
    when = {k: str(v).strip() for k, v in (rule.get("when") or {}).items() if k in _FIELDS and str(v).strip()}
    if not when:
        raise ValueError("a rule needs at least one condition (case, device or raw)")
    for k, pat in when.items():
        try:
            re.compile(pat)
        except re.error as e:
            raise ValueError(f"'{pat}' is not a valid pattern: {e}") from e
    fp = str(rule.get("footprint") or "").strip()
    if ":" not in fp:
        raise ValueError("the footprint must include its library, like Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
    out: dict = {"id": str(rule.get("id") or "").strip() or "my-rule", "when": when, "footprint": fp}
    if str(rule.get("scope") or "").strip():
        out["scope"] = str(rule["scope"]).strip()
    if rule.get("assumed"):
        out["assumed"] = True
    return out


def save_user_rules(db: Session, rules: list[dict]) -> list[dict]:
    clean = [validate_rule(r) for r in rules]
    set_kv(db, _KEY, clean)
    return clean


def _norm(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def package_texts(attributes: dict | None, footprint_raw: str | None) -> dict[str, str]:
    """{"case", "device", "raw"} for a part: the supplier's package attributes (whatever way the key is written
    - `packagecase`, "Package / Case") and the part's own footprint text."""
    out = {"case": "", "device": "", "raw": (footprint_raw or "").strip()}
    for k, v in (attributes or {}).items():
        if not isinstance(v, str):
            continue
        nk = _norm(k)
        if nk in ("packagecase", "casepackage"):
            out["case"] = v.strip()
        elif nk == "supplierdevicepackage":
            out["device"] = v.strip()
    return out


def match_rule(rules: list[dict], texts: dict[str, str], category_path: str | None = None) -> dict | None:
    """The first rule whose conditions all match: {"rule": id, "footprint", "assumed"}; None when none does."""
    path = (category_path or "").lower()
    for r in rules:
        scope = (r.get("scope") or "").lower()
        if scope and scope not in path:
            continue
        when = r.get("when") or {}
        if not when:
            continue
        try:
            ok = all(texts.get(k) and re.search(pat, texts[k], re.I) for k, pat in when.items())
        except re.error:
            continue
        if ok:
            return {"rule": r.get("id") or "", "footprint": r["footprint"], "assumed": bool(r.get("assumed"))}
    return None


# ---- "8-SOIC" -> "SOIC-8" ------------------------------------------------------------------

_LEAD = re.compile(r"^(\d+)-([A-Za-z][A-Za-z0-9]*)(.*)$")
_FAMILY_ALIAS = {"PDIP": "DIP", "SO": "SOIC"}
_KEEP = {"SMD", "SIP"}       # "8-SMD" / "4-SIP" are not package families to reorder


def normalize_package(text: str | None) -> str | None:
    """A supplier's package name as people write it: "8-SOIC" -> "SOIC-8", "44-TQFP (10x10)" -> "TQFP-44",
    "SOT-23-5" stays. Text in brackets and everything after a comma is dropped. None when there is nothing to use."""
    if not text:
        return None
    t = re.sub(r"\([^)]*\)", "", str(text)).split(",")[0].strip()
    if not t:
        return None
    m = _LEAD.match(t)
    if not m:
        return t
    n, fam, rest = m.groups()
    if fam.upper() in _KEEP:
        return t
    fam = _FAMILY_ALIAS.get(fam.upper(), fam.upper())
    return f"{fam}-{n}{rest}".strip()


def footprint_text_from_lookup(attributes: dict | None) -> str | None:
    """The Footprint text a lookup result suggests: the supplier device package, else the package / case."""
    texts = package_texts(attributes, None)
    return normalize_package(texts["device"]) or normalize_package(texts["case"])


_PREFER_KEY = "kicad:prefer"


def get_prefer(db: Session) -> str:
    """Which pads a standard passive gets as its default footprint: "hand" (hand-solder, the default) or "standard"."""
    return "standard" if get_kv(db, _PREFER_KEY, "hand") == "standard" else "hand"


def set_prefer(db: Session, value: str) -> str:
    value = "standard" if value == "standard" else "hand"
    set_kv(db, _PREFER_KEY, value)
    return value


def auto_names(db: Session, part, extra: dict | None = None) -> bool:
    """Give a new part its KiCad names when they are certain, filling only what is EMPTY. Used when a part is
    created and when a lookup fills in its package.

    * a standard SMD resistor, ceramic capacitor, inductor or LED (category + package size): symbol
      (Device:R, C, L, LED), default footprint (hand-solder or standard pads, per the KiCad… setting) and the
      other kind as an alternative;
    * anything else: the footprint from a certain (not `assumed`) footprint rule.
    Transistors and ICs get no symbol: their pins are numbered differently from part to part (Q_NPN_BEC / _BCE /
    _CBE …), so a guess would be a silent wiring mistake."""
    from .kicadlib import suggest_names
    from .services import category_path

    path = category_path(db, part.category_id)
    changed = False
    s = suggest_names(path, part.footprint_raw, get_prefer(db))
    if s:
        if not (part.kicad_symbol or "").strip():
            part.kicad_symbol, changed = s["symbol"], True
        if not (part.kicad_footprint or "").strip():
            part.kicad_footprint, changed = s["footprint"], True
            if not (part.kicad_footprint_alts or "").strip() and s["alts"]:
                part.kicad_footprint_alts = "\n".join(s["alts"])
        return changed
    if (part.kicad_footprint or "").strip():
        return False
    texts = package_texts({**(extra or {}), **(part.attributes or {})}, part.footprint_raw)
    hit = match_rule(all_rules(db), texts, path)
    if hit and not hit["assumed"]:
        part.kicad_footprint = hit["footprint"]
        return True
    return False
