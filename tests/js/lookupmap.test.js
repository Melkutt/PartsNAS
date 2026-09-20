// Tests for the supplier-attribute -> class-field mapping (frontend/js/lookupmap.js).
//   deno test --allow-read tests/js
//
// The fixture is 399 attribute names as Mouser / Digi-Key really return them, so a change
// to the alias table is checked against real vocabulary rather than invented examples.
import { ALIAS, guessField, resolveCollisions, scoreField } from "../../frontend/js/lookupmap.js";

const read = (p) => JSON.parse(Deno.readTextFileSync(new URL(p, import.meta.url)));
const NAMES = read("./fixtures/supplier_attribute_names.json");

// the schema the app serves: part_classes.json with part_classes_extra.json merged on top
// (same rules as backend/app/partschema.py)
function loadSchema() {
  const base = read("../../seed/part_classes.json");
  const extra = read("../../seed/part_classes_extra.json");
  const shared = extra._shared || [];
  delete extra._shared;
  const merge = (baseFields, extraFields) => {
    const byKey = new Map(extraFields.map((f) => [f.key, f]));
    const seen = new Set();
    const out = baseFields.map((f) => { seen.add(f.key); return byKey.get(f.key) || f; });
    for (const f of extraFields) if (!seen.has(f.key)) out.push(f);
    return out;
  };
  for (const [id, fields] of Object.entries(extra)) {
    base[id] ??= { id, label: id, fields: [] };
    base[id].fields = merge(base[id].fields, fields);
  }
  for (const c of Object.values(base)) c.fields = merge(c.fields, shared);
  return base;
}
const CLASSES = loadSchema();
const F = (cls) => CLASSES[cls].fields;

function eq(actual, expected, msg = "") {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${msg}\n  expected: ${JSON.stringify(expected)}\n  actual:   ${JSON.stringify(actual)}`);
  }
}

Deno.test("resistor: the four attributes from the bug report", () => {
  // Composition / Size / Number of Terminations all contain "io" and used to land on Resistance
  eq(guessField("Resistance", F("resistor")), "value");
  eq(guessField("Composition", F("resistor")), "resistor_type");
  eq(guessField("Size / Dimension", F("resistor")), "dimensions");
  eq(guessField("Number of Terminations", F("resistor")), "");
});

Deno.test("resistor: the everyday attributes", () => {
  const want = {
    "Tolerance": "tolerance",
    "Power Rating": "power",
    "Temperature Coefficient": "tempcoeff",
    "Termination Style": "mounting",
    "Series": "series",
    "Packaging": "",
  };
  for (const [name, field] of Object.entries(want)) eq(guessField(name, F("resistor")), field, name);
});

Deno.test("an alias must not match in the middle of a word", () => {
  // "Voltage - Input (Max)" is "...inputmax" = "...tmax": it was offered as "Operating temp max"
  const ic = F("ic");
  eq(guessField("Voltage - Input (Max)", ic), "", "Voltage - Input (Max)");
  eq(guessField("Voltage - Dropout (Max)", ic), "", "Voltage - Dropout (Max)");
  eq(guessField("Height (Max)", ic), "", "Height (Max)");
  eq(guessField("Current - Output (Max)", ic), "", "Current - Output (Max)");
  // ...while the real temperature range still maps
  eq(guessField("Operating Temperature", ic).startsWith("operating_temp"), true, "Operating Temperature");
  // "Bandwidth" contains "width", "Wavelength" contains "length"
  eq(guessField("Bandwidth", F("capacitor")), "", "Bandwidth");
  eq(guessField("Wavelength", F("resistor")), "", "Wavelength");
  eq(guessField("Serial Interfaces", ic), "interface", "Serial Interfaces");
  // a lone junction temperature ("150°C (TJ)") is a ceiling: it filled "min" on 13 parts
  eq(guessField("Operating Temperature - Junction", F("transistor_bjt")), "operating_temp_max", "junction");
});

Deno.test("every alias table entry belongs to a field some class really has", () => {
  // `current_rating` was written for a field that is called `currentrating`: the aliases never applied
  const real = new Set(Object.values(CLASSES).flatMap((c) => c.fields.map((f) => f.key)));
  const dead = Object.keys(ALIAS).filter((k) => !real.has(k));
  eq(dead, ["function"], "alias keys that no class has (known: 'function')");
});

Deno.test("real-life inductor / connector current rating", () => {
  eq(guessField("Current Rating (Amps)", F("inductor")), "currentrating");
  eq(guessField("Current Rating (Amps)", F("connector")), "currentrating");
  eq(guessField("Output", F("connector")), "", "a bare 'Output' is not a current");
});

Deno.test("no alias shorter than 4 characters may match by substring", () => {
  for (const [cls, c] of Object.entries(CLASSES)) {
    for (const name of ["Composition", "Size / Dimension", "Number of Terminations", "Operating Temperature - Junction"]) {
      const { key, score } = scoreField(name, c.fields);
      if (key && score === 2) {
        const norm = name.toLowerCase().replace(/[^a-z0-9]/g, "");
        const hit = (ALIAS[key] || []).find((al) => norm.includes(al));
        if (hit && hit.length < 4) throw new Error(`${cls}: "${name}" -> ${key} via the short alias "${hit}"`);
      }
    }
  }
});

Deno.test("for R / C / L / crystal, only value-like names land on the component value", () => {
  // (in other classes `value` is an enum such as "Channel" or "Function", so it is matched by label)
  const ok = /resist|capacit|induct|frequen|speed|clock|current|voltage|power|impedance|value|type|dcr|output|diode/i;
  const offenders = [];
  for (const cls of ["resistor", "capacitor", "inductor", "crystal"]) {
    const c = CLASSES[cls];
    for (const n of NAMES) {
      if (guessField(n, c.fields) === "value" && !ok.test(n)) offenders.push(`${cls}: ${n}`);
    }
  }
  eq(offenders, [], "attributes that should not be a component value");
});

Deno.test("every name maps to a field the class really has, or to nothing", () => {
  for (const [cls, c] of Object.entries(CLASSES)) {
    const keys = new Set(c.fields.map((f) => f.key));
    for (const n of NAMES) {
      const k = guessField(n, c.fields);
      if (k && !keys.has(k)) throw new Error(`${cls}: "${n}" -> ${k}, which the class does not have`);
    }
  }
});

Deno.test("collisions: the best guess keeps the field, the rest become 'keep as ...'", () => {
  const recomputed = [];
  const rows = [
    { name: "Frequency", field: "value", score: 3, include: true },
    { name: "Speed", field: "value", score: 2, include: true },
    { name: "Unticked", field: "value", score: 9, include: false }, // does not compete
  ];
  resolveCollisions(rows, (r) => recomputed.push(r.name));
  eq(rows.map((r) => r.field), ["value", "", "value"]);
  eq(recomputed, ["Speed"]);
});

Deno.test("collisions: the Mouser resistor page ends with one row per field", () => {
  const attrs = ["Resistance", "Tolerance", "Power Rating", "Temperature Coefficient", "Composition",
    "Size / Dimension", "Number of Terminations", "Termination Style", "Packaging"];
  const rows = attrs.map((name) => ({ name, ...scoreField(name, F("resistor")), field: scoreField(name, F("resistor")).key, include: true }));
  resolveCollisions(rows, () => {});
  const used = rows.map((r) => r.field).filter(Boolean);
  eq(used.length, new Set(used).size, "two rows share a field");
});
