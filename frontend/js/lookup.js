// "Look up" on a part: query a supplier API, then copy chosen fields onto the part.
import { api } from "./api.js";
import { el, modal, toast, spinner, withBusy } from "./ui.js";
import { formatValue, valueKind } from "./units.js";

const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
const slug = (s) => norm(s).slice(0, 40) || "attr";
const ALIAS = {
  value: ["resistance", "capacitance", "inductance", "value", "frequency", "currentrating"],
  voltage: ["voltagerating", "voltage", "voltagedc", "ratedvoltage", "dcvoltagerating", "workingvoltage"],
  tolerance: ["tolerance"],
  power: ["powerrating", "power", "powerw"],
  tempchar: ["temperaturecoefficient", "tempchar", "dielectric"],
  dielectric: ["dielectric", "dielectricmaterial", "dielectriccharacteristic"],
  mounting: ["mountingstyle", "mounting", "packagingtype", "terminationstyle", "mountingtype"],
  pitch: ["pitch", "leadpitch", "leadspacing"],
  pincount: ["numberofpins", "pincount", "pins", "numberofcontacts", "numberofpositions"],
  current_rating: ["currentrating", "currentcontinuous", "ratedcurrent", "current"],
  esr: ["esr", "equivalentseriesresistance", "dcr", "dcresistance"],
  ripple_current: ["ripplecurrent", "ripple"],
  series: ["series", "productseries", "family"],
  lifetime_hours: ["lifetime", "loadlife", "usefullife"],
  breaking_capacity: ["breakingcapacity", "interruptingrating"],
  fuse_type: ["fusetype", "response", "blowcharacteristic", "speed"],
  operating_temp_min: ["operatingtemperaturemin", "mintemp", "minimumoperatingtemperature", "tmin"],
  operating_temp_max: ["operatingtemperaturemax", "maxtemp", "maximumoperatingtemperature", "tmax"],
  maxtemp: ["maxtemp", "maximumoperatingtemperature", "tmax"],
  body_diameter: ["diameter", "bodydiameter"],
  body_length: ["length", "bodylength", "height"],
};

function guessField(attrName, fields) {
  const a = norm(attrName);
  for (const f of fields) if (norm(f.label) === a || norm(f.key) === a) return f.key;
  for (const f of fields) if ((ALIAS[f.key] || []).some((al) => a === al)) return f.key;
  for (const f of fields) if ((ALIAS[f.key] || []).some((al) => a.includes(al) || al.includes(a))) return f.key;
  for (const f of fields) if (norm(f.label) && (a.includes(norm(f.label)) || norm(f.label).includes(a))) return f.key;
  return "";
}

function splitRange(v) {
  const m = String(v).match(/(-?\d+(?:\.\d+)?)\s*°?\s*C?\s*(?:~|to|\.\.\.?|–|—|-)\s*(\+?-?\d+(?:\.\d+)?)/i);
  return m ? [m[1].replace("+", ""), m[2].replace("+", "")] : null;
}
const TEMP_RANGE_ATTR = /operating temp|temperature range|temp\.? range|working temp/i;

export async function openLookup(part, classFields, onApplied) {
  const cls = part.part_class;
  const provs = (await api("/api/lookup/providers")).filter((p) => p.configured);
  const provSel = el("select");
  if (!provs.length) provSel.append(el("option", {}, "— no API keys set (Settings) —"));
  else provs.forEach((p) => provSel.append(el("option", { value: p.name }, p.label)));

  const mpnInput = el("input", { type: "text", value: part.mpn || part.name || "", style: "flex:1" });
  const searchBtn = el("button", { class: "primary", onclick: search }, "Search");
  const outHost = el("div");
  const body = el("div", { class: "modal-body" },
    el("div", { class: "row" }, el("label", {}, "Provider"), provSel),
    el("div", { class: "row" }, el("label", {}, "MPN"), mpnInput, searchBtn),
    outHost,
  );

  const m = modal({ title: `Look up “${part.name}”`, wide: true, body, confirmText: "Close", onConfirm: () => {} });
  let chosen = null;
  const flags = { manufacturer: true, description: true, datasheet: true, image: true, supplier: true, lifecycle: true, category: false, category_id: null, mount: false, mount_value: null };
  let rows = []; // [{name, raw, field, converted, include}]

  async function search() {
    if (!provs.length) return toast("Add an API key in Settings first");
    outHost.innerHTML = "";
    outHost.append(spinner(`Searching ${provSel.selectedOptions[0].text}…`));
    try {
      await withBusy(searchBtn, async () => {
        const res = await api("/api/lookup", { method: "POST", body: { provider: provSel.value, mpn: mpnInput.value.trim() } });
        render(res.results);
      });
    } catch (e) {
      outHost.innerHTML = "";
      outHost.append(el("div", { style: "color:var(--warn)" }, e.message));
    }
  }

  function mkRow(name, raw) {
    const field = guessField(name, classFields);
    const kind = field ? valueKind(cls, field) : "num";
    let converted = field ? formatValue(raw, kind) : String(raw);
    if (field === "tempchar" && /np0|c0g|npo/i.test(String(raw))) converted = "C0G (NP0)";
    return { name, raw, field, kind, converted, include: true };
  }

  function buildRows(r) {
    rows = [];
    for (const [name, raw] of Object.entries(r.attributes || {})) {
      const rng = TEMP_RANGE_ATTR.test(name) && splitRange(raw);
      if (rng) {
        rows.push(mkRow(name + " (min)", rng[0]));
        rows.push(mkRow(name + " (max)", rng[1]));
        rows[rows.length - 2].field = pickKey("operating_temp_min", classFields);
        rows[rows.length - 1].field = pickKey("operating_temp_max", classFields);
        rows.push({ ...mkRow(name, raw), include: false }); // keep the raw range too, unchecked
      } else {
        rows.push(mkRow(name, raw));
      }
    }
  }
  function pickKey(key, fields) {
    return fields.some((f) => f.key === key) ? key : "";
  }

  function render(results) {
    outHost.innerHTML = "";
    if (!results.length) return void outHost.append(el("div", { class: "hint" }, "No match."));
    chosen = results[0];
    if (results.length > 1) {
      const pick = el("select", { onchange: (e) => { chosen = results[+e.target.value]; buildRows(chosen); paint(results); } });
      results.forEach((x, i) => pick.append(el("option", { value: i }, `${x.mpn} — ${x.manufacturer || ""}  (${x.attr_count} params)`)));
      outHost.append(el("div", { class: "row" }, el("label", {}, `Match (${results.length})`), pick));
    }
    buildRows(chosen);
    paint(results);
  }

  function paint(results) {
    // drop everything after the (optional) match picker
    while (outHost.children.length > (results.length > 1 ? 1 : 0)) outHost.lastChild.remove();
    const r = chosen;

    outHost.append(el("div", { style: "display:flex;gap:12px;margin:8px 0" },
      r.image_url ? el("div", { class: "img-mat", style: "width:82px;height:82px;flex:none" }, el("img", { src: r.image_url })) : null,
      el("div", {},
        el("div", {}, el("b", {}, r.mpn), " · ", r.manufacturer || "?"),
        el("div", { style: "color:var(--text-muted)" }, r.description || ""),
        el("div", { style: "color:var(--text-faint);font-size:12px" },
          [r.lifecycle, r.in_stock != null ? `${r.in_stock} in stock` : null,
           r.unit_price ? `${r.unit_price.ex_vat} ${r.unit_price.currency} ex VAT · ${r.unit_price.inc_vat_ceil} inc` : null].filter(Boolean).join("  ·  ")),
        el("div", {}, r.datasheet_url ? el("a", { href: r.datasheet_url, target: "_blank" }, "datasheet") : "",
          r.product_url ? el("a", { href: r.product_url, target: "_blank", style: "margin-left:10px" }, "product page") : ""),
        r.category_hint ? el("div", { style: "color:var(--text-faint);font-size:12px" },
          `category: ${r.category_hint}` + (r.category_match ? `  →  ${r.category_match.path}` : "  (no tree match)")) : null,
      ),
    ));

    const fchecks = el("div", { style: "display:flex;flex-wrap:wrap;gap:14px;margin:6px 0" });
    const items = [
      ["manufacturer", "Manufacturer", r.manufacturer],
      ["description", "Description", r.description],
      ["datasheet", "Datasheet URL", r.datasheet_url],
      ["image", "Image", r.image_url],
      ["supplier", `Add ${r.provider} as supplier`, r.sku || r.unit_price],
      ["lifecycle", "Mark discontinued if EOL", r.lifecycle],
    ];
    if (r.category_match) {
      flags.category = true;
      flags.category_id = r.category_match.id;
      fchecks.append(el("label", { class: "facet-opt" },
        el("input", { type: "checkbox", checked: "checked", onchange: (e) => (flags.category = e.target.checked) }),
        ` Category → ${r.category_match.path}`));
    } else {
      flags.category = false;
    }
    if (r.mount_guess) {
      flags.mount = true;
      flags.mount_value = r.mount_guess;
      fchecks.append(el("label", { class: "facet-opt" },
        el("input", { type: "checkbox", checked: "checked", onchange: (e) => (flags.mount = e.target.checked) }),
        ` Mount → ${r.mount_guess.toUpperCase()}`));
    } else {
      flags.mount = false;
    }
    for (const [k, lbl, avail] of items) {
      if (!avail) { flags[k] = false; continue; }
      flags[k] = true;
      fchecks.append(el("label", { class: "facet-opt" },
        el("input", { type: "checkbox", checked: "checked", onchange: (e) => (flags[k] = e.target.checked) }), " ", lbl));
    }
    outHost.append(fchecks);

    if (rows.length) {
      outHost.append(el("div", { class: "section-title" }, `Parameters (${rows.length}) — all selected by default`));
      if (rows.length < 4)
        outHost.append(el("div", { class: "hint" }, "Mouser's API sometimes returns fewer parameters than the website; extra ones parsed from the description are included."));
      const t = el("table", { class: "mini-table" });
      t.append(el("tr", {}, el("th", {}, "✓"), el("th", {}, `${chosen.provider} attribute`), el("th", {}, "Value"),
        el("th", {}, "→ field"), el("th", {}, "Stored as")));
      rows.forEach((row) => {
        const cb = el("input", { type: "checkbox", checked: "checked", onchange: (e) => (row.include = e.target.checked) });
        const sel = el("select", { onchange: (e) => { row.field = e.target.value; recompute(row); storedCell.textContent = row.converted; } },
          el("option", { value: "" }, "— keep as ‘" + slug(row.name) + "’ —"),
          ...classFields.map((f) => el("option", { value: f.key }, f.label + (f.unit ? ` (${f.unit})` : ""))));
        sel.value = row.field;
        const storedCell = el("td", {}, row.converted);
        t.append(el("tr", {}, el("td", {}, cb), el("td", {}, row.name), el("td", {}, String(row.raw)), el("td", {}, sel), storedCell));
      });
      outHost.append(t);
    }

    const applyBtn = el("button", { class: "primary", onclick: () => apply(applyBtn) }, "Apply selected");
    outHost.append(el("div", { style: "margin-top:12px;text-align:right" }, applyBtn));
  }

  function recompute(row) {
    row.kind = row.field ? valueKind(cls, row.field) : "num";
    row.converted = row.field ? formatValue(row.raw, row.kind) : String(row.raw);
  }

  async function apply(btn) {
    if (!chosen) return;
    const attributes = {};
    for (const row of rows) {
      if (!row.include) continue;
      const key = row.field || slug(row.name);
      attributes[key] = row.converted;
    }
    await withBusy(btn, async () => {
      const res = await api(`/api/parts/${part.id}/apply-lookup`, {
        method: "POST",
        body: { result: chosen, apply: { ...flags, attributes } },
      });
      toast("Applied: " + (res.changed.join(", ") || "nothing"));
      m.close();
      onApplied && onApplied();
    }).catch((e) => toast(e.message));
  }
}
