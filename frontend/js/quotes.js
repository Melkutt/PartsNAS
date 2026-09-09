// Quotes tab — invoice basis. Pick parts + qty for a customer; cost is a static
// snapshot, a markup (default 50%) gives the sell price, inc-VAT total rounds up.
import { api } from "./api.js";
import { el, modal, toast, partSearch } from "./ui.js";
import { parseNum } from "./units.js";

export class QuotesView {
  constructor({ openId } = {}) {
    this.el = el("div", { class: "parts" });
    this.openId = openId;
  }

  async mount(container) {
    container.append(this.el);
    if (this.openId) return this.openQuote(this.openId);
    await this.list();
  }

  async list() {
    this.el.innerHTML = "";
    const rows = await api("/api/quotes");
    const panel = el("div", { class: "panel" });
    panel.append(
      el("h2", {}, "Quotes / invoice basis"),
      el("div", { class: "panel-body" },
        el("button", { class: "primary", onclick: () => this.newQuote() }, "+ New quote"),
        this._table(rows)),
    );
    this.el.append(panel);
  }

  _table(rows) {
    const t = el("table", { class: "mini-table", style: "margin-top:12px" });
    t.append(el("tr", {}, el("th", {}, "Customer"), el("th", {}, "Title"), el("th", {}, "Lines"),
      el("th", { class: "num" }, "Sell ex VAT"), el("th", { class: "num" }, "Inc VAT"), el("th", {}, "Status"), el("th", {}, "")));
    for (const q of rows) {
      t.append(el("tr", { style: "cursor:pointer", onclick: () => this.openQuote(q.id) },
        el("td", {}, q.customer || "—"),
        el("td", {}, q.title || `#${q.id}`),
        el("td", {}, String(q.line_count)),
        el("td", { class: "num" }, q.totals.sell_ex_vat),
        el("td", { class: "num" }, q.totals.inc_vat_ceil),
        el("td", { class: q.status === "done" ? "pill-ok" : "pill-off" }, q.status),
        el("td", {}, el("button", { class: "ghost", onclick: (e) => { e.stopPropagation(); this._del(q.id); } }, "✕"))));
    }
    if (!rows.length) t.append(el("tr", {}, el("td", { colspan: "7", class: "pill-off" }, "no quotes yet")));
    return t;
  }

  async _del(id) {
    if (!confirm("Delete this quote?")) return;
    await api(`/api/quotes/${id}`, { method: "DELETE" });
    this.list();
  }

  newQuote() {
    const cust = el("input", { type: "text", placeholder: "customer" });
    const title = el("input", { type: "text", placeholder: "job / title" });
    const markup = el("input", { type: "text", value: "50", style: "width:70px" });
    modal({
      title: "New quote",
      body: el("div", { class: "modal-body" },
        el("div", { class: "row" }, el("label", {}, "Customer"), cust),
        el("div", { class: "row" }, el("label", {}, "Title"), title),
        el("div", { class: "row" }, el("label", {}, "Markup %"), markup)),
      confirmText: "Create",
      onConfirm: async () => {
        const { id } = await api("/api/quotes", { method: "POST",
          body: { customer: cust.value.trim() || null, title: title.value.trim() || null, markup_percent: parseNum(markup.value) ?? 50 } });
        this.openQuote(id);
      },
    });
  }

  async openQuote(id) {
    this.q = await api(`/api/quotes/${id}`);
    this._renderQuote();
  }

  _renderQuote() {
    const q = this.q;
    this.el.innerHTML = "";
    const panel = el("div", { class: "panel", style: "max-width:900px" });
    const head = el("div", { class: "panel-body", id: "quote-print" });

    const cust = el("input", { type: "text", value: q.customer || "", placeholder: "customer",
      onchange: (e) => this._patch({ customer: e.target.value }) });
    const title = el("input", { type: "text", value: q.title || "", placeholder: "title",
      onchange: (e) => this._patch({ title: e.target.value }) });
    const markup = el("input", { type: "text", value: q.markup_percent, style: "width:70px",
      onchange: (e) => this._patch({ markup_percent: parseNum(e.target.value) ?? 50 }) });
    const vat = el("input", { type: "text", value: q.vat_percent, style: "width:70px",
      onchange: (e) => this._patch({ vat_percent: parseNum(e.target.value) ?? 25 }) });
    const status = el("select", { onchange: (e) => this._patch({ status: e.target.value }) },
      el("option", { value: "draft" }, "draft"), el("option", { value: "done" }, "done"));
    status.value = q.status;

    head.append(
      el("div", { class: "no-print", style: "display:flex;gap:8px;margin-bottom:10px" },
        el("button", { class: "ghost", onclick: () => this.list() }, "← all quotes"),
        el("span", { style: "flex:1" }),
        el("button", { onclick: () => window.print() }, "Print"),
        el("button", { onclick: () => (window.location = `/api/quotes/${q.id}/export.csv`) }, "CSV")),
      el("h2", { style: "border:0;padding:0;text-transform:none;letter-spacing:0;color:var(--text);font-size:18px" },
        q.title || `Quote #${q.id}`),
      el("div", { class: "form-grid no-print", style: "max-width:520px;margin:8px 0" },
        el("label", {}, "Customer"), cust,
        el("label", {}, "Title"), title,
        el("label", {}, "Markup %"), markup,
        el("label", {}, "VAT %"), vat,
        el("label", {}, "Status"), status),
      el("div", { class: "print-only", style: "margin:6px 0;color:#000" },
        `Customer: ${q.customer || "—"}    Markup: ${q.markup_percent}%    VAT: ${q.vat_percent}%`),
    );

    // lines
    const t = el("table", { class: "mini-table", style: "margin-top:8px" });
    t.append(el("tr", {}, el("th", {}, "MPN"), el("th", {}, "Description"), el("th", { class: "num" }, "Qty"),
      el("th", { class: "num" }, "Unit cost"), el("th", {}, "Source"), el("th", { class: "num" }, "Sell/u ex"),
      el("th", { class: "num" }, "Line ex"), el("th", { class: "no-print" }, "")));
    for (const ln of q.lines) {
      const qtyI = el("input", { type: "text", value: ln.qty, style: "width:56px",
        onchange: (e) => this._patchLine(ln.id, { qty: parseNum(e.target.value) ?? 1 }) });
      const costI = el("input", { type: "text", value: ln.unit_cost, style: "width:80px",
        title: "static snapshot — edit to override",
        onchange: (e) => this._patchLine(ln.id, { unit_cost: parseNum(e.target.value) ?? 0 }) });
      const noteI = el("input", { type: "text", value: ln.note || "", placeholder: "note (e.g. replaced R12)",
        style: "width:100%", onchange: (e) => this._patchLine(ln.id, { note: e.target.value }) });
      t.append(el("tr", {},
        el("td", {}, ln.mpn || ""),
        el("td", {}, el("div", {}, ln.description), noteI),
        el("td", { class: "num" }, qtyI),
        el("td", { class: "num" }, costI),
        el("td", { style: "color:var(--text-faint);font-size:11px" }, ln.cost_source || ""),
        el("td", { class: "num" }, ln.sell_unit_ex),
        el("td", { class: "num" }, ln.line_ex),
        el("td", { class: "no-print" }, el("button", { class: "ghost", onclick: () => this._delLine(ln.id) }, "✕"))));
    }
    head.append(t);

    head.append(el("div", { class: "no-print", style: "margin-top:8px;display:flex;gap:8px" },
      el("button", { onclick: () => this._addLine() }, "+ Add part"),
      el("button", { class: "ghost", onclick: () => this._addFree() }, "+ Free line")));

    const tt = q.totals;
    head.append(el("div", { style: "margin-top:14px;margin-left:auto;max-width:280px" },
      row("Cost", tt.cost), row("Markup", tt.markup),
      row("Sell ex VAT", tt.sell_ex_vat, true),
      row(`VAT ${q.vat_percent}%`, tt.vat),
      row("Total inc VAT", tt.inc_vat_ceil, true)));

    panel.append(head);
    this.el.append(panel);

    function row(label, val, strong) {
      return el("div", { style: "display:flex;justify-content:space-between;padding:2px 0" + (strong ? ";font-weight:700" : "") },
        el("span", {}, label), el("span", {}, `${val} ${tt.currency}`));
    }
  }

  async _patch(body) { await api(`/api/quotes/${this.q.id}`, { method: "PATCH", body }); this.openQuote(this.q.id); }
  async _patchLine(lid, body) { await api(`/api/quotes/${this.q.id}/lines/${lid}`, { method: "PATCH", body }); this.openQuote(this.q.id); }
  async _delLine(lid) { await api(`/api/quotes/${this.q.id}/lines/${lid}`, { method: "DELETE" }); this.openQuote(this.q.id); }

  _addLine() {
    const ps = partSearch({ placeholder: "search part…" });
    const qty = el("input", { type: "text", value: "1", style: "width:70px" });
    modal({
      title: "Add part to quote",
      body: el("div", { class: "modal-body" },
        el("div", { class: "row" }, el("label", {}, "Part"), ps.el),
        el("div", { class: "row" }, el("label", {}, "Qty"), qty)),
      confirmText: "Add",
      onConfirm: async () => {
        const p = ps.get();
        if (!p) throw new Error("pick a part");
        await api(`/api/quotes/${this.q.id}/lines`, { method: "POST", body: { part_id: p.id, qty: parseNum(qty.value) ?? 1 } });
        toast("Added");
        this.openQuote(this.q.id);
      },
    });
  }

  _addFree() {
    const desc = el("input", { type: "text", placeholder: "description" });
    const mpn = el("input", { type: "text", placeholder: "MPN (optional)" });
    const qty = el("input", { type: "text", value: "1", style: "width:70px" });
    const cost = el("input", { type: "text", value: "0", style: "width:90px" });
    modal({
      title: "Free line",
      body: el("div", { class: "modal-body" },
        el("div", { class: "row" }, el("label", {}, "Description"), desc),
        el("div", { class: "row" }, el("label", {}, "MPN"), mpn),
        el("div", { class: "row" }, el("label", {}, "Qty"), qty),
        el("div", { class: "row" }, el("label", {}, "Unit cost ex VAT"), cost)),
      confirmText: "Add",
      onConfirm: async () => {
        if (!desc.value.trim()) throw new Error("description required");
        await api(`/api/quotes/${this.q.id}/lines`, { method: "POST",
          body: { description: desc.value.trim(), mpn: mpn.value.trim() || null, qty: parseNum(qty.value) ?? 1, unit_cost: parseNum(cost.value) ?? 0 } });
        this.openQuote(this.q.id);
      },
    });
  }
}

// pick or create a quote, then add the given part ids (qty 1). Used by the Parts bulk bar.
export async function addPartsToQuote(partIds) {
  const quotes = await api("/api/quotes");
  const sel = el("select");
  sel.append(el("option", { value: "__new__" }, "+ New quote…"),
    ...quotes.map((q) => el("option", { value: q.id }, `${q.title || "#" + q.id}${q.customer ? " — " + q.customer : ""}`)));
  const newTitle = el("input", { type: "text", placeholder: "new quote title", hidden: quotes.length ? "hidden" : null });
  sel.addEventListener("change", () => (newTitle.hidden = sel.value !== "__new__"));
  if (!quotes.length) sel.value = "__new__";
  modal({
    title: `Add ${partIds.length} part(s) to a quote`,
    body: el("div", { class: "modal-body" },
      el("div", { class: "row" }, el("label", {}, "Quote"), sel), newTitle),
    confirmText: "Add",
    onConfirm: async () => {
      let qid = sel.value;
      if (qid === "__new__") {
        const r = await api("/api/quotes", { method: "POST", body: { title: newTitle.value.trim() || null } });
        qid = r.id;
      }
      await api(`/api/quotes/${qid}/lines/bulk`, { method: "POST", body: partIds.map((id) => ({ part_id: id, qty: 1 })) });
      toast(`Added to quote #${qid}`);
      location.hash = "quotes";
    },
  });
}
