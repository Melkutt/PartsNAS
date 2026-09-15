// About tab: overall inventory facts (value, counts, logged labor hours).
import { api } from "./api.js";
import { el } from "./ui.js";

const fmt = (n) => Math.round(n).toLocaleString("sv-SE");

export class AboutView {
  constructor() {
    this.el = el("div", { class: "panel" });
  }

  async mount(container) {
    container.append(this.el);
    await this.reload();
  }

  async reload() {
    this.stats = await api("/api/stats");
    this._render();
  }

  _tile(value, label, title) {
    return el("div", { class: "stat-tile", title: title || "" },
      el("div", { class: "stat-value" }, value),
      el("div", { class: "stat-label" }, label));
  }

  _render() {
    const s = this.stats;
    this.el.innerHTML = "";
    this.el.append(
      el("h2", {}, "About"),
      el("div", { class: "panel-body" },
        el("div", { class: "section-title" }, "Inventory"),
        el("div", { class: "stat-grid" },
          this._tile(fmt(s.total_parts), "Distinct parts / MPNs"),
          this._tile(fmt(s.total_stock_units), "Total components in stock"),
        ),
        el("div", { class: "section-title", style: "margin-top:16px" }, "Inventory value"),
        el("div", { class: "hint" },
          `Sale value assumes the standard ${s.markup_percent_used}% markup (same default a new Quote starts at) applied to every part in stock — it's an estimate, not a real quote.`),
        el("div", { class: "stat-grid" },
          this._tile(`${fmt(s.inventory_cost_ex_vat)} ${s.currency}`, "Cost value, ex VAT", "what's currently sitting in stock, at cost"),
          this._tile(`${fmt(s.inventory_cost_inc_vat)} ${s.currency}`, "Cost value, inc VAT"),
          this._tile(`${fmt(s.inventory_sale_ex_vat)} ${s.currency}`, "Sale value, ex VAT", `at ${s.markup_percent_used}% markup`),
          this._tile(`${fmt(s.inventory_sale_inc_vat)} ${s.currency}`, "Sale value, inc VAT", `at ${s.markup_percent_used}% markup`),
        ),
        el("div", { class: "section-title", style: "margin-top:16px" }, "Work"),
        el("div", { class: "stat-grid" },
          this._tile(s.total_labor_hours, "Labor hours logged", "lifetime, across every quote/invoice"),
        ),
      ),
    );
  }
}
