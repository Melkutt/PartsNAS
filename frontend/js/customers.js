// Customers tab: quote/invoice customers (name + contact details).
import { api } from "./api.js";
import { el, modal, toast } from "./ui.js";

export class CustomersView {
  constructor() {
    this.el = el("div", { class: "panel" });
  }

  async mount(container) {
    container.append(this.el);
    await this.reload();
  }

  async reload() {
    this.rows = await api("/api/customers");
    this._render();
  }

  _render() {
    this.el.innerHTML = "";
    this.el.append(
      el("h2", {}, "Customers"),
      el(
        "div",
        { class: "panel-body" },
        el("button", { class: "primary", onclick: () => this._dialog() }, "+ Add customer"),
        this._table(),
      ),
    );
  }

  _table() {
    const t = el("table", { class: "mini-table", style: "margin-top:12px" });
    t.append(
      el("tr", {}, el("th", {}, "Name"), el("th", {}, "Address"), el("th", {}, "Org number"),
        el("th", {}, "Phone"), el("th", {}, "Email"), el("th", {}, "")),
    );
    for (const c of this.rows) {
      t.append(
        el("tr", {},
          el("td", {}, c.name),
          el("td", { style: "white-space:pre-line;max-width:220px" }, c.address || "—"),
          el("td", {}, c.org_number || "—"),
          el("td", {}, c.phone || "—"),
          el("td", {}, c.email || "—"),
          el("td", {},
            el("button", { class: "ghost", onclick: () => this._dialog(c) }, "edit"),
            c.in_use
              ? el("span", { class: "pill-off", title: "linked to a quote" }, "")
              : el("button", { class: "ghost", onclick: () => this._del(c) }, "✕"),
          ),
        ),
      );
    }
    if (!this.rows.length) t.append(el("tr", {}, el("td", { colspan: "6", class: "pill-off" }, "no customers yet")));
    return t;
  }

  _dialog(existing) {
    const name = el("input", { type: "text", value: existing?.name || "" });
    const address = el("textarea", { style: "width:100%;min-height:60px" }, existing?.address || "");
    const orgNumber = el("input", { type: "text", value: existing?.org_number || "", placeholder: "556677-8899" });
    const phone = el("input", { type: "text", value: existing?.phone || "" });
    const email = el("input", { type: "text", value: existing?.email || "" });
    const body = el("div", { class: "modal-body" },
      el("div", { class: "row" }, el("label", {}, "Name"), name),
      el("div", { class: "row" }, el("label", {}, "Address"), address),
      el("div", { class: "row" }, el("label", {}, "Org number"), orgNumber),
      el("div", { class: "row" }, el("label", {}, "Phone"), phone),
      el("div", { class: "row" }, el("label", {}, "Email"), email));
    modal({
      title: existing ? "Edit customer" : "Add customer",
      body,
      confirmText: "Save",
      onConfirm: async () => {
        if (!name.value.trim()) throw new Error("name required");
        const payload = {
          name: name.value.trim(),
          address: address.value.trim() || null,
          org_number: orgNumber.value.trim() || null,
          phone: phone.value.trim() || null,
          email: email.value.trim() || null,
        };
        if (existing) await api(`/api/customers/${existing.id}`, { method: "PATCH", body: payload });
        else await api("/api/customers", { method: "POST", body: payload });
        toast("Saved");
        await this.reload();
      },
    });
  }

  async _del(c) {
    if (!confirm(`Delete customer "${c.name}"?`)) return;
    try {
      await api(`/api/customers/${c.id}`, { method: "DELETE" });
      await this.reload();
    } catch (e) {
      alert(e.message);
    }
  }
}
