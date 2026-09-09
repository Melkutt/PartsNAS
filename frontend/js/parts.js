// Parts tab: left category/location rail, right = faceted filters + results table + bulk bar.
import { api } from "./api.js";
import { el, modal, toast, treeOptions } from "./ui.js";
import { PartDetail } from "./partdetail.js";
import { CatRail } from "./catrail.js";
import { addPartsToQuote } from "./quotes.js";

const FACET_ORDER = ["mount", "footprint", "manufacturer", "location", "tags", "in_stock"];
const FACET_LABEL = {
  mount: "Mount", footprint: "Footprint", manufacturer: "Manufacturer",
  location: "Location", tags: "Tags", in_stock: "Stock",
};
const MOUNT_LABEL = { smd: "SMD", tht: "THT", other: "Other" };

export class PartsView {
  constructor(initial = {}) {
    this.el = el("div", { class: "parts" });
    this.initial = initial;
    this.selected = new Set(); // bulk selection
    this.q = "";
    this.low = false;
    this.scanSelect = false;
    this.rail = { mode: "categories", id: null };
    this.facetSel = { mount: new Set(), footprint: new Set(), manufacturer: new Set(),
      location: new Set(), tags: new Set(), in_stock: null, attr: {} };
    this.expandFacet = new Set();
  }

  async mount(container) {
    container.append(this.el);
    const layout = el("div", { class: "parts-layout" });
    this.el.append(layout);

    const railHost = el("div", { style: "min-height:0;display:flex" });
    this.railCmp = new CatRail({ onSelect: ({ mode, id }) => { this.rail = { mode, id }; this.reload(); } });
    await this.railCmp.mount(railHost);

    this.main = el("div", { class: "parts-main" });
    layout.append(railHost, this.main);
    this.main.append(
      this._topBar(),
      (this.activeHost = el("div", { class: "active-filters" })),
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

  _onScan = (e) => {
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
    const scanL = el("label", { title: "Scanned codes tick the row instead of opening it" },
      el("input", { type: "checkbox", onchange: (e) => (this.scanSelect = e.target.checked) }), " Scan→select");
    this.orderSel = el("select", { onchange: () => this._renderTable() },
      el("option", { value: "name" }, "Sort: name"), el("option", { value: "stock" }, "Sort: stock"));
    this.countTag = el("span", { class: "count-tag" });
    bar.append(this.qInput, lowL, scanL, this.orderSel, el("span", { class: "grow" }), this.countTag);
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
    ]);
    this.items = list.items;
    this.lastTotal = list.total;
    this.facets = facets;
    this._renderActive();
    this._renderFacets();
    this._renderBulk();
    this._renderTable();
  }

  // ---- facets ----
  _renderFacets() {
    const host = this.facetHost;
    host.innerHTML = "";
    const groups = [];
    for (const key of FACET_ORDER) {
      const opts = this.facets[key] || [];
      if (!opts.length && !(key === "in_stock")) continue;
      groups.push(this._facetGroup(key, FACET_LABEL[key], opts, key === "location" ? "location" : key));
    }
    for (const [akey, def] of Object.entries(this.facets.attributes || {})) {
      groups.push(this._facetGroup("attr:" + akey, def.label + (def.unit ? ` (${def.unit})` : ""), def.options, "attr", akey));
    }
    host.hidden = groups.length === 0;
    groups.forEach((g) => host.append(g));
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
    const expanded = this.expandFacet.has(id);
    const list = expanded ? shown : shown.slice(0, 8);
    for (const o of list) {
      const isOn = kind === "in_stock" ? this.facetSel.in_stock === o.value : sel.has(o.value);
      const label2 = kind === "mount" ? (MOUNT_LABEL[o.value] || o.value) : o.value;
      const row = el("label", { class: "facet-opt" + (o.count ? "" : " zero") + (isOn ? " on" : "") },
        el("input", { type: kind === "in_stock" ? "radio" : "checkbox", name: "f-" + id,
          checked: isOn ? "checked" : null,
          onchange: () => this._toggleFacet(kind, akey, o.value) }),
        el("span", { class: "nm", title: label2 }, label2 || "—"),
        el("span", { class: "c" }, o.count),
      );
      g.append(row);
    }
    if (shown.length > 8)
      g.append(el("span", { class: "facet-more",
        onclick: () => { expanded ? this.expandFacet.delete(id) : this.expandFacet.add(id); this._renderFacets(); } },
        expanded ? "less" : `+${shown.length - 8} more`));
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

  async openDetail(id) {
    await new PartDetail(id, { onChange: () => this.reload() }).open();
  }
}
