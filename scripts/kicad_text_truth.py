"""KiCad python: dump all texts (absolute) of a board. text_truth.py board.kicad_pcb out.json"""
import json
import sys

import pcbnew

MM = 1e-6
board = pcbnew.LoadBoard(sys.argv[1])


def mm(v):
    return round(v * MM, 4)


def info(t, owner):
    s = t.GetTextSize()
    layer = board.GetLayerName(t.GetLayer())
    hj = t.GetHorizJustify() if hasattr(t, "GetHorizJustify") else None
    vj = t.GetVertJustify() if hasattr(t, "GetVertJustify") else None
    return {
        "owner": owner, "text": t.GetText(), "shown": t.GetShownText(True) if hasattr(t, "GetShownText") else t.GetText(),
        "pos": [mm(t.GetPosition().x), mm(t.GetPosition().y)],
        "angle": round(t.GetTextAngleDegrees(), 3), "h": mm(s.y), "w": mm(s.x), "thick": mm(t.GetTextThickness()),
        "visible": bool(t.IsVisible()), "layer": layer, "mirror": bool(t.IsMirrored()),
        "hj": int(hj) if hj is not None else None, "vj": int(vj) if vj is not None else None,
        "bold": bool(t.IsBold()), "italic": bool(t.IsItalic()),
    }


out = []
for fp in board.GetFootprints():
    out.append(info(fp.Reference(), fp.GetReference() + ":reference"))
    out.append(info(fp.Value(), fp.GetReference() + ":value"))
    for g in fp.GraphicalItems():
        if g.GetClass() in ("PCB_TEXT", "FP_TEXT"):
            out.append(info(g, fp.GetReference() + ":text"))
for d in board.GetDrawings():
    if d.GetClass() == "PCB_TEXT":
        out.append(info(d, "board"))
json.dump(out, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
print(len(out), "texts;", sum(1 for t in out if t["visible"]), "visible")
