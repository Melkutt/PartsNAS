// Suppliers management tab: the master list (6 built-ins + your own).
import { api } from "./api.js";
import { el, modal, toast } from "./ui.js";

export class SuppliersView {
  constructor() {
    this.el = el("div", { class: "panel" });
  }

  async mount(container) {
    container.append(this.el);
    await this.reload();
  }

  async reload() {
    this.rows = await api("/api/suppliers");
    this._render();
  }

  _render() {
    this.el.innerHTML = "";
    this.el.append(
      el("h2", {}, "Suppliers"),
      el(
        "div",
        { class: "panel-body" },
        el("button", { class: "primary", onclick: () => this._dialog() }, "+ Add supplier"),
        this._table(),
      ),
    );
  }

  _table() {
    const t = el("table", { class: "mini-table", style: "margin-top:12px" });
    t.append(
      el("tr", {}, el("th", {}, "Name"), el("th", {}, "Website"), el("th", {}, "Country"),
        el("th", {}, "Type"), el("th", {}, "")),
    );
    for (const s of this.rows) {
      t.append(
        el("tr", {},
          el("td", {}, s.name),
          el("td", {}, s.website ? el("a", { href: s.website, target: "_blank" }, s.website.replace(/^https?:\/\//, "")) : "—"),
          el("td", {}, s.country || "—"),
          el("td", { class: s.builtin ? "pill-off" : "" }, s.builtin ? "built-in" : "custom"),
          el("td", {},
            el("button", { class: "ghost", onclick: () => this._dialog(s) }, "edit"),
            s.builtin || s.in_use
              ? el("span", { class: "pill-off", title: s.in_use ? "in use" : "built-in" }, "")
              : el("button", { class: "ghost", onclick: () => this._del(s) }, "✕"),
          ),
        ),
      );
    }
    return t;
  }

  _dialog(existing) {
    const name = el("input", { type: "text", value: existing?.name || "" });
    const website = el("input", { type: "text", value: existing?.website || "", placeholder: "https://" });
    const country = el("input", { type: "text", value: existing?.country || "", placeholder: "SE", style: "width:80px" });
    const body = el("div", { class: "modal-body" },
      el("div", { class: "row" }, el("label", {}, "Name"), name),
      el("div", { class: "row" }, el("label", {}, "Website"), website),
      el("div", { class: "row" }, el("label", {}, "Country"), country));
    modal({
      title: existing ? "Edit supplier" : "Add supplier",
      body,
      confirmText: "Save",
      onConfirm: async () => {
        if (!name.value.trim()) throw new Error("name required");
        const payload = { name: name.value.trim(), website: website.value.trim() || null, country: country.value.trim() || null };
        if (existing) await api(`/api/suppliers/${existing.id}`, { method: "PATCH", body: payload });
        else await api("/api/suppliers", { method: "POST", body: payload });
        toast("Saved");
        await this.reload();
      },
    });
  }

  async _del(s) {
    if (!confirm(`Delete supplier "${s.name}"?`)) return;
    try {
      await api(`/api/suppliers/${s.id}`, { method: "DELETE" });
      await this.reload();
    } catch (e) {
      alert(e.message);
    }
  }
}
