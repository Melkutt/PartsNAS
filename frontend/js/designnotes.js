// Design Notes tab — searchable "when you build with part X, at condition Y, use these".
// e.g. anchor = SWI234 regulator; condition = "Vout=5V"; links = R1 100k, R2 33k2.
import { api } from "./api.js";
import { el, modal, toast, partSearch } from "./ui.js";
import { PartDetail } from "./partdetail.js";

export class DesignNotesView {
  constructor({ q = "" } = {}) {
    this.el = el("div", { class: "parts" });
    this.q = q;
  }

  async mount(container) {
    container.append(this.el);
    this._chrome();
    await this.reload();
  }

  _chrome() {
    this.search = el("input", {
      type: "search",
      placeholder: "Search anchor, condition, explanation, companion part…",
      value: this.q,
      oninput: () => {
        clearTimeout(this._t);
        this._t = setTimeout(() => this.reload(), 200);
      },
      style: "min-width:320px",
    });
    this.count = el("span", { class: "count-tag" });
    this.el.append(
      el(
        "div",
        { class: "filters" },
        this.search,
        el("span", { class: "grow" }),
        this.count,
        el("button", { class: "primary", onclick: () => this._edit(null) }, "New note"),
      ),
      (this.listHost = el("div", { class: "table-wrap", style: "padding:10px" })),
    );
  }

  async reload() {
    const q = this.search.value.trim();
    const seq = (this._reloadSeq = (this._reloadSeq || 0) + 1); // newest answer wins
    const notes = await api(`/api/design-notes${q ? `?q=${encodeURIComponent(q)}` : ""}`);
    if (seq !== this._reloadSeq) return;
    this.notes = notes;
    this.count.textContent = `${this.notes.length} note${this.notes.length === 1 ? "" : "s"}`;
    this._render();
  }

  _render() {
    this.listHost.innerHTML = "";
    if (!this.notes.length) {
      this.listHost.append(el("div", { class: "hint" }, "No design notes yet. Click “New note”."));
      return;
    }
    for (const n of this.notes) this.listHost.append(this._card(n));
  }

  _card(n) {
    const chips = (n.links || []).map((l) =>
      el("span", { class: "chip" }, `${l.role ? l.role + ": " : ""}${l.label}${l.value_hint ? " (" + l.value_hint + ")" : ""}`),
    );
    return el(
      "div",
      {
        style:
          "border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:8px;background:var(--surface)",
      },
      el(
        "div",
        { style: "display:flex;gap:8px;align-items:baseline;flex-wrap:wrap" },
        el("b", {}, n.title),
        n.condition ? el("span", { class: "chip", style: "border-color:var(--accent);color:var(--accent)" }, n.condition) : null,
        el("span", { class: "grow", style: "flex:1" }),
        el("button", { class: "ghost", onclick: () => this._edit(n) }, "edit"),
        el("button", { class: "ghost", onclick: () => this._del(n) }, "✕"),
      ),
      el(
        "div",
        { class: "sub", style: "margin:3px 0 6px;color:var(--text-muted)" },
        "anchor: ",
        el("a", { href: "#", onclick: (e) => (e.preventDefault(), new PartDetail(n.part_id, {}).open()) },
          `${n.anchor_name || "?"}${n.anchor_mpn && n.anchor_mpn !== n.anchor_name ? " · " + n.anchor_mpn : ""}`),
      ),
      n.body ? el("div", { style: "white-space:pre-wrap;margin-bottom:6px" }, n.body) : null,
      el("div", {}, ...chips),
    );
  }

  async _del(n) {
    if (!confirm(`Delete note “${n.title}”?`)) return;
    await api(`/api/design-notes/${n.id}`, { method: "DELETE" });
    await this.reload();
  }

  async _edit(existing) {
    const full = existing ? await api(`/api/design-notes/${existing.id}`) : null;
    const state = {
      part: full ? { id: full.part_id, name: full.anchor_name, mpn: full.anchor_mpn } : null,
      links: (full?.links || []).map((l) => ({
        part: l.part_id ? { id: l.part_id, name: l.part_name, mpn: l.part_mpn } : null,
        role: l.role || "", value_hint: l.value_hint || "", mpn: l.mpn || "", qty: l.qty || 1,
      })),
    };
    const title = el("input", { type: "text", value: full?.title || "" });
    const cond = el("input", { type: "text", value: full?.condition || "", placeholder: "Vout=5V / fsw=400kHz" });
    const bodyTxt = el("textarea", { style: "width:100%;min-height:70px", }, full?.body || "");

    const anchor = partSearch({ placeholder: "anchor part (the IC / module)…", onPick: (p) => (state.part = p) });
    if (state.part) anchor.set(state.part);

    const linksHost = el("div");
    const renderLinks = () => {
      linksHost.innerHTML = "";
      state.links.forEach((lk, i) => {
        const ps = partSearch({ placeholder: "companion part…", onPick: (p) => (lk.part = p) });
        if (lk.part) ps.set(lk.part);
        const role = el("input", { type: "text", value: lk.role, placeholder: "R1", style: "width:70px",
          oninput: (e) => (lk.role = e.target.value) });
        const vh = el("input", { type: "text", value: lk.value_hint, placeholder: "10k", style: "width:80px",
          oninput: (e) => (lk.value_hint = e.target.value) });
        const mpn = el("input", { type: "text", value: lk.mpn, placeholder: "or free MPN", style: "width:120px",
          oninput: (e) => (lk.mpn = e.target.value) });
        linksHost.append(
          el("div", { class: "row", style: "gap:6px;margin-bottom:5px" },
            role, ps.el, vh, mpn,
            el("button", { class: "ghost", onclick: () => { state.links.splice(i, 1); renderLinks(); } }, "✕")),
        );
      });
    };
    renderLinks();

    const body = el(
      "div",
      { class: "modal-body" },
      el("div", { class: "row" }, el("label", {}, "Anchor part"), anchor.el),
      el("div", { class: "row" }, el("label", {}, "Title"), title),
      el("div", { class: "row" }, el("label", {}, "Condition"), cond),
      el("div", {}, el("label", { style: "color:var(--text-muted)" }, "Explanation"), bodyTxt),
      el("div", { class: "section-title" }, "Companion parts"),
      linksHost,
      el("button", { class: "ghost", onclick: () => { state.links.push({ part: null, role: "", value_hint: "", mpn: "", qty: 1 }); renderLinks(); } }, "+ add companion"),
    );

    modal({
      title: existing ? "Edit design note" : "New design note",
      wide: true,
      body,
      confirmText: "Save",
      onConfirm: async () => {
        if (!state.part) throw new Error("pick an anchor part");
        if (!title.value.trim()) throw new Error("title required");
        const payload = {
          part_id: state.part.id,
          title: title.value.trim(),
          condition: cond.value.trim() || null,
          body: bodyTxt.value.trim() || null,
          links: state.links
            .filter((l) => l.part || l.mpn)
            .map((l) => ({
              part_id: l.part?.id || null,
              role: l.role || null,
              value_hint: l.value_hint || null,
              mpn: l.part ? null : l.mpn || null,
              qty: Number(l.qty) || 1,
            })),
        };
        if (existing) await api(`/api/design-notes/${existing.id}`, { method: "PATCH", body: payload });
        else await api("/api/design-notes", { method: "POST", body: payload });
        toast("Saved");
        await this.reload();
      },
    });
  }
}
