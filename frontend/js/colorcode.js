// Resistor colour code: value + tolerance -> the coloured bands on an axial resistor.
// Pure functions (tested in tests/js/colorcode.test.js) plus a small SVG drawing.
import { parseMagnitude } from "./units.js";

const DIGIT = [
  ["black", "#111111"], ["brown", "#7a4a21"], ["red", "#d3202a"], ["orange", "#f08a1c"], ["yellow", "#f2d21b"],
  ["green", "#2f9e44"], ["blue", "#2b6cd4"], ["violet", "#8a3fc7"], ["grey", "#8c8c8c"], ["white", "#f4f4f4"],
];
const GOLD = ["gold", "#c9a227"];
const SILVER = ["silver", "#b9bcc2"];

// tolerance in % -> colour; no band at all means +/-20 %
const TOLERANCE = new Map([
  [0.05, DIGIT[8]], [0.1, DIGIT[7]], [0.25, DIGIT[6]], [0.5, DIGIT[5]],
  [1, DIGIT[1]], [2, DIGIT[2]], [5, GOLD], [10, SILVER],
]);

const band = ([name, hex], role) => ({ name, hex, role });

// The multiplier band for 10^e: black..white for 0..9, gold = x0.1, silver = x0.01.
function multiplier(e) {
  if (e >= 0 && e <= 9) return DIGIT[e];
  if (e === -1) return GOLD;
  if (e === -2) return SILVER;
  return null;
}

/**
 * @param {number} ohms
 * @param {number|null} tolerancePct  e.g. 1, 5 - null when unknown
 * @returns {{bands: {name:string, hex:string, role:string}[], count: number, note: string}|null}
 *          null when the value cannot be written in colour code (0, negative, needs 4+ digits)
 */
export function resistorBands(ohms, tolerancePct = null) {
  if (!Number.isFinite(ohms) || ohms <= 0) return null;
  // 5 bands (3 digits) for the precise resistors, 4 bands (2 digits) otherwise - unless the value
  // needs a third digit, then 5 bands it is
  const wantFive = tolerancePct != null && tolerancePct <= 2;
  const order = wantFive ? [3, 2] : [2, 3];
  for (const digits of order) {
    const e = Math.floor(Math.log10(ohms) + 1e-12) - (digits - 1);
    const d = Math.round(ohms / 10 ** e);
    if (d < 10 ** (digits - 1) || d >= 10 ** digits) continue;
    if (Math.abs(d * 10 ** e - ohms) > ohms * 1e-9) continue;   // not exactly writable with that many digits
    const mult = multiplier(e);
    if (!mult) continue;
    const bands = [...String(d)].map((c) => band(DIGIT[+c], "digit")).concat(band(mult, "multiplier"));
    let note = "";
    if (tolerancePct == null) note = "tolerance unknown - no tolerance band drawn";
    else if (TOLERANCE.has(tolerancePct)) bands.push(band(TOLERANCE.get(tolerancePct), "tolerance"));
    else if (tolerancePct === 20) note = "±20 % has no tolerance band";
    else note = `±${tolerancePct} % has no colour`;
    return { bands, count: digits + 2, note };
  }
  return null;
}

/** "3k3", "3.3 kOhms" -> 3300 (null if it is not a number) */
export function ohmsOf(value) {
  const v = parseMagnitude(value);
  return v == null ? null : v;
}

/** "±1%", "1 %", "0.5" -> 1, 1, 0.5 (null if there is no number) */
export function toleranceOf(text) {
  const m = String(text ?? "").replace(",", ".").match(/(\d+(?:\.\d+)?)/);
  return m ? parseFloat(m[1]) : null;
}

const NS = "http://www.w3.org/2000/svg";

/** A small axial resistor drawn with the given bands, as an <svg> element. */
export function resistorSvg(bands) {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 150 34");
  svg.setAttribute("width", "150");
  svg.setAttribute("height", "34");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", bands.map((b) => b.name).join(", "));
  const add = (tag, attrs) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    svg.append(n);
    return n;
  };
  add("line", { x1: 2, y1: 17, x2: 148, y2: 17, stroke: "#9aa0a6", "stroke-width": 3, "stroke-linecap": "round" });
  add("rect", { x: 26, y: 5, width: 98, height: 24, rx: 10, fill: "#d9c8a0", stroke: "#8a7a55", "stroke-width": 1 });
  // bands are spread evenly over the body; the tolerance band sits a little apart, as on the real thing
  const n = bands.length;
  const x0 = 38, x1 = 108;
  bands.forEach((b, i) => {
    const gap = b.role === "tolerance" ? 10 : 0;
    const x = x0 + (i * (x1 - x0)) / (n - 1 || 1) + gap;
    add("rect", { x: x - 3, y: 5, width: 6, height: 24, fill: b.hex, stroke: "#00000033", "stroke-width": 0.5 });
  });
  return svg;
}
