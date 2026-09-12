// BOM tab: import a KiCad BOM export (CSV), review/confirm the match against
// parts already in the database, save it as a Project, then track builds
// (deduct stock for N boards, reversible) and shortages.
//
// Matching (see backend/app/bommatch.py): exact MPN, or a remembered
// Value+Footprint rule, apply automatically. Anything else is only ever a
// scored *suggestion* — confirming one (ticking "remember") saves that exact
// Value+Footprint pairing for next time. A different value on the same
// footprint (an unvalued placeholder, a different voltage, ...) never
// matches an old rule, since the rule is keyed on the value too.
import { api } from "./api.js";
import { el, modal, toast, partSearch, withBusy } from "./ui.js";

const badge = (score, kind) => {
  const cls = kind === "mpn" || kind === "remembered" ? "ok" : score >= 70 ? "warn" : "low";
  const label = kind === "mpn" ? "MPN exact" : kind === "remembered" ? "Remembered" : kind === "none" ? "No match" : `~${score}% match`;
  return el("span", { class: `match-badge ${cls}` }, label);
};

export class BomView {
  constructor() {
    this.el = el("div", { class: "parts" });
    this.mode = "list"; // list | review | detail
  }

  async mount(container) {
    container.append(this.el);
    await this.showList();
  }

  destroy() {}

  async showList() {
    this.mode = "list";
    this.el.innerHTML = "";
    const rows = await api("/api/bom/projects");
    const panel = el("div", { class: "panel", style: "max-width:960px" });
    panel.append(
      el("h2", {}, "BOM / Projects"),
      el("div", { class: "panel-body" },
        el("button", { class: "primary", onclick: () => this.openImportModal() }, "Import BOM…"),
        el("div", { class: "hint" }, "Export a BOM (CSV) from KiCad's schematic editor — Tools → Generate BOM / the Export BOM toolbar button — then import it here."),
        this._projectsTable(rows)),
    );
    this.el.append(panel);
  }

  _projectsTable(rows) {
    if (!rows.length) return el("div", { class: "pill-off", style: "margin-top:10px" }, "No BOMs imported yet.");
    const t = el("table", { class: "mini-table", style: "margin-top:12px" });
    t.append(el("tr", {}, el("th", {}, "Project"), el("th", {}, "Lines"),
      el("th", {}, "Unresolved"), el("th", {}, "Last build"), el("th", {}, "")));
    for (const p of rows) {
      t.append(el("tr", { style: "cursor:pointer", onclick: () => this.showDetail(p.id) },
        el("td", {}, p.name),
        el("td", {}, String(p.line_count)),
        el("td", {}, p.unresolved_count ? el("span", { class: "match-badge low" }, `${p.unresolved_count} unresolved`) : "—"),
        el("td", {}, p.last_build ? new Date(p.last_build).toLocaleDateString() : "never"),
        el("td", {}, el("button", { class: "ghost", onclick: (e) => { e.stopPropagation(); this._deleteProject(p.id); } }, "✕"))));
    }
    return t;
  }

  async _deleteProject(id) {
    if (!confirm("Delete this BOM project? This does not touch stock (past builds already happened).")) return;
    await api(`/api/bom/projects/${id}`, { method: "DELETE" });
    toast("Deleted");
    this.showList();
  }

  // ---------- Import + review ----------
  openImportModal() {
    const fileInp = el("input", { type: "file", accept: ".csv" });
    modal({
      title: "Import BOM",
      confirmText: "Parse",
      body: el("div", { class: "modal-body" },
        el("div", { class: "row" }, el("label", {}, "KiCad BOM (.csv)"), fileInp),
        el("div", { class: "hint" }, "Export from KiCad's schematic editor: Tools → Generate BOM, or the Export BOM toolbar button.")),
      onConfirm: async () => {
        const file = fileInp.files[0];
        if (!file) throw new Error("Choose a .csv file first");
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch("/api/bom/parse", { method: "POST", body: fd });
        const text = await res.text();
        const data = text ? JSON.parse(text) : null;
        if (!res.ok) throw new Error(data?.detail || res.statusText);
        this._startReview(data);
      },
    });
  }

  _startReview(data) {
    this.mode = "review";
    this.el.innerHTML = "";
    this.reviewLines = data.lines.map((l) => ({
      ...l,
      part_id: l.match.part_id,
      remember: false,
    }));
    const nameInp = el("input", { type: "text", value: data.suggested_name, style: "max-width:320px" });
    const panel = el("div", { class: "panel", style: "max-width:1100px" });
    const body = el("div", { class: "panel-body" });
    panel.append(
      el("h2", {}, "Review BOM"),
      body,
    );
    body.append(
      el("div", { class: "row" }, el("label", {}, "Project name"), nameInp),
      el("div", { class: "hint" },
        "Green = exact (MPN, or a previously-confirmed match). Amber/grey = a guess from footprint + value — pick the right part or tick Remember once you're sure, and it'll apply on its own next time."),
    );
    const table = el("table", { class: "mini-table" });
    table.append(el("tr", {}, el("th", {}, "Refdes"), el("th", {}, "Value"), el("th", {}, "Footprint"),
      el("th", { class: "num" }, "Qty"), el("th", {}, "Match"), el("th", {}, "Part"), el("th", {}, "Remember")));
    this.reviewLines.forEach((ln, i) => table.append(this._reviewRow(ln, i)));
    body.append(table);
    body.append(
      el("div", { style: "display:flex;gap:8px;margin-top:14px" },
        el("button", { class: "ghost", onclick: () => this.showList() }, "Cancel"),
        el("button", { class: "primary", onclick: () => this._saveProject(nameInp.value) }, "Save project")),
    );
    this.el.append(panel);
  }

  _reviewRow(ln, i) {
    const m = ln.match;
    const partCell = el("span", {});
    const renderPartCell = () => {
      partCell.innerHTML = "";
      if (ln.part_id) {
        const name = m.candidates.find((c) => c.id === ln.part_id)?.name || m.part_name || ln.part_id;
        partCell.append(name);
      } else {
        partCell.append(el("span", { class: "pill-off" }, "— pick —"));
      }
    };
    renderPartCell();

    const rememberChk = el("input", {
      type: "checkbox", checked: ln.remember ? "checked" : null, disabled: ln.part_id ? null : "disabled",
      onchange: (e) => (ln.remember = e.target.checked),
    });

    const controls = el("span", { style: "display:flex;gap:6px;align-items:center" });
    if (m.kind === "mpn" || m.kind === "remembered") {
      // already certain — nothing to pick, remembering an MPN match would be redundant
      rememberChk.disabled = true;
    } else if (m.candidates.length > 1) {
      const sel = el("select", {
        onchange: (e) => { ln.part_id = e.target.value || null; renderPartCell(); rememberChk.disabled = !ln.part_id; },
      }, el("option", { value: "" }, "— pick manually —"), ...m.candidates.map((c) =>
        el("option", { value: c.id }, `${c.name} (~${c.score}%)`)));
      sel.value = ln.part_id || "";
      controls.append(sel);
    } else {
      const ps = partSearch({
        placeholder: "search part…",
        onPick: (p) => { ln.part_id = p.id; renderPartCell(); rememberChk.disabled = false; },
      });
      if (ln.part_id) ps.set({ id: ln.part_id, name: m.part_name });
      controls.append(ps.el);
    }

    return el("tr", {},
      el("td", {}, ln.refdes || ""),
      el("td", {}, ln.value || ""),
      el("td", { style: "max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" }, ln.footprint || ""),
      el("td", { class: "num" }, String(ln.qty)),
      el("td", {}, badge(m.score, m.kind)),
      el("td", {}, partCell, controls.childNodes.length ? el("div", {}, controls) : null),
      el("td", {}, rememberChk));
  }

  async _saveProject(name) {
    name = name.trim();
    if (!name) return toast("Name the project first");
    const lines = this.reviewLines.map((ln) => ({
      mpn: ln.mpn, value: ln.value, footprint: ln.footprint, qty: ln.qty, refdes: ln.refdes,
      part_id: ln.part_id || null, remember: !!(ln.remember && ln.part_id),
    }));
    try {
      const { id } = await api("/api/bom/projects", { method: "POST", body: { name, lines } });
      toast(`Saved “${name}”`);
      this.showDetail(id);
    } catch (e) {
      toast(e.message);
    }
  }

  // ---------- Project detail: shortage + build ----------
  async showDetail(id, boards = 1) {
    this.mode = "detail";
    const data = await api(`/api/bom/projects/${id}?boards=${boards}`);
    this.el.innerHTML = "";
    const panel = el("div", { class: "panel", style: "max-width:1100px" });
    const boardsInp = el("input", { type: "number", min: 1, value: boards, style: "width:5em",
      onchange: (e) => this.showDetail(id, Number(e.target.value) || 1) });
    const table = el("table", { class: "mini-table" });
    table.append(el("tr", {}, el("th", {}, "Refdes"), el("th", {}, "Part"), el("th", {}, "Value"),
      el("th", { class: "num" }, "Per board"), el("th", { class: "num" }, `Needed (${boards})`),
      el("th", { class: "num" }, "On hand"), el("th", { class: "num" }, "Short")));
    for (const ln of data.lines) {
      const short = ln.short;
      table.append(el("tr", {},
        el("td", {}, ln.refdes || ""),
        el("td", {}, ln.part_name || el("span", { class: "match-badge low" }, ln.unresolved_mpn || "unresolved")),
        el("td", {}, ln.value || ""),
        el("td", { class: "num" }, String(ln.qty_per_board)),
        el("td", { class: "num" }, String(ln.needed)),
        el("td", { class: "num" }, ln.part_id ? String(ln.on_hand) : "—"),
        el("td", { class: "num" }, short ? el("b", { style: "color:var(--danger)" }, String(short)) : (ln.part_id ? "0" : "—"))));
    }
    const buildBtn = el("button", { class: "primary", onclick: async () => {
      if (!confirm(`Deduct stock for ${boardsInp.value} board(s)? This is reversible.`)) return;
      await withBusy(buildBtn, async () => {
        await api(`/api/bom/projects/${id}/build`, { method: "POST", body: { boards: Number(boardsInp.value) || 1 } });
        toast("Stock deducted");
        this.showDetail(id, Number(boardsInp.value) || 1);
      });
    } }, "Build (deduct stock)");
    panel.append(
      el("div", { style: "display:flex;align-items:center;gap:10px" },
        el("button", { class: "ghost", onclick: () => this.showList() }, "← Projects"),
        el("h2", { style: "margin:0" }, data.name)),
      el("div", { class: "panel-body" },
        el("div", { class: "row" }, el("label", {}, "Boards to build"), boardsInp, buildBtn),
        table,
        el("div", { class: "section-title" }, "Build history"),
        this._buildsTable(id, data.builds, boards)),
    );
    this.el.append(panel);
  }

  _buildsTable(id, builds, boards) {
    if (!builds.length) return el("div", { class: "pill-off" }, "No builds yet.");
    const t = el("table", { class: "mini-table" });
    t.append(el("tr", {}, el("th", {}, "When"), el("th", {}, "Boards"), el("th", {}, "Note"), el("th", {}, "")));
    for (const b of builds) {
      t.append(el("tr", {},
        el("td", {}, new Date(b.created_at).toLocaleString()),
        el("td", {}, String(b.qty_boards)),
        el("td", {}, b.reverted ? el("span", { class: "pill-off" }, "reverted") : (b.note || "")),
        el("td", {}, b.reverted ? "" : el("button", { class: "ghost", onclick: async () => {
          await api(`/api/bom/builds/${b.id}/undo`, { method: "POST" });
          toast("Reversed");
          this.showDetail(id, boards);
        } }, "Undo"))));
    }
    return t;
  }
}
