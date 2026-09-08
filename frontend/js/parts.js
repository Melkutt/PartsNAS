// Parts tab: filter bar, checkbox table, bulk action bar, detail drawer.
import { api } from "./api.js";
import { el, modal, toast, treeOptions } from "./ui.js";
import { PartDetail } from "./partdetail.js";

export class PartsView {
  constructor(initial = {}) {
    this.el = el("div", { class: "parts" });
    this.initial = initial; // {category_id, location_id, q}
    this.selected = new Set();
    this.lastTotal = 0;
    this.items = [];
  }

  async mount(container) {
    container.append(this.el);
    this.el.append(this._filterBar(), (this.bulkHost = el("div")), (this.tableWrap = el("div", { class: "table-wrap" })));
    await this._loadFilterOptions();
    if (this.initial.q) this.q.value = this.initial.q;
    if (this.initial.category_id) this.catSel.value = String(this.initial.category_id);
    if (this.initial.location_id) this.locSel.value = String(this.initial.location_id);
    await this.reload();
    document.addEventListener("partsnas:scan", this._onScan);
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
          this._render();
          toast(`Scanned: ${p.name} — selected (${this.selected.size})`);
        } else {
          this.openDetail(p.id);
        }
      })
      .catch(() => toast(`No part matches "${code}"`, {}));
  };

  _filterBar() {
    const bar = el("div", { class: "filters" });
    this.q = el("input", {
      type: "search",
      placeholder: "Search name / MPN / description",
      oninput: () => this._debouncedReload(),
    });
    this.catSel = el("select", { onchange: () => this.reload() });
    this.locSel = el("select", { onchange: () => this.reload() });
    this.low = el("input", { type: "checkbox", onchange: () => this.reload() });
    this.scanChk = el("input", {
      type: "checkbox",
      onchange: (e) => (this.scanSelect = e.target.checked),
    });
    this.countTag = el("span", { class: "count-tag" });
    bar.append(
      this.q,
      el("label", {}, "Category ", this.catSel),
      el("label", {}, "Location ", this.locSel),
      el("label", {}, this.low, " Low stock"),
      el("label", { title: "Scanned codes tick the row instead of opening it" }, this.scanChk, " Scan→select"),
      el("span", { class: "grow" }),
      this.countTag,
    );
    return bar;
  }

  async _loadFilterOptions() {
    this.catSel.append(...(await treeOptions("/api/categories", { includeBlank: "All categories" })));
    this.locSel.append(...(await treeOptions("/api/locations", { includeBlank: "All locations" })));
  }

  _debouncedReload() {
    clearTimeout(this._t);
    this._t = setTimeout(() => this.reload(), 250);
  }

  _currentFilter() {
    return {
      q: this.q.value.trim() || undefined,
      category_id: this.catSel.value || undefined,
      location_id: this.locSel.value || undefined,
      low_stock: this.low.checked || undefined,
    };
  }

  async reload() {
    const f = this._currentFilter();
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== undefined));
    const data = await api(`/api/parts?${qs}`);
    this.items = data.items;
    this.lastTotal = data.total;
    // drop selections no longer in view? keep them (select-all-matching may exceed page)
    this._render();
  }

  _render() {
    this.countTag.textContent = `${this.lastTotal} part${this.lastTotal === 1 ? "" : "s"}`;
    this._renderBulk();
    this.tableWrap.innerHTML = "";
    const t = el("table", { class: "parts-table" });
    t.append(
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          el("th", {}, this._allChk()),
          el("th", {}, "Name"),
          el("th", {}, "MPN"),
          el("th", {}, "Category"),
          el("th", {}, "Footprint"),
          el("th", { class: "num" }, "On hand"),
          el("th", {}, "Locations"),
        ),
      ),
    );
    const tb = el("tbody");
    for (const p of this.items) tb.append(this._row(p));
    if (!this.items.length)
      tb.append(el("tr", {}, el("td", { colspan: "7", class: "hint" }, "No parts. Use Import (top-right) to load your PartsBox export.")));
    t.append(tb);
    this.tableWrap.append(t);
  }

  _allChk() {
    const pageIds = this.items.map((p) => p.id);
    const allSel = pageIds.length > 0 && pageIds.every((id) => this.selected.has(id));
    return el("input", {
      type: "checkbox",
      checked: allSel ? "checked" : null,
      onchange: (e) => {
        if (e.target.checked) pageIds.forEach((id) => this.selected.add(id));
        else pageIds.forEach((id) => this.selected.delete(id));
        this._render();
      },
    });
  }

  _row(p) {
    const checked = this.selected.has(p.id);
    const cb = el("input", {
      type: "checkbox",
      checked: checked ? "checked" : null,
      onclick: (e) => {
        e.stopPropagation();
        e.target.checked ? this.selected.add(p.id) : this.selected.delete(p.id);
        tr.classList.toggle("sel", e.target.checked);
        this._renderBulk();
      },
    });
    const onhand = el(
      "td",
      { class: "num " + (p.on_hand <= 0 ? "zero" : p.min_stock && p.on_hand <= p.min_stock ? "low" : "") },
      String(p.on_hand),
    );
    const locs = el(
      "td",
      { class: "locs" },
      p.locations.map((l) => el("span", { class: "chip" }, `${l.location}: ${l.qty}`)),
    );
    const tr = el(
      "tr",
      { class: checked ? "sel" : "", onclick: () => this.openDetail(p.id) },
      el("td", {}, cb),
      el("td", { class: "name" }, p.name),
      el("td", {}, p.mpn || ""),
      el("td", {}, p.category || el("span", { class: "zero" }, "—")),
      el("td", {}, p.footprint || ""),
      onhand,
      locs,
    );
    return tr;
  }

  _renderBulk() {
    this.bulkHost.innerHTML = "";
    const n = this.selected.size;
    if (!n) return;
    const bar = el("div", { class: "bulkbar" });
    bar.append(el("span", { class: "n" }, `${n} selected`));
    if (n < this.lastTotal)
      bar.append(el("button", { class: "ghost", onclick: () => this._selectAllMatching() }, `Select all ${this.lastTotal} matching`));
    bar.append(el("button", { class: "ghost", onclick: () => { this.selected.clear(); this._render(); } }, "Clear"));
    bar.append(el("span", { class: "sep" }));
    bar.append(
      el("button", { onclick: () => this._bulkMoveCategory() }, "Move to category…"),
      el("button", { onclick: () => this._bulkMoveStock() }, "Move stock to location…"),
      el("button", { onclick: () => this._bulkTag() }, "Add tag…"),
      el("button", { onclick: () => this._bulkMinStock() }, "Set min stock…"),
      el("button", { class: "ghost", onclick: () => this._bulkDelete() }, "Delete"),
    );
    this.bulkHost.append(bar);
  }

  async _selectAllMatching() {
    const f = this._currentFilter();
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== undefined && v !== true));
    if (f.low_stock) qs.set("low_stock", "true"); // /ids has no low_stock; approximate by page
    const { ids } = await api(`/api/parts/ids?${qs}`);
    ids.forEach((id) => this.selected.add(id));
    this._render();
  }

  _ids() {
    return [...this.selected];
  }

  async _runBulk(action, params, describe) {
    const res = await api("/api/bulk", { method: "POST", body: { ids: this._ids(), action, params } });
    this.selected.clear();
    await this.reload();
    if (res.op_id)
      toast(res.summary || describe, {
        actionText: "Undo",
        onAction: async () => {
          await api(`/api/bulk/${res.op_id}/undo`, { method: "POST" });
          this.reload();
          toast("Undone");
        },
      });
    else toast(describe);
  }

  _bulkMoveCategory() {
    const sel = el("select");
    treeOptions("/api/categories", { includeBlank: "—" }).then((o) => sel.append(...o));
    const body = el("div", { class: "modal-body" }, el("div", { class: "row" }, el("label", {}, "Category"), sel));
    modal({
      title: `Move ${this.selected.size} part(s) to category`,
      body,
      confirmText: "Move",
      onConfirm: () => this._runBulk("move_category", { category_id: Number(sel.value) || null }, "Moved"),
    });
  }

  _bulkMoveStock() {
    const to = el("select");
    const from = el("select");
    Promise.all([
      treeOptions("/api/locations", { includeBlank: "— pick —" }),
      treeOptions("/api/locations", { includeBlank: "Any (all locations)" }),
    ]).then(([a, b]) => {
      to.append(...a);
      from.append(...b);
    });
    const body = el(
      "div",
      { class: "modal-body" },
      el("div", { class: "row" }, el("label", {}, "From"), from),
      el("div", { class: "row" }, el("label", {}, "To"), to),
      el("div", { class: "hint" }, "Moves the current on-hand quantity. Writes ledger entries; undoable."),
    );
    modal({
      title: `Move stock of ${this.selected.size} part(s)`,
      body,
      confirmText: "Move stock",
      onConfirm: () => {
        if (!to.value) throw new Error("Pick a destination location");
        return this._runBulk(
          "move_stock",
          { to_location_id: Number(to.value), from_location_id: from.value ? Number(from.value) : null },
          "Stock moved",
        );
      },
    });
  }

  _bulkTag() {
    const inp = el("input", { type: "text", placeholder: "tag name" });
    modal({
      title: `Add tag to ${this.selected.size} part(s)`,
      body: el("div", { class: "modal-body" }, el("div", { class: "row" }, el("label", {}, "Tag"), inp)),
      confirmText: "Add tag",
      onConfirm: () => {
        if (!inp.value.trim()) throw new Error("empty tag");
        return this._runBulk("add_tag", { tag: inp.value.trim() }, "Tag added");
      },
    });
  }

  _bulkMinStock() {
    const inp = el("input", { type: "text", value: "0", inputmode: "numeric" });
    modal({
      title: `Set min stock on ${this.selected.size} part(s)`,
      body: el("div", { class: "modal-body" }, el("div", { class: "row" }, el("label", {}, "Min stock"), inp)),
      confirmText: "Set",
      onConfirm: () => this._runBulk("set_min_stock", { min_stock: Number(inp.value) || 0 }, "Min stock set"),
    });
  }

  _bulkDelete() {
    const n = this.selected.size;
    modal({
      title: `Delete ${n} part(s)?`,
      body: el("div", { class: "modal-body" }, el("div", {}, "This removes the parts and their stock history. Not undoable.")),
      confirmText: "Delete",
      onConfirm: async () => {
        await api("/api/bulk", { method: "POST", body: { ids: this._ids(), action: "delete", params: {} } });
        this.selected.clear();
        await this.reload();
        toast(`Deleted ${n} part(s)`);
      },
    });
  }

  async openDetail(id) {
    await new PartDetail(id, { onChange: () => this.reload() }).open();
  }
}
