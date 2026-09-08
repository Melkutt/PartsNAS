"""Extract the category tree, footprint aliases and per-class field schemas from
the hand-authored spec workbook (komponentspec.xlsx) into JSON seed files.

Run once (or whenever the workbook changes):

    python scripts/extract_spec.py "C:/Users/Melker/Desktop/komponentspec.xlsx"

Outputs, under seed/:
    categories.json        nested category tree (arbitrary depth)
    footprint_aliases.json  canonical footprint name -> aliases + kicad hint
    part_classes.json      per-class extra field definitions (JSON attributes)
    common_fields.json     the shared field list, for reference

Everything downstream is English; Swedish labels from the sheet are kept as
`label_sv` so the UI can show them.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import openpyxl

# sheet title (minus emoji/whitespace) -> stable English class id
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

TYPE_MAP = {"TEXT": "text", "NUMMER": "number", "VAL": "enum", "BOOL": "bool", "DATUM": "date"}

_emoji = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u2190-\u21FF\u2300-\u23FF]"
)


def clean(s) -> str:
    if s is None:
        return ""
    return _emoji.sub("", str(s)).strip()


def is_attr_row(row) -> bool:
    """A real field row: has a label (col A) and a known type (col D)."""
    label = clean(row[0])
    typ = clean(row[3]).upper()
    return bool(label) and typ in TYPE_MAP


def parse_field_sheet(ws) -> list[dict]:
    fields: list[dict] = []
    for row in ws.iter_rows(values_only=True):
        if not is_attr_row(row):
            continue
        label_sv, kicad, unit, typ, required, api_source, comment = (
            list(row) + [None] * 7
        )[:7]
        entry = {
            "key": _slug(clean(kicad) or clean(label_sv)),
            "label_sv": clean(label_sv),
            "kicad_field": clean(kicad) or None,
            "unit": clean(unit) or None,
            "type": TYPE_MAP[clean(typ).upper()],
            "required": clean(required).upper().startswith("JA"),
            "api_source": clean(api_source) or None,
            "comment": clean(comment) or None,
        }
        if entry["type"] == "enum" and entry["comment"]:
            opts = _enum_options(entry["comment"])
            if opts:
                entry["options"] = opts
        fields.append(entry)
    return fields


def _slug(s: str) -> str:
    s = clean(s).lower()
    s = s.replace("å", "a").replace("ä", "a").replace("ö", "o")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "field"


def _enum_options(comment: str) -> list[str] | None:
    # e.g. "Tjockfilm, Tunnfilm, Metallfilm, Trådlindad" -> list
    body = re.sub(r"^(t\.?ex\.?|ex\.?|dvs\.?)[:\s]*", "", comment.strip(), flags=re.I)
    if "." in body and "," not in body:
        return None
    parts = [p.strip(" .") for p in re.split(r"[,/]", body)]
    parts = [p for p in parts if p and len(p) <= 30 and " " not in p.strip().rstrip("²")]
    return parts if len(parts) >= 2 else None


def parse_category_tree(ws) -> list[dict]:
    roots: list[dict] = []
    index: dict[tuple, dict] = {}
    l1 = l2 = None
    first = True
    for row in ws.iter_rows(values_only=True):
        if first:  # header
            first = False
            continue
        a, b, c, comment = (list(row) + [None] * 4)[:4]
        a, b, c, comment = clean(a), clean(b), clean(c), clean(comment)
        if a:
            l1 = a
        if b:
            l2 = b
            # new level-2 group resets nothing else; level-3 always comes from c
        if not any([a, b, c]):
            continue
        # ensure level-1
        if l1 and (l1,) not in index:
            node = {"name": l1, "children": [], "comment": None}
            index[(l1,)] = node
            roots.append(node)
        # ensure level-2
        if l2 and (l1, l2) not in index:
            node = {"name": l2, "children": [], "comment": None}
            index[(l1, l2)] = node
            index[(l1,)]["children"].append(node)
        # level-3 leaf
        if c and (l1, l2, c) not in index:
            node = {"name": c, "children": [], "comment": comment or None}
            index[(l1, l2, c)] = node
            index[(l1, l2)]["children"].append(node)
        elif comment and l2 and not c:
            index[(l1, l2)]["comment"] = comment
    return roots


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
        out.append(
            {
                "canonical": canonical,
                "aliases": sorted(set(alist) | {canonical}),
                "group": clean(category) or None,
                "kicad_footprint": None,  # filled in later by hand / mapping table
            }
        )
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])
    out_dir = Path(__file__).resolve().parents[1] / "seed"
    out_dir.mkdir(exist_ok=True)
    wb = openpyxl.load_workbook(src, data_only=True)

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
                "label_sv": title,
                "fields": parse_field_sheet(ws),
            }

    def dump(name: str, data) -> None:
        p = out_dir / name
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {p.relative_to(out_dir.parent)}  ({_count(data)})")

    print("Extracted:")
    dump("categories.json", categories or [])
    dump("footprint_aliases.json", footprints or [])
    dump("part_classes.json", part_classes)
    dump("common_fields.json", common_fields)
    return 0


def _count(data) -> str:
    if isinstance(data, list):
        return f"{len(data)} top-level"
    if isinstance(data, dict):
        return f"{len(data)} classes"
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
