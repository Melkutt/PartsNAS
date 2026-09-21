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
import { el, modal, toast, partSearch, treeOptions, withBusy } from "./ui.js";

const CERTAIN = ["mpn", "remembered", "new"];
const badge = (score, kind, why) => {
  const cls = CERTAIN.includes(kind) || kind === "manual" ? "ok" : score >= 70 ? "warn" : "low";
  const label = kind === "mpn" ? "MPN exact" : kind === "remembered" ? "Remembered" : kind === "manual" ? "Picked"
    : kind === "new" ? "New part" : kind === "none" ? "No match" : `~${score}% match`;
  return el("span", { class: `match-badge ${cls}`, title: why ? why : null }, label);
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
    const panel = el("div", { class: "panel bom-panel", style: "max-width:1100px" });
    const body = el("div", { class: "panel-body" });
    panel.append(
      el("h2", {}, "Review BOM"),
      body,
    );
    body.append(
      el("div", { class: "row" }, el("label", {}, "Project name"), nameInp),
      el("div", { class: "hint" },
        "Green = exact (MPN, or a previously-confirmed match). Amber/grey = a guess from footprint + value — pick the right part or tick Remember once you're sure, and it'll apply on its own next time. " +
        "A BOM rarely says which voltage, dielectric (NP0/X7R) or fuse style it means, so press Change on any line to pick another part, or Browse to see the parts that fit."),
    );
    const table = el("table", { class: "mini-table bom-table" });
    table.append(el("tr", {}, el("th", {}, "Refdes"), el("th", {}, "Value"), el("th", {}, "Footprint"),
      el("th", { class: "num" }, "Qty"), el("th", {}, "Match"), el("th", {}, "Part"), el("th", {}, "Remember")));
    this.reviewLines.forEach((ln) => table.append(this._reviewRow(ln)));
    body.append(table);
    body.append(
      el("div", { style: "display:flex;gap:8px;margin-top:14px" },
        el("button", { class: "ghost", onclick: () => this.showList() }, "Cancel"),
        el("button", { class: "primary", onclick: () => this._saveProject(nameInp.value) }, "Save project")),
    );
    this.el.append(panel);
  }

  _reviewRow(ln) {
    const whyText = (m) => m.kind !== "candidate" ? null :
      `A guess: ${(m.why || []).join(", ")}. ${m.score >= 95 ? "95 % is the highest a guess gets — " : ""}` +
      "it becomes exact when you tick Remember, or when the part is found by MPN (put it in the KiCad symbol's MPN field).";
    const badgeCell = el("td", {}, badge(ln.match.score, ln.match.kind, whyText(ln.match)));
    const partCell = el("div", {});
    const renderPartCell = () => {
      partCell.innerHTML = "";
      if (ln.part_id) {
        const c = ln.match.candidates.find((c) => c.id === ln.part_id);
        const name = c?.name || ln.match.part_name || ln.part_id;
        const summary = c?.summary || ln.match.summary;
        partCell.append(...[el("div", {}, name), summary ? el("div", { class: "hint", style: "padding:0" }, summary) : null].filter(Boolean));
      } else {
        partCell.append(el("span", { class: "pill-off" }, "— pick —"));
      }
    };
    renderPartCell();

    const rememberChk = el("input", {
      type: "checkbox", checked: ln.remember ? "checked" : null, disabled: ln.part_id ? null : "disabled",
      onchange: (e) => (ln.remember = e.target.checked),
    });

    const controls = el("span", { class: "bom-controls" });
    let editing = !CERTAIN.includes(ln.match.kind);
    // a part was chosen by hand (search, the list or Browse): show it, and offer to remember it
    const picked = (p) => {
      ln.part_id = p.id;
      ln.match = { ...ln.match, kind: "manual", score: 100, part_id: p.id, part_name: p.name, summary: null };
      renderPartCell();
      rememberChk.disabled = false;
      badgeCell.innerHTML = "";
      badgeCell.append(badge(100, "manual"));
    };
    const buildControls = () => {
      controls.innerHTML = "";
      if (!editing) {
        // exact / remembered: nothing to pick unless this board needs something else
        rememberChk.disabled = true;
        controls.append(el("button", { class: "ghost",
          title: ln.match.kind === "remembered"
            ? "Remembered for this Value + Footprint. Use another part this time (tick Remember to change it for good)."
            : "Use another part for this line",
          onclick: () => { editing = true; rememberChk.disabled = !ln.part_id; buildControls(); } }, "Change…"));
        return;
      }
      if (ln.match.candidates.length > 1) {
        const sel = el("select", {
          onchange: (e) => {
            const c = ln.match.candidates.find((x) => x.id === e.target.value);
            if (c) picked(c);
            else { ln.part_id = null; renderPartCell(); rememberChk.disabled = true; }
          },
        }, el("option", { value: "" }, "— pick manually —"), ...ln.match.candidates.map((c) =>
          el("option", { value: c.id }, `${c.name} — ${c.summary} (~${c.score}%)`)));
        sel.value = ln.part_id || "";
        controls.append(sel);
      } else {
        const ps = partSearch({ placeholder: "search part…", onPick: picked });
        if (ln.part_id) ps.set({ id: ln.part_id, name: ln.match.part_name });
        controls.append(ps.el);
      }
      controls.append(
        el("button", { class: "ghost", title: "Browse the parts that fit this line (value and size are filled in) - like the shopping cart",
          onclick: () => this._browseFor(ln, picked) }, "Browse…"),
        el("button", { class: "ghost", onclick: () => this._newPartFor(ln, onCreated) }, "+ New part"));
    };
    const onCreated = (part) => {
      ln.part_id = part.id;
      ln.match = {
        kind: "new", score: 100, part_id: part.id, part_name: part.name, summary: "new part",
        candidates: [{ id: part.id, name: part.name, summary: "new part", score: 100 }],
      };
      renderPartCell();
      rememberChk.disabled = false;
      badgeCell.innerHTML = "";
      badgeCell.append(badge(100, "new"));
      buildControls();
    };
    buildControls();

    return el("tr", {},
      el("td", {}, ln.refdes || ""),
      el("td", {}, ln.value || ""),
      el("td", { style: "max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" }, ln.footprint || ""),
      el("td", { class: "num" }, String(ln.qty)),
      badgeCell,
      el("td", { class: "bom-part" }, partCell, controls.childNodes.length ? el("div", {}, controls) : null),
      el("td", {}, rememberChk));
  }

  // The Parts list in a window, filtered to what this BOM line asks for (its value and, when the
  // footprint names one, the package size); Use puts the part on the line. Both ways of choosing -
  // the drop-down and the shop-style list - end up in the same place.
  async _browseFor(ln, onPick) {
    const { PartsView } = await import("./parts.js");
    const host = el("div", { style: "height:70vh;min-height:340px" });
    let view = null;
    const size = String(ln.footprint || "").match(/(?<![0-9])(0201|0402|0603|0805|1206|1210|1812|2010|2512)(?![0-9])/)?.[1];
    const m = modal({
      title: `Pick a part for ${ln.refdes} — ${[ln.value, ln.footprint].filter(Boolean).join("  ·  ")}`,
      wide: "min(1180px, 96vw)",
      confirmText: "Close",
      body: host,
      onClose: () => view && view.destroy(),
    });
    view = new PartsView({
      value: ln.value || "",          // by number: "1u" finds 1uF and 1000nF, never 100nF
      footprint: size || null,
      // the reference designator says what kind of part (C -> Capacitor): 1u is also a 1uH inductor
      category_id: ln.match.suggested_category_id || null,
      pick: { onPick: (p) => { onPick({ id: p.id, name: p.name, mpn: p.mpn }); m.close(); } },
    });
    await view.mount(host);
  }

  // Create a part on the spot for a BOM line with no good match — category
  // is preselected from the reference-designator guess (see bommatch.py
  // _suggest_category_id), so it lands in the right place without having
  // to remember to file it later.
  _newPartFor(ln, onCreated) {
    const nameInp = el("input", { type: "text", value: ln.mpn || ln.value || "" });
    const mpnInp = el("input", { type: "text", value: ln.mpn || "" });
    const fpInp = el("input", { type: "text", value: ln.footprint || "" });
    const catSel = el("select");
    treeOptions("/api/categories", { includeBlank: "— none —" }).then((opts) => {
      catSel.append(...opts);
      if (ln.match.suggested_category_id) catSel.value = String(ln.match.suggested_category_id);
    });
    modal({
      title: "New part",
      body: el("div", { class: "modal-body" },
        el("div", { class: "row" }, el("label", {}, "Name *"), nameInp),
        el("div", { class: "row" }, el("label", {}, "MPN"), mpnInp),
        el("div", { class: "row" }, el("label", {}, "Footprint"), fpInp),
        el("div", { class: "row" }, el("label", {}, "Category"), catSel),
        el("div", { class: "hint" }, "Category is guessed from the reference designator (e.g. R → Resistor) — check it. Open the part afterwards to fill in the value, tolerance, etc.")),
      confirmText: "Create",
      onConfirm: async () => {
        if (!nameInp.value.trim()) throw new Error("Name is required");
        const name = nameInp.value.trim();
        const part = await api("/api/parts", { method: "POST", body: {
          name, mpn: mpnInp.value.trim() || null, footprint_raw: fpInp.value.trim() || null,
          category_id: catSel.value ? Number(catSel.value) : null,
        } });
        onCreated({ id: part.id, name });
        toast(`Created ${name}`);
      },
    });
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
    const panel = el("div", { class: "panel bom-panel", style: "max-width:1100px" });
    const boardsInp = el("input", { type: "number", min: 1, value: boards, style: "width:5em",
      onchange: (e) => this.showDetail(id, Number(e.target.value) || 1) });
    const table = el("table", { class: "mini-table bom-table" });
    table.append(el("tr", {}, el("th", { class: "print-only pick-col" }, "✓"), el("th", {}, "Refdes"), el("th", {}, "Part"), el("th", {}, "Value"),
      el("th", {}, "Where it is"),
      el("th", { class: "num" }, "Per board"), el("th", { class: "num" }, `Needed (${boards})`),
      el("th", { class: "num" }, "On hand"), el("th", { class: "num" }, "Short")));
    // a pick list: walk the shelves once instead of hunting for each line
    const firstLoc = (ln) => (ln.locations && ln.locations[0] ? ln.locations[0].location : "\uffff");
    const lines = this.sortByLocation
      ? [...data.lines].sort((a, b) => firstLoc(a).localeCompare(firstLoc(b), undefined, { numeric: true }) ||
          (a.refdes || "").localeCompare(b.refdes || "", undefined, { numeric: true }))
      : data.lines;
    for (const ln of lines) {
      const short = ln.short;
      const where = !ln.part_id ? "—" : ln.locations.length ? ln.locations.map((l) => `${l.location}: ${l.qty}`).join("  ·  ") : "none in stock";
      table.append(el("tr", {},
        el("td", { class: "print-only pick-col" }, "☐"),
        el("td", {}, ln.refdes || ""),
        el("td", {}, ln.part_name
          ? el("div", {}, el("div", {}, ln.part_name), ln.part_summary ? el("div", { class: "hint", style: "padding:0" }, ln.part_summary) : null)
          : el("span", { class: "match-badge low" }, ln.unresolved_mpn || "unresolved")),
        el("td", {}, ln.value || ""),
        el("td", { class: ln.part_id && !ln.locations.length ? "bom-where none" : "bom-where" }, where),
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
    const sortChk = el("input", { type: "checkbox", checked: this.sortByLocation ? "checked" : null,
      onchange: (e) => { this.sortByLocation = e.target.checked; this.showDetail(id, boards); } });
    panel.append(
      el("div", { class: "no-print", style: "display:flex;align-items:center;gap:10px" },
        el("button", { class: "ghost", onclick: () => this.showList() }, "← Projects"),
        el("h2", { style: "margin:0" }, data.name)),
      el("div", { class: "print-only bom-print-head" },
        el("h2", {}, data.name),
        el("div", {}, `${boards} board${boards === 1 ? "" : "s"} · pick list ${new Date().toLocaleDateString()}`)),
      el("div", { class: "panel-body" },
        el("div", { class: "row no-print" }, el("label", {}, "Boards to build"), boardsInp, buildBtn,
          el("span", { style: "flex:1" }),
          el("label", { title: "Order the lines by shelf, so you can collect the parts in one round" }, sortChk, " Sort by location"),
          el("button", { onclick: () => window.print() }, "Print pick list")),
        table,
        el("div", { class: "no-print" },
          el("div", { class: "section-title" }, "Build history"),
          this._buildsTable(id, data.builds, boards))),
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
