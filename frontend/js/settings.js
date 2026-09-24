// Settings modal: supplier API credentials + auto-categorisation rules.
import { api } from "./api.js";
import { el, modal, toast, treeOptions, selectWithAdd, partSearch } from "./ui.js";
import { parseNum } from "./units.js";

const CURRENCIES = ["SEK", "NOK", "DKK", "EUR", "USD", "GBP", "CHF"];

export async function openSettings() {
  const [rows, ruleData, catOpts, bomRules, logoData, footerData, defaultsData, swishData, autoData] = await Promise.all([
    api("/api/settings/providers"),
    api("/api/meta/attr-rules"),
    treeOptions("/api/categories", { includeBlank: "— category —" }),
    api("/api/bom/match-rules"),
    api("/api/settings/logo"),
    api("/api/settings/footer"),
    api("/api/settings/defaults"),
    api("/api/settings/swish"),
    api("/api/settings/autosnapshot"),
  ]);
  const body = el("div", { class: "modal-body" });
  body.append(
    el("p", { style: "color:var(--text-muted);margin:0" },
      "Credentials are stored on the NAS (single-user). Lookups only run when you press ‘Look up’ on a part — never in bulk. Each provider is rate-limited, disk-cached and auto-paused if it returns a block."),
  );

  // ---- defaults (currency + VAT %) ----
  body.append(el("div", { class: "section-title" }, "Defaults"));
  body.append(el("div", { class: "hint" },
    "Used for new quotes, stock entries and supplier prices whenever nothing more specific says otherwise. Saved immediately."));
  const curDefaults = { ...defaultsData };
  const saveDefaults = async () => {
    await api("/api/settings/defaults", { method: "PUT", body: curDefaults });
    toast("Defaults saved");
  };
  const currencySel = selectWithAdd(curDefaults.currency, CURRENCIES, async (v) => {
    curDefaults.currency = v;
    await saveDefaults();
  }, { addLabel: "+ Add other…", addTitle: "Add a currency code" });
  const vatInput = el("input", { type: "text", inputmode: "decimal", style: "width:80px", value: String(curDefaults.vat_percent),
    onchange: async () => {
      curDefaults.vat_percent = parseNum(vatInput.value) ?? curDefaults.vat_percent;
      vatInput.value = String(curDefaults.vat_percent);
      await saveDefaults();
    } });
  body.append(
    el("div", { class: "row", style: "align-items:center;gap:16px;flex-wrap:wrap" },
      el("label", { style: "display:flex;gap:6px;align-items:center" }, "Currency", currencySel),
      el("label", { style: "display:flex;gap:6px;align-items:center" }, "VAT %", vatInput)),
  );

  const inputs = {}; // name -> { fields:{}, priceChk, priceWas }
  for (const p of rows) {
    inputs[p.name] = { fields: {}, priceWas: p.price_enabled };
    const status = p.blocked_until
      ? el("span", { style: "color:var(--warn)" }, `paused until ${new Date(p.blocked_until * 1000).toLocaleTimeString()}`)
      : el("span", { style: "color:var(--text-faint)" }, p.configured ? `ready · ${p.used_today}/${p.quota_day} today · ${p.per_min}/min` : "not configured");
    const resetBtn = p.blocked_until
      ? el("button", { class: "ghost", style: "font-size:12px;padding:2px 8px",
          title: "Only useful if the pause was tripped by a bug (bad signature, wrong parameter) rather than a real block — a real block will just trip again",
          onclick: async () => {
            await api(`/api/settings/providers/${p.name}/reset`, { method: "POST" });
            toast(`${p.label} reset`);
            handle.close();
            openSettings();
          } }, "Reset")
      : null;
    const block = el("div", { style: "border-top:1px solid var(--border);padding-top:10px;margin-top:10px" },
      el("div", { style: "display:flex;gap:8px;align-items:baseline" },
        el("b", {}, p.label),
        el("a", { href: p.website, target: "_blank", style: "font-size:12px" }, "site"),
        el("span", { style: "flex:1" }), status, resetBtn));
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

  // ---- KiCad footprint rules ----
  const kicadRules = await api("/api/kicad/rules");
  body.append(el("div", { class: "section-title", style: "margin-top:16px" }, "KiCad footprint rules"));
  body.append(el("div", { class: "hint" },
    "Turn a package text into a KiCad footprint. A rule matches when ALL its patterns (regular expressions, any case) match: " +
    "Case = the supplier's Package / Case, Device = its Supplier Device Package, Footprint = your own Footprint text. " +
    "Scope = a word the category must contain. Tick 'guess' for a rule that only assumes the common variant: it is proposed unticked. " +
    "Your rules are tried first, then the built-in ones. A new part gets its KiCad footprint from a certain rule straight away."));
  const rulesHost = el("div");
  const ruleRowsK = [];
  const addRuleRow = (r = {}) => {
    const w = r.when || {};
    const f = (v, ph, wd) => el("input", { type: "text", value: v || "", placeholder: ph, style: `width:${wd}px` });
    const row = { id: f(r.id, "name", 90), case_: f(w.case, "Case pattern", 150), device: f(w.device, "Device pattern", 120),
      raw: f(w.raw, "Footprint pattern", 110), scope: f(r.scope, "Scope", 70), fp: f(r.footprint, "Library:Footprint", 260),
      guess: el("input", { type: "checkbox", checked: r.assumed ? "checked" : null, title: "only a guess of the common variant" }) };
    row.el = el("div", { class: "row", style: "gap:4px;align-items:center;flex-wrap:wrap;margin-top:4px" },
      row.id, row.case_, row.device, row.raw, row.scope, row.fp, el("label", { style: "display:flex;gap:3px;align-items:center" }, row.guess, "guess"),
      el("button", { class: "ghost", title: "Remove this rule", onclick: () => { ruleRowsK.splice(ruleRowsK.indexOf(row), 1); row.el.remove(); } }, "✕"));
    ruleRowsK.push(row);
    rulesHost.append(row.el);
  };
  kicadRules.user.forEach(addRuleRow);
  body.append(rulesHost);
  body.append(el("div", { class: "row", style: "margin-top:6px;align-items:center;gap:12px" },
    el("button", { class: "ghost", onclick: () => addRuleRow() }, "+ Add rule"),
    el("span", { class: "hint", style: "padding:0" }, `${kicadRules.defaults.length} built-in rules`)));
  const builtin = el("details", { style: "margin-top:4px" }, el("summary", { class: "hint" }, "Show the built-in rules"));
  const bt = el("table", { class: "mini-table", style: "width:100%;margin-top:4px" });
  bt.append(el("tr", {}, el("th", {}, "Rule"), el("th", {}, "Matches"), el("th", {}, "KiCad footprint")));
  for (const r of kicadRules.defaults) {
    const w = r.when || {};
    bt.append(el("tr", {}, el("td", {}, (r.assumed ? "⚠ " : "") + r.id),
      el("td", { style: "font-family:monospace;font-size:11px" }, Object.entries(w).map(([k, v]) => `${k}: ${v}`).join("   ")),
      el("td", {}, r.footprint)));
  }
  builtin.append(bt);
  body.append(builtin);

  // ---- automatic backup ----
  body.append(el("div", { class: "section-title", style: "margin-top:16px" }, "Automatic backup"));
  body.append(el("div", { class: "hint" },
    "Once a day the app saves a full snapshot (the same file as Export → Snapshot) into a folder and keeps the newest few. " +
    "The folder is a path inside the container: the default sits next to your data on the NAS. To save to another NAS folder, " +
    "map it as a volume in docker-compose.yml and enter its container path here. The snapshot contains your API keys — keep the folder private."));
  const autoOn = el("input", { type: "checkbox" });
  const autoFolder = el("input", { type: "text", style: "flex:1", placeholder: autoData.default_folder });
  const autoKeep = el("input", { type: "text", inputmode: "numeric", style: "width:4em" });
  const autoHour = el("select");
  for (let h = 0; h < 24; h++) autoHour.append(el("option", { value: String(h) }, `${String(h).padStart(2, "0")}:00`));
  const autoStatus = el("div", { class: "hint", style: "padding:4px 0" });
  const autoFiles = el("div", { class: "hint", style: "padding:0 0 4px" });
  const fmtBytes = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
  const paintAuto = (d) => {
    autoOn.checked = !!d.config.enabled;
    autoFolder.value = d.config.folder;
    autoKeep.value = String(d.config.keep);
    autoHour.value = String(d.config.hour);
    const st = d.state || {};
    autoStatus.innerHTML = "";
    autoStatus.style.color = st.last_error ? "var(--warn)" : "";
    if (st.last_error) autoStatus.append(el("b", {}, "Last backup failed: "), st.last_error);
    else if (st.last_ok_at) autoStatus.append(`Last backup: ${new Date(st.last_ok_at).toLocaleString()} · ${st.last_file} (${fmtBytes(st.last_bytes || 0)})`);
    else autoStatus.append(d.config.enabled ? "Waiting for the first backup." : "Off - no automatic backups are made.");
    autoFiles.textContent = d.files.length
      ? `${d.files.length} in ${d.folder_resolved}: ` + d.files.slice(0, 4).map((f) => `${f.name.replace(/^partsnas-auto-|\.zip$/g, "")} (${fmtBytes(f.bytes)})`).join(" · ") + (d.files.length > 4 ? " …" : "")
      : `Folder: ${d.folder_resolved}`;
  };
  paintAuto(autoData);
  const saveAuto = async () => {
    try {
      const d = await api("/api/settings/autosnapshot", { method: "PUT", body: {
        enabled: autoOn.checked, folder: autoFolder.value.trim() || autoData.default_folder,
        keep: Math.max(1, Math.round(parseNum(autoKeep.value) ?? 7)), hour: Number(autoHour.value) } });
      paintAuto(d);
      toast(d.config.enabled ? "Automatic backup saved" : "Automatic backup is off");
    } catch (e) {
      toast(e.message);
    }
  };
  const runAuto = async (btn) => {
    btn.disabled = true;
    try {
      await saveAuto();   // back up into the folder as it is entered now
      const d = await api("/api/settings/autosnapshot/run", { method: "POST" });
      paintAuto(d);
      toast(`Backup saved: ${d.file} (${fmtBytes(d.bytes)})`);
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
    }
  };
  const runBtn = el("button", { onclick: () => runAuto(runBtn) }, "Back up now");
  body.append(
    el("div", { class: "row", style: "align-items:center;gap:10px" },
      el("label", { style: "display:flex;gap:6px;align-items:center" }, autoOn, "Back up every day at"), autoHour,
      el("span", { class: "hint", style: "padding:0" }, "(the NAS's clock)")),
    el("div", { class: "row", style: "align-items:center;gap:10px" }, el("label", {}, "Folder"), autoFolder),
    el("div", { class: "row", style: "align-items:center;gap:10px" }, el("label", {}, "Keep the newest"), autoKeep,
      el("span", { class: "hint", style: "padding:0" }, "backups; older ones are deleted"),
      el("span", { style: "flex:1" }),
      el("button", { class: "primary", onclick: saveAuto }, "Save backup settings"), runBtn),
    autoStatus, autoFiles);

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

  // ---- invoice footer ----
  body.append(el("div", { class: "section-title", style: "margin-top:16px" }, "Invoice footer"));
  body.append(el("div", { class: "hint" }, "Your name, address and payment options — printed at the bottom of every Quote/Invoice. Saved automatically."));
  const footerTa = el("textarea", { rows: 4, style: "width:100%", placeholder: "e.g.\nJohn Doe\n123 Main St, 12345 Anytown\nSwish: 070-000 00 00",
    onchange: async () => {
      await api("/api/settings/footer", { method: "PUT", body: { text: footerTa.value } });
      toast("Footer saved");
    } }, footerData.text || "");
  body.append(footerTa);
  const swishInp = el("input", { type: "text", inputmode: "tel", placeholder: "070-123 45 67", style: "width:170px",
    value: swishData.number,
    onchange: async () => {
      try {
        const r = await api("/api/settings/swish", { method: "PUT", body: { number: swishInp.value } });
        swishInp.value = r.number;
        toast(r.number ? "Swish number saved" : "Swish QR turned off");
      } catch (e) {
        toast("Error: " + e.message);
      }
    } });
  body.append(el("div", { class: "row", style: "align-items:center;gap:10px;margin-top:6px" },
    el("label", { title: "Invoices in SEK get a Swish QR in the footer's right corner, pre-filled with the total and the invoice number. Leave empty to turn it off." },
      "Swish number"), swishInp,
    el("span", { class: "hint", style: "padding:0" }, "adds a payment QR to printed invoices")));

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
        el("td", { style: "white-space:nowrap" },
          el("button", { class: "ghost", title: "Point this Value + Footprint at another part (voltage, NP0 / X7R, fuse style ...)",
            onclick: (e) => {
              const cell = e.target.closest("tr").children[2];
              cell.innerHTML = "";
              cell.append(partSearch({ placeholder: "search part…", onPick: async (p) => {
                try {
                  await api(`/api/bom/match-rules/${r.id}`, { method: "PATCH", body: { part_id: p.id } });
                  r.part_id = p.id;
                  r.part_name = p.name;
                  toast(`${r.value} · ${r.footprint} now uses ${p.name}`);
                } catch (err) {
                  toast(err.message);
                }
                renderBomRules();
              } }).el);
            } }, "Change…"),
          el("button", { class: "ghost", onclick: async () => {
          await api(`/api/bom/match-rules/${r.id}`, { method: "DELETE" });
          bomRules.splice(bomRules.indexOf(r), 1);
          renderBomRules();
        } }, "✕"))));
    }
    bomHost.append(t);
  };
  renderBomRules();
  body.append(bomHost);

  const handle = modal({
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
      const kr = ruleRowsK.filter((r) => r.case_.value.trim() || r.device.value.trim() || r.raw.value.trim() || r.fp.value.trim()).map((r) => ({
        id: r.id.value.trim(), when: { case: r.case_.value.trim(), device: r.device.value.trim(), raw: r.raw.value.trim() },
        scope: r.scope.value.trim(), footprint: r.fp.value.trim(), assumed: r.guess.checked }));
      await api("/api/kicad/rules", { method: "PUT", body: { rules: kr } });
      const res = await api("/api/meta/attr-rules", { method: "PUT", body: { rules } });
      toast(`Saved ${n} provider(s), ${res.count} rule(s)`);
    },
  });
}
