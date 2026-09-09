// "Look up" on a part: query a supplier API, then copy chosen fields onto the part.
import { api } from "./api.js";
import { el, modal, toast } from "./ui.js";

const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
const ALIAS = {
  value: ["resistance", "capacitance", "inductance", "value", "frequency"],
  voltage: ["voltagerating", "voltage", "voltagedc", "ratedvoltage"],
  tolerance: ["tolerance"],
  power: ["powerrating", "power", "powerw"],
  tempchar: ["temperaturecoefficient", "dielectric", "tempchar"],
  dielectric: ["dielectric", "dielectricmaterial"],
  mounting: ["mountingstyle", "mounting", "packagingtype", "termination"],
  pitch: ["pitch", "leadpitch", "leadspacing"],
  pincount: ["numberofpins", "pincount", "pins"],
  current_rating: ["currentrating", "currentcontinuous", "ratedcurrent"],
};

function guessField(attrName, fields) {
  const a = norm(attrName);
  for (const f of fields) {
    if (norm(f.label) === a || norm(f.key) === a) return f.key;
    if ((ALIAS[f.key] || []).some((al) => a.includes(al) || al.includes(a))) return f.key;
  }
  for (const f of fields) if (a.includes(norm(f.label)) || norm(f.label).includes(a)) return f.key;
  return "";
}

export async function openLookup(part, classFields, onApplied) {
  const provs = (await api("/api/lookup/providers")).filter((p) => p.configured);
  const provSel = el("select");
  if (!provs.length) provSel.append(el("option", {}, "— no API keys set (Settings) —"));
  else provs.forEach((p) => provSel.append(el("option", { value: p.name }, p.label)));

  const mpnInput = el("input", { type: "text", value: part.mpn || part.name || "", style: "flex:1" });
  const outHost = el("div");
  const body = el("div", { class: "modal-body" },
    el("div", { class: "row" }, el("label", {}, "Provider"), provSel),
    el("div", { class: "row" }, el("label", {}, "MPN"), mpnInput,
      el("button", { class: "primary", onclick: search }, "Search")),
    outHost,
  );

  const m = modal({ title: `Look up “${part.name}”`, wide: true, body, confirmText: "Close", onConfirm: () => {} });
  let chosen = null;
  const applyState = { manufacturer: false, description: false, datasheet: false, image: false, supplier: false, map: {} };

  async function search() {
    if (!provs.length) return toast("Add an API key in Settings first");
    outHost.innerHTML = "loading…";
    try {
      const { results } = await api("/api/lookup", { method: "POST", body: { provider: provSel.value, mpn: mpnInput.value.trim() } });
      render(results);
    } catch (e) {
      outHost.innerHTML = "";
      outHost.append(el("div", { style: "color:var(--warn)" }, e.message));
    }
  }

  function render(results) {
    outHost.innerHTML = "";
    if (!results.length) return void outHost.append(el("div", { class: "hint" }, "No match."));
    chosen = results[0];
    const r = chosen;
    if (results.length > 1) {
      const pick = el("select", { onchange: (e) => { chosen = results[e.target.value]; render(results); } });
      results.forEach((x, i) => pick.append(el("option", { value: i }, `${x.mpn} — ${x.manufacturer || ""}`)));
      pick.value = String(results.indexOf(chosen));
      outHost.append(el("div", { class: "row" }, el("label", {}, "Match"), pick));
    }

    outHost.append(el("div", { style: "display:flex;gap:12px;margin:8px 0" },
      r.image_url ? el("div", { class: "img-mat", style: "width:80px;height:80px;flex:none" }, el("img", { src: r.image_url })) : null,
      el("div", {},
        el("div", {}, el("b", {}, r.mpn), " · ", r.manufacturer || "?"),
        el("div", { class: "sub", style: "color:var(--text-muted)" }, r.description || ""),
        el("div", { class: "sub", style: "color:var(--text-faint)" },
          [r.lifecycle, r.in_stock != null ? `${r.in_stock} in stock` : null,
           r.unit_price ? `${r.unit_price.ex_vat} ${r.unit_price.currency} ex VAT` : null].filter(Boolean).join("  ·  ")),
        el("div", {}, r.datasheet_url ? el("a", { href: r.datasheet_url, target: "_blank" }, "datasheet ") : "",
          r.product_url ? el("a", { href: r.product_url, target: "_blank" }, " product page") : ""),
      ),
    ));

    const fchecks = el("div", { style: "display:flex;flex-wrap:wrap;gap:12px;margin:6px 0" });
    for (const [k, lbl, avail] of [
      ["manufacturer", "Manufacturer", r.manufacturer],
      ["description", "Description", r.description],
      ["datasheet", "Datasheet URL", r.datasheet_url],
      ["image", "Image", r.image_url],
      ["supplier", `Add ${r.provider} as supplier`, r.sku || r.unit_price],
    ]) {
      if (!avail) continue;
      const cb = el("input", { type: "checkbox", checked: "checked", onchange: (e) => (applyState[k] = e.target.checked) });
      applyState[k] = true;
      fchecks.append(el("label", { class: "facet-opt" }, cb, " ", lbl));
    }
    outHost.append(fchecks);

    // parameter mapping
    const attrs = Object.entries(r.attributes || {});
    if (attrs.length && classFields.length) {
      outHost.append(el("div", { class: "section-title" }, "Parameters → this part’s fields"));
      const t = el("table", { class: "mini-table" });
      t.append(el("tr", {}, el("th", {}, ""), el("th", {}, "Mouser attribute"), el("th", {}, "Value"), el("th", {}, "Fill field")));
      applyState.map = {};
      for (const [an, av] of attrs) {
        const guess = guessField(an, classFields);
        const sel = el("select", { onchange: (e) => setMap(an, av, e.target.value) },
          el("option", { value: "" }, "— ignore —"),
          ...classFields.map((f) => el("option", { value: f.key }, f.label + (f.unit ? ` (${f.unit})` : ""))));
        sel.value = guess;
        const cb = el("input", { type: "checkbox", checked: guess ? "checked" : null,
          onchange: (e) => { if (e.target.checked) setMap(an, av, sel.value); else delete applyState.map[keyOf(sel.value)]; } });
        if (guess) setMap(an, av, guess);
        t.append(el("tr", {}, el("td", {}, cb), el("td", {}, an), el("td", {}, String(av)), el("td", {}, sel)));
      }
      outHost.append(t);
    }

    outHost.append(el("div", { style: "margin-top:12px;text-align:right" },
      el("button", { class: "primary", onclick: apply }, "Apply selected")));
  }

  function keyOf(fieldKey) { return fieldKey; }
  function setMap(_an, av, fieldKey) {
    if (!fieldKey) return;
    // last mapping wins per target field; strip unit words lightly for numbers
    applyState.map[fieldKey] = String(av).trim();
  }

  async function apply() {
    if (!chosen) return;
    const res = await api(`/api/parts/${part.id}/apply-lookup`, {
      method: "POST",
      body: {
        result: chosen,
        apply: {
          manufacturer: applyState.manufacturer, description: applyState.description,
          datasheet: applyState.datasheet, image: applyState.image, supplier: applyState.supplier,
          attributes: applyState.map,
        },
      },
    });
    toast("Applied: " + (res.changed.join(", ") || "nothing"));
    m.close();
    onApplied && onApplied();
  }
}
