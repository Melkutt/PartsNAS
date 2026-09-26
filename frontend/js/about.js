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
    [this.stats, this.health] = await Promise.all([api("/api/stats"), api("/api/health")]);
    this._render();
  }

  // "Check for updates": the published version.json against what is running here
  async _checkUpdates(btn, out) {
    btn.disabled = true;
    out.textContent = "Checking…";
    out.style.color = "";
    try {
      const r = await api("/api/update/check?refresh=1");
      out.textContent = r.message;
      out.style.color = r.status === "newer" || r.status === "other_build" ? "var(--warn)" : r.status === "error" ? "var(--danger)" : "var(--ok, #3fb950)";
      if (r.status === "newer" && r.latest) {
        out.append(document.createElement("br"),
          `${r.latest.released ? r.latest.released + ": " : ""}${r.latest.notes || ""}`.trim(),
          document.createElement("br"),
          "Update: copy the new code to the server and rebuild it (see the README, Backups and updating). Take a snapshot first.");
      }
    } catch (e) {
      out.textContent = `Could not check: ${e.message}`;
      out.style.color = "var(--danger)";
    } finally {
      btn.disabled = false;
    }
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
        el("div", { class: "section-title", style: "margin-top:16px" }, "Sales"),
        el("div", { class: "hint" }, "From invoiced quotes only — not open/draft ones."),
        el("div", { class: "stat-grid" },
          this._tile(`${fmt(s.sales_ex_vat)} ${s.currency}`, "Sales, ex VAT"),
          this._tile(`${fmt(s.sales_inc_vat)} ${s.currency}`, "Sales, inc VAT"),
          this._tile(`${fmt(s.shipping_total)} ${s.currency}`, "Shipping charged"),
          this._tile(s.labor_hours_invoiced, "Labor hours invoiced"),
          this._tile(`${fmt(s.labor_revenue_invoiced)} ${s.currency}`, "Labor revenue invoiced"),
        ),
        el("div", { class: "section-title", style: "margin-top:16px" }, "Work"),
        el("div", { class: "stat-grid" },
          this._tile(s.total_labor_hours, "Labor hours logged", "lifetime, across every quote/invoice"),
        ),
        el("div", { class: "section-title", style: "margin-top:16px" }, "PartsNAS"),
        el("div", {}, `Version ${this.health.version} · build ${this.health.build}`),
        el("div", {}, "SA1CKW - ", el("a", { href: "https://github.com/Melkutt/PartsNAS", target: "_blank", rel: "noopener noreferrer" },
          "https://github.com/Melkutt/PartsNAS")),
        (() => {
          const out = el("div", { class: "hint", style: "padding:6px 0" });
          const btn = el("button", { class: "ghost", onclick: () => this._checkUpdates(btn, out) }, "Check for updates");
          return el("div", { style: "margin-top:8px" }, btn, out);
        })(),
      ),
    );
  }
}
