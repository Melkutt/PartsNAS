"""Read a KiCad board file (.kicad_pcb) and boil it down to what a browser needs to DRAW the board:
the outline, every footprint with its pads and silkscreen / fab / courtyard lines, and (optionally
simplified) copper. Everything is returned in board coordinates (millimetres, y pointing down, as in the
file), already rotated and mirrored, so the viewer only has to draw.

The .kicad_pcb format is plain text (an S-expression) and open, and it is the same file KiCad itself
saves, so nothing here needs KiCad, a plugin or a running program. It reads what KiCad 7 writes
(`fp_text reference ...`) as well as KiCad 8-10 (`property "Reference" ...`).

Conventions, all checked against pcbnew's own numbers (see tests/test_kicadpcb.py):
  * a footprint is placed at (x, y) with an angle; a point p in its own frame lands at
    (x, y) + R(angle) * p, where R turns counter-clockwise on screen (y down),
  * a pad's own angle in the file is the pad's angle on the BOARD (it already includes the footprint's;
    an omitted angle means 0 on the board, not "same as the footprint"),
  * a footprint on the back is stored already mirrored, with its layers named B.*.
"""
from __future__ import annotations

import math
import re
from typing import Any

_TOKEN = re.compile(r'\(|\)|"((?:[^"\\]|\\.)*)"|[^\s()"]+')
_ESCAPE = re.compile(r"\\(.)")
_UNESCAPED = {"n": "\n", "t": "\t"}          # KiCad writes a line break inside a string as \n
FORMAT = 2   # 2: silkscreen / fab text


# ------------------------------------------------------------------ S-expression
def parse_sexpr(text: str) -> list:
    """Nested lists: a `(a b (c))` becomes ["a", "b", ["c"]]. Atoms stay strings."""
    root: list = []
    stack: list[list] = [root]
    for m in _TOKEN.finditer(text):
        tok = m.group(0)
        if tok == "(":
            node: list = []
            stack[-1].append(node)
            stack.append(node)
        elif tok == ")":
            if len(stack) == 1:
                raise ValueError("unbalanced ')' in the board file")
            stack.pop()
        elif m.group(1) is not None:
            stack[-1].append(_ESCAPE.sub(lambda e: _UNESCAPED.get(e.group(1), e.group(1)), m.group(1)))
        else:
            stack[-1].append(tok)
    if len(stack) != 1:
        raise ValueError("unbalanced '(' in the board file - is it complete?")
    return root


def _kids(node: list, name: str):
    for c in node:
        if isinstance(c, list) and c and c[0] == name:
            yield c


def _first(node: list, name: str) -> list | None:
    return next(_kids(node, name), None)


def _num(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _xy(node: list | None) -> tuple[float, float]:
    return (_num(node[1]), _num(node[2])) if node and len(node) >= 3 else (0.0, 0.0)


def _r(v: float) -> float:
    return round(v, 3)


# ------------------------------------------------------------------ geometry
def _rot(x: float, y: float, deg: float) -> tuple[float, float]:
    """Turn (x, y) counter-clockwise on screen (y down) by deg degrees."""
    if not deg:
        return x, y
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return x * c + y * s, -x * s + y * c


class _Frame:
    """A footprint's frame: local point -> board point."""

    def __init__(self, x: float, y: float, deg: float):
        self.x, self.y, self.deg = x, y, deg

    def pt(self, x: float, y: float) -> tuple[float, float]:
        rx, ry = _rot(x, y, self.deg)
        return self.x + rx, self.y + ry


def _width(node: list) -> float:
    w = _first(node, "width")
    if w:
        return _num(w[1])
    stroke = _first(node, "stroke")
    if stroke:
        w = _first(stroke, "width")
        if w:
            return _num(w[1])
    return 0.0


def _filled(node: list) -> bool:
    f = _first(node, "fill")
    return bool(f and len(f) > 1 and f[1] in ("solid", "yes"))


def _pts(node: list | None, place) -> list[float]:
    out: list[float] = []
    if not node:
        return out
    for xy in _kids(node, "xy"):
        x, y = place(_num(xy[1]), _num(xy[2]))
        out += [_r(x), _r(y)]
    return out


def _primitive(kind: str, node: list, place) -> list | None:
    """One drawing element (line, rect, circle, arc, polygon) as a compact list in board coordinates."""
    w = _r(_width(node))
    if kind == "line":
        a, b = place(*_xy(_first(node, "start"))), place(*_xy(_first(node, "end")))
        return ["l", _r(a[0]), _r(a[1]), _r(b[0]), _r(b[1]), w]
    if kind == "rect":
        (x1, y1), (x2, y2) = _xy(_first(node, "start")), _xy(_first(node, "end"))
        pts = [place(x1, y1), place(x2, y1), place(x2, y2), place(x1, y2)]
        return ["p", [_r(v) for p in pts for v in p], w, 1 if _filled(node) else 0]
    if kind == "circle":
        c, e = _xy(_first(node, "center")), _xy(_first(node, "end"))
        cx, cy = place(*c)
        return ["c", _r(cx), _r(cy), _r(math.hypot(e[0] - c[0], e[1] - c[1])), w, 1 if _filled(node) else 0]
    if kind == "arc":
        mid = _first(node, "mid")
        s, e = _xy(_first(node, "start")), _xy(_first(node, "end"))
        if mid:                                    # KiCad 7+: start, mid, end
            m = _xy(mid)
        else:                                      # KiCad 5/6: centre (start), start point (end), angle
            ang = _num((_first(node, "angle") or [0, 0])[1])
            cx, cy = s
            sx, sy = e
            r = math.hypot(sx - cx, sy - cy)
            a0 = math.atan2(sy - cy, sx - cx)
            a1 = a0 + math.radians(ang)
            am = a0 + math.radians(ang) / 2
            s, m, e = (sx, sy), (cx + r * math.cos(am), cy + r * math.sin(am)), (cx + r * math.cos(a1), cy + r * math.sin(a1))
        (sx, sy), (mx, my), (ex, ey) = place(*s), place(*m), place(*e)
        return ["a", _r(sx), _r(sy), _r(mx), _r(my), _r(ex), _r(ey), w]
    if kind == "poly":
        pts = _pts(_first(node, "pts"), place)
        return ["p", pts, w, 1 if _filled(node) else 0] if len(pts) >= 6 else None
    if kind == "curve":                            # a bezier: its end points are close enough to see where it goes
        pts = _pts(_first(node, "pts"), place)
        return ["l", pts[0], pts[1], pts[-2], pts[-1], w] if len(pts) >= 4 else None
    return None


_KINDS = {"line": "line", "rect": "rect", "circle": "circle", "arc": "arc", "poly": "poly", "curve": "curve"}


def _prim_bbox(p: list) -> list[float]:
    if p[0] == "l":
        xs, ys = [p[1], p[3]], [p[2], p[4]]
    elif p[0] == "c":
        return [p[1] - p[3], p[2] - p[3], p[1] + p[3], p[2] + p[3]]
    elif p[0] == "a":
        xs, ys = [p[1], p[3], p[5]], [p[2], p[4], p[6]]
    else:
        xs, ys = p[1][0::2], p[1][1::2]
    return [min(xs), min(ys), max(xs), max(ys)]


def _union(a: list[float] | None, b: list[float]) -> list[float]:
    return list(b) if a is None else [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


# ------------------------------------------------------------------ text
_HJ = {"left": -1, "right": 1}
_VJ = {"top": -1, "bottom": 1}


def _hidden(node: list) -> bool:
    for c in node:
        if c == "hide" or (isinstance(c, list) and c and c[0] == "hide" and (len(c) < 2 or c[1] != "no")):
            return True
    eff = _first(node, "effects")
    return bool(eff and any(c == "hide" or (isinstance(c, list) and c and c[0] == "hide" and (len(c) < 2 or c[1] != "no")) for c in eff))


def _text(node: list, text: str, frame: _Frame | None, layer: str) -> list | None:
    """["t", text, x, y, angle, height, width, thickness, hj, vj, mirror, bold] in board coordinates.
    hj / vj: -1 left / top, 0 centre, 1 right / bottom (KiCad's own numbers). The angle in the file is the text's
    angle on the board, like a pad's."""
    if not text.strip():
        return None
    at = _first(node, "at") or ["at", 0, 0]
    lx, ly = _num(at[1]), _num(at[2])
    x, y = frame.pt(lx, ly) if frame else (lx, ly)
    angle = _num(at[3]) if len(at) > 3 else 0.0
    eff = _first(node, "effects") or []
    font = _first(eff, "font") or []
    size = _first(font, "size") or ["size", 1, 1]
    h, w = _num(size[1], 1.0), _num(size[2], _num(size[1], 1.0))
    th = _num((_first(font, "thickness") or [0, 0.15])[1], 0.15)
    bold = any(c == "bold" or (isinstance(c, list) and c[0] == "bold" and c[1:2] != ["no"]) for c in font)
    just = [str(c) for c in (_first(eff, "justify") or [])[1:]]
    hj = next((_HJ[t] for t in just if t in _HJ), 0)
    vj = next((_VJ[t] for t in just if t in _VJ), 0)
    return ["t", text, _r(x), _r(y), _r(angle % 360), _r(h), _r(w), _r(th), hj, vj, 1 if "mirror" in just else 0, 1 if bold else 0]


def _expand(text: str, ref: str, value: str) -> str:
    return text.replace("${REFERENCE}", ref).replace("${VALUE}", value)


# ------------------------------------------------------------------ pads
_PAD_SHAPES = {"circle": "circle", "rect": "rect", "oval": "oval", "roundrect": "roundrect",
               "trapezoid": "rect", "custom": "custom"}


def _pad_layer(layers: list[str]) -> str:
    front = any(l in ("F.Cu", "*.Cu", "F&B.Cu") for l in layers)   # "F&B.Cu": older files, mounting holes
    back = any(l in ("B.Cu", "*.Cu", "F&B.Cu") for l in layers)
    return "FB" if front and back else "F" if front else "B" if back else ""


def _pad(node: list, frame: _Frame) -> dict | None:
    layers = [str(x) for x in (_first(node, "layers") or [])[1:]]
    layer = _pad_layer(layers)
    if not layer:
        return None                                # paste / mask / user-layer only: nothing to draw as copper
    kind = node[3] if len(node) > 3 else "rect"
    shape = _PAD_SHAPES.get(kind, "rect")
    at = _first(node, "at") or ["at", 0, 0]
    lx, ly = _num(at[1]), _num(at[2])
    x, y = frame.pt(lx, ly)
    size = _first(node, "size") or ["size", 1, 1]
    w, h = _num(size[1]), _num(size[2], _num(size[1]))
    angle = _num(at[3]) if len(at) > 3 else 0.0                # board angle, and KiCad leaves out a 0
    drill_node = _first(node, "drill")
    drill = 0.0
    if drill_node:
        nums = [_num(v, -1) for v in drill_node[1:] if v not in ("oval",) and not isinstance(v, list)]
        drill = next((v for v in nums if v > 0), 0.0)
    pad: dict[str, Any] = {"n": str(node[1]), "s": shape, "x": _r(x), "y": _r(y), "w": _r(w), "h": _r(h),
                           "r": _r(angle % 360), "L": layer}
    if shape == "roundrect":
        pad["rr"] = _r(_num((_first(node, "roundrect_rratio") or [0, 0.25])[1], 0.25))
    if drill:
        pad["d"] = _r(drill)
    if kind == "trapezoid":                        # a rectangle whose sides are skewed by rect_delta
        delta = _first(node, "rect_delta")
        ddx, ddy = (_num(delta[1]), _num(delta[2])) if delta and len(delta) >= 3 else (0.0, 0.0)
        hx, hy, ax, ay = w / 2, h / 2, ddx / 2, ddy / 2
        corners = [(-hx - ay, hy + ax), (-hx + ay, -hy - ax), (hx - ay, -hy + ax), (hx + ay, hy - ax)]
        pf = _Frame(x, y, angle)
        pad["poly"] = [_r(v) for c in corners for v in pf.pt(*c)]
        pad["s"] = "poly"
    if shape == "custom":                          # a pad drawn from polygons: keep the polygons, in board coordinates
        poly: list[float] = []
        prim = _first(node, "primitives")
        pad_frame = _Frame(x, y, angle)
        for gp in (_kids(prim, "gr_poly") if prim else []):
            poly = _pts(_first(gp, "pts"), pad_frame.pt)
            if poly:
                break
        if poly:
            pad["poly"] = poly
        else:
            pad["s"] = "rect"
    return pad


# ------------------------------------------------------------------ footprints
def _text_of(fp: list, which: str) -> str:
    """Reference / Value: `(fp_text reference "R1" ...)` in KiCad 7, `(property "Reference" "R1" ...)` in 8+."""
    for t in _kids(fp, "fp_text"):
        if len(t) > 2 and t[1] == which.lower():
            return str(t[2])
    for p in _kids(fp, "property"):
        if len(p) > 2 and p[1] == which:
            return str(p[2])
    return ""


_DRAW_LAYERS = {"F.SilkS", "B.SilkS", "F.Fab", "B.Fab", "F.CrtYd", "B.CrtYd"}
_TEXT_LAYERS = {"F.SilkS", "B.SilkS", "F.Fab", "B.Fab"}
_GR = {f"gr_{k}": v for k, v in _KINDS.items()}
_FP = {f"fp_{k}": v for k, v in _KINDS.items()}


def _footprint(fp: list, gfx: dict[str, list]) -> dict:
    at = _first(fp, "at") or ["at", 0, 0]
    x, y = _num(at[1]), _num(at[2])
    deg = _num(at[3]) if len(at) > 3 else 0.0
    frame = _Frame(x, y, deg)
    layer = (_first(fp, "layer") or ["layer", "F.Cu"])[1]
    attrs = [str(a) for a in (_first(fp, "attr") or [])[1:] if not isinstance(a, list)]
    pads = [p for p in (_pad(n, frame) for n in _kids(fp, "pad")) if p]

    ref, value = _text_of(fp, "Reference"), _text_of(fp, "Value")

    def add_text(node: list, text: str) -> None:
        lyr = (_first(node, "layer") or ["layer", ""])[1]
        if lyr in _TEXT_LAYERS and not _hidden(node):
            t = _text(node, _expand(text, ref, value), frame, lyr)
            if t:
                gfx[lyr].append(t)

    for t in _kids(fp, "fp_text"):                 # KiCad 5-7: reference, value and free text alike
        if len(t) > 2:
            add_text(t, str(t[2]))
    for prop in _kids(fp, "property"):             # KiCad 8+: the reference and the value are properties
        if len(prop) > 2 and prop[1] in ("Reference", "Value"):
            add_text(prop, str(prop[2]))

    bbox: list[float] | None = None
    for p in pads:                                 # the pad's rotated rectangle (or its polygon) -> box
        if p.get("poly"):
            xs, ys = p["poly"][0::2], p["poly"][1::2]
            bbox = _union(bbox, [min(xs), min(ys), max(xs), max(ys)])
        else:
            a = math.radians(p["r"])
            ex = (abs(math.cos(a)) * p["w"] + abs(math.sin(a)) * p["h"]) / 2
            ey = (abs(math.sin(a)) * p["w"] + abs(math.cos(a)) * p["h"]) / 2
            bbox = _union(bbox, [p["x"] - ex, p["y"] - ey, p["x"] + ex, p["y"] + ey])

    for child in fp:
        if not isinstance(child, list) or not child or child[0] not in _FP:
            continue
        lyr = (_first(child, "layer") or ["layer", ""])[1]
        if lyr not in _DRAW_LAYERS:
            continue
        prim = _primitive(_FP[child[0]], child, frame.pt)
        if prim:
            gfx[lyr].append(prim)
            if lyr.endswith("CrtYd"):              # the courtyard is the part's footprint on the board
                bbox = _union(bbox, _prim_bbox(prim))
    if bbox is None:
        bbox = [x - 0.5, y - 0.5, x + 0.5, y + 0.5]
    return {
        "ref": _text_of(fp, "Reference"), "value": _text_of(fp, "Value"),
        "fpid": str(fp[1]) if len(fp) > 1 and not isinstance(fp[1], list) else "",
        "x": _r(x), "y": _r(y), "rot": _r(deg % 360), "side": "B" if layer.startswith("B.") else "F",
        "attr": attrs, "bbox": [_r(v) for v in bbox], "pads": pads,
    }


# ------------------------------------------------------------------ copper
def _simplify(pts: list[float], tol: float = 0.03) -> list[float]:
    """Drop points closer than `tol` mm to the previous one: zone fills carry far more detail than a screen shows."""
    out = pts[:2]
    for i in range(2, len(pts) - 1, 2):
        if math.hypot(pts[i] - out[-2], pts[i + 1] - out[-1]) >= tol:
            out += pts[i:i + 2]
    return out if len(out) >= 6 else pts


def extract_board(text: str, *, copper: bool = True) -> dict:
    """The drawing model of a .kicad_pcb (see the module docstring). Raises ValueError for anything else."""
    tree = parse_sexpr(text)
    if not tree or not isinstance(tree[0], list) or not tree[0] or tree[0][0] != "kicad_pcb":
        raise ValueError("this is not a KiCad board file (.kicad_pcb)")
    root = tree[0]
    version = int(_num((_first(root, "version") or [0, 0])[1]))

    gfx: dict[str, list] = {l: [] for l in _DRAW_LAYERS}
    edge: list = []
    footprints = [_footprint(fp, gfx) for fp in _kids(root, "footprint")] + \
                 [_footprint(fp, gfx) for fp in _kids(root, "module")]          # KiCad 5 called them modules

    ident = lambda x, y: (x, y)  # noqa: E731 - top-level items are already in board coordinates
    for gt in _kids(root, "gr_text"):
        lyr = (_first(gt, "layer") or ["layer", ""])[1]
        if lyr in _TEXT_LAYERS and len(gt) > 1 and not _hidden(gt):
            t = _text(gt, str(gt[1]), None, lyr)
            if t:
                gfx[lyr].append(t)
    for child in root:
        if not isinstance(child, list) or not child or child[0] not in _GR:
            continue
        lyr = (_first(child, "layer") or ["layer", ""])[1]
        prim = _primitive(_GR[child[0]], child, ident)
        if not prim:
            continue
        if lyr == "Edge.Cuts":
            edge.append(prim)
        elif lyr in _DRAW_LAYERS:
            gfx[lyr].append(prim)

    tracks: dict[str, list] = {}
    vias: list = []
    zones: dict[str, list] = {}
    if copper:
        for s in _kids(root, "segment"):
            lyr = (_first(s, "layer") or ["layer", ""])[1]
            a, b = _xy(_first(s, "start")), _xy(_first(s, "end"))
            tracks.setdefault(lyr, []).append(["l", _r(a[0]), _r(a[1]), _r(b[0]), _r(b[1]), _r(_num((_first(s, "width") or [0, 0])[1]))])
        for s in _kids(root, "arc"):               # a curved track
            lyr = (_first(s, "layer") or ["layer", ""])[1]
            pr = _primitive("arc", s, ident)
            if pr:
                tracks.setdefault(lyr, []).append(pr)
        for v in _kids(root, "via"):
            x, y = _xy(_first(v, "at"))
            vias.append([_r(x), _r(y), _r(_num((_first(v, "size") or [0, 0.6])[1], 0.6)),
                         _r(_num((_first(v, "drill") or [0, 0.3])[1], 0.3))])
        for z in _kids(root, "zone"):
            for fpoly in _kids(z, "filled_polygon"):
                lyr = (_first(fpoly, "layer") or _first(z, "layer") or ["layer", ""])[1]
                pts = _simplify(_pts(_first(fpoly, "pts"), ident))
                if len(pts) >= 6:
                    zones.setdefault(lyr, []).append(pts)

    boxes = [_prim_bbox(p) for p in edge] or [f["bbox"] for f in footprints]
    bbox = None
    for b in boxes:
        bbox = _union(bbox, b)
    return {
        "format": FORMAT, "kicad_version": version,
        "bbox": [_r(v) for v in (bbox or [0, 0, 100, 100])],
        "edge": edge, "gfx": {k: v for k, v in gfx.items() if v},
        "footprints": footprints,
        "tracks": tracks, "vias": vias, "zones": zones,
    }
