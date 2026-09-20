// Order tab: every part that has run down to (or below) its Min stock, worst
// first, grouped by the supplier to buy from, with an editable quantity so the
// list can be copied/exported straight into an order.
import { api } from "./api.js";
import { el, modal, toast, treeOptions } from "./ui.js";
import { PartDetail } from "./partdetail.js";
import { parseNum } from "./units.js";

const httpUrl = (u) => /^https?:\/\//i.test(String(u || "").trim());

// navigator.clipboard only exists on https/localhost; the NAS is plain http on the LAN
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = el("textarea", { style: "position:fixed;left:-9999px" }, text);
    document.body.append(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { /* ignore */ }
    ta.remove();
    return ok;
  }
}

const csvCell = (v) => {
  const s = v == null ? "" : String(v);
  return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export class OrderView {
  constructor() {
    this.el = el("div", { class: "panel", style: "max-width:1200px" });
    this._seq = 0;
  }

  async mount(container) {
    container.append(this.el);
    await this.reload();
  }

  async reload() {
    const seq = ++this._seq; // newest answer wins
    const data = await api("/api/order");
    if (seq !== this._seq) return;
    this.data = data;
    this._render();
    document.dispatchEvent(new CustomEvent("partsnas:orderchanged")); // refresh the tab badge
  }

  _qtyOf(it) { return it.suggested_qty; } // the server returns the remembered quantity, else the shortfall

  // supplier name -> items; parts with no supplier link go last
  _groups() {
    const m = new Map();
    for (const it of this.data.items) {
      const k = it.supplier?.name || "No supplier link yet";
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(it);
    }
    return [...m.entries()].sort(([a], [b]) => (a.startsWith("No supplier") ? 1 : b.startsWith("No supplier") ? -1 : a.localeCompare(b)));
  }

  _lines(items) {
    return items.map((it) => `${it.supplier?.sku || it.mpn || it.name}\t${this._qtyOf(it)}`).join("\n");
  }

  _downloadCsv() {
    const rows = [["Supplier", "SKU", "MPN", "Name", "Qty", "Unit price ex VAT", "Currency", "Line total"]];
    for (const [supplier, items] of this._groups())
      for (const it of items) {
        const q = this._qtyOf(it), p = it.supplier?.unit_price;
        rows.push([supplier.startsWith("No supplier") ? "" : supplier, it.supplier?.sku || "", it.mpn || "", it.name, q,
          p ?? "", it.supplier?.currency || "", p != null ? Math.round(p * q * 100) / 100 : ""]);
      }
    const blob = new Blob(["﻿" + rows.map((r) => r.map(csvCell).join(";")).join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = el("a", { href: URL.createObjectURL(blob), download: `order-list-${new Date().toISOString().slice(0, 10)}.csv` });
    document.body.append(a);
    a.click();
    a.remove();
  }

  _render() {
    const d = this.data;
    this.el.innerHTML = "";
    const body = el("div", { class: "panel-body" });
    this.el.append(el("h2", {}, "Order list"), body);

    if ((d.on_order || []).length) body.append(this._onOrder(d.on_order));

    if (!d.count) {
      body.append(el("div", { class: "hint" },
        d.on_order?.length ? "Nothing more to order right now."
          : "Nothing to order — every part that has a Min stock is above it. Set a Min stock on a part (Details tab) and it is watched here."));
      return;
    }

    body.append(el("div", { style: "display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:4px 6px 10px" },
      el("span", {}, el("b", {}, `${d.count} part${d.count === 1 ? "" : "s"}`), " at or below Min stock",
        d.out ? el("span", { class: "order-out", style: "margin-left:8px" }, `${d.out} out of stock`) : null),
      el("span", { style: "flex:1" }),
      el("button", { title: "One line per part: supplier article number, tab, quantity — paste into a supplier's quick-order / BOM tool",
        onclick: async () => toast((await copyText(this._lines(d.items))) ? "Copied SKU + quantity for all parts" : "Couldn't copy") }, "Copy all"),
      el("button", { class: "primary", onclick: () => this._downloadCsv() }, "Download CSV")));
    body.append(el("div", { class: "hint", style: "padding-top:0" },
      "Worst first. Order qty starts at how far below the minimum the part is (at least 1); type your own and it is remembered for that part " +
      "(clear the box to go back). " +
      "The supplier is the ★ preferred one, else the cheapest priced link. After you have placed the order, press Ordered - it moves to " +
      "'On order' until it arrives, and Received adds it to stock."));

    for (const [supplier, items] of this._groups()) {
      const est = items.reduce((n, it) => n + (it.supplier?.unit_price != null ? it.supplier.unit_price * this._qtyOf(it) : 0), 0);
      const cur = items.find((it) => it.supplier?.currency)?.supplier.currency || "";
      body.append(el("div", { style: "display:flex;gap:10px;align-items:baseline;margin:14px 6px 2px" },
        el("h3", { style: "margin:0;font-size:14px" }, supplier),
        el("span", { class: "hint", style: "padding:0" }, `${items.length} part${items.length === 1 ? "" : "s"}` +
          (est ? ` · about ${Math.round(est * 100) / 100} ${cur} ex VAT` : "")),
        el("span", { style: "flex:1" }),
        supplier.startsWith("No supplier") ? null
          : el("button", { class: "ghost", onclick: async () => toast((await copyText(this._lines(items))) ? `Copied ${supplier} list` : "Couldn't copy") }, "Copy SKU + qty"),
        supplier.startsWith("No supplier") ? null
          : el("button", { class: "ghost", title: "You have placed this order: the parts move to 'On order' until they arrive",
              onclick: () => this._markDialog(items, supplier) }, "Mark all ordered…")));
      body.append(this._table(items, supplier.startsWith("No supplier")));
    }
  }

  async _markOrdered(lines, ref) {
    try {
      await api("/api/order/mark-ordered", { method: "POST", body: { items: lines, ref: ref || null } });
      toast(`${lines.length} part${lines.length === 1 ? "" : "s"} marked as ordered`);
    } catch (e) {
      toast(e.message);
    }
    this.reload();
  }

  _markDialog(items, supplier) {
    const ref = el("input", { type: "text", placeholder: `optional - e.g. your ${supplier} order number`, style: "flex:1" });
    modal({
      title: `Mark ${items.length} part${items.length === 1 ? "" : "s"} from ${supplier} as ordered`,
      confirmText: "Mark ordered",
      body: el("div", { class: "modal-body" },
        el("div", { class: "hint" }, "The parts move to 'On order' with the quantities shown here. When the package arrives, press Received."),
        el("div", { class: "row" }, el("label", {}, "Order ref"), ref)),
      onConfirm: () => this._markOrdered(items.map((it) => ({ part_id: it.id, qty: this._qtyOf(it) })), ref.value.trim()),
    });
  }

  // parts that are bought but not here yet
  _onOrder(list) {
    const wrap = el("div", {});
    wrap.append(el("div", { style: "display:flex;gap:10px;align-items:baseline;margin:6px 6px 2px" },
      el("h3", { style: "margin:0;font-size:14px" }, "On order"),
      el("span", { class: "hint", style: "padding:0" }, `${list.length} part${list.length === 1 ? "" : "s"} waiting for delivery`)));
    const t = el("table", { class: "mini-table" });
    t.append(el("tr", {}, el("th", {}, "Part"), el("th", { class: "num" }, "On hand"), el("th", { class: "num" }, "Ordered"),
      el("th", {}, "Supplier"), el("th", {}, "Ordered on"), el("th", {}, "Ref"), el("th", {}, "")));
    for (const o of list) {
      const when = o.ordered_at ? new Date(o.ordered_at).toLocaleDateString() : "—";
      t.append(el("tr", {},
        el("td", {}, el("a", { href: "#", class: "mpn-link", title: "Open the part",
          onclick: (e) => { e.preventDefault(); new PartDetail(o.id, { onChange: () => this.reload() }).open(); } }, o.name),
          o.mpn && o.mpn !== o.name ? el("span", { class: "zero" }, `  ${o.mpn}`) : null),
        el("td", { class: "num" }, String(o.on_hand)),
        el("td", { class: "num" }, String(o.qty)),
        el("td", {}, o.supplier ? `${o.supplier.name}${o.supplier.sku ? " · " + o.supplier.sku : ""}` : el("span", { class: "zero" }, "—")),
        el("td", {}, when, o.days != null ? el("span", { class: "zero" }, `  (${o.days} d)`) : null),
        el("td", {}, o.ref || el("span", { class: "zero" }, "—")),
        el("td", { style: "white-space:nowrap" },
          el("button", { class: "primary", onclick: () => this._receiveDialog(o) }, "Received…"),
          el("button", { class: "ghost", title: "Not ordered after all - put it back on the order list",
            onclick: async () => { await api("/api/order/unmark-ordered", { method: "POST", body: { part_ids: [o.id] } }); this.reload(); } }, "Undo"))));
    }
    wrap.append(t);
    return wrap;
  }

  _receiveDialog(o) {
    const qty = el("input", { type: "text", inputmode: "numeric", value: o.qty, style: "width:7em" });
    const loc = el("select");
    treeOptions("/api/locations", { includeBlank: "— no location —" }).then((opts) => {
      loc.append(...opts);
      if (o.default_location_id) loc.value = String(o.default_location_id);
    });
    const price = el("input", { type: "text", inputmode: "decimal", style: "width:8em",
      value: o.supplier?.unit_price ?? "", placeholder: "per unit" });
    const upd = el("input", { type: "checkbox", checked: "checked" });
    const ref = el("input", { type: "text", value: o.ref || "", style: "flex:1" });
    const row = (label, ...c) => el("div", { class: "row" }, el("label", {}, label), ...c);
    modal({
      title: `Received: ${o.name}`,
      confirmText: "Add to stock",
      body: el("div", { class: "modal-body" },
        el("div", { class: "hint" }, `${o.qty} were ordered. Fewer is fine - the rest stays on order.`),
        row("Quantity", qty),
        row("Location", loc),
        row("Price paid", price, el("span", { style: "opacity:.7" }, `${o.supplier?.currency || ""} per unit, ex VAT`)),
        el("label", { class: "facet-opt", style: "margin:2px 0 6px 6em" }, upd,
          " Use this as the part's supplier price, so quotes are priced on what you actually paid"),
        row("Order ref", ref)),
      onConfirm: async () => {
        const n = Math.round(parseNum(qty.value) ?? 0);
        if (n < 1) throw new Error("Enter how many arrived");
        const p = parseNum(price.value);
        const r = await api("/api/order/receive", { method: "POST", body: {
          part_id: o.id, qty: n, location_id: Number(loc.value) || null,
          unit_price: p == null ? null : p, update_price: upd.checked, ref: ref.value.trim() || null } });
        toast(`Added ${n} - now ${r.on_hand} on hand` + (r.still_on_order ? `, ${r.still_on_order} still on order` : ""));
        this.reload();
      },
    });
  }

  _table(items, noSupplier) {
    const t = el("table", { class: "mini-table" });
    t.append(el("tr", {}, el("th", {}, ""), el("th", {}, "Part"), el("th", { class: "num" }, "On hand"),
      el("th", { class: "num" }, "Min"), el("th", { class: "num", title: "how many to order — editable" }, "Order qty"),
      el("th", { class: "num" }, "Price ex VAT"), el("th", {}, "Supplier article no."), el("th", {}, "")));
    for (const it of items) {
      const sup = it.supplier;
      const minI = el("input", { type: "text", inputmode: "numeric", value: it.min_stock, style: "width:52px",
        title: "Min stock — set 0 to stop watching this part",
        onchange: async (e) => {
          await api(`/api/parts/${it.id}`, { method: "PATCH", body: { min_stock: Math.max(0, Math.round(parseNum(e.target.value) ?? it.min_stock)) } });
          this.reload();
        } });
      const qtyI = el("input", { type: "text", inputmode: "numeric", value: this._qtyOf(it), style: "width:60px",
        title: it.order_qty ? "Remembered for this part — clear the box to go back to the suggestion" : "Type how many to order — it is remembered",
        onchange: async (e) => {
          const n = Math.round(parseNum(e.target.value) ?? 0);
          try {
            // saved on the part, so it is still there next time; empty/0 = back to "how far below the minimum"
            await api(`/api/parts/${it.id}`, { method: "PATCH", body: { order_qty: n >= 1 ? n : null } });
          } catch (err) {
            toast(err.message);
          }
          this.reload();
        } });
      t.append(el("tr", {},
        el("td", {}, el("span", { class: it.status === "out" ? "order-out" : "order-low" }, it.status === "out" ? "OUT" : "low")),
        el("td", {},
          el("a", { href: "#", class: "mpn-link", title: "Open the part",
            onclick: (e) => { e.preventDefault(); new PartDetail(it.id, { onChange: () => this.reload() }).open(); } }, it.name),
          it.mpn && it.mpn !== it.name ? el("span", { class: "zero" }, `  ${it.mpn}`) : null,
          httpUrl(it.datasheet_url) ? el("a", { class: "ds-link", href: it.datasheet_url.trim(), target: "_blank", rel: "noopener noreferrer",
            title: "Open datasheet in a new tab", style: "margin-left:6px" }, "📄") : null,
          it.discontinued ? el("span", { class: "chip", style: "margin-left:6px;border-color:var(--warn);color:var(--warn)" },
            it.replacement ? `discontinued → ${it.replacement}` : "discontinued") : null),
        el("td", { class: "num" }, String(it.on_hand)),
        el("td", { class: "num" }, minI),
        el("td", { class: "num" }, qtyI),
        el("td", { class: "num" }, sup?.unit_price != null ? `${sup.unit_price} ${sup.currency}` : el("span", { class: "zero" }, "—")),
        el("td", {}, sup?.sku
          ? (httpUrl(sup.url) ? el("a", { href: sup.url.trim(), target: "_blank", rel: "noopener noreferrer", title: "Open the product page" }, sup.sku) : sup.sku)
          : el("span", { class: "zero" }, noSupplier ? "add a supplier link" : "—")),
        el("td", {}, el("button", { class: "ghost", title: "You have ordered this: move it to 'On order' until it arrives",
          onclick: async () => { await this._markOrdered([{ part_id: it.id, qty: this._qtyOf(it) }]); } }, "Ordered"))));
    }
    return t;
  }
}
