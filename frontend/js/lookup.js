// "Look up" on a part: query a supplier API, then copy chosen fields onto the part.
import { api } from "./api.js";
import { el, modal, toast, spinner, withBusy, treeOptions } from "./ui.js";
import { formatValue, valueKind, awgToMm2, isAwg } from "./units.js";
import { norm, slug, scoreField, resolveCollisions } from "./lookupmap.js";

// Mouser attribute-name -> our "<base>" for a min/max field pair (if the class
// has <base>_min and <base>_max), matched loosely.
const RANGE_BASES = {
  operating_temp: ["operatingtemperature", "temperaturerange", "temprange", "workingtemperature"],
  vcc: ["voltagesupply", "supplyvoltage", "voltagesupplyvccvdd"],
};

function splitRange(v) {
  const m = String(v).match(/([-+]?\d+(?:\.\d+)?)\s*[^\d~.\-–—]*\s*(?:~|to|\.\.\.?|–|—|-)\s*([-+]?\d+(?:\.\d+)?)/i);
  return m ? [m[1].replace("+", ""), m[2].replace("+", "")] : null;
}

// if an attr name matches a known range base and the class has *_min/*_max, return that base
function rangeBaseFor(attrName, fields) {
  const a = norm(attrName);
  const keys = new Set(fields.map((f) => f.key));
  for (const [base, als] of Object.entries(RANGE_BASES)) {
    if (!keys.has(base + "_min") || !keys.has(base + "_max")) continue;
    if (als.some((al) => a.includes(al))) return base;
  }
  return null;
}

export async function openLookup(part, classFields, onApplied) {
  const cls = part.part_class;
  const [provsAll, catOpts] = await Promise.all([
    api("/api/lookup/providers"),
    treeOptions("/api/categories", { includeBlank: "— pick a category —" }),
  ]);
  const provs = provsAll.filter((p) => p.configured);
  const provSel = el("select", {
    onchange: () => localStorage.setItem("partsnas.lookupProvider", provSel.value),
  });
  if (!provs.length) provSel.append(el("option", {}, "— no API keys set (Settings) —"));
  else provs.forEach((p) => provSel.append(el("option", { value: p.name }, p.label)));
  const rememberedProv = localStorage.getItem("partsnas.lookupProvider");
  if (rememberedProv && [...provSel.options].some((o) => o.value === rememberedProv))
    provSel.value = rememberedProv;

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
        localStorage.setItem("partsnas.lookupProvider", provSel.value);
        const res = await api("/api/lookup", { method: "POST", body: { provider: provSel.value, mpn: mpnInput.value.trim() } });
        render(res.results);
      });
    } catch (e) {
      outHost.innerHTML = "";
      outHost.append(el("div", { style: "color:var(--warn)" }, e.message));
    }
  }

  // Text and enum fields keep the supplier's words ("2.3 mm x 6.3 mm" must not be
  // parsed as the number 2.3); an enum is snapped to its option's spelling when one matches.
  function convert(raw, field) {
    const f = classFields.find((x) => x.key === field);
    if (f && (f.type === "text" || f.type === "enum")) {
      const s = String(raw ?? "").trim();
      const opt = (f.options || []).find((o) => norm(o) === norm(s));
      return opt || s;
    }
    return formatValue(raw, valueKind(cls, field));
  }

  function mkRow(name, raw) {
    const { key: field, score } = scoreField(name, classFields);
    const kind = field ? valueKind(cls, field) : "num";
    let converted = field ? convert(raw, field) : String(raw);
    if (field === "tempchar" && /np0|c0g|npo/i.test(String(raw))) converted = "C0G (NP0)";
    return { name, raw, field, kind, converted, include: true, score };
  }

  function buildRows(r) {
    rows = [];
    for (const [name, raw] of Object.entries(r.attributes || {})) {
      const base = rangeBaseFor(name, classFields);
      const rng = base && splitRange(raw);
      if (rng) {
        const lo = mkRow(name + " (min)", rng[0]);
        const hi = mkRow(name + " (max)", rng[1]);
        lo.field = base + "_min";
        hi.field = base + "_max";
        lo.score = hi.score = 5; // deliberate, not a guess
        recompute(lo);
        recompute(hi);
        rows.push(lo, hi, { ...mkRow(name, raw), include: false }); // keep the raw range, unchecked
      } else {
        rows.push(mkRow(name, raw));
        if (isAwg(raw)) {
          const mm2 = awgToMm2(raw);
          if (mm2) {
            const extra = mkRow(name + " (mm²)", mm2);
            extra.field = classFields.some((f) => f.key === "cross_section") ? "cross_section" : "";
            extra.score = 5;
            rows.push(extra);
          }
        }
      }
    }
    resolveCollisions(rows, recompute);
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
    // Category — always offer a control. Auto-matched -> preselected; otherwise
    // the raw supplier text is shown and you pick from the tree yourself.
    {
      const sel = el("select", { onchange: (e) => {
        flags.category_id = Number(e.target.value) || null;
        flags.category = !!flags.category_id;
      } });
      sel.append(...catOpts.map((o) => o.cloneNode(true)));
      sel.value = r.category_match ? String(r.category_match.id) : "";
      flags.category = !!r.category_match;
      flags.category_id = r.category_match ? r.category_match.id : null;
      outHost.append(el("div", { class: "row", style: "margin:4px 0" },
        el("label", {}, "Category"),
        sel,
        el("span", { style: "color:var(--text-faint);font-size:12px" },
          r.category_hint
            ? (r.category_match ? `matched from “${r.category_hint}”` : `supplier: “${r.category_hint}” — no auto-match`)
            : ""),
      ));
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
    row.converted = row.field ? convert(row.raw, row.field) : String(row.raw);
  }

  async function apply(btn) {
    if (!chosen) return;
    const attributes = {};
    const from = {};
    for (const row of rows) {
      if (!row.include) continue;
      const key = row.field || slug(row.name);
      if (key in attributes) {
        const label = classFields.find((f) => f.key === key)?.label || key;
        return toast(`“${from[key]}” and “${row.name}” both go to ${label} — the second would overwrite the first. ` +
          "Untick one, or set it to ‘keep as …’.");
      }
      attributes[key] = row.converted;
      from[key] = row.name;
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
