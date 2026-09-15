// Quotes tab — invoice basis. Pick parts + qty for a customer; cost is a static
// snapshot, a markup (default 50%, overridable per line) gives the sell price,
// inc-VAT total rounds up. Tick "Stock" to deduct qty from inventory (reversible);
// tick "Invoiced" to archive it to the Invoices list (reversible).
import { api } from "./api.js";
import { el, modal, toast, partSearch } from "./ui.js";
import { parseNum } from "./units.js";

let CUSTOMERS = null; // cached /api/customers
async function customersList(force) {
  if (!CUSTOMERS || force) CUSTOMERS = await api("/api/customers");
  return CUSTOMERS;
}
let LOGO_URL; // cached /api/settings/logo (undefined = not fetched yet)
async function logoUrl() {
  if (LOGO_URL === undefined) LOGO_URL = (await api("/api/settings/logo")).logo_url;
  return LOGO_URL;
}

export class QuotesView {
  constructor({ openId } = {}) {
    this.el = el("div", { class: "parts" });
    this.openId = openId;
    this.tab = "open"; // open | invoiced
  }

  async mount(container) {
    container.append(this.el);
    if (this.openId) return this.openQuote(this.openId);
    await this.list();
  }

  async list() {
    this.el.innerHTML = "";
    const rows = await api(`/api/quotes?status=${this.tab}`);
    const panel = el("div", { class: "panel", style: "max-width:960px" });
    const seg = el("div", { class: "seg", style: "margin:10px 0 0 12px" });
    for (const t of ["open", "invoiced"])
      seg.append(el("button", { class: this.tab === t ? "active" : "",
        onclick: () => { this.tab = t; this.list(); } }, t === "open" ? "Quotes" : "Invoices"));
    panel.append(
      el("h2", {}, this.tab === "open" ? "Quotes / invoice basis" : "Invoices"),
      el("div", { class: "panel-body" }, seg,
        this.tab === "open" ? el("button", { class: "primary", style: "margin:10px 0 0 6px", onclick: () => this.newQuote() }, "+ New quote") : null,
        this._table(rows)),
    );
    this.el.append(panel);
  }

  _table(rows) {
    const t = el("table", { class: "mini-table", style: "margin-top:12px" });
    t.append(el("tr", {},
      el("th", {}, "Customer"), el("th", {}, "Title"), el("th", {}, "Lines"),
      el("th", { class: "num" }, "Sell ex"), el("th", { class: "num" }, "Inc VAT"),
      el("th", {}, "Stock"), el("th", {}, this.tab === "open" ? "Invoiced" : "Re-open"), el("th", {}, "")));
    for (const q of rows) {
      const stockCb = el("input", { type: "checkbox", checked: q.stock_committed ? "checked" : null,
        title: "deduct line quantities from inventory",
        onclick: async (e) => {
          e.stopPropagation();
          const ep = e.target.checked ? "commit-stock" : "uncommit-stock";
          await api(`/api/quotes/${q.id}/${ep}`, { method: "POST" });
          toast(e.target.checked ? "Stock deducted" : "Stock restored");
          this.list();
        } });
      const invCb = el("input", { type: "checkbox", checked: this.tab === "invoiced" ? "checked" : null,
        title: this.tab === "open" ? "archive to Invoices (also deducts stock)" : "move back to Quotes",
        onclick: async (e) => {
          e.stopPropagation();
          await api(`/api/quotes/${q.id}/${this.tab === "open" ? "invoice" : "unarchive"}`, { method: "POST" });
          toast(this.tab === "open" ? "Invoiced" : "Re-opened");
          this.list();
        } });
      t.append(el("tr", { style: "cursor:pointer", onclick: () => this.openQuote(q.id) },
        el("td", {}, q.customer || "—"),
        el("td", {}, q.title || `#${q.id}`),
        el("td", {}, String(q.line_count)),
        el("td", { class: "num" }, q.totals.sell_ex_vat),
        el("td", { class: "num" }, q.totals.inc_vat_ceil),
        el("td", {}, stockCb),
        el("td", {}, invCb),
        el("td", {}, el("button", { class: "ghost", onclick: (e) => { e.stopPropagation(); this._del(q.id); } }, "✕"))));
    }
    if (!rows.length) t.append(el("tr", {}, el("td", { colspan: "8", class: "pill-off" }, this.tab === "open" ? "no open quotes" : "no invoices")));
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
    [this.q, this.customers, this.logoUrl] = await Promise.all([
      api(`/api/quotes/${id}`),
      customersList(),
      logoUrl(),
    ]);
    this._renderQuote();
  }

  _renderQuote() {
    const q = this.q;
    this.el.innerHTML = "";
    const panel = el("div", { class: "panel", style: "max-width:940px" });
    const head = el("div", { class: "panel-body", id: "quote-print" });

    const cust = el("input", { type: "text", value: q.customer || "", placeholder: "customer name",
      onchange: (e) => this._patch({ customer: e.target.value, customer_id: null }) });
    const custSel = el("select", {});
    custSel.append(el("option", { value: "" }, "— pick saved customer —"),
      ...this.customers.map((c) => el("option", { value: c.id }, c.name)),
      el("option", { value: "__new__" }, "+ New customer…"));
    custSel.value = q.customer_id || "";
    custSel.addEventListener("change", () => {
      if (custSel.value === "__new__") {
        this._newCustomerDialog(
          async (c) => { this.customers.push(c); await this._patch({ customer_id: c.id, customer: c.name }); },
          () => { custSel.value = q.customer_id || ""; },
        );
        return;
      }
      const id = custSel.value ? Number(custSel.value) : null;
      const c = this.customers.find((x) => x.id === id);
      this._patch({ customer_id: id, customer: c ? c.name : q.customer });
    });
    const title = el("input", { type: "text", value: q.title || "", placeholder: "title",
      onchange: (e) => this._patch({ title: e.target.value }) });
    const markup = el("input", { type: "text", value: q.markup_percent, style: "width:70px",
      onchange: (e) => this._patch({ markup_percent: parseNum(e.target.value) ?? 50 }) });
    const vat = el("input", { type: "text", value: q.vat_percent, style: "width:70px",
      onchange: (e) => this._patch({ vat_percent: parseNum(e.target.value) ?? 25 }) });
    if (q.hide_cost) head.classList.add("hide-cost-print");
    const hideCostCb = el("input", { type: "checkbox", checked: q.hide_cost ? "checked" : null,
      onchange: (e) => { head.classList.toggle("hide-cost-print", e.target.checked); this._patch({ hide_cost: e.target.checked }); } });

    head.append(...[
      el("div", { class: "no-print", style: "display:flex;gap:8px;align-items:center;margin-bottom:10px" },
        el("button", { class: "ghost", onclick: () => this.list() }, "← all quotes"),
        el("span", { style: "flex:1" }),
        el("label", { style: "display:flex;gap:4px;align-items:center;font-size:12px;color:var(--text-muted)",
          title: "Omit cost/markup/source from print and CSV/Excel export — the on-screen view here always shows them" },
          hideCostCb, "Hide cost (customer copy)"),
        el("button", { onclick: () => window.print() }, "Print"),
        el("button", { onclick: () => (window.location = `/api/quotes/${q.id}/export.csv`) }, "CSV"),
        el("button", { onclick: () => (window.location = `/api/quotes/${q.id}/export.xlsx`) }, "Excel")),
      el("div", { style: "display:flex;align-items:center;gap:12px" },
        this.logoUrl ? el("img", { src: this.logoUrl, class: "quote-logo" }) : null,
        el("h2", { style: "border:0;padding:0;text-transform:none;letter-spacing:0;color:var(--text);font-size:18px" },
          q.title || `Quote #${q.id}`)),
      q.stock_committed ? el("div", { class: "repl-banner no-print" },
        el("b", {}, "Stock deducted for this quote. "),
        el("a", { href: "#", onclick: async (e) => { e.preventDefault(); await api(`/api/quotes/${q.id}/uncommit-stock`, { method: "POST" }); toast("Restored"); this.openQuote(q.id); } }, "Undo")) : null,
      el("div", { class: "form-grid no-print", style: "max-width:520px;margin:8px 0" },
        el("label", {}, "Customer"), cust,
        el("label", {}, ""), custSel,
        el("label", {}, "Title"), title,
        el("label", {}, "Markup %"), markup,
        el("label", {}, "VAT %"), vat),
      q.customer_info
        ? el("div", { class: "print-only", style: "margin:6px 0 2px;color:#000;white-space:pre-line" },
            [q.customer_info.name, q.customer_info.address,
              [q.customer_info.org_number && `Org.nr: ${q.customer_info.org_number}`,
                q.customer_info.phone && `Tel: ${q.customer_info.phone}`,
                q.customer_info.email].filter(Boolean).join("   ")]
              .filter(Boolean).join("\n"))
        : el("div", { class: "print-only", style: "margin:6px 0 2px;color:#000" }, `Customer: ${q.customer || "—"}`),
      el("div", { class: "print-only", style: "margin:0 0 6px;color:#000" },
        el("span", { class: "cost-col" }, `Markup: ${q.markup_percent}%    `),
        `VAT: ${q.vat_percent}%`),
    ].filter(Boolean));

    const t = el("table", { class: "mini-table", style: "margin-top:8px" });
    t.append(el("tr", {}, el("th", {}, "MPN"), el("th", {}, "Description"), el("th", { class: "num" }, "Qty"),
      el("th", { class: "num cost-col" }, "Unit cost"), el("th", { class: "num cost-col" }, "Markup %"), el("th", { class: "cost-col" }, "Source"),
      el("th", { class: "num" }, "Sell/u ex"), el("th", { class: "num" }, "Line ex"), el("th", { class: "no-print" }, "")));
    for (const ln of q.lines) {
      const qtyI = el("input", { type: "text", value: ln.qty, style: "width:56px",
        onchange: (e) => this._patchLine(ln.id, { qty: parseNum(e.target.value) ?? 1 }) });
      const costI = el("input", { type: "text", value: ln.unit_cost, style: "width:80px",
        title: "static snapshot — edit to override",
        onchange: (e) => this._patchLine(ln.id, { unit_cost: parseNum(e.target.value) ?? 0 }) });
      const mkI = el("input", { type: "text", value: ln.markup_percent ?? "", placeholder: String(q.markup_percent), style: "width:60px",
        title: "blank = use the quote markup",
        onchange: (e) => this._patchLine(ln.id, { markup_percent: e.target.value.trim() === "" ? null : parseNum(e.target.value) }) });
      const noteI = el("input", { type: "text", value: ln.note || "", placeholder: "note (e.g. replaced R12)",
        class: ln.note ? "" : "print-hide-empty",
        style: "width:100%", onchange: (e) => this._patchLine(ln.id, { note: e.target.value }) });
      t.append(el("tr", {},
        el("td", {}, ln.line_type && ln.line_type !== "part" ? el("span", { class: "pill-off" }, ln.line_type.toUpperCase()) : (ln.mpn || "")),
        el("td", {}, el("div", {}, ln.description), noteI),
        el("td", { class: "num" }, qtyI),
        el("td", { class: "num cost-col" }, costI),
        el("td", { class: "num cost-col" }, mkI),
        el("td", { class: "cost-col", style: "color:var(--text-faint);font-size:11px" }, ln.cost_source || ""),
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
      row("Cost", tt.cost, false, true), row("Markup", tt.markup, false, true),
      row("Sell ex VAT", tt.sell_ex_vat, true),
      row(`VAT ${q.vat_percent}%`, tt.vat),
      row("Total inc VAT", tt.inc_vat_ceil, true)));

    head.append(...[
      el("div", { class: "no-print", style: "margin-top:14px" },
        el("label", { style: "display:block;margin-bottom:4px;color:var(--text-muted);font-size:12px" }, "Notes"),
        el("textarea", { style: "width:100%;min-height:70px;resize:vertical",
          placeholder: "Notes for this quote — wraps automatically, Enter for a new line…",
          onchange: (e) => this._patch({ note: e.target.value }) }, q.note || "")),
      q.note ? el("div", { class: "print-only", style: "margin-top:10px;white-space:pre-wrap;color:#000" }, q.note) : null,
    ].filter(Boolean));

    panel.append(head);
    this.el.append(panel);

    function row(label, val, strong, costOnly) {
      return el("div", { class: costOnly ? "cost-col" : "",
        style: "display:flex;justify-content:space-between;padding:2px 0" + (strong ? ";font-weight:700" : "") },
        el("span", {}, label), el("span", {}, `${val} ${tt.currency}`));
    }
  }

  async _patch(body) { await api(`/api/quotes/${this.q.id}`, { method: "PATCH", body }); this.openQuote(this.q.id); }
  async _patchLine(lid, body) { await api(`/api/quotes/${this.q.id}/lines/${lid}`, { method: "PATCH", body }); this.openQuote(this.q.id); }
  async _delLine(lid) { await api(`/api/quotes/${this.q.id}/lines/${lid}`, { method: "DELETE" }); this.openQuote(this.q.id); }

  _addLine() {
    const priceRow = el("div");
    let priceSel = null;
    const ps = partSearch({
      placeholder: "search part…",
      onPick: async (p) => {
        priceRow.innerHTML = "";
        priceSel = null;
        const co = await api(`/api/parts/${p.id}/cost`).catch(() => null);
        if (!co || co.options.length < 2 || co.has_preferred) {
          if (co && co.has_preferred) {
            const pref = co.options.find((o) => o.preferred);
            priceRow.append(el("div", { class: "row" }, el("label", {}, "Price"),
              el("span", { style: "color:var(--text-muted)" }, `${pref.supplier} ${pref.unit_price} ${pref.currency} (preferred)`)));
          }
          return;
        }
        priceSel = el("select");
        for (const o of co.options)
          priceSel.append(el("option", { value: o.link_id },
            `${o.supplier}${o.sku ? " " + o.sku : ""} — ${o.unit_price} ${o.currency}`));
        priceSel.value = String(co.auto_link_id);
        priceRow.append(
          el("div", { class: "row" }, el("label", {}, "Price from"), priceSel),
          el("div", { class: "hint" }, "No ★ preferred supplier — defaults to the dearest. Set ★ on the Suppliers tab to skip this."),
        );
      },
    });
    const qty = el("input", { type: "text", value: "1", style: "width:70px" });
    modal({
      title: "Add part to quote",
      body: el("div", { class: "modal-body" },
        el("div", { class: "row" }, el("label", {}, "Part"), ps.el),
        el("div", { class: "row" }, el("label", {}, "Qty"), qty),
        priceRow),
      confirmText: "Add",
      onConfirm: async () => {
        const p = ps.get();
        if (!p) throw new Error("pick a part");
        const body = { part_id: p.id, qty: parseNum(qty.value) ?? 1 };
        if (priceSel && priceSel.value) body.supplier_link_id = Number(priceSel.value);
        await api(`/api/quotes/${this.q.id}/lines`, { method: "POST", body });
        toast("Added");
        this.openQuote(this.q.id);
      },
    });
  }

  _addFree() {
    const typeSel = el("select", {},
      el("option", { value: "part" }, "Part (manual)"),
      el("option", { value: "labor" }, "Labor"),
      el("option", { value: "fee" }, "Fee"));
    const desc = el("input", { type: "text", placeholder: "description" });
    const mpn = el("input", { type: "text", placeholder: "MPN (optional)" });
    const qty = el("input", { type: "text", value: "1", style: "width:70px" });
    const cost = el("input", { type: "text", value: "0", style: "width:90px" });
    const qtyLabel = el("label", {}, "Qty");
    const costLabel = el("label", {}, "Unit cost ex VAT");
    const mpnRow = el("div", { class: "row" }, el("label", {}, "MPN"), mpn);
    const applyType = () => {
      if (typeSel.value === "labor") {
        qtyLabel.textContent = "Hours";
        costLabel.textContent = "Rate/hour ex VAT";
        mpnRow.style.display = "none";
        qty.disabled = false;
      } else if (typeSel.value === "fee") {
        qtyLabel.textContent = "Qty";
        costLabel.textContent = "Fee amount ex VAT";
        mpnRow.style.display = "none";
        qty.value = "1";
        qty.disabled = true;
      } else {
        qtyLabel.textContent = "Qty";
        costLabel.textContent = "Unit cost ex VAT";
        mpnRow.style.display = "";
        qty.disabled = false;
      }
    };
    typeSel.addEventListener("change", applyType);
    applyType();
    modal({
      title: "Free line",
      body: el("div", { class: "modal-body" },
        el("div", { class: "row" }, el("label", {}, "Type"), typeSel),
        el("div", { class: "row" }, el("label", {}, "Description"), desc),
        mpnRow,
        el("div", { class: "row" }, qtyLabel, qty),
        el("div", { class: "row" }, costLabel, cost)),
      confirmText: "Add",
      onConfirm: async () => {
        if (!desc.value.trim()) throw new Error("description required");
        await api(`/api/quotes/${this.q.id}/lines`, { method: "POST",
          body: { line_type: typeSel.value, description: desc.value.trim(), mpn: mpn.value.trim() || null,
            qty: parseNum(qty.value) ?? 1, unit_cost: parseNum(cost.value) ?? 0 } });
        this.openQuote(this.q.id);
      },
    });
  }

  // used by the "+ New customer…" option in the quote's customer <select>
  _newCustomerDialog(onCreated, onCancel) {
    const name = el("input", { type: "text" });
    const address = el("textarea", { style: "width:100%;min-height:50px" });
    const orgNumber = el("input", { type: "text" });
    const phone = el("input", { type: "text" });
    const email = el("input", { type: "text" });
    modal({
      title: "New customer",
      body: el("div", { class: "modal-body" },
        el("div", { class: "row" }, el("label", {}, "Name"), name),
        el("div", { class: "row" }, el("label", {}, "Address"), address),
        el("div", { class: "row" }, el("label", {}, "Org number"), orgNumber),
        el("div", { class: "row" }, el("label", {}, "Phone"), phone),
        el("div", { class: "row" }, el("label", {}, "Email"), email)),
      confirmText: "Create",
      onConfirm: async () => {
        if (!name.value.trim()) throw new Error("name required");
        const c = await api("/api/customers", { method: "POST",
          body: { name: name.value.trim(), address: address.value.trim() || null,
            org_number: orgNumber.value.trim() || null, phone: phone.value.trim() || null,
            email: email.value.trim() || null } });
        await onCreated(c);
      },
      onClose: () => onCancel && onCancel(),
    });
  }
}

// pick or create a quote, then add the given part ids (qty 1). Used by the Parts bulk bar.
export async function addPartsToQuote(partIds) {
  const quotes = await api("/api/quotes?status=open");
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
