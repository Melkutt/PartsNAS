// Quotes tab — invoice basis. Pick parts + qty for a customer; cost is a static
// snapshot, a markup (default 50%, overridable per line) gives the sell price,
// inc-VAT total rounds up. Tick "Stock" to deduct qty from inventory (reversible);
// tick "Invoiced" to archive it to the Invoices list (reversible). "Locked"
// freezes editing; deleting sends it to Trash (soft delete) instead of gone
// for good — Trash can restore it or purge it permanently.
import { api } from "./api.js";
import { el, modal, toast, partSearch } from "./ui.js";
import { parseNum } from "./units.js";
import { PartDetail } from "./partdetail.js";

let CUSTOMERS = null; // cached /api/customers
async function customersList(force) {
  if (!CUSTOMERS || force) CUSTOMERS = await api("/api/customers");
  return CUSTOMERS;
}
// not cached: they're edited in Settings while a quote view can stay mounted,
// and a stale logo/footer/Swish number on a printed invoice is worse than one
// tiny extra request per opened quote
async function logoUrl() { return (await api("/api/settings/logo")).logo_url; }
async function footerText() { return (await api("/api/settings/footer")).text; }
async function swishNumber() { return (await api("/api/settings/swish")).number; }
const HIDE_VAT_KEY = "partsnas.hideVatDefault";
// A view preference, not part of the document: show how old the price behind each line is.
// Screen only - it is never printed or exported.
const PRICE_AGE_KEY = "partsnas.quotePriceAge";
const STALE_PRICE_DAYS = 180;

// "Mouser 2026-09-09" -> days since that date (null when the source carries no date)
function priceAgeDays(costSource) {
  const m = String(costSource || "").match(/(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return null;
  const then = Date.UTC(+m[1], +m[2] - 1, +m[3]);
  const now = new Date();
  return Math.max(0, Math.round((Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) - then) / 86400000));
}
// hand over to the Parts tab in "shopping cart" mode for this quote (see app.js / parts.js)
const startShopping = (quoteId) => document.dispatchEvent(new CustomEvent("partsnas:shop", { detail: { quoteId } }));
// "fee" is the stored line_type (unchanged, so existing quotes keep working);
// "Other" is just a friendlier label for it than "Fee" everywhere it's shown.
const LINE_TYPE_LABELS = { labor: "Labor", fee: "Other", shipping: "Shipping" };
const lineTypeLabel = (t) => (LINE_TYPE_LABELS[t] || t).toUpperCase();

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
    const labels = { open: "Quotes", invoiced: "Invoices", archive: "Archive", trash: "Trash" };
    const titles = { open: "Quotes / invoice basis", invoiced: "Invoices", trash: "Trash",
      archive: "Archive — locked invoices" };
    for (const t of ["open", "invoiced", "archive", "trash"])
      seg.append(el("button", { class: this.tab === t ? "active" : "",
        title: t === "archive" ? "Invoices you've locked — finished history" : "",
        onclick: () => { this.tab = t; this.list(); } }, labels[t]));
    // client-side search over number / customer / title — the point of the
    // Archive is digging out an old invoice, so it must be quick to find
    const host = el("div");
    const draw = () => {
      const f = (this.filterText || "").trim().toLowerCase().replace(/^#/, "");
      const shown = f ? rows.filter((q) => `${q.id} ${q.customer || ""} ${q.title || ""}`.toLowerCase().includes(f)) : rows;
      host.innerHTML = "";
      host.append(this.tab === "trash" ? this._trashTable(shown) : this._table(shown)); // archive reuses _table, read-only
    };
    const search = el("input", { type: "search", placeholder: "find by number, customer or title…", value: this.filterText || "",
      style: "margin:10px 0 0 8px;min-width:250px",
      oninput: (e) => { this.filterText = e.target.value; draw(); } });
    draw();
    panel.append(
      el("h2", {}, titles[this.tab]),
      el("div", { class: "panel-body" }, seg,
        this.tab === "open" ? el("button", { class: "primary", style: "margin:10px 0 0 6px", onclick: () => this.newQuote() }, "+ New quote") : null,
        search, host),
    );
    this.el.append(panel);
  }

  _fmtDate(iso) { return iso ? new Date(iso).toLocaleDateString() : "—"; }

  // "priced 12 days ago" - screen only (no-print), red once it is older than STALE_PRICE_DAYS
  _ageTag(ln) {
    const d = priceAgeDays(ln.cost_source);
    if (d == null) return el("div", { class: "no-print", style: "color:var(--warn)" }, ln.cost_source === "no price on file" ? "no price" : "no price date");
    const old = d > STALE_PRICE_DAYS;
    return el("div", { class: "no-print", title: `Supplier price from ${ln.cost_source}`,
      style: old ? "color:var(--warn);font-weight:600" : "" }, `${d} d old${old ? " ⚠" : ""}`);
  }

  _table(rows) {
    const archive = this.tab === "archive"; // read-only history: no stock/re-open toggles
    const t = el("table", { class: "mini-table", style: "margin-top:12px" });
    t.append(el("tr", {},
      el("th", {}, "No."), el("th", {}, "Customer"), el("th", {}, "Title"), el("th", {}, this.tab === "open" ? "Created" : "Invoiced"),
      el("th", {}, "Lines"),
      el("th", { class: "num" }, "Sell ex"), el("th", { class: "num" }, "Inc VAT"),
      archive ? null : el("th", {}, "Stock"),
      archive ? null : el("th", {}, this.tab === "open" ? "Invoiced" : "Re-open"), el("th", {}, "")));
    for (const q of rows) {
      const stockCb = el("input", { type: "checkbox", checked: q.stock_committed ? "checked" : null,
        disabled: q.locked ? "disabled" : null,
        title: q.locked ? "locked" : "deduct line quantities from inventory",
        onclick: async (e) => {
          e.stopPropagation();
          const ep = e.target.checked ? "commit-stock" : "uncommit-stock";
          await api(`/api/quotes/${q.id}/${ep}`, { method: "POST" });
          toast(e.target.checked ? "Stock deducted" : "Stock restored");
          this.list();
        } });
      const invCb = el("input", { type: "checkbox", checked: this.tab === "invoiced" ? "checked" : null,
        disabled: q.locked ? "disabled" : null,
        title: this.tab === "open" ? "archive to Invoices (also deducts stock)" : "move back to Quotes",
        onclick: async (e) => {
          e.stopPropagation();
          await api(`/api/quotes/${q.id}/${this.tab === "open" ? "invoice" : "unarchive"}`, { method: "POST" });
          toast(this.tab === "open" ? "Invoiced" : "Re-opened");
          this.list();
        } });
      t.append(el("tr", { style: "cursor:pointer", onclick: () => this.openQuote(q.id) },
        el("td", { style: "font-variant-numeric:tabular-nums;white-space:nowrap" }, `#${q.id}`),
        el("td", {}, q.customer || "—"),
        el("td", {}, q.title || `#${q.id}`, q.locked ? el("span", { class: "pill-off", title: "locked", style: "margin-left:6px" }, "🔒") : null),
        el("td", {}, this._fmtDate(this.tab === "open" ? q.created_at : q.invoiced_at)),
        el("td", {}, String(q.line_count)),
        el("td", { class: "num" }, q.totals.sell_ex_vat),
        el("td", { class: "num" }, q.totals.inc_vat_ceil),
        archive ? null : el("td", {}, stockCb),
        archive ? null : el("td", {}, invCb),
        el("td", {}, el("button", { class: "ghost", onclick: (e) => { e.stopPropagation(); this._del(q); } }, "✕"))));
    }
    const empty = { open: "no open quotes", invoiced: "no invoices", archive: "no locked invoices yet" }[this.tab];
    if (!rows.length) t.append(el("tr", {}, el("td", { colspan: "10", class: "pill-off" }, empty)));
    return t;
  }

  _trashTable(rows) {
    const t = el("table", { class: "mini-table", style: "margin-top:12px" });
    t.append(el("tr", {}, el("th", {}, "No."), el("th", {}, "Customer"), el("th", {}, "Title"), el("th", {}, "Was"),
      el("th", {}, "Deleted"), el("th", {}, "")));
    for (const q of rows) {
      t.append(el("tr", {},
        el("td", { style: "font-variant-numeric:tabular-nums;white-space:nowrap" }, `#${q.id}`),
        el("td", {}, q.customer || "—"),
        el("td", {}, q.title || `#${q.id}`),
        el("td", {}, q.status === "invoiced" ? "Invoice" : "Quote"),
        el("td", {}, this._fmtDate(q.deleted_at)),
        el("td", { style: "display:flex;gap:6px" },
          el("button", { class: "ghost", onclick: async () => {
            await api(`/api/quotes/${q.id}/restore`, { method: "POST" });
            toast("Restored");
            this.list();
          } }, "Restore"),
          el("button", { class: "ghost", onclick: async () => {
            if (!await this._typedConfirm("Delete permanently",
              `This can't be undone. Type DELETE to permanently remove "${q.title || "#" + q.id}".`)) return;
            await api(`/api/quotes/${q.id}/purge`, { method: "DELETE" });
            toast("Permanently deleted");
            this.list();
          } }, "Delete permanently"))));
    }
    if (!rows.length) t.append(el("tr", {}, el("td", { colspan: "6", class: "pill-off" }, "trash is empty")));
    return t;
  }

  // typed-word confirmation for anything harder to undo than a normal delete
  _typedConfirm(title, message) {
    return new Promise((resolve) => {
      let ok = false;
      const inp = el("input", { type: "text", placeholder: "DELETE" });
      modal({
        title, body: el("div", { class: "modal-body" }, el("p", {}, message), inp),
        confirmText: "Delete",
        onConfirm: () => {
          if (inp.value.trim() !== "DELETE") throw new Error('type "DELETE" exactly to confirm');
          ok = true;
        },
        onClose: () => resolve(ok),
      });
    });
  }

  async _del(q) {
    if (q.locked) {
      if (!await this._typedConfirm("Delete locked invoice",
        `"${q.title || "#" + q.id}" is locked. Type DELETE to move it to Trash anyway.`)) return;
    } else if (!confirm("Delete this quote? (moves to Trash, can be restored)")) {
      return;
    }
    await api(`/api/quotes/${q.id}`, { method: "DELETE" });
    this.list();
  }

  newQuote() {
    const cust = el("input", { type: "text", placeholder: "customer" });
    const title = el("input", { type: "text", placeholder: "job / title" });
    const markup = el("input", { type: "text", value: "50", style: "width:70px" });
    const browse = el("input", { type: "checkbox", checked: "checked" });
    modal({
      title: "New quote",
      body: el("div", { class: "modal-body" },
        el("div", { class: "row" }, el("label", {}, "Customer"), cust),
        el("div", { class: "row" }, el("label", {}, "Title"), title),
        el("div", { class: "row" }, el("label", {}, "Markup %"), markup),
        el("label", { class: "facet-opt", style: "margin-top:8px" }, browse, " then browse parts and click them into the quote")),
      confirmText: "Create",
      onConfirm: async () => {
        const hideVat = localStorage.getItem(HIDE_VAT_KEY) === "true";
        const { id } = await api("/api/quotes", { method: "POST",
          body: { customer: cust.value.trim() || null, title: title.value.trim() || null,
            markup_percent: parseNum(markup.value) ?? 50, hide_vat: hideVat } });
        if (browse.checked) startShopping(id);
        else this.openQuote(id);
      },
    });
  }

  async openQuote(id) {
    [this.q, this.customers, this.logoUrl, this.footerText, this.swishNumber] = await Promise.all([
      api(`/api/quotes/${id}`),
      customersList(),
      logoUrl(),
      footerText(),
      swishNumber(),
    ]);
    this._renderQuote();
  }

  _renderQuote() {
    const q = this.q;
    const locked = q.locked;
    this.el.innerHTML = "";
    const panel = el("div", { class: "panel", style: "max-width:940px" });
    const head = el("div", { class: "panel-body", id: "quote-print" });

    const cust = el("input", { type: "text", value: q.customer || "", placeholder: "customer name", disabled: locked ? "disabled" : null,
      onchange: (e) => this._patch({ customer: e.target.value, customer_id: null }) });
    const custSel = el("select", { disabled: locked ? "disabled" : null });
    custSel.append(el("option", { value: "" }, "— pick saved customer —"),
      ...this.customers.map((c) => el("option", { value: c.id }, c.name)),
      // an archived customer is hidden from the list but must still show on the quote it belongs to
      q.customer_id && !this.customers.some((c) => c.id === q.customer_id)
        ? el("option", { value: q.customer_id }, `${q.customer || "customer"} (archived)`) : null,
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
    const title = el("input", { type: "text", value: q.title || "", placeholder: "title", disabled: locked ? "disabled" : null,
      onchange: (e) => this._patch({ title: e.target.value }) });
    const markup = el("input", { type: "text", value: q.markup_percent, style: "width:70px", disabled: locked ? "disabled" : null,
      onchange: (e) => this._patch({ markup_percent: parseNum(e.target.value) ?? 50 }) });
    const vat = el("input", { type: "text", value: q.vat_percent, style: "width:70px", disabled: locked ? "disabled" : null,
      onchange: (e) => this._patch({ vat_percent: parseNum(e.target.value) ?? 25 }) });
    if (q.hide_cost) head.classList.add("hide-cost-print");
    const hideCostCb = el("input", { type: "checkbox", checked: q.hide_cost ? "checked" : null, disabled: locked ? "disabled" : null,
      onchange: (e) => { head.classList.toggle("hide-cost-print", e.target.checked); this._patch({ hide_cost: e.target.checked }); } });
    const hideVatCb = el("input", { type: "checkbox", checked: q.hide_vat ? "checked" : null, disabled: locked ? "disabled" : null,
      onchange: (e) => { localStorage.setItem(HIDE_VAT_KEY, String(e.target.checked)); this._patch({ hide_vat: e.target.checked }); } });
    const lockedCb = el("input", { type: "checkbox", checked: locked ? "checked" : null,
      onchange: (e) => this._patch({ locked: e.target.checked }) });
    const docLabel = q.status === "invoiced" ? "Invoice" : "Quote";
    let showAge = false;
    try { showAge = localStorage.getItem(PRICE_AGE_KEY) === "true"; } catch { /* private mode */ }
    const ageCb = el("input", { type: "checkbox", checked: showAge ? "checked" : null,
      onchange: (e) => { try { localStorage.setItem(PRICE_AGE_KEY, String(e.target.checked)); } catch { /* ignore */ } this.openQuote(q.id); } });
    const aged = showAge ? q.lines.filter((l) => l.part_id).map((l) => ({ l, d: priceAgeDays(l.cost_source) })).filter((x) => x.d != null) : [];
    const oldest = aged.length ? aged.reduce((a, b) => (b.d > a.d ? b : a)) : null;
    // parts that were added while they had no price at all (they'd print as 0 / free)
    const unpriced = q.lines.filter((l) => l.part_id && l.cost_source === "no price on file");

    head.append(...[
      el("div", { class: "no-print", style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px" },
        el("button", { class: "ghost", onclick: () => this.list() }, "← all quotes"),
        el("span", { style: "flex:1" }),
        el("label", { style: "display:flex;gap:4px;align-items:center;font-size:12px;color:var(--text-muted)",
          title: "Freeze this document against accidental edits — untick to edit again" },
          lockedCb, "🔒 Locked"),
        el("label", { style: "display:flex;gap:4px;align-items:center;font-size:12px;color:var(--text-muted)",
          title: "Omit cost/markup/source from print and CSV/Excel export — the on-screen view here always shows them" },
          hideCostCb, "Hide cost (customer copy)"),
        el("label", { style: "display:flex;gap:4px;align-items:center;font-size:12px;color:var(--text-muted)",
          title: "Show how old each line's supplier price is (from the date in its source). Only on screen: never printed or exported." },
          ageCb, "Price age"),
        el("label", { style: "display:flex;gap:4px;align-items:center;font-size:12px;color:var(--text-muted)",
          title: "Not VAT-registered — can't itemise VAT on the invoice, so it's folded into one all-inclusive price instead of broken out. Remembered for new quotes." },
          hideVatCb, "No VAT"),
        q.status === "open" ? el("button", { class: "primary", title: "Also deducts stock, same as ticking Invoiced in the list",
          onclick: async () => {
            if (unpriced.length && !confirm(`${unpriced.length} line(s) have no price and would print as 0. Invoice anyway?`)) return;
            await api(`/api/quotes/${q.id}/invoice`, { method: "POST" });
            toast("Marked as Invoice");
            this.openQuote(q.id);
          } }, "→ Invoice") : null,
        el("button", { onclick: () => window.print() }, "Print"),
        el("button", { onclick: () => (window.location = `/api/quotes/${q.id}/export.csv`) }, "CSV"),
        el("button", { onclick: () => (window.location = `/api/quotes/${q.id}/export.xlsx`) }, "Excel")),
      el("div", { style: "display:flex;align-items:center;gap:12px" },
        this.logoUrl ? el("img", { src: this.logoUrl, class: "quote-logo" }) : null,
        el("h2", { style: "border:0;padding:0;text-transform:none;letter-spacing:0;color:var(--text);font-size:18px" },
          q.title || `${docLabel} #${q.id}`),
        el("div", { class: "print-only quote-docno" }, `${docLabel} ${q.id}`)),
      el("div", { class: "no-print", style: "font-size:12px;color:var(--text-muted);margin:-2px 0 8px" },
        `Created ${this._fmtDate(q.created_at)}`,
        q.invoiced_at ? ` · Invoiced ${this._fmtDate(q.invoiced_at)}` : ""),
      unpriced.length ? el("div", { class: "repl-banner no-print" },
        el("b", {}, `\u26a0 ${unpriced.length} line${unpriced.length === 1 ? " has" : "s have"} no price: `),
        unpriced.flatMap((l, i) => [i ? ", " : "", el("a", { href: "#", onclick: (e) => { e.preventDefault(); this._openPart(l.part_id); } }, l.mpn || l.description)]),
        ". Click the article number to open the part and fetch prices \u2014 the line is priced when you close it.") : null,
      showAge && oldest ? el("div", { class: "hint no-print", style: "padding:0 0 6px" },
        `Oldest price on this ${docLabel.toLowerCase()}: ${oldest.d} days (${oldest.l.mpn || oldest.l.description}, ${oldest.l.cost_source}).`,
        oldest.d > STALE_PRICE_DAYS ? " Lines older than 6 months are marked." : "") : null,
      q.stock_committed ? el("div", { class: "repl-banner no-print" },
        el("b", {}, "Stock deducted for this quote. "),
        locked ? null : el("a", { href: "#", onclick: async (e) => { e.preventDefault(); await api(`/api/quotes/${q.id}/uncommit-stock`, { method: "POST" }); toast("Restored"); this.openQuote(q.id); } }, "Undo")) : null,
      el("div", { class: "form-grid no-print", style: "max-width:520px;margin:8px 0" },
        el("label", {}, "Customer"), cust,
        el("label", {}, ""), custSel,
        el("label", {}, "Title"), title,
        el("label", {}, "Markup %"), markup,
        el("label", {}, "VAT %"), vat),
      q.customer_info
        ? el("div", { class: "print-only", style: "margin:6px 0 2px;color:#000;white-space:pre-line" },
            [q.customer_info.name, q.customer_info.address,
              q.customer_info.org_number && `Org.nr: ${q.customer_info.org_number}`,
              q.customer_info.phone && `Tel: ${q.customer_info.phone}`,
              q.customer_info.email]
              .filter(Boolean).join("\n"))
        : el("div", { class: "print-only", style: "margin:6px 0 2px;color:#000" }, `Customer: ${q.customer || "—"}`),
      el("div", { class: "print-only", style: "margin:0 0 2px;color:#000" },
        q.invoiced_at ? `Invoice date: ${this._fmtDate(q.invoiced_at)}` : `Quote date: ${this._fmtDate(q.created_at)}`),
      el("div", { class: "print-only cost-col", style: "margin:0 0 6px;color:#000" }, `Markup: ${q.markup_percent}%`),
    ].filter(Boolean));

    const t = el("table", { class: "mini-table", style: "margin-top:8px" });
    t.append(el("tr", {}, el("th", {}, "MPN"), el("th", {}, "Description"), el("th", { class: "num" }, "Qty"),
      el("th", { class: "num cost-col" }, "Unit cost"), el("th", { class: "num cost-col" }, "Markup %"), el("th", { class: "cost-col" }, "Source"),
      el("th", { class: "num" }, "Sell/u ex"), el("th", { class: "num" }, "Line ex"), el("th", { class: "no-print" }, "")));
    for (const ln of q.lines) {
      const qtyI = el("input", { type: "text", value: ln.qty, style: "width:56px", disabled: locked ? "disabled" : null,
        onchange: (e) => this._patchLine(ln.id, { qty: parseNum(e.target.value) ?? 1 }) });
      const costI = el("input", { type: "text", value: ln.unit_cost, style: "width:80px", disabled: locked ? "disabled" : null,
        title: "static snapshot — edit to override",
        onchange: (e) => this._patchLine(ln.id, { unit_cost: parseNum(e.target.value) ?? 0 }) });
      const mkI = el("input", { type: "text", value: ln.markup_percent ?? "", placeholder: String(q.markup_percent), style: "width:60px", disabled: locked ? "disabled" : null,
        title: "blank = use the quote markup",
        onchange: (e) => this._patchLine(ln.id, { markup_percent: e.target.value.trim() === "" ? null : parseNum(e.target.value) }) });
      const noteI = el("input", { type: "text", value: ln.note || "", placeholder: "note (e.g. replaced R12)",
        class: ln.note ? "" : "print-hide-empty", disabled: locked ? "disabled" : null,
        style: "width:100%", onchange: (e) => this._patchLine(ln.id, { note: e.target.value }) });
      const mpnCell = ln.line_type && ln.line_type !== "part" ? el("span", { class: "pill-off" }, lineTypeLabel(ln.line_type))
        : ln.part_id ? el("a", { href: "#", class: "mpn-link", title: "Open this part \u2014 edit it, look up prices",
            onclick: (e) => { e.preventDefault(); this._openPart(ln.part_id); } }, ln.mpn || ln.description)
        : (ln.mpn || "");
      t.append(el("tr", { class: ln.part_id && ln.cost_source === "no price on file" ? "unpriced" : "" },
        el("td", {}, mpnCell),
        el("td", {}, el("div", {}, ln.description), noteI),
        el("td", { class: "num" }, qtyI),
        el("td", { class: "num cost-col" }, costI),
        el("td", { class: "num cost-col" }, mkI),
        el("td", { class: "cost-col", style: "color:var(--text-faint);font-size:11px" }, ln.cost_source || "",
          showAge && ln.part_id ? this._ageTag(ln) : null),
        el("td", { class: "num" }, ln.sell_unit_ex),
        el("td", { class: "num" }, ln.line_ex),
        el("td", { class: "no-print" }, locked ? null : el("button", { class: "ghost", onclick: () => this._delLine(ln.id) }, "✕"))));
    }
    head.append(t);

    head.append(el("div", { class: "no-print", style: "margin-top:8px;display:flex;gap:8px;flex-wrap:wrap" },
      el("button", { class: "primary", disabled: locked ? "disabled" : null,
        title: "Browse categories and filters and click parts into this quote, like a web shop",
        onclick: () => startShopping(q.id) }, "🛒 Browse parts"),
      el("button", { disabled: locked ? "disabled" : null, onclick: () => this._addLine() }, "+ Add part"),
      el("button", { class: "ghost", disabled: locked ? "disabled" : null, onclick: () => this._addFree() }, "+ Free line")));

    const tt = q.totals;
    // Printed page footer (pinned to the bottom of every page by CSS): the
    // seller's own details on the left, a Swish payment QR on the right. The
    // QR only makes sense on a real invoice, in SEK, with something to pay.
    const showSwish = !!this.swishNumber && q.status === "invoiced" && tt.currency === "SEK" && tt.inc_vat_ceil > 0;
    const footer = this.footerText || showSwish
      ? el("div", { class: "quote-footer print-only" },
          el("div", { class: "quote-footer-text" }, this.footerText || ""),
          showSwish ? el("div", { class: "quote-footer-swish" },
            el("span", { class: "swish-word" }, "SWISH:"),
            el("img", { src: `/api/quotes/${q.id}/swish.png?t=${Date.now()}`, alt: "Swish QR" })) : null)
      : null;
    head.append(el("div", { style: "margin-top:14px;margin-left:auto;max-width:280px" },
      ...[
        row("Cost", tt.cost, false, true), row("Markup", tt.markup, false, true),
        q.hide_vat ? null : row("Sell ex VAT", tt.sell_ex_vat, true),
        q.hide_vat ? null : row(`VAT ${tt.vat_percent}%`, tt.vat),
        row(q.hide_vat ? "Total" : "Total inc VAT", tt.inc_vat_ceil, true),
      ].filter(Boolean)));

    head.append(...[
      el("div", { class: "no-print", style: "margin-top:14px" },
        el("label", { style: "display:block;margin-bottom:4px;color:var(--text-muted);font-size:12px" }, "Notes"),
        el("textarea", { style: "width:100%;min-height:70px;resize:vertical", disabled: locked ? "disabled" : null,
          placeholder: "Notes for this quote — wraps automatically, Enter for a new line…",
          onchange: (e) => this._patch({ note: e.target.value }) }, q.note || "")),
      q.note ? el("div", { class: "print-only", style: "margin-top:10px;white-space:pre-wrap;color:#000" }, q.note) : null,
      footer,
    ].filter(Boolean));
    if (footer) head.classList.add("has-footer");

    panel.append(head);
    this.el.append(panel);

    function row(label, val, strong, costOnly) {
      return el("div", { class: costOnly ? "cost-col" : "",
        style: "display:flex;justify-content:space-between;padding:2px 0" + (strong ? ";font-weight:700" : "") },
        el("span", {}, label), el("span", {}, `${val} ${tt.currency}`));
    }
  }

  // open the part on top of the quote; when it closes, price any lines that had
  // no price (the user may have just run a supplier lookup) and redraw
  async _openPart(partId) {
    const q = this.q;
    await new PartDetail(partId, {
      onClose: async () => {
        if (!q.locked) {
          try {
            const r = await api(`/api/quotes/${q.id}/reprice-missing`, { method: "POST" });
            if (r.updated) toast(`Priced ${r.updated} line${r.updated === 1 ? "" : "s"} from the part's supplier prices`);
          } catch { /* nothing to reprice / quote gone */ }
        }
        this.openQuote(q.id);
      },
    }).open();
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
      el("option", { value: "fee" }, "Other"),
      el("option", { value: "shipping" }, "Shipping"));
    const desc = el("input", { type: "text", placeholder: "description" });
    const mpn = el("input", { type: "text", placeholder: "MPN (optional)" });
    const qty = el("input", { type: "text", value: "1", style: "width:70px" });
    const cost = el("input", { type: "text", value: "0", style: "width:90px" });
    const markup = el("input", { type: "text", placeholder: String(this.q.markup_percent), style: "width:70px" });
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
        costLabel.textContent = "Amount ex VAT";
        mpnRow.style.display = "none";
        qty.value = "1";
        qty.disabled = true;
      } else if (typeSel.value === "shipping") {
        qtyLabel.textContent = "Qty";
        costLabel.textContent = "Shipping cost ex VAT";
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
        el("div", { class: "row" }, costLabel, cost),
        el("div", { class: "row" }, el("label", { title: "blank = use the quote's markup" }, "Markup %"), markup)),
      confirmText: "Add",
      onConfirm: async () => {
        if (!desc.value.trim()) throw new Error("description required");
        const body = { line_type: typeSel.value, description: desc.value.trim(), mpn: mpn.value.trim() || null,
          qty: parseNum(qty.value) ?? 1, unit_cost: parseNum(cost.value) ?? 0 };
        if (markup.value.trim() !== "") body.markup_percent = parseNum(markup.value);
        await api(`/api/quotes/${this.q.id}/lines`, { method: "POST", body });
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
  const quotes = (await api("/api/quotes?status=open")).filter((q) => !q.locked); // locked = frozen
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
