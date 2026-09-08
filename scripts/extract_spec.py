"""Generate the English seed/*.json from the (Swedish) source workbooks.

    python scripts/extract_spec.py "C:/Users/Melker/Desktop/komponentspec.xlsx" \
                                   "C:/Users/Melker/Downloads/partsbox.xlsx"

The second argument is optional; give it to (re)generate storage_locations.json.

Outputs, under seed/:
    categories.json          nested category tree (arbitrary depth), English
    footprint_aliases.json   canonical footprint name -> aliases + kicad hint
    part_classes.json        per-class field definitions for Part.attributes
    common_fields.json       the shared field list, for reference
    storage_locations.json   flat starter list from the PartsBox export

Swedish -> English is done via scripts/translations.py. Untranslated strings are
passed through and printed as `WARN: no translation for ...` so the map can grow.
The workbooks are development scaffolding only; the JSON under seed/ is the
maintained artifact.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from translations import (  # noqa: E402
    CATEGORY_COMMENT_EN,
    CATEGORY_EN,
    ENUM_VALUE_EN,
    FIELD_EN,
    LOCATION_EN,
)

CLASS_IDS = {
    "Resistor": "resistor",
    "Kondensator": "capacitor",
    "Induktor": "inductor",
    "Diod": "diode",
    "Transistor BJT": "transistor_bjt",
    "Transistor MOSFET": "transistor_mosfet",
    "IC – Integrerad krets": "ic",
    "IC - Integrerad krets": "ic",
    "Kristall & Oscillator": "crystal",
    "Kontakt & Connector": "connector",
    "Mekanisk": "mechanical",
}
CLASS_LABEL_EN = {
    "resistor": "Resistor",
    "capacitor": "Capacitor",
    "inductor": "Inductor",
    "diode": "Diode",
    "transistor_bjt": "Transistor (BJT)",
    "transistor_mosfet": "Transistor (MOSFET)",
    "ic": "IC – Integrated circuit",
    "crystal": "Crystal & Oscillator",
    "connector": "Connector",
    "mechanical": "Mechanical",
}
GROUP_EN = {
    "SMD passiv": "SMD passive",
    "SMD aktiv": "SMD active",
    "SMD IC": "SMD IC",
    "SMD diod": "SMD diode",
    "THT aktiv": "THT active",
    "THT IC": "THT IC",
    "THT diod": "THT diode",
    "THT passiv": "THT passive",
}

TYPE_MAP = {"TEXT": "text", "NUMMER": "number", "VAL": "enum", "BOOL": "bool", "DATUM": "date"}

_emoji = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u2190-\u21FF\u2300-\u23FF]"
)
_missing: set[str] = set()


def clean(s) -> str:
    if s is None:
        return ""
    return _emoji.sub("", str(s)).strip()


def tr(value: str, table: dict[str, str], *, what: str) -> str:
    v = value.strip()
    if v in table:
        return table[v]
    if v:
        _missing.add(f"{what}: {v!r}")
    return v


def _slug(s: str) -> str:
    s = s.lower().replace("å", "a").replace("ä", "a").replace("ö", "o")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "field"


# --- field sheets --------------------------------------------------------------
def is_attr_row(row) -> bool:
    return bool(clean(row[0])) and clean(row[3]).upper() in TYPE_MAP


def _enum_options(comment: str) -> list[str] | None:
    body = re.sub(r"^(t\.?ex\.?|ex\.?|dvs\.?)[:\s]*", "", comment.strip(), flags=re.I)
    if "." in body and "," not in body:
        return None
    parts = [p.strip(" .") for p in re.split(r"[,/]", body)]
    parts = [p for p in parts if p and len(p) <= 30 and " " not in p.strip().rstrip("²")]
    return parts if len(parts) >= 2 else None


def parse_field_sheet(ws) -> list[dict]:
    fields: list[dict] = []
    for row in ws.iter_rows(values_only=True):
        if not is_attr_row(row):
            continue
        label_sv, kicad, unit, typ, required, api_source, comment = (list(row) + [None] * 7)[:7]
        label_sv, kicad = clean(label_sv), clean(kicad)
        label = tr(label_sv, FIELD_EN, what="field") or kicad or label_sv
        entry = {
            "key": _slug(kicad or label),
            "label": label,
            "kicad_field": kicad or None,
            "unit": clean(unit) or None,
            "type": TYPE_MAP[clean(typ).upper()],
            "required": clean(required).upper().startswith("JA"),
            "api_source": clean(api_source) or None,
        }
        if entry["type"] == "enum" and clean(comment):
            opts = _enum_options(clean(comment))
            if opts:
                entry["options"] = [tr(o, ENUM_VALUE_EN, what="enum") for o in opts]
        fields.append(entry)
    return fields


# --- category tree -----------------------------------------------------------
def parse_category_tree(ws) -> list[dict]:
    roots: list[dict] = []
    index: dict[tuple, dict] = {}
    l1 = l2 = None
    first = True
    for row in ws.iter_rows(values_only=True):
        if first:
            first = False
            continue
        a, b, c, comment = (list(row) + [None] * 4)[:4]
        a, b, c, comment = clean(a), clean(b), clean(c), clean(comment)
        if a:
            l1 = a
        if b:
            l2 = b
        if not any([a, b, c]):
            continue
        en_comment = tr(comment, CATEGORY_COMMENT_EN, what="cat-comment") if comment else None
        if l1 and (l1,) not in index:
            node = {"name": tr(l1, CATEGORY_EN, what="cat"), "children": [], "comment": None}
            index[(l1,)] = node
            roots.append(node)
        if l2 and (l1, l2) not in index:
            node = {"name": tr(l2, CATEGORY_EN, what="cat"), "children": [], "comment": None}
            index[(l1, l2)] = node
            index[(l1,)]["children"].append(node)
        if c and (l1, l2, c) not in index:
            node = {
                "name": tr(c, CATEGORY_EN, what="cat"),
                "children": [],
                "comment": en_comment,
            }
            index[(l1, l2, c)] = node
            index[(l1, l2)]["children"].append(node)
        elif en_comment and l2 and not c:
            index[(l1, l2)]["comment"] = en_comment
    return roots


# --- footprint aliases -----------------------------------------------------------
def parse_footprint_aliases(ws) -> list[dict]:
    out: list[dict] = []
    first = True
    for row in ws.iter_rows(values_only=True):
        if first:
            first = False
            continue
        canonical, aliases, category = (list(row) + [None] * 3)[:3]
        canonical = clean(canonical)
        if not canonical:
            continue
        alist = [a.strip() for a in str(aliases or "").split(",") if a.strip()]
        grp = clean(category)
        out.append(
            {
                "canonical": canonical,
                "aliases": sorted(set(alist) | {canonical}),
                "group": GROUP_EN.get(grp, grp) or None,
                "kicad_footprint": None,
            }
        )
    return out


# --- storage locations (from the PartsBox export) ------------------------------
def parse_storage_locations(path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = next((w for w in wb.worksheets if clean(w.title).lower().startswith("förvaring")), None)
    if ws is None:
        return []
    rows: list[dict] = []
    for i, (a, b) in enumerate(ws.iter_rows(values_only=True)):
        if i == 0 or not b:
            continue
        name = str(b).strip()
        rows.append(
            {
                "legacy_id": str(a).strip() if a else None,
                "name": tr(name, LOCATION_EN, what="location"),
            }
        )
    return rows


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    spec = Path(sys.argv[1])
    partsbox = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    out_dir = Path(__file__).resolve().parents[1] / "seed"
    out_dir.mkdir(exist_ok=True)

    wb = openpyxl.load_workbook(spec, data_only=True)
    categories = footprints = None
    part_classes: dict[str, dict] = {}
    common_fields: list[dict] = []
    for ws in wb.worksheets:
        title = clean(ws.title)
        if title.startswith("Kategoritr"):
            categories = parse_category_tree(ws)
        elif title.startswith("Footprint alias"):
            footprints = parse_footprint_aliases(ws)
        elif title.startswith("Gemensamma"):
            common_fields = parse_field_sheet(ws)
        elif title in CLASS_IDS:
            cid = CLASS_IDS[title]
            part_classes[cid] = {
                "id": cid,
                "label": CLASS_LABEL_EN.get(cid, cid),
                "fields": parse_field_sheet(ws),
            }

    def dump(name: str, data) -> None:
        p = out_dir / name
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  seed/{name}  ({_count(data)})")

    print("Extracted:")
    dump("categories.json", categories or [])
    dump("footprint_aliases.json", footprints or [])
    dump("part_classes.json", part_classes)
    dump("common_fields.json", common_fields)
    if partsbox and partsbox.exists():
        dump("storage_locations.json", parse_storage_locations(partsbox))

    if _missing:
        print("\nWARN: no translation for -")
        for m in sorted(_missing):
            print("  " + m)
    return 0


def _count(data) -> str:
    if isinstance(data, list):
        return f"{len(data)} top-level"
    if isinstance(data, dict):
        return f"{len(data)} classes"
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
