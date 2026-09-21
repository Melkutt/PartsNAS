"""Run with KiCad's own python:  "C:/Program Files/KiCad/10.0/bin/python.exe" kicad_truth.py <board.kicad_pcb> <out.json>
Dumps absolute (board-frame) geometry as pcbnew computes it: the ground truth our parser is tested against."""
import json
import sys

import pcbnew

MM = 1e-6  # internal units are nm


def mm(v):
    return round(v * MM, 4)


def pt(p):
    return [mm(p.x), mm(p.y)]


SHAPES = {}
for name in ("PAD_SHAPE_CIRCLE", "PAD_SHAPE_RECT", "PAD_SHAPE_OVAL", "PAD_SHAPE_TRAPEZOID", "PAD_SHAPE_ROUNDRECT", "PAD_SHAPE_CUSTOM"):
    if hasattr(pcbnew, name):
        SHAPES[getattr(pcbnew, name)] = name.replace("PAD_SHAPE_", "").lower()

board = pcbnew.LoadBoard(sys.argv[1])
out = {"footprints": []}
for fp in board.GetFootprints():
    item = {
        "ref": fp.GetReference(), "value": fp.GetValue(),
        "pos": pt(fp.GetPosition()), "orient": round(fp.GetOrientationDegrees(), 4),
        "side": "B" if fp.IsFlipped() else "F",
        "pads": [],
    }
    for pad in fp.Pads():
        s = pad.GetSize()
        item["pads"].append({
            "num": pad.GetNumber(), "pos": pt(pad.GetPosition()),
            "size": [mm(s.x), mm(s.y)], "orient": round(pad.GetOrientationDegrees(), 4),
            "shape": SHAPES.get(pad.GetShape(), str(pad.GetShape())),
            "drill": mm(pad.GetDrillSize().x),
            "on_front": pad.IsOnLayer(pcbnew.F_Cu), "on_back": pad.IsOnLayer(pcbnew.B_Cu),
            # the absolute box pcbnew draws: this is the truth for size + orientation, however they are stored
            "box": [mm(pad.GetBoundingBox().GetX()), mm(pad.GetBoundingBox().GetY()),
                    mm(pad.GetBoundingBox().GetRight()), mm(pad.GetBoundingBox().GetBottom())],
        })
    item["graphics"] = []
    for g in fp.GraphicalItems():
        if g.GetClass() != "PCB_SHAPE":
            continue
        item["graphics"].append({
            "layer": board.GetLayerName(g.GetLayer()), "shape": g.GetShapeStr(),
            "start": pt(g.GetStart()), "end": pt(g.GetEnd()),
            "width": mm(g.GetWidth()),
        })
    out["footprints"].append(item)

out["edge"] = []
for d in board.GetDrawings():
    if d.GetClass() == "PCB_SHAPE" and board.GetLayerName(d.GetLayer()) == "Edge.Cuts":
        out["edge"].append({"shape": d.GetShapeStr(), "start": pt(d.GetStart()), "end": pt(d.GetEnd())})
out["tracks"] = [{"start": pt(t.GetStart()), "end": pt(t.GetEnd()), "width": mm(t.GetWidth()),
                  "layer": board.GetLayerName(t.GetLayer())} for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
out["vias"] = [{"pos": pt(t.GetPosition()), "width": mm(t.GetWidth(pcbnew.F_Cu)), "drill": mm(t.GetDrillValue())}
               for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
bb = board.GetBoardEdgesBoundingBox()
out["bbox"] = [mm(bb.GetX()), mm(bb.GetY()), mm(bb.GetRight()), mm(bb.GetBottom())]
json.dump(out, open(sys.argv[2], "w"), indent=1)
print(len(out["footprints"]), "footprints,", len(out["tracks"]), "tracks,", len(out["vias"]), "vias")
