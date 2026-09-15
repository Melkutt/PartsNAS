// Settings modal: supplier API credentials + auto-categorisation rules.
import { api } from "./api.js";
import { el, modal, toast, treeOptions } from "./ui.js";

export async function openSettings() {
  const [rows, ruleData, catOpts, bomRules, logoData] = await Promise.all([
    api("/api/settings/providers"),
    api("/api/meta/attr-rules"),
    treeOptions("/api/categories", { includeBlank: "— category —" }),
    api("/api/bom/match-rules"),
    api("/api/settings/logo"),
  ]);
  const body = el("div", { class: "modal-body" });
  body.append(
    el("p", { style: "color:var(--text-muted);margin:0" },
      "Credentials are stored on the NAS (single-user). Lookups only run when you press ‘Look up’ on a part — never in bulk. Each provider is rate-limited, disk-cached and auto-paused if it returns a block."),
  );

  const inputs = {}; // name -> { fields:{}, priceChk, priceWas }
  for (const p of rows) {
    inputs[p.name] = { fields: {}, priceWas: p.price_enabled };
    const status = p.blocked_until
      ? el("span", { style: "color:var(--warn)" }, `paused until ${new Date(p.blocked_until * 1000).toLocaleTimeString()}`)
      : el("span", { style: "color:var(--text-faint)" }, p.configured ? `ready · ${p.used_today}/${p.quota_day} today · ${p.per_min}/min` : "not configured");
    const block = el("div", { style: "border-top:1px solid var(--border);padding-top:10px;margin-top:10px" },
      el("div", { style: "display:flex;gap:8px;align-items:baseline" },
        el("b", {}, p.label),
        el("a", { href: p.website, target: "_blank", style: "font-size:12px" }, "site"),
        el("span", { style: "flex:1" }), status));
    for (const f of p.cred_fields) {
      const inp = el("input", { type: "password", style: "flex:1",
        placeholder: f.from_env ? "(set via environment)" : f.stored ? "•••••• stored — type to replace" : "paste " + f.name,
        disabled: f.from_env ? "disabled" : null });
      inputs[p.name].fields[f.name] = inp;
      block.append(el("div", { class: "row", style: "margin-top:6px" },
        el("label", { style: "min-width:100px" }, f.name.replace(/_/g, " ")), inp));
    }
    const priceChk = el("input", { type: "checkbox", checked: p.price_enabled ? "checked" : null });
    inputs[p.name].priceChk = priceChk;
    block.append(el("label", { class: "facet-opt", style: "margin-top:6px",
      title: "included when you press ‘Fetch prices from all APIs’ on a part" },
      priceChk, " search prices from here"));
    body.append(block);
  }

  // ---- company logo ----
  body.append(el("div", { class: "section-title", style: "margin-top:16px" }, "Company logo"));
  body.append(el("div", { class: "hint" }, "Shown on printed Quotes/Invoices. Uploads immediately."));
  const logoPreview = el("img", { class: "quote-logo", src: logoData.logo_url || "",
    style: logoData.logo_url ? "" : "display:none" });
  const logoFile = el("input", { type: "file", accept: "image/*" });
  const removeLogoBtn = el("button", { class: "ghost", style: logoData.logo_url ? "" : "display:none",
    onclick: async () => {
      await api("/api/settings/logo", { method: "DELETE" });
      logoPreview.style.display = "none";
      removeLogoBtn.style.display = "none";
      logoFile.value = "";
      toast("Logo removed");
    } }, "Remove logo");
  logoFile.addEventListener("change", async () => {
    const f = logoFile.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/api/settings/logo", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) return toast("Error: " + (data.detail || res.statusText));
    logoPreview.src = data.logo_url;
    logoPreview.style.display = "";
    removeLogoBtn.style.display = "";
    toast("Logo uploaded");
  });
  body.append(el("div", { class: "row", style: "align-items:center;gap:10px" }, logoPreview, logoFile, removeLogoBtn));

  // ---- auto-categorisation rules ----
  body.append(el("div", { class: "section-title", style: "margin-top:16px" }, "Auto-categorisation rules"));
  body.append(el("div", { class: "repl-banner" },
    el("b", {}, "⚠ Handle with care. "),
    "These run first when you press Look up. If a rule's text appears anywhere in a " +
    "part's attributes, it forces that category. A broad word (“Capacitor”, “SMD”, “Chip”) " +
    "will mis-file lots of parts — use a distinctive value: ",
    el("code", {}, "MLCC"), ", ", el("code", {}, "WCAP-ATG"), ", ", el("code", {}, "N-Channel"),
    ". Tick “regex” only if you know regular expressions."));

  const ruleHost = el("div");
  const ruleRows = [];
  const mkRuleRow = (r = {}) => {
    const pat = el("input", { type: "text", value: r.pattern || "", placeholder: "attribute text, e.g. WCAP-ATG", style: "flex:1;min-width:120px" });
    const rx = el("input", { type: "checkbox", checked: r.regex ? "checked" : null, title: "match as a regular expression" });
    const cat = el("select", { style: "min-width:150px" });
    cat.append(...catOpts.map((o) => o.cloneNode(true)));
    if (r.category_id) cat.value = String(r.category_id);
    const note = el("input", { type: "text", value: r.note || "", placeholder: "note (optional)", style: "flex:1;min-width:100px" });
    const row = el("div", { class: "row", style: "flex-wrap:wrap;gap:6px;align-items:center" },
      pat, el("label", { title: "regex" }, rx, " re"), cat, note,
      el("button", { class: "ghost", onclick: () => { const i = ruleRows.indexOf(entry); if (i >= 0) ruleRows.splice(i, 1); row.remove(); } }, "✕"));
    const entry = { row, pat, rx, cat, note };
    ruleRows.push(entry);
    ruleHost.append(row);
  };
  (ruleData.rules || []).forEach(mkRuleRow);
  body.append(ruleHost, el("button", { class: "ghost", onclick: () => mkRuleRow() }, "+ add rule"));
  if (ruleData.builtin?.length)
    body.append(el("div", { class: "hint" },
      "Built-in examples (always active, lower priority): " +
      ruleData.builtin.slice(0, 6).map((b) => `${b.pattern.replace(/\\b|\(\?i\)/g, "")} → ${b.category}`).join(" · ") + " …"));

  // ---- remembered BOM Value+Footprint matches ----
  body.append(el("div", { class: "section-title", style: "margin-top:16px" }, "Remembered BOM matches"));
  body.append(el("div", { class: "hint" },
    "Confirmed once during a BOM import (Value + Footprint → part) and applied automatically after that. Remove one here if it was wrong."));
  const bomHost = el("div");
  const renderBomRules = () => {
    bomHost.innerHTML = "";
    if (!bomRules.length) return bomHost.append(el("div", { class: "pill-off" }, "none yet"));
    const t = el("table", { class: "mini-table" });
    t.append(el("tr", {}, el("th", {}, "Value"), el("th", {}, "Footprint"), el("th", {}, "→ Part"), el("th", {}, "")));
    for (const r of bomRules) {
      t.append(el("tr", {},
        el("td", {}, r.value),
        el("td", { style: "max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" }, r.footprint),
        el("td", {}, r.part_name),
        el("td", {}, el("button", { class: "ghost", onclick: async () => {
          await api(`/api/bom/match-rules/${r.id}`, { method: "DELETE" });
          bomRules.splice(bomRules.indexOf(r), 1);
          renderBomRules();
        } }, "✕"))));
    }
    bomHost.append(t);
  };
  renderBomRules();
  body.append(bomHost);

  modal({
    title: "Settings",
    body,
    confirmText: "Save",
    onConfirm: async () => {
      let n = 0;
      for (const [name, o] of Object.entries(inputs)) {
        const creds = {};
        for (const [fld, inp] of Object.entries(o.fields)) {
          if (!inp.disabled && inp.value.trim()) creds[fld] = inp.value.trim();
        }
        const b = {};
        if (Object.keys(creds).length) b.creds = creds;
        if (o.priceChk.checked !== o.priceWas) b.price_enabled = o.priceChk.checked;
        if (Object.keys(b).length) { await api(`/api/settings/providers/${name}`, { method: "PUT", body: b }); n++; }
      }
      const rules = ruleRows
        .filter((e) => e.pat.value.trim() && e.cat.value)
        .map((e) => ({ pattern: e.pat.value.trim(), regex: e.rx.checked, category_id: Number(e.cat.value), note: e.note.value.trim() }));
      const res = await api("/api/meta/attr-rules", { method: "PUT", body: { rules } });
      toast(`Saved ${n} provider(s), ${res.count} rule(s)`);
    },
  });
}
