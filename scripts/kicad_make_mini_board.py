"""Build a small synthetic board with KiCad 10's own API and save it: "C:/Program Files/KiCad/10.0/bin/python.exe" make_mini.py out.kicad_pcb"""
import sys

import pcbnew

MM = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))  # noqa: E731

board = pcbnew.CreateEmptyBoard()


def make_pad(fp, num, x, y, w, h, shape, attr="smd", drill=0.0, angle=0.0, rratio=None):
    pad = pcbnew.PAD(fp)
    pad.SetNumber(num)
    pad.SetShape(shape)
    pad.SetSize(pcbnew.VECTOR2I(MM(w), MM(h)))
    pad.SetPosition(V(x, y))
    if attr == "smd":
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetLayerSet(pad.SMDMask())
    else:
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetLayerSet(pad.PTHMask())
        pad.SetDrillSize(pcbnew.VECTOR2I(MM(drill), MM(drill)))
    if rratio is not None:
        pad.SetRoundRectRadiusRatio(rratio)
    if angle:
        pad.SetOrientationDegrees(angle)
    fp.Add(pad)
    return pad


def line(parent, layer, x1, y1, x2, y2, width=0.12):
    s = pcbnew.PCB_SHAPE(parent)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(x1, y1))
    s.SetEnd(V(x2, y2))
    s.SetLayer(layer)
    s.SetWidth(MM(width))
    parent.Add(s)


def footprint(ref, value, x, y, angle=0.0, back=False):
    fp = pcbnew.FOOTPRINT(board)
    fp.SetReference(ref)
    fp.SetValue(value)
    fp.SetFPIDAsString("Mini:" + value)
    board.Add(fp)
    # the footprint's own drawing, in its frame, placed at the origin first
    make_pad(fp, "1", -1.0, 0, 0.9, 1.2, pcbnew.PAD_SHAPE_ROUNDRECT, rratio=0.25)
    make_pad(fp, "2", 1.0, 0, 0.9, 1.2, pcbnew.PAD_SHAPE_RECT)
    line(fp, pcbnew.F_SilkS, -0.5, -0.8, 0.5, -0.8)
    line(fp, pcbnew.F_Fab, -1.6, -0.8, 1.6, -0.8)
    line(fp, pcbnew.F_Fab, 1.6, -0.8, 1.6, 0.8)
    line(fp, pcbnew.F_CrtYd, -1.8, -1.0, 1.8, -1.0, 0.05)
    line(fp, pcbnew.F_CrtYd, 1.8, -1.0, 1.8, 1.0, 0.05)
    fp.SetPosition(V(x, y))
    if back:
        fp.Flip(V(x, y), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    if angle:
        fp.SetOrientationDegrees(angle)
    return fp


footprint("R1", "R_0603", 20, 20)
footprint("R2", "R_0603", 30, 20, angle=90)
footprint("C1", "C_0603", 20, 30, angle=45)
footprint("C2", "C_0603", 30, 30, back=True)
footprint("C3", "C_0603", 40, 30, angle=270, back=True)

# a through-hole part with an oval and a round pad
th = pcbnew.FOOTPRINT(board)
th.SetReference("J1")
th.SetValue("Conn_2")
th.SetFPIDAsString("Mini:Conn_2")
board.Add(th)
make_pad(th, "1", -1.27, 0, 1.7, 1.7, pcbnew.PAD_SHAPE_CIRCLE, attr="pth", drill=1.0)
make_pad(th, "2", 1.27, 0, 1.7, 2.2, pcbnew.PAD_SHAPE_OVAL, attr="pth", drill=1.0)
th.SetPosition(V(40, 20))
th.SetOrientationDegrees(-90)

# board outline, a track, a via
for x1, y1, x2, y2 in ((10, 10, 50, 10), (50, 10, 50, 40), (50, 40, 10, 40), (10, 40, 10, 10)):
    line(board, pcbnew.Edge_Cuts, x1, y1, x2, y2, 0.1)
t = pcbnew.PCB_TRACK(board)
t.SetStart(V(21, 20))
t.SetEnd(V(29, 20))
t.SetWidth(MM(0.25))
t.SetLayer(pcbnew.F_Cu)
board.Add(t)
v = pcbnew.PCB_VIA(board)
v.SetPosition(V(25, 25))
v.SetWidth(MM(0.6))
v.SetDrill(MM(0.3))
board.Add(v)

board.Save(sys.argv[1])
print("saved", sys.argv[1])
