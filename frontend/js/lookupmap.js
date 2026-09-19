// Mapping of a supplier's attribute names (Mouser / Digi-Key) onto our own part-class
// fields. Kept apart from the dialog so it can be tested on its own.

export const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
export const slug = (s) => norm(s).slice(0, 40) || "attr";

// our field key -> normalised aliases seen in Mouser/other attribute names.
// Mouser decorates names a lot ("Voltage - Supply", "Current - Output (Max)",
// "Number of I/O") so entries are matched as substrings after norm().
export const ALIAS = {
  value: ["resistance", "capacitance", "inductance", "frequency", "clockfrequency", "speed", "currentaveragerectified", "io"],
  voltage: ["voltagerating", "voltage", "voltagedc", "ratedvoltage", "workingvoltage", "voltagereverse", "vr", "vrrm", "breakdownvoltage", "vdss", "drainsourcevoltage"],
  tolerance: ["tolerance"],
  power: ["powerrating", "power", "powermax", "powerdissipation", "ptot"],
  tempchar: ["temperaturecoefficient", "tempchar", "dielectric"],
  dielectric: ["dielectric", "dielectricmaterial", "dielectriccharacteristic"],
  mounting: ["mountingstyle", "mounting", "mountingtype", "terminationstyle", "packagingtype", "packagetype"],
  pitch: ["pitch", "leadpitch", "leadspacing", "pinpitch", "contactpitch"],
  pincount: ["numberofpins", "pincount", "pins", "numberofcontacts", "numberofpositions", "numberofio", "numberofterminations", "numberofcircuits", "circuits"],
  current_rating: ["currentrating", "currentcontinuous", "ratedcurrent", "currentoutput", "currentmax", "currentcontinuousdrain", "id", "if", "currentaveragerectified"],
  esr: ["esr", "equivalentseriesresistance", "dcr", "dcresistance", "impedance"],
  ripple_current: ["ripplecurrent", "ripple"],
  series: ["series", "productseries", "family"],
  lifetime_hours: ["lifetime", "loadlife", "usefullife", "operationallife"],
  breaking_capacity: ["breakingcapacity", "interruptingrating"],
  resistor_type: ["resistortype", "composition", "resistivematerial", "technology"],
  dimensions: ["sizedimension", "dimensions"],
  fuse_type: ["fusetype", "type", "response", "blowcharacteristic", "speed"],
  operating_temp_min: ["operatingtemperaturemin", "minimumoperatingtemperature", "tmin"],
  operating_temp_max: ["operatingtemperaturemax", "maximumoperatingtemperature", "tmax"],
  maxtemp: ["maxtemp"],
  vcc_min: ["voltagesupplymin", "supplyvoltagemin", "vccmin", "vsmin"],
  vcc_max: ["voltagesupplymax", "supplyvoltagemax", "vccmax", "vsmax"],
  icc: ["currentsupply", "supplycurrent", "icc", "quiescentcurrent", "iq", "quiescent"],
  hfe: ["dccurrentgain", "currentgain", "hfe"],
  frequency: ["frequency", "clockfrequency", "speed", "maxoperatingfrequency", "bandwidth", "coresize"],
  flash: ["memorysize", "flashsize", "programmemorysize", "programmemory"],
  ram: ["ramsize", "sramsize", "datamemorysize", "ram"],
  interface: ["interface", "connectivity", "peripherals"],
  function: ["function", "type", "amplifiertype", "regulatortopology", "coreprocessor"],
  vds: ["vdss", "drainsourcevoltage", "vds"],
  vgsth: ["vgsth", "gatethresholdvoltage"],
  rdson: ["rdson", "drainsourceonresistance"],
  vf: ["voltageforward", "vf"],
  vz: ["voltagezener", "vz"],
  body_diameter: ["diameter", "bodydiameter"],
  body_length: ["bodylength", "length"],
  body_width: ["bodywidth", "width"],
  body_height: ["height", "heightseated", "bodyheight", "thickness"],
};

// Aliases shorter than this only count on an EXACT match. Substring matching with
// "io", "id", "if", "vr" ... is what sent "Composition", "Size / Dimension" and
// "Number of Terminations" (all containing "io") onto the resistance field.
const MIN_ALIAS_SUBSTR = 4;
// ...and an attribute name that is merely a fragment of an alias needs to be long enough to mean it
const MIN_NAME_FRAGMENT = 5;

// how sure the guess is: 4 label/key equals the name, 3 exact alias, 2 alias inside the name, 1 label inside the name
export function scoreField(attrName, fields) {
  const a = norm(attrName);
  for (const f of fields) if (norm(f.label) === a || norm(f.key) === a) return { key: f.key, score: 4 };
  for (const f of fields) if ((ALIAS[f.key] || []).some((al) => a === al)) return { key: f.key, score: 3 };
  for (const f of fields) {
    const hit = (ALIAS[f.key] || []).some((al) =>
      (al.length >= MIN_ALIAS_SUBSTR && a.includes(al)) || (a.length >= MIN_NAME_FRAGMENT && al.includes(a)));
    if (hit) return { key: f.key, score: 2 };
  }
  for (const f of fields) {
    const l = norm(f.label);
    if (l && ((l.length >= MIN_ALIAS_SUBSTR && a.includes(l)) || (a.length >= MIN_NAME_FRAGMENT && l.includes(a))))
      return { key: f.key, score: 1 };
  }
  return { key: "", score: 0 };
}

export const guessField = (attrName, fields) => scoreField(attrName, fields).key;

// Two ticked parameters must never fill the same field - the later one silently
// overwrote the earlier, so a resistor ended up with "Resistance = 2R" (the number
// of terminations). The best guess keeps the field; the others fall back to
// "keep as <name>" (still saved, just not in that field). Unticked rows don't compete.
export function resolveCollisions(rows, recompute) {
  const best = new Map();
  for (const r of rows) {
    if (!r.field || r.include === false) continue;
    const b = best.get(r.field);
    if (!b || (r.score ?? 0) > (b.score ?? 0)) best.set(r.field, r);
  }
  for (const r of rows) {
    if (!r.field || r.include === false || best.get(r.field) === r) continue;
    r.field = "";
    recompute(r);
  }
}
