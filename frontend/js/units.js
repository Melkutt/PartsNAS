// Value formatting: engineering notation split on thousands, resistor RKM style.
//   capacitor / inductor / crystal:  0.1uF -> 100nF ,  1000pF -> 1nF
//   resistor:                        2200  -> 2k2  ,  4.7 -> 4R7 , 1e6 -> 1M
// Plain numeric fields (voltage, tolerance, ...) just get the unit stripped.

const PREFIX = { p: 1e-12, n: 1e-9, u: 1e-6, "µ": 1e-6, "μ": 1e-6, m: 1e-3, "": 1, k: 1e3, K: 1e3, M: 1e6, G: 1e9 };

// "0.1 uF", "100nF", "4700", "10 kOhms", "50 V", "2k2", "4R7", "470R", "1M"
export function parseMagnitude(raw) {
  if (raw == null) return null;
  let s = String(raw).trim().replace(",", ".");
  if (!s) return null;
  // RKM: <int?><letter><frac?>   2k2 | 4R7 | 470R | R47 | 1M
  let m = s.match(/^(\d*)\s*([RrkKMmGpnµμu])\s*(\d*)$/);
  if (m && (m[1] || m[3])) {
    const mult = m[2] === "R" || m[2] === "r" ? 1 : PREFIX[m[2]] ?? 1;
    const num = parseFloat((m[1] || "0") + "." + (m[3] || "0"));
    return num * mult;
  }
  // <number><prefix?><unit?>
  m = s.match(/^([-+]?[\d.]+)\s*([pnuµμmkKMG]?)\s*([a-zA-ZΩ%/]*)$/);
  if (m && m[1] !== "" && !isNaN(parseFloat(m[1]))) {
    return parseFloat(m[1]) * (PREFIX[m[2]] ?? 1);
  }
  return null;
}

function trimMantissa(x, digits = 3) {
  let s = x.toFixed(digits);
  if (s.indexOf(".") >= 0) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s;
}

function formatEng(value, unit) {
  if (value === 0) return "0" + unit;
  const steps = [[1e9, "G"], [1e6, "M"], [1e3, "k"], [1, ""], [1e-3, "m"], [1e-6, "µ"], [1e-9, "n"], [1e-12, "p"]];
  for (const [base, sym] of steps) {
    const mant = value / base;
    if (Math.abs(mant) >= 1 && Math.abs(mant) < 1000) return trimMantissa(mant) + sym + unit;
  }
  return trimMantissa(value / 1e-12) + "p" + unit;
}

function formatRKM(value) {
  let base = 1, sym = "R";
  if (Math.abs(value) >= 1e6) { base = 1e6; sym = "M"; }
  else if (Math.abs(value) >= 1e3) { base = 1e3; sym = "k"; }
  const mant = value / base;
  const whole = Math.trunc(mant);
  const fracNum = Math.round((Math.abs(mant) - Math.abs(whole)) * 100);
  const frac = fracNum ? String(fracNum).padStart(2, "0").replace(/0+$/, "") : "";
  return frac ? `${whole}${sym}${frac}` : `${whole}${sym}`;
}

const KIND_UNIT = { farads: "F", henries: "H", hertz: "Hz" };

// cls = part_class id, key = attribute key
export function valueKind(cls, key) {
  if (key !== "value") return "num";
  return { resistor: "ohms", capacitor: "farads", inductor: "henries", crystal: "hertz" }[cls] || "num";
}

export function formatValue(raw, kind) {
  const v = parseMagnitude(raw);
  if (v == null) return String(raw ?? "").trim();
  if (kind === "ohms") return formatRKM(v);
  if (KIND_UNIT[kind]) return formatEng(v, KIND_UNIT[kind]);
  return trimMantissa(v, 6); // plain number, unit stripped
}

// price entry: accept "179,1" or "179.1"; NaN -> null
export function parseNum(s) {
  if (s == null || s === "") return null;
  const n = parseFloat(String(s).replace(",", ".").replace(/\s/g, ""));
  return isNaN(n) ? null : n;
}

// AWG -> conductor cross-section in mm² (3 sig figs).
//   "24 AWG" / "AWG 24" / "24AWG"      -> "0.205"
//   "26-28 AWG" / "AWG 26 to 28"       -> "0.081 - 0.129"  (ascending mm²)
// d(mm) = 0.127 · 92^((36−AWG)/39) ; area = π/4 · d²
function _awgArea(awg) {
  if (isNaN(awg) || awg < 0 || awg > 50) return null;
  const d = 0.127 * Math.pow(92, (36 - awg) / 39);
  return (Math.PI / 4) * d * d;
}
const _sig3 = (x) => Number(x.toPrecision(3)).toString();

export function awgToMm2(v) {
  const s = String(v);
  const rng = s.match(
    /(\d{1,2})\s*(?:-|–|—|~|to)\s*(\d{1,2})\s*awg|awg\s*(\d{1,2})\s*(?:-|–|—|~|to)\s*(\d{1,2})/i,
  );
  if (rng) {
    const a = _awgArea(parseInt(rng[1] || rng[3], 10));
    const b = _awgArea(parseInt(rng[2] || rng[4], 10));
    if (a == null || b == null) return null;
    return `${_sig3(Math.min(a, b))} - ${_sig3(Math.max(a, b))}`;
  }
  const m = s.match(/awg\s*(\d{1,2})|(\d{1,2})\s*awg/i);
  if (!m) return null;
  const area = _awgArea(parseInt(m[1] || m[2], 10));
  return area == null ? null : _sig3(area);
}
export const isAwg = (v) => /\bawg\s*\d{1,2}\b|\b\d{1,2}\s*awg\b/i.test(String(v || ""));
