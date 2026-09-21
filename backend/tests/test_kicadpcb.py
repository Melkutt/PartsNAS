"""The KiCad board reader, checked against pcbnew's own numbers.

fixtures/mini.kicad_pcb is a small synthetic board made with KiCad 10's API (rotated and back-side footprints,
rounded / rect / oval / round pads, through-hole drills, a track, a via, an outline). fixtures/mini.truth.json is
what pcbnew reports for it: absolute positions and the absolute box of every pad. The reader must agree.
(The same comparison was run by hand on 19 real boards of KiCad 6, 7 and 9, with rotated and back-side parts.)
"""
import json
import math
from pathlib import Path

import pytest

from app.kicadpcb import extract_board, parse_sexpr

FIX = Path(__file__).parent / "fixtures"
TOL = 0.002


@pytest.fixture(scope="module")
def mini():
    return extract_board((FIX / "mini.kicad_pcb").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def truth():
    return json.loads((FIX / "mini.truth.json").read_text(encoding="utf-8"))


def _box(p):
    a = math.radians(p["r"])
    ex = (abs(math.cos(a)) * p["w"] + abs(math.sin(a)) * p["h"]) / 2
    ey = (abs(math.sin(a)) * p["w"] + abs(math.cos(a)) * p["h"]) / 2
    return [p["x"] - ex, p["y"] - ey, p["x"] + ex, p["y"] + ey]


def test_footprints_land_where_pcbnew_puts_them(mini, truth):
    got = {f["ref"]: f for f in mini["footprints"]}
    assert set(got) == {t["ref"] for t in truth["footprints"]}
    for t in truth["footprints"]:
        f = got[t["ref"]]
        assert abs(f["x"] - t["pos"][0]) < TOL and abs(f["y"] - t["pos"][1]) < TOL, t["ref"]
        assert f["side"] == t["side"], t["ref"]
    assert {r for r, f in got.items() if f["side"] == "B"} == {"C2", "C3"}


def test_pads_have_the_position_and_absolute_box_pcbnew_reports(mini, truth):
    got = {f["ref"]: f for f in mini["footprints"]}
    checked = 0
    for t in truth["footprints"]:
        for tp in t["pads"]:
            cands = [p for p in got[t["ref"]]["pads"]
                     if p["n"] == tp["num"] and abs(p["x"] - tp["pos"][0]) < TOL and abs(p["y"] - tp["pos"][1]) < TOL]
            assert cands, (t["ref"], tp["num"])
            if tp["shape"] == "roundrect" and t["orient"] % 90:
                continue            # pcbnew's box of a rounded pad at 45 degrees is tighter than the rotated rectangle's
            assert all(abs(a - b) < 0.02 for a, b in zip(_box(cands[0]), tp["box"])), (t["ref"], tp["num"], _box(cands[0]), tp["box"])
            checked += 1
    assert checked >= 10


def test_shapes_layers_and_drills(mini):
    j1 = next(f for f in mini["footprints"] if f["ref"] == "J1")
    assert [(p["s"], p["L"], p["d"]) for p in j1["pads"]] == [("circle", "FB", 1.0), ("oval", "FB", 1.0)]
    r1 = next(f for f in mini["footprints"] if f["ref"] == "R1")
    assert [(p["s"], p["L"]) for p in r1["pads"]] == [("roundrect", "F"), ("rect", "F")] and r1["pads"][0]["rr"] == 0.25
    c2 = next(f for f in mini["footprints"] if f["ref"] == "C2")
    assert [p["L"] for p in c2["pads"]] == ["B", "B"]


def test_lines_outline_and_copper(mini, truth):
    lines = [(tuple(p[1:3]), tuple(p[3:5])) for p in mini["gfx"]["F.Fab"] if p[0] == "l"]
    for t in truth["footprints"]:
        for g in t["graphics"]:
            if g["layer"] == "F.Fab" and g["shape"] == "Line":
                a, b = tuple(g["start"]), tuple(g["end"])
                near = lambda u, v: abs(u[0] - v[0]) < 0.003 and abs(u[1] - v[1]) < 0.003  # noqa: E731
                assert any((near(a, p) and near(b, q)) or (near(a, q) and near(b, p)) for p, q in lines), (t["ref"], g)
    assert mini["bbox"] == [10.0, 10.0, 50.0, 40.0] and len(mini["edge"]) == 4
    assert mini["tracks"]["F.Cu"][0][:5] == ["l", 21.0, 20.0, 29.0, 20.0] and mini["vias"] == [[25.0, 25.0, 0.6, 0.3]]
    assert len(json.dumps(mini)) < 20_000


# -- KiCad 7 writes the reference as fp_text and leaves the pad angle absolute; the others use property -------------
V7 = '''(kicad_pcb (version 20221018) (generator pcbnew)
  (gr_rect (start 0 0) (end 20 10) (layer "Edge.Cuts") (width 0.1) (fill none))
  (footprint "Lib:R" (layer "F.Cu") (at 10 5 90)
    (fp_text reference "R7" (at 0 1 90) (layer "F.SilkS"))
    (fp_text value "10k" (at 0 -1 90) (layer "F.Fab"))
    (pad "1" smd rect (at -1 0 90) (size 0.6 1) (layers "F.Cu" "F.Paste" "F.Mask"))
    (pad "2" smd rect (at 1 0 90) (size 0.6 1) (layers "F.Cu" "F.Paste" "F.Mask"))
    (fp_line (start -1 -1) (end 1 -1) (layer "F.CrtYd") (width 0.05))))'''

V9 = V7.replace("version 20221018", "version 20241229").replace(
    '(fp_text reference "R7" (at 0 1 90) (layer "F.SilkS"))', '(property "Reference" "R7" (at 0 1 90) (layer "F.SilkS"))').replace(
    '(fp_text value "10k" (at 0 -1 90) (layer "F.Fab"))', '(property "Value" "10k" (at 0 -1 90) (layer "F.Fab"))')


@pytest.mark.parametrize("text", [V7, V9], ids=["kicad7", "kicad9"])
def test_reference_value_and_rotation_in_both_generations(text):
    b = extract_board(text)
    f = b["footprints"][0]
    assert (f["ref"], f["value"], f["x"], f["y"], f["rot"]) == ("R7", "10k", 10.0, 5.0, 90.0)
    # local (-1, 0) turned 90 degrees counter-clockwise on screen is (0, +1): pad 1 sits BELOW the centre
    p1, p2 = f["pads"]
    assert (p1["x"], p1["y"], p2["x"], p2["y"]) == (10.0, 6.0, 10.0, 4.0)
    assert p1["r"] == 90.0                                      # 0.6 x 1 turned: a tall pad becomes a wide one on the board


def test_a_pad_without_an_angle_is_unrotated_on_the_board_even_in_a_rotated_footprint():
    text = V7.replace('(at -1 0 90) (size 0.6 1)', '(at -1 0) (size 0.6 1)')
    assert extract_board(text)["footprints"][0]["pads"][0]["r"] == 0.0


def test_things_that_are_not_boards_are_refused_with_a_message():
    for bad in ("", "hello", "(kicad_sch (version 1))", "(kicad_pcb (version 1)", "(kicad_pcb))"):
        with pytest.raises(ValueError):
            extract_board(bad)
    assert parse_sexpr('(a "b c" (d 1.5))') == [["a", "b c", ["d", "1.5"]]]


# -- text: silkscreen and fab text, in the size, place and direction pcbnew reports -------------------------------
LAYER = {"F.Silkscreen": "F.SilkS", "B.Silkscreen": "B.SilkS", "F.Fab": "F.Fab", "B.Fab": "B.Fab"}


def test_text_matches_pcbnew(mini):
    truth = json.loads((FIX / "mini.text.json").read_text(encoding="utf-8"))
    have = [(lyr, p) for lyr, prims in mini["gfx"].items() for p in prims if p[0] == "t"]
    checked = 0
    for t in truth:
        if not t["visible"] or t["layer"] not in LAYER:
            continue
        cands = [p for lyr, p in have if lyr == LAYER[t["layer"]] and p[1] == t["shown"]
                 and abs(p[2] - t["pos"][0]) < 0.003 and abs(p[3] - t["pos"][1]) < 0.003]
        assert cands, t["owner"]
        p = cands[0]
        turn = (p[4] - t["angle"]) % 360
        assert min(turn, 360 - turn) < 0.01, (t["owner"], p[4], t["angle"])
        assert abs(p[5] - t["h"]) < 0.002 and bool(p[10]) == t["mirror"], t["owner"]
        checked += 1
    assert checked == 12
    back = [p for lyr, prims in mini["gfx"].items() if lyr.startswith("B.") for p in prims if p[0] == "t"]
    assert back and all(p[10] == 1 for p in back)          # text on the back is stored mirrored


TEXTS = '''(kicad_pcb (version 20221018)
  (footprint "Lib:R" (layer "F.Cu") (at 10 5 90)
    (fp_text reference "R7" (at -1.5 7 90) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
    (fp_text value "10k" (at 0 0) (layer "F.Fab") hide (effects (font (size 1 1) (thickness 0.15))))
    (fp_text user "${REFERENCE} / ${VALUE}" (at 0 2 0) (layer "F.Fab") (effects (font (size 0.8 0.6) (thickness 0.1) bold) (justify left bottom))))
  (gr_text "HELLO\nWORLD" (at 30 40 180) (layer "B.SilkS") (effects (font (size 2 2)) (justify mirror))))'''


def test_text_position_angle_visibility_variables_and_line_breaks():
    b = extract_board(TEXTS)
    silk = [p for p in b["gfx"]["F.SilkS"] if p[0] == "t"]
    # local (-1.5, 7) in a footprint at (10, 5) turned 90 degrees counter-clockwise: (10 + 7, 5 + 1.5); its angle is the board angle
    assert silk == [["t", "R7", 17.0, 6.5, 90.0, 1.0, 1.0, 0.15, 0, 0, 0, 0]]
    fab = [p for p in b["gfx"]["F.Fab"] if p[0] == "t"]
    assert [p[1] for p in fab] == ["R7 / 10k"]                 # ${REFERENCE} / ${VALUE} filled in, hidden value not drawn
    assert fab[0][5:7] == [0.8, 0.6] and fab[0][8:10] == [-1, 1] and fab[0][11] == 1   # size h/w, left + bottom, bold
    back = [p for p in b["gfx"]["B.SilkS"] if p[0] == "t"]
    assert back[0][1] == "HELLO\nWORLD" and back[0][2:5] == [30.0, 40.0, 180.0] and back[0][10] == 1
