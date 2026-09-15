// Parts tab: left category/location rail, right = faceted filters + results table + bulk bar.
import { api } from "./api.js";
import { el, modal, toast, treeOptions, withBusy, selectWithAdd } from "./ui.js";
import { PartDetail } from "./partdetail.js";
import { CatRail } from "./catrail.js";
import { addPartsToQuote } from "./quotes.js";
import { openLookup } from "./lookup.js";
import { addToLabelSheet } from "./labelcommon.js";

const FACET_ORDER = ["mount", "footprint", "manufacturer", "location", "tags", "in_stock"];
const FACET_LABEL = {
  mount: "Mount", footprint: "Footprint", manufacturer: "Manufacturer",
  location: "Location", tags: "Tags", in_stock: "Stock",
};
const MOUNT_LABEL = { smd: "SMD", tht: "THT", other: "Other", "": "Unknown" };

// Attribute/footprint facets sort by numeric magnitude when their options
// are numeric-ish (Capacitance, V Max, or parametric strings like
// "15 nC @ 4.5 V" / "500mW (Ta)" copied verbatim from a Mouser/Digi-Key
// lookup) — only the LEADING number+prefix+unit is read, trailing
// condition text is ignored, so sorting still reflects the primary
// quantity. Falls back to a natural string sort (still better than raw
// count-order) for genuinely textual facets like packagecase/footprint.
const _PREFIX_MULT = { p: 1e-12, n: 1e-9, u: 1e-6, "µ": 1e-6, "μ": 1e-6, m: 1e-3, k: 1e3, K: 1e3, M: 1e6, G: 1e9 };
const _RKM_LEAD = /^\s*(\d*)\s*([RrkKMmGpnµμu])\s*(\d*)/; // "5k1" / "4R7" / "49R9"
const _NUM_LEAD = /^\s*([-+]?[\d.]+)\s*([pnuµμmkKMG]?)/; // "100nF" / "931 pF @ 10 V" / "50V"

function leadingMagnitude(raw) {
  if (raw == null) return null;
  const s = String(raw).trim().replace(",", ".").replace(/^[±]\s*/, "");
  if (!s) return null;
  let m = s.match(_RKM_LEAD);
  if (m && (m[1] || m[3])) {
    const mult = m[2] === "R" || m[2] === "r" ? 1 : (_PREFIX_MULT[m[2]] ?? 1);
    return parseFloat((m[1] || "0") + "." + (m[3] || "0")) * mult;
  }
  m = s.match(_NUM_LEAD);
  if (m && m[1]) {
    const num = parseFloat(m[1]);
    return isNaN(num) ? null : num * (m[2] ? (_PREFIX_MULT[m[2]] ?? 1) : 1);
  }
  return null;
}

const magEq = (a, b) => a != null && b != null && Math.abs(a - b) <= Math.max(Math.abs(a), Math.abs(b), 1e-15) * 1e-9;
const naturalCompare = (a, b) => String(a ?? "").localeCompare(String(b ?? ""), undefined, { numeric: true, sensitivity: "base" });

export class PartsView {
  constructor(initial = {}) {
    this.el = el("div", { class: "parts" });
    this.initial = initial;
    this.selected = new Set(); // bulk selection
    this.q = "";
    this.low = false;
    this.noCat = false;
    this.scanSelect = false;
    this.rail = { mode: "categories", id: null };
    this.facetSel = { mount: new Set(), footprint: new Set(), manufacturer: new Set(),
      location: new Set(), tags: new Set(), in_stock: null, attr: {} };
    this.facetConfig = null; // per-category visible/ordered/renamed facets, see _openFacetEditor()
  }

  async mount(container) {
    container.append(this.el);
    const layout = el("div", { class: "parts-layout" });
    this.el.append(layout);

    const railHost = el("div", { style: "min-height:0;display:flex" });
    this.railCmp = new CatRail({ onSelect: ({ mode, id, name }) => { this.rail = { mode, id, name }; this.reload(); } });
    await this.railCmp.mount(railHost);

    this.main = el("div", { class: "parts-main" });
    layout.append(railHost, this.main);
    this.main.append(
      this._topBar(),
      (this.activeHost = el("div", { class: "active-filters" })),
      (this.facetToolbar = el("div", { class: "facet-toolbar", hidden: "hidden" })),
      (this.facetHost = el("div", { class: "facets", hidden: "hidden" })),
      (this.bulkHost = el("div")),
      (this.tableWrap = el("div", { class: "table-wrap" })),
    );

    // apply an incoming filter (from a tree-node click elsewhere)
    if (this.initial.q) { this.q = this.initial.q; this.qInput.value = this.initial.q; }
    if (this.initial.category_id) { this.rail = { mode: "categories", id: Number(this.initial.category_id) }; this.railCmp.setSelected("categories", this.rail.id); }
    else if (this.initial.location_id) { this.rail = { mode: "locations", id: Number(this.initial.location_id) }; this.railCmp.setSelected("locations", this.rail.id); }

    document.addEventListener("partsnas:scan", this._onScan);
    await this.reload();
  }

  destroy() {
    document.removeEventListener("partsnas:scan", this._onScan);
  }

  // "All categories" / Unsorted / Locations mode all pass no category_id and
  // always come back unrestricted+non-editable (see backend/app/api/meta.py) —
  // only fetched fresh when the category actually changed, not on every reload
  async _loadFacetConfig() {
    const catId = this.rail.mode === "categories" ? this.rail.id : null;
    if (this.facetConfig && this._facetConfigFor === catId) return;
    this.facetConfig = await api(`/api/meta/facet-config${catId != null ? `?category_id=${catId}` : ""}`);
    this._facetConfigFor = catId;
  }

  _onScan = (e) => {
    // a modal on top (e.g. "New part") captures scans itself — don't also
    // look the code up as if it were meant for the list behind it
    if (document.querySelector(".modal-back")) return;
    const code = e.detail.code;
    api(`/api/parts/lookup?code=${encodeURIComponent(code)}`)
      .then((p) => {
        if (this.scanSelect) {
          this.selected.add(p.id);
          this._renderTable();
          this._renderBulk();
          toast(`Scanned: ${p.name} — selected (${this.selected.size})`);
        } else {
          this.openDetail(p.id);
        }
      })
      .catch(() => toast(`No part matches "${code}"`));
  };

  _topBar() {
    const bar = el("div", { class: "filters" });
    this.qInput = el("input", { type: "search", placeholder: "Search name / MPN / description",
      oninput: () => { this.q = this.qInput.value.trim(); this._debounced(); } });
    const lowL = el("label", {}, (this.lowChk = el("input", { type: "checkbox",
      onchange: (e) => { this.low = e.target.checked; this.reload(); } })), " Low stock");
    const noCatL = el("label", { title: "parts with no category / in Unsorted — for triage" },
      (this.noCatChk = el("input", { type: "checkbox",
        onchange: (e) => { this.noCat = e.target.checked; this.reload(); } })), " Uncategorized");
    const scanL = el("label", { title: "Scanned codes tick the row instead of opening it" },
      el("input", { type: "checkbox", onchange: (e) => (this.scanSelect = e.target.checked) }), " Scan→select");
    this.orderSel = el("select", { onchange: () => this._renderTable() },
      el("option", { value: "name" }, "Sort: name"), el("option", { value: "stock" }, "Sort: stock"));
    this.countTag = el("span", { class: "count-tag" });
    const addBtn = el("button", { class: "primary", onclick: () => this._newPart() }, "+ New part");
    bar.append(this.qInput, lowL, noCatL, scanL, this.orderSel, el("span", { class: "grow" }), addBtn, this.countTag);
    return bar;
  }

  _debounced() {
    clearTimeout(this._t);
    this._t = setTimeout(() => this.reload(), 250);
  }

  _query() {
    const p = new URLSearchParams();
    if (this.q) p.set("q", this.q);
    if (this.low) p.set("low_stock", "true");
    if (this.noCat) p.set("no_category", "true");
    if (this.rail.mode === "categories" && this.rail.id) p.set("category_id", this.rail.id);
    if (this.rail.mode === "locations" && this.rail.id) p.append("location_id", this.rail.id);
    for (const v of this.facetSel.mount) p.append("mount", v);
    for (const v of this.facetSel.footprint) p.append("footprint", v);
    for (const v of this.facetSel.manufacturer) p.append("manufacturer", v);
    for (const v of this.facetSel.location) p.append("location_id", v);
    for (const v of this.facetSel.tags) p.append("tag", v);
    if (this.facetSel.in_stock) p.set("in_stock", this.facetSel.in_stock);
    for (const [k, set] of Object.entries(this.facetSel.attr))
      for (const v of set) p.append("attr", `${k}:${v}`);
    return p;
  }

  async reload() {
    const qs = this._query().toString();
    const [list, facets] = await Promise.all([
      api(`/api/parts?${qs}&limit=1000`),
      api(`/api/parts/facets?${qs}`),
      this._loadFacetConfig(),
    ]);
    this.items = list.items;
    this.lastTotal = list.total;
    this.facets = facets;
    this._renderActive();
    this._renderFacetToolbar();
    this._renderFacets();
    this._renderBulk();
    this._renderTable();
  }

  // ---- facets ----
  _renderFacetToolbar() {
    this.facetToolbar.innerHTML = "";
    this.facetToolbar.hidden = !this.facetConfig?.editable;
    if (!this.facetConfig?.editable) return;
    this.facetToolbar.append(
      el("button", { class: "ghost", onclick: () => this._openFacetEditor() }, "⚙ Customize filters"),
    );
  }

  _openFacetEditor() {
    const { available } = this.facetConfig;
    const rows = (this.facetConfig.selected || []).map((e) => ({ id: e.id, label: e.label || "" }));
    const defaultLabel = (id) => {
      if (id.startsWith("attr:")) {
        const a = available.attrs.find((a) => "attr:" + a.key === id);
        return a ? a.label + (a.unit ? ` (${a.unit})` : "") : id;
      }
      return available.builtins.find((b) => b.id === id)?.label || id;
    };

    const rowHost = el("div");
    const addSel = el("select", { style: "min-width:180px" });
    const refreshAddSel = () => {
      addSel.innerHTML = "";
      addSel.append(el("option", { value: "" }, "+ add filter…"));
      const used = new Set(rows.map((r) => r.id));
      const bGroup = el("optgroup", { label: "Built-in" });
      for (const b of available.builtins) if (!used.has(b.id)) bGroup.append(el("option", { value: b.id }, b.label));
      const aGroup = el("optgroup", { label: "Attribute" });
      for (const a of available.attrs) {
        const id = "attr:" + a.key;
        if (!used.has(id)) aGroup.append(el("option", { value: id }, a.label + (a.unit ? ` (${a.unit})` : "")));
      }
      if (bGroup.children.length) addSel.append(bGroup);
      if (aGroup.children.length) addSel.append(aGroup);
    };
    const renderRows = () => {
      rowHost.innerHTML = "";
      rows.forEach((entry, i) => {
        const nameEl = el("span", { style: "flex:1;min-width:120px" }, defaultLabel(entry.id));
        const labelInp = el("input", { type: "text", value: entry.label, placeholder: "rename (optional)", style: "flex:1;min-width:100px",
          oninput: (e) => (entry.label = e.target.value) });
        const upBtn = el("button", { class: "ghost", title: "move up", disabled: i === 0 ? "disabled" : null,
          onclick: () => { [rows[i - 1], rows[i]] = [rows[i], rows[i - 1]]; renderRows(); } }, "▲");
        const downBtn = el("button", { class: "ghost", title: "move down", disabled: i === rows.length - 1 ? "disabled" : null,
          onclick: () => { [rows[i + 1], rows[i]] = [rows[i], rows[i + 1]]; renderRows(); } }, "▼");
        const rmBtn = el("button", { class: "ghost", onclick: () => { rows.splice(i, 1); renderRows(); refreshAddSel(); } }, "✕");
        rowHost.append(el("div", { class: "row", style: "flex-wrap:wrap;gap:6px;align-items:center" },
          nameEl, labelInp, upBtn, downBtn, rmBtn));
      });
    };
    addSel.addEventListener("change", () => {
      if (!addSel.value) return;
      rows.push({ id: addSel.value, label: "" });
      renderRows();
      refreshAddSel();
    });
    renderRows();
    refreshAddSel();

    modal({
      title: "Customize filters" + (this.rail.name ? ` — ${this.rail.name}` : ""),
      body: el("div", { class: "modal-body" },
        el("div", { class: "hint" },
          "Which filter groups show while browsing this category, and in what order. Leave empty to show everything present, same as \"All categories\"."),
        rowHost, addSel),
      confirmText: "Save",
      onConfirm: async () => {
        const selected = rows.map((r) => ({ id: r.id, label: r.label.trim() || null }));
        await api("/api/meta/facet-config", { method: "PUT", body: { category_id: this.rail.id, selected } });
        this.facetConfig = null; // force a refetch even though the category id itself hasn't changed
        await this._loadFacetConfig();
        this._renderFacetToolbar();
        this._renderFacets();
      },
    });
  }
  _renderFacets() {
    const host = this.facetHost;
    host.innerHTML = "";
    const groups = [];
    const cfg = this.facetConfig?.selected;
    if (cfg && cfg.length) {
      for (const entry of cfg) {
        const g = this._resolveFacetEntry(entry);
        if (g) groups.push(g);
      }
    } else {
      for (const key of FACET_ORDER) {
        const opts = this.facets[key] || [];
        if (!opts.length && !(key === "in_stock")) continue;
        groups.push(this._facetGroup(key, FACET_LABEL[key], opts, key === "location" ? "location" : key));
      }
      for (const [akey, def] of Object.entries(this.facets.attributes || {})) {
        groups.push(this._facetGroup("attr:" + akey, def.label + (def.unit ? ` (${def.unit})` : ""), def.options, "attr", akey));
      }
    }
    host.hidden = groups.length === 0;
    groups.forEach((g) => host.append(g));
  }

  // resolve one entry from the user's saved facet-config list to a rendered
  // group, or null if that facet has nothing to show for the current query
  // (e.g. "Voltage" while browsing inductors, which have no such field)
  _resolveFacetEntry({ id, label }) {
    if (id.startsWith("attr:")) {
      const akey = id.slice(5);
      const def = this.facets.attributes?.[akey];
      if (!def || !def.options?.length) return null;
      return this._facetGroup(id, label || def.label + (def.unit ? ` (${def.unit})` : ""), def.options, "attr", akey);
    }
    const opts = this.facets[id] || [];
    if (!opts.length && id !== "in_stock") return null;
    return this._facetGroup(id, label || FACET_LABEL[id], opts, id === "location" ? "location" : id);
  }

  _selSet(kind, akey) {
    return kind === "attr" ? (this.facetSel.attr[akey] ||= new Set()) : this.facetSel[kind];
  }

  _facetGroup(id, label, options, kind, akey) {
    const g = el("div", { class: "facet-group" });
    g.append(el("h4", {}, label));
    const sel = kind === "in_stock" ? null : this._selSet(kind, akey);
    // keep a selected value visible even if it dropped to 0
    const shown = options.slice();
    if (sel) for (const v of sel) if (!shown.find((o) => o.value === v)) shown.push({ value: v, count: 0 });

    // attribute/footprint facets get a sensible order instead of raw
    // count-order: numeric magnitude when most options parse as one
    // (Capacitance, V Max, "15 nC @ 4.5 V" parametrics, ...), else a
    // natural alphanumeric sort (packagecase, footprint package names, ...)
    const sortable = kind === "attr" || kind === "footprint";
    const byMagnitude = sortable && shown.length > 0
      && shown.filter((o) => leadingMagnitude(o.value) != null).length / shown.length >= 0.9;
    if (byMagnitude) {
      shown.sort((a, b) => {
        const ma = leadingMagnitude(a.value), mb = leadingMagnitude(b.value);
        if (ma == null || mb == null) return ma == null ? (mb == null ? 0 : 1) : -1;
        return ma - mb;
      });
    } else if (sortable) {
      shown.sort((a, b) => naturalCompare(a.value, b.value));
    }

    const listEl = el("div", { class: "facet-list" });
    const renderRows = (filterText) => {
      listEl.innerHTML = "";
      const f = (filterText || "").trim().toLowerCase();
      const qMag = byMagnitude && f ? leadingMagnitude(filterText.trim()) : null;
      for (const o of shown) {
        const label2 = kind === "mount" ? (MOUNT_LABEL[o.value] || o.value) : o.value;
        if (f) {
          const substrHit = String(label2 ?? "").toLowerCase().includes(f);
          const magHit = qMag != null && magEq(leadingMagnitude(o.value), qMag);
          if (!substrHit && !magHit) continue;
        }
        const isOn = kind === "in_stock" ? this.facetSel.in_stock === o.value : sel.has(o.value);
        listEl.append(el("label", { class: "facet-opt" + (o.count ? "" : " zero") + (isOn ? " on" : "") },
          el("input", { type: kind === "in_stock" ? "radio" : "checkbox", name: "f-" + id,
            checked: isOn ? "checked" : null,
            onchange: () => this._toggleFacet(kind, akey, o.value) }),
          el("span", { class: "nm", title: label2 }, label2 || "—"),
          el("span", { class: "c" }, o.count),
        ));
      }
    };
    if (shown.length > 6)
      g.append(el("input", { type: "text", class: "facet-search", placeholder: "search…",
        oninput: (e) => renderRows(e.target.value) }));
    g.append(listEl);
    renderRows("");
    return g;
  }

  _toggleFacet(kind, akey, value) {
    if (kind === "in_stock") {
      this.facetSel.in_stock = this.facetSel.in_stock === value ? null : value;
    } else {
      const set = this._selSet(kind, akey);
      set.has(value) ? set.delete(value) : set.add(value);
    }
    this.reload();
  }

  _renderActive() {
    const host = this.activeHost;
    host.innerHTML = "";
    const add = (text, clear) => host.append(el("span", { class: "chip", onclick: () => { clear(); this.reload(); } }, text));
    for (const kind of ["mount", "footprint", "manufacturer", "tags"])
      for (const v of this.facetSel[kind])
        add(`${FACET_LABEL[kind]}: ${kind === "mount" ? MOUNT_LABEL[v] || v : v}`, () => this.facetSel[kind].delete(v));
    for (const v of this.facetSel.location) {
      const nm = (this.facets.location || []).find((o) => String(o.id) === String(v))?.value || v;
      add(`Location: ${nm}`, () => this.facetSel.location.delete(v));
    }
    if (this.facetSel.in_stock) add(`Stock: ${this.facetSel.in_stock}`, () => (this.facetSel.in_stock = null));
    for (const [k, set] of Object.entries(this.facetSel.attr))
      for (const v of set) {
        const lbl = this.facets.attributes?.[k]?.label || k;
        add(`${lbl}: ${v}`, () => set.delete(v));
      }
  }

  // ---- table ----
  _renderTable() {
    this.countTag.textContent = `${this.lastTotal} part${this.lastTotal === 1 ? "" : "s"}`;
    const order = this.orderSel.value;
    const rows = [...this.items].sort(
      order === "stock" ? (a, b) => b.on_hand - a.on_hand : (a, b) => (a.name || "").toLowerCase().localeCompare((b.name || "").toLowerCase()),
    );
    this.tableWrap.innerHTML = "";
    const t = el("table", { class: "parts-table" });
    t.append(el("thead", {}, el("tr", {},
      el("th", {}, this._allChk(rows)),
      el("th", {}, "Name"), el("th", {}, "MPN"), el("th", {}, "Category"),
      el("th", {}, "Footprint"), el("th", { class: "num" }, "On hand"), el("th", {}, "Locations"))));
    const tb = el("tbody");
    for (const p of rows) tb.append(this._row(p));
    if (!rows.length) tb.append(el("tr", {}, el("td", { colspan: "7", class: "hint" }, "No parts match. Adjust filters, or use Import (top-right).")));
    t.append(tb);
    this.tableWrap.append(t);
  }

  _allChk(rows) {
    const ids = rows.map((p) => p.id);
    const all = ids.length && ids.every((i) => this.selected.has(i));
    return el("input", { type: "checkbox", checked: all ? "checked" : null,
      onchange: (e) => { ids.forEach((i) => e.target.checked ? this.selected.add(i) : this.selected.delete(i)); this._renderTable(); this._renderBulk(); } });
  }

  _row(p) {
    const checked = this.selected.has(p.id);
    const cb = el("input", { type: "checkbox", checked: checked ? "checked" : null,
      onclick: (e) => { e.stopPropagation(); e.target.checked ? this.selected.add(p.id) : this.selected.delete(p.id); tr.classList.toggle("sel", e.target.checked); this._renderBulk(); } });
    const nameCell = el("td", { class: "name" }, p.name);
    if (p.replacement)
      nameCell.append(el("span", { class: "chip", style: "border-color:var(--warn);color:var(--warn)", title: "discontinued" }, "→ " + p.replacement));
    const tr = el("tr", { class: checked ? "sel" : "", onclick: () => this.openDetail(p.id) },
      el("td", {}, cb),
      nameCell,
      el("td", {}, p.mpn || ""),
      el("td", {}, p.category || el("span", { class: "zero" }, "—")),
      el("td", {}, p.footprint || ""),
      el("td", { class: "num " + (p.on_hand <= 0 ? "zero" : p.min_stock && p.on_hand <= p.min_stock ? "low" : "") }, String(p.on_hand)),
      el("td", { class: "locs" }, p.locations.map((l) => el("span", { class: "chip" }, `${l.location}: ${l.qty}`))));
    return tr;
  }

  // ---- bulk ----
  _renderBulk() {
    this.bulkHost.innerHTML = "";
    const n = this.selected.size;
    if (!n) return;
    const bar = el("div", { class: "bulkbar" });
    bar.append(el("span", { class: "n" }, `${n} selected`));
    if (n < this.lastTotal)
      bar.append(el("button", { class: "ghost", onclick: () => this._selectAll() }, `Select all ${this.lastTotal} matching`));
    bar.append(el("button", { class: "ghost", onclick: () => { this.selected.clear(); this._renderTable(); this._renderBulk(); } }, "Clear"));
    bar.append(el("span", { class: "sep" }));
    bar.append(
      el("button", { onclick: () => this._bulkMoveCategory() }, "Move to category…"),
      el("button", { onclick: () => this._bulkMoveStock() }, "Move stock to location…"),
      el("button", { onclick: () => addPartsToQuote(this._ids()) }, "Add to quote…"),
      el("button", { onclick: () => this._bulkTag() }, "Add tag…"),
      el("button", { onclick: () => addToLabelSheet(this._ids()) }, "Print labels…"),
      el("button", { onclick: () => this._bulkMinStock() }, "Set min stock…"),
      el("button", { class: "ghost", onclick: () => this._bulkDelete() }, "Delete"),
    );
    this.bulkHost.append(bar);
  }

  async _selectAll() {
    const { ids } = await api(`/api/parts/ids?${this._query()}`);
    ids.forEach((i) => this.selected.add(i));
    this._renderTable();
    this._renderBulk();
  }

  _ids() { return [...this.selected]; }

  async _runBulk(action, params, describe) {
    const res = await api("/api/bulk", { method: "POST", body: { ids: this._ids(), action, params } });
    this.selected.clear();
    await this.reload();
    if (res.op_id)
      toast(res.summary || describe, { actionText: "Undo", onAction: async () => {
        await api(`/api/bulk/${res.op_id}/undo`, { method: "POST" }); this.reload(); toast("Undone");
      } });
    else toast(describe);
  }

  _bulkMoveCategory() {
    const sel = el("select");
    treeOptions("/api/categories", { includeBlank: "—" }).then((o) => sel.append(...o));
    modal({ title: `Move ${this.selected.size} part(s) to category`,
      body: el("div", { class: "modal-body" }, el("div", { class: "row" }, el("label", {}, "Category"), sel)),
      confirmText: "Move",
      onConfirm: () => this._runBulk("move_category", { category_id: Number(sel.value) || null }, "Moved") });
  }

  _bulkMoveStock() {
    const to = el("select");
    const from = el("select");
    Promise.all([treeOptions("/api/locations", { includeBlank: "— pick —" }), treeOptions("/api/locations", { includeBlank: "Any" })])
      .then(([a, b]) => { to.append(...a); from.append(...b); });
    modal({ title: `Move stock of ${this.selected.size} part(s)`,
      body: el("div", { class: "modal-body" },
        el("div", { class: "row" }, el("label", {}, "From"), from),
        el("div", { class: "row" }, el("label", {}, "To"), to),
        el("div", { class: "hint" }, "Moves the current on-hand quantity. Undoable.")),
      confirmText: "Move stock",
      onConfirm: () => {
        if (!to.value) throw new Error("Pick a destination");
        return this._runBulk("move_stock", { to_location_id: Number(to.value), from_location_id: from.value ? Number(from.value) : null }, "Stock moved");
      } });
  }

  _bulkTag() {
    const inp = el("input", { type: "text", placeholder: "tag name" });
    modal({ title: `Add tag to ${this.selected.size} part(s)`,
      body: el("div", { class: "modal-body" }, el("div", { class: "row" }, el("label", {}, "Tag"), inp)),
      confirmText: "Add tag",
      onConfirm: () => { if (!inp.value.trim()) throw new Error("empty tag"); return this._runBulk("add_tag", { tag: inp.value.trim() }, "Tag added"); } });
  }

  _bulkMinStock() {
    const inp = el("input", { type: "text", value: "0", inputmode: "numeric" });
    modal({ title: `Set min stock on ${this.selected.size} part(s)`,
      body: el("div", { class: "modal-body" }, el("div", { class: "row" }, el("label", {}, "Min stock"), inp)),
      confirmText: "Set",
      onConfirm: () => this._runBulk("set_min_stock", { min_stock: Number(inp.value) || 0 }, "Min stock set") });
  }

  _bulkDelete() {
    const n = this.selected.size;
    modal({ title: `Delete ${n} part(s)?`,
      body: el("div", { class: "modal-body" }, el("div", {}, "Removes the parts and their stock history. Not undoable.")),
      confirmText: "Delete",
      onConfirm: async () => {
        await api("/api/bulk", { method: "POST", body: { ids: this._ids(), action: "delete", params: {} } });
        this.selected.clear();
        await this.reload();
        toast(`Deleted ${n} part(s)`);
      } });
  }

  // shared by the modal's plain "Create" and its "Look up specs…" shortcut
  async _createPartFromFields({ name, mpn, mfr, desc, cat, mount, fp, minStock, tags, qty, loc }) {
    const body = {
      name: name.value.trim(),
      mpn: mpn.value.trim() || null,
      manufacturer: mfr.value.trim() || null,
      description: desc.value.trim() || null,
      category_id: cat.value ? Number(cat.value) : null,
      mount: mount.value.trim() || null,
      footprint_raw: fp.value.trim() || null,
      min_stock: Number(minStock.value) || 0,
      tags: tags.value.split(",").map((s) => s.trim()).filter(Boolean),
    };
    const { id } = await api("/api/parts", { method: "POST", body });
    const n = Number(qty.value) || 0;
    if (n > 0) {
      await api(`/api/parts/${id}/stock`, {
        method: "POST",
        body: { delta: n, kind: "add", location_id: loc.value ? Number(loc.value) : null },
      });
    }
    return { id, name: body.name };
  }

  _newPart() {
    const name = el("input", { type: "text", placeholder: "e.g. LM358 or M3x10 screw" });
    const mpn = el("input", { type: "text", placeholder: "manufacturer part no. — scan or type" });
    const mfr = el("input", { type: "text" });
    const desc = el("input", { type: "text" });
    const cat = el("select");
    const mount = selectWithAdd("", []);
    api("/api/meta/attr-values").then((v) => mount.setOptions(v.mount || []));
    const fp = el("input", { type: "text", placeholder: "e.g. 0805, SOIC-8, TO-220" });
    const minStock = el("input", { type: "text", value: "0", inputmode: "numeric", style: "width:6em" });
    const tags = el("input", { type: "text", placeholder: "comma,separated" });
    const qty = el("input", { type: "text", value: "0", inputmode: "numeric", style: "width:6em" });
    const loc = el("select");
    const fields = { name, mpn, mfr, desc, cat, mount, fp, minStock, tags, qty, loc };

    treeOptions("/api/categories", { includeBlank: "—" }).then((o) => {
      cat.append(...o);
      if (this.rail.mode === "categories" && this.rail.id) cat.value = String(this.rail.id);
    });
    treeOptions("/api/locations", { includeBlank: "— none —" }).then((o) => {
      loc.append(...o);
      if (this.rail.mode === "locations" && this.rail.id) loc.value = String(this.rail.id);
    });

    // A scan while this modal is open fills a field instead of doing the
    // normal parts-list scan lookup: a pure-digit code -> Qty (a count you
    // scanned or keyed on the scanner), anything else -> MPN.
    const onScan = (e) => {
      const code = e.detail.code;
      if (/^\d+$/.test(code)) {
        qty.value = code;
        toast(`Scanned qty: ${code}`);
      } else {
        mpn.value = code;
        if (!name.value.trim()) name.value = code;
        toast(`Scanned MPN: ${code}`);
      }
    };
    document.addEventListener("partsnas:scan", onScan);

    const lookupBtn = el("button", { class: "ghost", onclick: () => doLookup() }, "Look up specs…");
    const doLookup = async () => {
      if (!mpn.value.trim()) return toast("Enter or scan an MPN first");
      if (!name.value.trim()) name.value = mpn.value.trim();
      await withBusy(lookupBtn, async () => {
        const { id } = await this._createPartFromFields(fields);
        await this.reload();
        handle.close();
        const detail = new PartDetail(id, { onChange: () => this.reload() });
        await detail.open();
        const classes = await api("/api/meta/part-classes");
        openLookup(detail.p, classes[detail.p.part_class]?.fields || [], () => detail._reload());
      });
    };

    const row = (label, ...ctl) => el("div", { class: "row" }, el("label", {}, label), ...ctl);
    const handle = modal({
      title: "New part",
      wide: true,
      confirmText: "Create",
      onClose: () => document.removeEventListener("partsnas:scan", onScan),
      body: el("div", { class: "modal-body" },
        el("div", { class: "hint" }, "📷 Scanner ready — a scanned number fills Qty, anything else fills MPN."),
        row("Name *", name),
        row("MPN", mpn, lookupBtn),
        row("Manufacturer", mfr),
        row("Description", desc),
        row("Category", cat),
        row("Mount", mount),
        row("Footprint", fp),
        row("Min stock", minStock),
        row("Tags", tags),
        el("div", { class: "hint" }, "Optional starting stock — you can also add it later on the Stock tab."),
        row("Initial qty", qty, el("span", { style: "opacity:.7" }, "into"), loc),
        el("div", { class: "hint" }, "\"Look up specs…\" creates the part from just the MPN, then opens Look up (Mouser/Digi-Key) to fill in the rest. \"Create\" makes it from what's filled in here, no lookup.")),
      onConfirm: async () => {
        if (!name.value.trim()) throw new Error("Name is required");
        const { id, name: n } = await this._createPartFromFields(fields);
        await this.reload();
        toast(`Created ${n}`);
        this.openDetail(id);
      },
    });
  }

  async openDetail(id) {
    await new PartDetail(id, { onChange: () => this.reload() }).open();
  }
}
