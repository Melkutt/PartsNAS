// Customers tab: quote/invoice customers (name + contact details). Archiving
// hides a customer from the list and the quote picker (found again under the
// Archived tab); deleting erases them, except while a locked invoice still
// belongs to them — that's kept history, archive instead.
import { api } from "./api.js";
import { el, modal, toast } from "./ui.js";

export class CustomersView {
  constructor() {
    this.el = el("div", { class: "panel" });
    this.tab = "active"; // active | archived
  }

  async mount(container) {
    container.append(this.el);
    await this.reload();
  }

  async reload() {
    this.rows = await api(`/api/customers?archived=${this.tab === "archived"}`);
    this._render();
  }

  _render() {
    this.el.innerHTML = "";
    const seg = el("div", { class: "seg", style: "margin:6px 0 0 6px" });
    for (const [t, label] of [["active", "Customers"], ["archived", "Archived"]])
      seg.append(el("button", { class: this.tab === t ? "active" : "",
        onclick: () => { this.tab = t; this.reload(); } }, label));
    this.el.append(
      el("h2", {}, this.tab === "archived" ? "Archived customers" : "Customers"),
      el(
        "div",
        { class: "panel-body" },
        seg,
        this.tab === "active" ? el("button", { class: "primary", style: "margin:6px 0 0 8px", onclick: () => this._dialog() }, "+ Add customer") : null,
        this._table(),
      ),
    );
  }

  _table() {
    const t = el("table", { class: "mini-table", style: "margin-top:12px" });
    t.append(
      el("tr", {}, el("th", {}, "Name"), el("th", {}, "Address"), el("th", {}, "Org number"),
        el("th", {}, "Phone"), el("th", {}, "Email"), el("th", {}, "Archived"), el("th", {}, "")),
    );
    for (const c of this.rows) {
      t.append(
        el("tr", {},
          el("td", {}, c.name),
          el("td", { style: "white-space:pre-line;max-width:220px" }, c.address || "—"),
          el("td", {}, c.org_number || "—"),
          el("td", {}, c.phone || "—"),
          el("td", {}, c.email || "—"),
          el("td", {}, el("input", { type: "checkbox", checked: c.archived ? "checked" : null,
            title: c.archived ? "untick to bring back to the customer list" : "hide from the customer list and the quote picker",
            onchange: async (e) => {
              await api(`/api/customers/${c.id}`, { method: "PATCH", body: { archived: e.target.checked } });
              toast(e.target.checked ? "Archived" : "Restored");
              this.reload();
            } })),
          el("td", {},
            el("button", { class: "ghost", onclick: () => this._dialog(c) }, "edit"),
            c.locked_invoices
              ? el("span", { class: "pill-off", title: `${c.locked_invoices} locked invoice(s) still belong to this customer — kept history, so it can't be deleted. Archive it instead.` }, "🔒")
              : el("button", { class: "ghost", title: "delete permanently", onclick: () => this._del(c) }, "✕"),
          ),
        ),
      );
    }
    if (!this.rows.length) t.append(el("tr", {}, el("td", { colspan: "7", class: "pill-off" }, this.tab === "archived" ? "no archived customers" : "no customers yet")));
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
    const detach = c.quotes
      ? `

${c.quotes} quote(s)/invoice(s) are linked to them. Those are detached: the address, phone and email stop appearing on them, but the name typed on each document stays.`
      : "";
    if (!confirm(`Permanently delete "${c.name}" and their contact details?${detach}`)) return;
    try {
      await api(`/api/customers/${c.id}`, { method: "DELETE" });
      await this.reload();
    } catch (e) {
      alert(e.message);
    }
  }
}
