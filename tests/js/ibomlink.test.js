// deno test --allow-read tests/js
import { highlightRefs, linesFromPcbdata, onBoardClick, splitRefs } from "../../frontend/js/ibomlink.js";

function eq(actual, expected, msg = "") {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${msg}\n  expected: ${JSON.stringify(expected)}\n  actual:   ${JSON.stringify(actual)}`);
  }
}

// the shape of a real ibom.html (BGA2802 board): groups of [reference, footprintIndex], and one
// list of fields per footprint index, in the order of config.fields
const PCBDATA = {
  bom: {
    both: [
      [["C3", 15], ["C1", 10], ["C2", 22]],
      [["C6", 9], ["C10", 2], ["C8", 6]],
      [["U1", 3]],
    ],
    fields: {
      10: ["10n", "C_0402_1005Metric_Pad0.74x0.62mm_HandSolder", "MPN-A"],
      9: ["1u", "C_0402_1005Metric_Pad0.74x0.62mm_HandSolder", ""],
      3: ["MIC5504-3.3YM5", "SOT-23-5", "MIC5504"],
    },
  },
  footprints: [],
};

Deno.test("the parts list is read from the page's own data", () => {
  const lines = linesFromPcbdata(PCBDATA, ["Value", "Footprint"]);
  eq(lines.map((l) => [l.refdes, l.value, l.qty]), [["C1 C2 C3", "10n", 3], ["C6 C8 C10", "1u", 3], ["U1", "MIC5504-3.3YM5", 1]]);
  eq(lines[0].footprint, "C_0402_1005Metric_Pad0.74x0.62mm_HandSolder");
  eq(lines[0].mpn, "");
});

Deno.test("an MPN column is picked up whatever it is called", () => {
  for (const name of ["MPN", "Manufacturer Part Number", "Mfr Part No", "PN"]) {
    const lines = linesFromPcbdata(PCBDATA, ["Value", "Footprint", name]);
    eq(lines[2].mpn, "MIC5504", name);
  }
});

Deno.test("data that does not look like that gives null, never an exception", () => {
  eq(linesFromPcbdata(null, ["Value"]), null);
  eq(linesFromPcbdata({}, ["Value"]), null);
  eq(linesFromPcbdata({ bom: { both: [], fields: {} } }, ["Value"]), null);
  eq(linesFromPcbdata(PCBDATA, ["Quantity"]), null);          // neither value nor footprint
  eq(linesFromPcbdata({ bom: { both: [[["C1", 1]]], fields: {} } }, ["Value"]), null);
});

Deno.test("references are split like the KiCad BOM writes them", () => {
  eq(splitRefs("C6 C8, C10"), ["C6", "C8", "C10"]);
  eq(splitRefs(""), []);
  eq(splitRefs(null), []);
});

Deno.test("highlighting uses the page's own row handler when there is one", () => {
  const called = [];
  const cell = (t) => ({ textContent: t });
  const row = (id, refs) => ({ id, querySelectorAll: () => [cell("1"), cell(refs), cell("1u")] });
  const w = {
    document: { querySelectorAll: () => [row("bomrow1", "C1, C2, C3"), row("bomrow2", "C6, C8, C10")] },
    highlightHandlers: [{ id: "bomrow1", handler: () => called.push(1) }, { id: "bomrow2", handler: () => called.push(2) }],
    pcbdata: { footprints: [] },
  };
  eq(highlightRefs(w, ["C8"]), true);
  eq(called, [2]);
});

Deno.test("...and marks the footprints itself when it does not", () => {
  let drawn = 0;
  const w = {
    document: { querySelectorAll: () => [] },
    pcbdata: { footprints: [{ ref: "R1" }, { ref: "C5" }, { ref: "C6" }] },
    highlightedFootprints: [],
    drawHighlights: () => drawn++,
  };
  eq(highlightRefs(w, ["C5", "C6"]), true);
  eq(w.highlightedFootprints, [1, 2]);
  eq(drawn, 1);
  eq(highlightRefs(w, ["X99"]), false);
  eq(highlightRefs({}, ["C1"]), false);                        // a page of another shape: no exception
});

Deno.test("a click on the board is reported with the references", () => {
  const w = { pcbdata: { footprints: [{ ref: "C9" }, { ref: "R2" }] }, highlightedFootprints: [] };
  w.footprintsClicked = (idx) => { w.highlightedFootprints = idx; return "orig"; };
  const seen = [];
  eq(onBoardClick(w, (refs) => seen.push(refs)), true);
  eq(w.footprintsClicked([0]), "orig");                        // the page still behaves as before
  eq(seen, [["C9"]]);
  eq(onBoardClick({}, () => {}), false);
});
