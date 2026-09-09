// Part detail panel: Details (edit) / Stock / Suppliers / Notes, in a right-side overlay.
import { api } from "./api.js";
import { el, modal, toast, treeOptions, partSearch } from "./ui.js";
import { openLookup } from "./lookup.js";
import { formatValue, valueKind, parseNum } from "./units.js";

let CLASSES = null; // cached /api/meta/part-classes
async function partClasses() {
  if (!CLASSES) CLASSES = await api("/api/meta/part-classes");
  return CLASSES;
}
let ATTR_VALUES = null; // { field_key: [previously used values] }
async function attrValues(force) {
  if (!ATTR_VALUES || force) ATTR_VALUES = await api("/api/meta/attr-values");
  return ATTR_VALUES;
}

const MOUNTS = ["", "smd", "tht", "other"];

// "3,3" -> "3.3" so a comma and a dot don't create two values of the same thing
const commaFix = (v) => (/^-?\d+,\d+$/.test(String(v).trim()) ? String(v).trim().replace(",", ".") : v);

export class PartDetail {
  constructor(id, { onChange } = {}) {
    this.id = id;
    this.onChange = onChange || (() => {});
    this.tab = "details";
  }

  async open() {
    await this._load();
    this.back = el("div", { class: "detail-back", onclick: () => this.close() });
    this.panel = el("div", { class: "detail-panel" });
    document.body.append(this.back, this.panel);
    document.addEventListener("keydown", this._esc);
    this._render();
  }

  close = () => {
    document.removeEventListener("keydown", this._esc);
    this.back?.remove();
    this.panel?.remove();
  };
  _esc = (e) => {
    if (e.key === "Escape" && !document.querySelector(".modal-back")) this.close();
  };

  async _load() {
    [this.p, this.stock, this.suppliers, this.classes, this.attrVals] = await Promise.all([
      api(`/api/parts/${this.id}`),
      api(`/api/parts/${this.id}/stock`),
      api("/api/suppliers"),
      partClasses(),
      attrValues(),
    ]);
  }

  async _reload() {
    await this._load();
    this._render();
    this.onChange();
  }

  _render() {
    this.panel.innerHTML = "";
    const p = this.p;
    this.panel.append(
      el(
        "div",
        { class: "detail-head" },
        el("div", { class: "img-mat thumb" }, p.image_path ? el("img", { src: p.image_path }) : ""),
        el(
          "div",
          { style: "flex:1" },
          el("h3", {}, p.discontinued ? p.name + "  ⚠" : p.name),
          el("div", { class: "sub" }, [p.mpn, p.manufacturer, p.category].filter(Boolean).join("  ·  ") || "—"),
          el("div", { class: "on-hand" }, `On hand: ${p.on_hand}`),
        ),
        el("button", { class: "ghost", onclick: () => this.close() }, "✕"),
      ),
    );
    const repl = this._replLabel();
    if (repl && (p.discontinued || p.on_hand <= 0)) {
      this.panel.append(
        el("div", { class: "repl-banner" },
          el("b", {}, p.on_hand <= 0 ? "Out of stock — discontinued. " : "Discontinued. "),
          `Replaced by ${repl}. `,
          p.replaced_by
            ? el("a", { href: "#", onclick: (e) => { e.preventDefault(); this.close(); new PartDetail(p.replaced_by.id, { onChange: this.onChange }).open(); } }, "Open replacement")
            : null),
      );
    }
    const tabs = el("div", { class: "detail-tabs" });
    const defs = [
      ["details", "Details"],
      ["stock", "Stock"],
      ["suppliers", `Suppliers (${this.suppliers ? p.suppliers.length : 0})`],
      ["notes", `Notes (${p.design_note_count})`],
    ];
    for (const [key, label] of defs) {
      tabs.append(
        el("button", {
          class: this.tab === key ? "active" : "",
          onclick: () => {
            this.tab = key;
            this._render();
          },
        }, label),
      );
    }
    this.panel.append(tabs);
    const body = el("div", { class: "detail-body" });
    this.panel.append(body);
    ({
      details: () => this._details(body),
      stock: () => this._stock(body),
      suppliers: () => this._suppliersTab(body),
      notes: () => this._notes(body),
    })[this.tab]();
  }

  _replLabel() {
    const p = this.p;
    if (p.replaced_by)
      return `${p.replaced_by.name}${p.replaced_by.mpn && p.replaced_by.mpn !== p.replaced_by.name ? " (" + p.replaced_by.mpn + ")" : ""}`;
    if (p.replacement_mpn)
      return `${p.replacement_mpn}${p.replacement_sku ? " · " + p.replacement_sku : ""}`;
    return null;
  }

  // ---------- Details (edit) ----------
  async _details(body) {
    const p = this.p;
    const draft = {
      name: p.name, mpn: p.mpn || "", manufacturer: p.manufacturer || "",
      category_id: p.category_id || "", mount: p.mount || "",
      footprint_raw: p.footprint_raw || "", kicad_symbol: p.kicad_symbol || "",
      kicad_footprint: p.kicad_footprint || "", datasheet_url: p.datasheet_url || "",
      min_stock: p.min_stock, description: p.description || "", notes: p.notes || "",
      tags: p.tags.join(", "),
      attributes: { ...(p.attributes || {}) },
      discontinued: !!p.discontinued,
      replaced_by_id: p.replaced_by ? p.replaced_by.id : null,
      replacement_mpn: p.replacement_mpn || "",
      replacement_sku: p.replacement_sku || "",
    };
    const g = el("div", { class: "form-grid" });
    const field = (label, node) => g.append(el("label", {}, label), node);
    const inp = (key, attrs = {}) =>
      el("input", { type: "text", value: draft[key], oninput: (e) => (draft[key] = e.target.value), ...attrs });

    field("Name", inp("name"));
    field("MPN", inp("mpn"));
    field("Manufacturer", inp("manufacturer"));

    const cat = el("select", { onchange: (e) => (draft.category_id = e.target.value) });
    cat.append(...(await treeOptions("/api/categories", { includeBlank: "— none —" })));
    cat.value = String(draft.category_id || "");
    field("Category", cat);

    const mount = el("select", { onchange: (e) => (draft.mount = e.target.value) });
    mount.append(...MOUNTS.map((m) => el("option", { value: m }, m || "—")));
    mount.value = draft.mount;
    field("Mount", mount);

    field("Footprint", inp("footprint_raw"));
    field("KiCad symbol", inp("kicad_symbol"));
    field("KiCad footprint", inp("kicad_footprint"));
    field("Datasheet URL", inp("datasheet_url"));
    field("Min stock", inp("min_stock", { inputmode: "numeric" }));
    field("Tags", inp("tags", { placeholder: "comma, separated" }));
    field("Description", el("textarea", { class: "full", oninput: (e) => (draft.description = e.target.value) }, draft.description));
    field("Notes", el("textarea", { class: "full", oninput: (e) => (draft.notes = e.target.value) }, draft.notes));
    body.append(g);

    // per-class parameter fields
    const cls = this.classes[p.part_class];
    if (cls) {
      body.append(el("div", { class: "section-title" }, `${cls.label} parameters`));
      const pg = el("div", { class: "form-grid" });
      for (const f of cls.fields) {
        const val = draft.attributes[f.key] ?? "";
        let node;
        if (f.type === "bool") {
          node = el("input", { type: "checkbox", checked: val === true || val === "true" ? "checked" : null,
            onchange: (e) => (draft.attributes[f.key] = e.target.checked) });
        } else if (f.type === "enum" && f.options) {
          node = el("select", { onchange: (e) => (draft.attributes[f.key] = e.target.value) },
            el("option", { value: "" }, "—"), ...f.options.map((o) => el("option", { value: o }, o)));
          node.value = val;
        } else {
          // free text/number, but offer values already used for this parameter
          const listId = `dl-${f.key}`;
          const seen = this.attrVals[f.key] || [];
          const dl = el("datalist", { id: listId }, ...seen.map((v) => el("option", { value: v })));
          const kind = valueKind(p.part_class, f.key); // ohms/farads/henries/hertz/num
          const box = el("input", { type: "text", value: val, list: listId,
            inputmode: f.type === "number" ? "decimal" : null,
            title: kind !== "num" ? "1000pF = 1nF · 2200 = 2k2 — normalised on blur" : "",
            style: "flex:1",
            oninput: (e) => (draft.attributes[f.key] = e.target.value),
            onchange: (e) => {
              e.target.value = commaFix(e.target.value);
              if (f.key === "value" && kind !== "num" && e.target.value.trim()) {
                e.target.value = formatValue(e.target.value, kind);
              }
              draft.attributes[f.key] = e.target.value;
            } });
          node = el("span", { style: "display:flex;gap:0" }, box, dl);
        }
        pg.append(el("label", { title: f.comment || "" }, f.label + (f.unit ? ` (${f.unit})` : "")), node);
      }
      body.append(pg);
    }

    // Anything stored in attributes that the class schema doesn't cover
    // (e.g. copied from a supplier lookup) — always visible, always editable.
    const schemaKeys = new Set((cls?.fields || []).map((f) => f.key));
    body.append(el("div", { class: "section-title" }, "Additional parameters"));
    const og = el("div", { class: "form-grid" });
    const renderExtra = () => {
      og.innerHTML = "";
      const extras = Object.keys(draft.attributes).filter((k) => !schemaKeys.has(k)).sort();
      for (const k of extras) {
        const inp = el("input", { type: "text", value: draft.attributes[k] ?? "", style: "flex:1",
          oninput: (e) => (draft.attributes[k] = e.target.value),
          onchange: (e) => { e.target.value = commaFix(e.target.value); draft.attributes[k] = e.target.value; } });
        og.append(
          el("label", { title: k }, k),
          el("span", { style: "display:flex;gap:4px" }, inp,
            el("button", { class: "ghost", title: "remove", onclick: () => { delete draft.attributes[k]; renderExtra(); } }, "✕")),
        );
      }
      const nk = el("input", { type: "text", placeholder: "name", style: "width:100%" });
      const nv = el("input", { type: "text", placeholder: "value", style: "flex:1" });
      og.append(
        el("label", {}, nk),
        el("span", { style: "display:flex;gap:4px" }, nv,
          el("button", { onclick: () => {
            const key = nk.value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
            if (key) { draft.attributes[key] = nv.value.trim(); renderExtra(); }
          } }, "add")),
      );
    };
    renderExtra();
    body.append(og);

    body.append(el("div", { class: "section-title" }, "Replacement / lifecycle"));
    body.append(this._replacementSection(draft));

    body.append(el("div", { class: "section-title" }, "Images & files"));
    body.append(this._imagesSection());

    const saveBar = el(
      "div",
      { class: "save-bar" },
      el("button", {
        onclick: () =>
          openLookup(this.p, this.classes[this.p.part_class]?.fields || [], () => this._reload()),
      }, "Look up specs…"),
      el("span", { style: "flex:1" }),
      el("button", { class: "primary", onclick: () => this._saveDetails(draft) }, "Save"),
    );
    body.append(saveBar);
  }

  _replacementSection(draft) {
    const g = el("div", { class: "form-grid" });
    const disc = el("input", { type: "checkbox", checked: draft.discontinued ? "checked" : null,
      onchange: (e) => (draft.discontinued = e.target.checked) });
    g.append(el("label", {}, "Discontinued"), disc);

    const ps = partSearch({ placeholder: "replacement part in the DB…", onPick: (x) => (draft.replaced_by_id = x.id) });
    if (this.p.replaced_by) ps.set({ id: this.p.replaced_by.id, name: this.p.replaced_by.name });
    const clr = el("button", { class: "ghost", onclick: () => { draft.replaced_by_id = null; ps.set(null); } }, "clear");
    g.append(el("label", {}, "Replaced by (part)"), el("span", { style: "display:flex;gap:6px" }, ps.el, clr));

    const mpn = el("input", { type: "text", value: draft.replacement_mpn, placeholder: "or the new MPN",
      oninput: (e) => (draft.replacement_mpn = e.target.value) });
    const sku = el("input", { type: "text", value: draft.replacement_sku, placeholder: "supplier art. no. of the new one",
      oninput: (e) => (draft.replacement_sku = e.target.value) });
    g.append(el("label", {}, "…or replacement MPN"), mpn);
    g.append(el("label", {}, "Replacement SKU"), sku);
    g.append(el("span", { class: "full hint" },
      "When this part hits zero on hand, the panel shows a banner pointing at the replacement."));
    return g;
  }

  _imagesSection() {
    const wrap = el("div");
    const grid = el("div", { class: "img-grid" });
    (this.p.images || []).forEach((im, i) => {
      const cell = el("div", { class: "cell" + (i === 0 && im.kind === "image" ? " primary" : "") });
      const mat = el("div", { class: "img-mat" });
      if (im.thumb_url || im.kind === "image") mat.append(el("img", { src: im.thumb_url || im.url, title: im.filename }));
      else mat.append(el("a", { href: im.url, target: "_blank" }, im.filename));
      cell.append(mat, el("button", { class: "x", title: "delete", onclick: () => this._delImage(im.id) }, "✕"));
      if (im.kind === "image" && i !== 0)
        cell.append(el("button", { class: "x", style: "right:auto;left:2px", title: "make primary",
          onclick: () => this._primaryImage(im.id) }, "★"));
      grid.append(cell);
    });
    const file = el("input", { type: "file", accept: "image/*,.pdf", multiple: "multiple",
      onchange: (e) => this._upload(e.target.files) });
    wrap.append(grid, el("div", { style: "margin-top:8px" }, file));
    return wrap;
  }

  async _upload(files) {
    if (!files || !files.length) return;
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    const res = await fetch(`/api/parts/${this.id}/images`, { method: "POST", body: fd });
    if (!res.ok) return toast("Upload failed");
    toast("Uploaded");
    await this._reload();
  }
  async _delImage(aid) {
    await api(`/api/parts/${this.id}/images/${aid}`, { method: "DELETE" });
    await this._reload();
  }
  async _primaryImage(aid) {
    await api(`/api/parts/${this.id}/images/${aid}/primary`, { method: "POST" });
    await this._reload();
  }

  async _saveDetails(draft) {
    const patch = {
      name: draft.name.trim(),
      mpn: draft.mpn.trim() || null,
      manufacturer: draft.manufacturer.trim() || null,
      category_id: draft.category_id ? Number(draft.category_id) : null,
      set_category: true,
      mount: draft.mount || null,
      footprint_raw: draft.footprint_raw.trim() || null,
      kicad_symbol: draft.kicad_symbol.trim() || null,
      kicad_footprint: draft.kicad_footprint.trim() || null,
      datasheet_url: draft.datasheet_url.trim() || null,
      min_stock: Number(draft.min_stock) || 0,
      description: draft.description.trim() || null,
      notes: draft.notes.trim() || null,
      tags: draft.tags.split(",").map((s) => s.trim()).filter(Boolean),
      attributes: draft.attributes,
      discontinued: draft.discontinued,
      replaced_by_id: draft.replaced_by_id || null,
      set_replaced_by: true,
      replacement_mpn: draft.replacement_mpn.trim() || null,
      replacement_sku: draft.replacement_sku.trim() || null,
    };
    await api(`/api/parts/${this.id}`, { method: "PATCH", body: patch });
    await attrValues(true); // new parameter values become datalist suggestions
    toast("Saved");
    await this._reload();
  }

  // ---------- Stock ----------
  _stock(body) {
    const s = this.stock;
    body.append(
      el(
        "div",
        { style: "display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap" },
        el("button", { class: "primary", onclick: () => this._stockDialog("add") }, "Add stock"),
        el("button", { onclick: () => this._stockDialog("remove") }, "Remove"),
        el("button", { onclick: () => this._moveDialog() }, "Move"),
        el("button", { onclick: () => this._stockDialog("count") }, "Set count"),
      ),
    );
    body.append(el("div", { class: "section-title" }, "By location"));
    const t1 = el("table", { class: "mini-table" });
    t1.append(el("tr", {}, el("th", {}, "Location"), el("th", { class: "num" }, "Qty")));
    if (!s.by_location.length) t1.append(el("tr", {}, el("td", { colspan: "2", class: "pill-off" }, "empty")));
    for (const r of s.by_location) t1.append(el("tr", {}, el("td", {}, r.location), el("td", { class: "num" }, String(r.qty))));
    body.append(t1);

    body.append(el("div", { class: "section-title" }, "Ledger"));
    const t2 = el("table", { class: "mini-table" });
    t2.append(el("tr", {}, el("th", {}, "When"), el("th", {}, "Kind"), el("th", {}, "Location"), el("th", { class: "num" }, "Δ"), el("th", {}, "Price ex/inc"), el("th", {}, "Supplier")));
    for (const e of s.entries.slice(0, 40)) {
      const px = e.price.ex_vat != null ? `${e.price.ex_vat} / ${e.price.inc_vat_ceil}` : "";
      t2.append(
        el("tr", {},
          el("td", {}, (e.created_at || "").slice(0, 10)),
          el("td", {}, e.kind),
          el("td", {}, e.location),
          el("td", { class: "num " + (e.delta < 0 ? "low" : "") }, (e.delta > 0 ? "+" : "") + e.delta),
          el("td", {}, px),
          el("td", {}, [e.supplier, e.supplier_sku].filter(Boolean).join(" ")),
        ),
      );
    }
    body.append(t2);
  }

  _supplierSelect(onNew) {
    const sel = el("select");
    sel.append(el("option", { value: "" }, "— supplier —"),
      ...this.suppliers.map((s) => el("option", { value: s.id }, s.name)),
      el("option", { value: "__new__" }, "+ Add new supplier…"));
    sel.addEventListener("change", async () => {
      if (sel.value === "__new__") {
        const name = prompt("New supplier name:");
        sel.value = "";
        if (name && name.trim()) {
          const { id } = await api("/api/suppliers", { method: "POST", body: { name: name.trim() } });
          this.suppliers = await api("/api/suppliers");
          sel.innerHTML = "";
          sel.append(el("option", { value: "" }, "— supplier —"),
            ...this.suppliers.map((s) => el("option", { value: s.id }, s.name)),
            el("option", { value: "__new__" }, "+ Add new supplier…"));
          sel.value = String(id);
          onNew && onNew(id);
        }
      }
    });
    return sel;
  }

  _stockDialog(kind) {
    const qty = el("input", { type: "text", inputmode: "numeric", value: kind === "count" ? "0" : "1" });
    const loc = el("select");
    treeOptions("/api/locations", { includeBlank: "— location —" }).then((o) => loc.append(...o));
    const price = el("input", { type: "text", inputmode: "decimal", placeholder: "unit price" });
    const incVat = el("input", { type: "checkbox" });
    const vat = el("input", { type: "text", inputmode: "decimal", value: "25", style: "width:60px" });
    const sku = el("input", { type: "text", placeholder: "supplier article no." });
    const sup = this._supplierSelect();
    const note = el("input", { type: "text", placeholder: "note" });
    const rows = [
      ["Qty", qty],
      ["Location", loc],
    ];
    if (kind === "add") rows.push(["Supplier", sup], ["Supplier SKU", sku], ["Unit price", price],
      ["Incl. VAT?", el("span", {}, incVat, " at ", vat, " %")]);
    rows.push(["Note", note]);
    const body = el("div", { class: "modal-body" },
      ...rows.map(([l, n]) => el("div", { class: "row" }, el("label", {}, l), n)));
    const titles = { add: "Add stock", remove: "Remove stock", count: "Set exact count at a location" };
    modal({
      title: titles[kind],
      body,
      confirmText: kind === "count" ? "Set" : titles[kind],
      onConfirm: async () => {
        const q = Math.abs(Number(qty.value) || 0);
        if (kind !== "count" && q <= 0) throw new Error("qty must be > 0");
        if (kind === "count") {
          if (!loc.value) throw new Error("pick a location");
          const cur = this.stock.by_location.find((r) => String(r.location_id) === loc.value)?.qty || 0;
          const delta = Number(qty.value) - cur;
          if (delta === 0) return;
          await api(`/api/parts/${this.id}/stock`, { method: "POST", body: { location_id: Number(loc.value), delta, kind: "count", note: note.value || "manual count" } });
        } else {
          const b = {
            location_id: loc.value ? Number(loc.value) : null,
            delta: kind === "remove" ? -q : q,
            kind,
            note: note.value || null,
          };
          if (kind === "add") {
            Object.assign(b, {
              unit_price: parseNum(price.value),
              price_includes_vat: incVat.checked,
              vat_percent: parseNum(vat.value) || 25,
              supplier_id: sup.value ? Number(sup.value) : null,
              supplier_sku: sku.value || null,
            });
          }
          await api(`/api/parts/${this.id}/stock`, { method: "POST", body: b });
        }
        toast("Stock updated");
        await this._reload();
      },
    });
  }

  _moveDialog() {
    const from = el("select");
    const to = el("select");
    const qty = el("input", { type: "text", inputmode: "numeric", value: "1" });
    treeOptions("/api/locations", { includeBlank: "— from —" }).then((o) => from.append(...o));
    treeOptions("/api/locations", { includeBlank: "— to —" }).then((o) => to.append(...o));
    const body = el("div", { class: "modal-body" },
      el("div", { class: "row" }, el("label", {}, "From"), from),
      el("div", { class: "row" }, el("label", {}, "To"), to),
      el("div", { class: "row" }, el("label", {}, "Qty"), qty));
    modal({
      title: "Move stock between locations",
      body,
      confirmText: "Move",
      onConfirm: async () => {
        if (!to.value) throw new Error("pick a destination");
        await api(`/api/parts/${this.id}/stock/move`, {
          method: "POST",
          body: { from_location_id: from.value ? Number(from.value) : null, to_location_id: Number(to.value), qty: Number(qty.value) || 1 },
        });
        toast("Moved");
        await this._reload();
      },
    });
  }

  // ---------- Suppliers ----------
  _suppliersTab(body) {
    body.append(el("button", { class: "primary", onclick: () => this._linkDialog() }, "Add supplier link"));
    const t = el("table", { class: "mini-table", style: "margin-top:10px" });
    t.append(el("tr", {}, el("th", {}, ""), el("th", {}, "Supplier"), el("th", {}, "Article no."),
      el("th", { class: "num" }, "ex VAT"), el("th", { class: "num" }, "inc VAT"), el("th", {}, ""), el("th", {}, "")));
    for (const l of this.p.suppliers) {
      const star = el("span", { class: "star" + (l.preferred ? " on" : ""), title: "preferred",
        onclick: () => this._patchLink(l.id, { preferred: true }) }, "★");
      t.append(
        el("tr", {},
          el("td", {}, star),
          el("td", {}, l.supplier + (l.active ? "" : " (inactive)")),
          el("td", {}, l.url ? el("a", { href: l.url, target: "_blank" }, l.sku || "link") : (l.sku || "—")),
          el("td", { class: "num" }, l.price.ex_vat ?? "—"),
          el("td", { class: "num" }, l.price.inc_vat_ceil ?? "—"),
          el("td", {}, el("button", { class: "ghost", onclick: () => this._linkDialog(l) }, "edit")),
          el("td", {}, el("button", { class: "ghost", onclick: () => this._delLink(l.id) }, "✕")),
        ),
      );
    }
    if (!this.p.suppliers.length) t.append(el("tr", {}, el("td", { colspan: "7", class: "pill-off" }, "no supplier links yet")));
    body.append(t);
  }

  _linkDialog(existing) {
    const sup = this._supplierSelect();
    if (existing) {
      sup.value = String(existing.supplier_id);
    } else {
      // default to the remembered supplier (last one chosen that is an API
      // provider), else Mouser
      const want = (localStorage.getItem("partsnas.defaultSupplier") || "Mouser").toLowerCase();
      const opt = [...sup.options].find((o) => o.textContent.toLowerCase() === want)
        || [...sup.options].find((o) => o.textContent.toLowerCase() === "mouser");
      if (opt) sup.value = opt.value;
    }
    const sku = el("input", { type: "text", value: existing?.sku || (existing ? "" : this.p.mpn || "") });
    const url = el("input", { type: "text", value: existing?.url || "", placeholder: "product page URL" });
    const price = el("input", { type: "text", inputmode: "decimal", value: existing?.price.ex_vat ?? "" });
    const incVat = el("input", { type: "checkbox" });
    const vat = el("input", { type: "text", value: existing?.price.vat_percent ?? 25, style: "width:60px" });
    const active = el("input", { type: "checkbox", checked: existing ? (existing.active ? "checked" : null) : "checked" });
    const pref = el("input", { type: "checkbox", checked: existing?.preferred ? "checked" : null });
    const body = el("div", { class: "modal-body" },
      el("div", { class: "row" }, el("label", {}, "Supplier"), sup),
      el("div", { class: "row" }, el("label", {}, "Article no."), sku),
      el("div", { class: "row" }, el("label", {}, "URL"), url),
      el("div", { class: "row" }, el("label", {}, "Price"), price, el("span", {}, incVat, " incl. VAT @ ", vat, "%")),
      el("div", { class: "row" }, el("label", {}, "Active"), active, el("label", { style: "margin-left:16px" }, "Preferred"), pref));
    modal({
      title: existing ? "Edit supplier link" : "Add supplier link",
      body,
      confirmText: "Save",
      onConfirm: async () => {
        if (!existing && !sup.value) throw new Error("pick a supplier");
        const payload = {
          sku: sku.value.trim() || null, url: url.value.trim() || null,
          price: parseNum(price.value),
          price_includes_vat: incVat.checked, vat_percent: parseNum(vat.value) || 25,
          active: active.checked, preferred: pref.checked,
        };
        if (existing) {
          await api(`/api/parts/${this.id}/suppliers/${existing.id}`, { method: "PATCH", body: payload });
        } else {
          await api(`/api/parts/${this.id}/suppliers`, { method: "POST", body: { supplier_id: Number(sup.value), ...payload } });
          // remember this supplier as the default if it's an API provider
          const name = sup.selectedOptions[0]?.textContent || "";
          const providers = (this._provNames ||= (await api("/api/lookup/providers")).map((p) => p.label.toLowerCase()));
          if (providers.includes(name.toLowerCase())) localStorage.setItem("partsnas.defaultSupplier", name);
        }
        toast("Saved");
        await this._reload();
      },
    });
  }

  async _patchLink(lid, patch) {
    await api(`/api/parts/${this.id}/suppliers/${lid}`, { method: "PATCH", body: patch });
    await this._reload();
  }
  async _delLink(lid) {
    if (!confirm("Remove this supplier link?")) return;
    await api(`/api/parts/${this.id}/suppliers/${lid}`, { method: "DELETE" });
    await this._reload();
  }

  // ---------- Notes ----------
  async _notes(body) {
    body.append(
      el("button", {
        onclick: () =>
          document.dispatchEvent(
            new CustomEvent("partsnas:gototab", { detail: { tab: "notes", q: this.p.mpn || this.p.name } }),
          ),
      }, "Open in Design Notes tab →"),
    );
    let data;
    try {
      data = await api(`/api/parts/${this.id}/design-notes`);
    } catch {
      return;
    }
    const section = (heading, notes, anchored) => {
      body.append(el("div", { class: "section-title" }, heading));
      if (!notes.length) return body.append(el("div", { class: "pill-off" }, "none"));
      for (const n of notes) {
        body.append(
          el(
            "div",
            { style: "border:1px solid var(--border);border-radius:6px;padding:8px 10px;margin-bottom:6px" },
            el("div", { style: "display:flex;gap:6px;align-items:baseline" },
              el("b", {}, n.title),
              n.condition ? el("span", { class: "chip", style: "border-color:var(--accent);color:var(--accent)" }, n.condition) : null,
              anchored ? "" : el("span", { class: "sub", style: "color:var(--text-muted)" }, ` — anchor: ${n.anchor_name || "?"}`)),
            n.body ? el("div", { style: "white-space:pre-wrap;margin:4px 0" }, n.body) : null,
            el("div", {}, ...(n.links || []).map((l) =>
              el("span", { class: "chip" }, `${l.role ? l.role + ": " : ""}${l.part_name || l.label || l.mpn || "?"}${l.value_hint ? " (" + l.value_hint + ")" : ""}`))),
          ),
        );
      }
    };
    section("Notes anchored here", data.anchored, true);
    section("Referenced by other notes", data.referenced_by, false);
  }
}
