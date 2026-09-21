// deno test --allow-read tests/js
import { arcPoints, boardToScreen, edgeLoops, fitScale, hitFootprint, padPolygon, PcbView, primWidth, rotateCcw, screenToBoard } from "../../frontend/js/pcbview.js";

function eq(actual, expected, msg = "") {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${msg}\n  expected: ${JSON.stringify(expected)}\n  actual:   ${JSON.stringify(actual)}`);
  }
}
const close = (a, b, tol = 1e-6) => Math.abs(a - b) <= tol;
const round = (arr, d = 3) => arr.map((v) => Math.round(v * 10 ** d) / 10 ** d);

Deno.test("KiCad turns things counter-clockwise on screen (y down)", () => {
  eq(round(rotateCcw(1, 0, 90)), [0, -1]);      // a point to the right ends up ABOVE the centre
  eq(round(rotateCcw(-1, 0, 90)), [0, 1]);      // ...and the left one below (as the parser test: pad 1 sits below)
  eq(round(rotateCcw(1, 2, 0)), [1, 2]);
  eq(round(rotateCcw(1, 0, 180)), [-1, 0]);
});

Deno.test("pads become polygons in board coordinates", () => {
  const rect = padPolygon({ s: "rect", x: 10, y: 5, w: 2, h: 1, r: 0 });
  eq(round(rect), [9, 4.5, 11, 4.5, 11, 5.5, 9, 5.5]);
  const turned = padPolygon({ s: "rect", x: 10, y: 5, w: 2, h: 1, r: 90 });
  const xs = turned.filter((_, i) => i % 2 === 0), ys = turned.filter((_, i) => i % 2 === 1);
  eq([round([Math.max(...xs) - Math.min(...xs)])[0], round([Math.max(...ys) - Math.min(...ys)])[0]], [1, 2]);   // a wide pad turned 90 is tall
  const oval = padPolygon({ s: "oval", x: 0, y: 0, w: 4, h: 2, r: 0 });
  eq(round([Math.max(...oval.filter((_, i) => i % 2 === 0))]), [2]);
  eq(padPolygon({ s: "custom", x: 0, y: 0, w: 1, h: 1, r: 0, poly: [0, 0, 1, 0, 1, 1] }), [0, 0, 1, 0, 1, 1]);
});

Deno.test("an arc goes the way that passes through its middle point", () => {
  // a half circle from (2,0) over the top (0,2) to (-2,0), then the same the other way, through the bottom
  const over = arcPoints(2, 0, 0, 2, -2, 0);
  eq(over.slice(0, 2), [2, 0]);
  eq(round(over.slice(-2)), [-2, 0]);
  eq(over.filter((_, i) => i % 2 === 1).every((y) => y >= -1e-9), true, "stays above");
  const under = arcPoints(2, 0, 0, -2, -2, 0);
  eq(under.filter((_, i) => i % 2 === 1).every((y) => y <= 1e-9), true, "stays below");
  eq(arcPoints(0, 0, 1, 1, 2, 2), [0, 0, 2, 2]);                               // three points on a line
  for (let i = 0; i < over.length; i += 2) eq(close(Math.hypot(over[i], over[i + 1]), 2, 1e-6), true);
});

Deno.test("the outline is chained into closed loops", () => {
  const square = [["l", 0, 0, 10, 0, 0.1], ["l", 10, 0, 10, 5, 0.1], ["l", 10, 5, 0, 5, 0.1], ["l", 0, 5, 0, 0, 0.1]];
  const loops = edgeLoops(square);
  eq(loops.length, 1);
  eq(loops[0].length, 10);                                                       // 4 corners + back to the start
  // segments in any order and direction still make one loop
  const shuffled = [square[2], ["l", 0, 0, 0, 5, 0.1], square[0], ["l", 10, 5, 10, 0, 0.1]];
  eq(edgeLoops(shuffled).length, 1);
  // a rectangle with a round hole: two loops; an open path is dropped
  eq(edgeLoops([...square, ["c", 5, 2.5, 1, 0.1, 0]]).length, 2);
  eq(edgeLoops([["l", 0, 0, 10, 0, 0.1], ["l", 10, 0, 10, 5, 0.1]]).length, 0);
  // a rounded corner: two lines and an arc that meet
  const rounded = [["l", 0, 0, 8, 0, 0.1], ["a", 8, 0, 9.414, 0.586, 10, 2, 0.1], ["l", 10, 2, 10, 8, 0.1], ["l", 10, 8, 0, 8, 0.1], ["l", 0, 8, 0, 0, 0.1]];
  eq(edgeLoops(rounded).length, 1);
});

Deno.test("board <-> screen is a round trip, in every orientation and when flipped", () => {
  for (const flip of [false, true]) {
    for (const rot of [0, 90, 180, 270]) {
      const view = { bbox: [10, 20, 50, 40], rot, flip, scale: 7.5, panX: 13, panY: -9, w: 800, h: 500 };
      for (const [x, y] of [[10, 20], [50, 40], [33.3, 27.1]]) {
        const [sx, sy] = boardToScreen(view, x, y);
        const [bx, by] = screenToBoard(view, sx, sy);
        eq(close(bx, x, 1e-9) && close(by, y, 1e-9), true, `flip=${flip} rot=${rot}`);
      }
    }
  }
  // the back is looked at mirrored: the left edge of the board is on the right of the screen
  const front = boardToScreen({ bbox: [0, 0, 10, 10], rot: 0, flip: false, scale: 10, panX: 0, panY: 0, w: 200, h: 200 }, 0, 5);
  const back = boardToScreen({ bbox: [0, 0, 10, 10], rot: 0, flip: true, scale: 10, panX: 0, panY: 0, w: 200, h: 200 }, 0, 5);
  eq([front[0] < 100, back[0] > 100], [true, true]);
});

Deno.test("fit makes the board fill the view, also when turned", () => {
  eq(round([fitScale([0, 0, 100, 50], 0, 1000, 600, 0)]), [10]);            // width limits
  eq(round([fitScale([0, 0, 100, 50], 90, 1000, 600, 0)]), [6]);            // turned: 50 wide, 100 tall -> height limits
});

Deno.test("a click picks the part on top: this side first, then the smallest box", () => {
  const fp = (ref, side, bbox, attr = [], pads = []) => ({ ref, side, bbox, attr, pads });
  const model = { footprints: [
    fp("U1", "F", [0, 0, 20, 20]), fp("C1", "F", [5, 5, 8, 7]), fp("C2", "B", [5, 5, 8, 7]),
    fp("J1", "F", [30, 0, 40, 5], ["through_hole"], [{ L: "FB" }]),
  ] };
  eq(hitFootprint(model, 6, 6, "F"), "C1");        // the small part sits on top of the big one
  eq(hitFootprint(model, 15, 15, "F"), "U1");
  eq(hitFootprint(model, 6, 6, "B"), "C2");        // from the back the back part wins
  eq(hitFootprint(model, 35, 2, "B"), "J1");       // a through-hole part shows from both sides
  eq(hitFootprint(model, 100, 100, "F"), null);
});

Deno.test("stroke widths sit in different places per primitive", () => {
  eq([primWidth(["l", 0, 0, 1, 1, 0.2]), primWidth(["c", 0, 0, 1, 0.3, 0]), primWidth(["p", [0, 0, 1, 0, 1, 1], 0.4, 0]), primWidth(["a", 0, 0, 1, 1, 2, 0, 0.5])],
    [0.2, 0.3, 0.4, 0.5]);
});

Deno.test("the print picture of a board can be drawn (the pick list prints it)", () => {
  // no browser here: a canvas whose 2D context accepts any call, and remembers the text that was drawn
  const drawn = [];
  const ctx = new Proxy({}, {
    get: (t, k) => (k === "fillText" || k === "strokeText" ? (s) => drawn.push(s) : k in t ? t[k] : () => {}),
    set: (t, k, v) => { t[k] = v; return true; },
  });
  globalThis.document = { createElement: () => ({ getContext: () => ctx }) };
  const model = {
    bbox: [0, 0, 40, 30], edge: [["l", 0, 0, 40, 0, 0.1], ["l", 40, 0, 40, 30, 0.1], ["l", 40, 30, 0, 30, 0.1], ["l", 0, 30, 0, 0, 0.1]],
    gfx: { "F.SilkS": [["t", "R1", 20, 15, 0, 1, 1, 0.15, 0, 0, 0, 0]] },
    footprints: [{ ref: "R1", value: "10k", fpid: "R", x: 20, y: 15, rot: 0, side: "F", attr: "smd", bbox: [19, 14, 21, 16],
      pads: [{ n: "1", s: "rect", x: 19.5, y: 15, w: 1, h: 1, r: 0, L: "F" }] }],
    tracks: {}, vias: [], zones: {},
  };
  const canvas = PcbView.renderImage(model, { side: "F", refs: true, width: 400, height: 300 });
  eq(canvas.width, 400);
  eq(drawn.includes("R1"), true);
  PcbView.renderImage(model, { side: "B", rot: 90, refs: false, width: 400, height: 300 });   // the back, turned, no names
});
