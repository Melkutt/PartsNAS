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
import { splitRefs } from "./refdes.js";
import { PcbView } from "./pcbview.js";

const CERTAIN = ["mpn", "remembered", "new"];
// mounting holes, fiducials, logos, symbols, net ties: on the board, but not something you build in
const AUTO_SKIP = /^(H|MH|FID|G|LOGO|SYM|NT)\d*$/i;
const isSkippable = (refdes) => { const r = splitRefs(refdes); return r.length > 0 && r.every((x) => AUTO_SKIP.test(x)); };
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
    this._destroyBoard();
    this.el.innerHTML = "";
    const rows = await api("/api/bom/projects");
    const panel = el("div", { class: "panel", style: "max-width:960px" });
    panel.append(
      el("h2", {}, "BOM / Projects"),
      el("div", { class: "panel-body" },
        el("div", { class: "bom-import" },
          el("div", { class: "bom-import-card" },
            el("button", { class: "primary", onclick: () => this.openImportModal() }, "Import BOM…"),
            el("div", { class: "hint" },
              "The KiCad BOM file (.csv): Tools → Generate BOM, or the Export BOM button in the schematic editor. " +
              "Matches the lines against your parts, shows what is missing, deducts stock when you build and prints a pick list. " +
              "Add the board file (.kicad_pcb) too and PartsNAS draws the board next to the list: click a line to see where the parts sit, " +
              "click a part on the board to see what it is and where you keep it. The BOM always works without the board."))),
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
        el("td", { style: "white-space:nowrap" },
          el("button", { class: "ghost", title: "Rename", onclick: (e) => { e.stopPropagation(); this._renameProject(p.id, p.name, () => this.showList()); } }, "✎"),
          el("button", { class: "ghost", title: "Delete", onclick: (e) => { e.stopPropagation(); this._deleteProject(p.id); } }, "✕"))));
    }
    return t;
  }

  _renameProject(id, current, done) {
    const inp = el("input", { type: "text", value: current, style: "width:100%" });
    modal({
      title: "Rename project",
      confirmText: "Rename",
      body: el("div", { class: "modal-body" }, el("div", { class: "row" }, el("label", {}, "Name"), inp)),
      onConfirm: async () => {
        const name = inp.value.trim();
        if (!name) throw new Error("Name is required");
        if (name !== current) await api(`/api/bom/projects/${id}`, { method: "PATCH", body: { name } });
        toast(`Renamed to “${name}”`);
        done();
      },
    });
    setTimeout(() => { inp.focus(); inp.select(); }, 50);
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
    const boardInp = el("input", { type: "file", accept: ".kicad_pcb" });
    modal({
      title: "Import BOM",
      confirmText: "Parse",
      body: el("div", { class: "modal-body" },
        el("div", { class: "row" }, el("label", {}, "KiCad BOM (.csv)"), fileInp),
        el("div", { class: "hint" }, "Export from KiCad's schematic editor: Tools → Generate BOM, or the Export BOM toolbar button."),
        el("div", { class: "row" }, el("label", {}, "Board (optional)"), boardInp),
        el("div", { class: "hint" },
          "The board file <project>.kicad_pcb from the same KiCad project. PartsNAS draws the board (parts, pads, silkscreen, outline) " +
          "next to the list, so you can see where each part sits while you choose parts, and later when you build. " +
          "A compressed copy of the file is kept with the project, so the drawing can be redrawn when PartsNAS learns to show more. The BOM works without it.")),
      onConfirm: async () => {
        const file = fileInp.files[0];
        if (!file) throw new Error("Choose a .csv file first");
        const post = async (url, f) => {
          const fd = new FormData();
          fd.append("file", f);
          const res = await fetch(url, { method: "POST", body: fd });
          const text = await res.text();
          const body = text ? JSON.parse(text) : null;
          if (!res.ok) throw new Error(body?.detail || res.statusText);
          return body;
        };
        const data = await post("/api/bom/parse", file);
        const boardFile = boardInp.files[0] || null;
        let board = null;
        if (boardFile) {
          try {
            board = await post("/api/bom/board/parse", boardFile);
          } catch (e) {
            throw new Error(`The board file could not be read: ${e.message}. Clear the board field to import the BOM without it.`);
          }
        }
        this._startReview(data, { boardFile, board });
      },
    });
  }

  _destroyBoard() {
    if (this._pcb) {
      this._pcb.destroy();
      this._pcb = null;
    }
  }

  _startReview(data, opts = {}) {
    this.mode = "review";
    this.boardFile = opts.boardFile || null;
    this._destroyBoard();
    this.el.innerHTML = "";
    this.reviewLines = data.lines.map((l) => ({
      ...l,
      part_id: l.match.part_id,
      remember: false,
      ignored: isSkippable(l.refdes),     // holes, fiducials, logos: kept in the list but not part of the build
    }));
    const nameInp = el("input", { type: "text", value: data.suggested_name, style: "max-width:320px" });
    const hasBoard = !!opts.board;
    const panel = el("div", { class: `panel bom-panel${hasBoard ? " bom-panel-sticky" : ""}`, style: hasBoard ? "max-width:none" : "max-width:1100px" });
    const body = el("div", { class: `panel-body${hasBoard ? " has-board" : ""}` });
    panel.append(
      el("h2", {}, "Review BOM"),
      body,
    );
    const trOf = new Map();
    const pickReview = (ln, fromBoard) => {
      trOf.forEach((tr) => tr.classList.remove("board-hit"));
      const tr = trOf.get(ln);
      if (tr) {
        tr.classList.add("board-hit");
        if (fromBoard) tr.scrollIntoView({ block: "center", behavior: "smooth" });
      }
      if (!fromBoard && this._pcb) this._pcb.highlight(splitRefs(ln.refdes));
    };
    if (hasBoard) {
      const host = el("div", { class: "bom-boardbar" });
      body.append(host);
      this._pcb = new PcbView(host, { onSelect: (refs) => {
        const hit = new Set(refs);
        const ln = this.reviewLines.find((l) => splitRefs(l.refdes).some((r) => hit.has(r)));
        if (ln) pickReview(ln, true);
      } });
      setTimeout(() => this._pcb && this._pcb.setBoard(opts.board), 0);   // after the layout, without waiting for a frame
    }
    body.append(
      el("div", { class: "row" }, el("label", {}, "Project name"), nameInp),
      el("div", { class: "hint" },
        "Green = exact (MPN, or a previously-confirmed match). Amber/grey = a guess from footprint + value — pick the right part or tick Remember once you're sure, and it'll apply on its own next time. " +
        "A BOM rarely says which voltage, dielectric (NP0/X7R) or fuse style it means, so press Change on any line to pick another part, or Browse to see the parts that fit."),
    );
    const table = el("table", { class: "mini-table bom-table" });
    table.append(el("tr", {}, el("th", {}, "Refdes"), el("th", {}, "Value"), el("th", {}, "Footprint"),
      el("th", { class: "num" }, "Qty"), el("th", {}, "Match"), el("th", {}, "Part"),
      el("th", { title: "Not part of the build: mounting holes, fiducials, logos, do-not-fit. Kept in the list, left out of shortages, builds and the pick list." }, "Skip"),
      el("th", {}, "Remember")));
    this.reviewLines.forEach((ln) => {
      const tr = this._reviewRow(ln);
      if (hasBoard) {
        tr.classList.add("bom-line-link");
        tr.addEventListener("click", (e) => { if (!e.target.closest("input,button,select,a,textarea")) pickReview(ln, false); });
      }
      trOf.set(ln, tr);
      table.append(tr);
    });
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

    const tr = el("tr", { class: ln.ignored ? "bom-skipped" : "" },
      el("td", {}, ln.refdes || ""),
      el("td", {}, ln.value || ""),
      el("td", { style: "max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" }, ln.footprint || ""),
      el("td", { class: "num" }, String(ln.qty)),
      badgeCell,
      el("td", { class: "bom-part" }, partCell, controls.childNodes.length ? el("div", {}, controls) : null),
      el("td", {}, el("input", { type: "checkbox", checked: ln.ignored ? "checked" : null,
        title: "Not part of the build (hole, fiducial, logo, do-not-fit)",
        onchange: (e) => { ln.ignored = e.target.checked; tr.classList.toggle("bom-skipped", ln.ignored); } })),
      el("td", {}, rememberChk));
    return tr;
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
      part_id: ln.part_id || null, remember: !!(ln.remember && ln.part_id), ignored: !!ln.ignored,
    }));
    try {
      const { id } = await api("/api/bom/projects", { method: "POST", body: { name, lines } });
      toast(`Saved “${name}”`);
      if (this.boardFile) {
        try {
          await this._uploadBoard(id, this.boardFile);
        } catch (e) {
          toast(`Saved, but the board could not be attached: ${e.message}`);
        }
        this.boardFile = null;
      }
      this.showDetail(id);
    } catch (e) {
      toast(e.message);
    }
  }

  async _upload(url, file) {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(url, { method: "POST", body: fd });
    const text = await res.text();
    const body = text ? JSON.parse(text) : null;
    if (!res.ok) throw new Error(body?.detail || res.statusText);
    return body;
  }


  _uploadBoard(id, file) { return this._upload(`/api/bom/projects/${id}/board`, file); }

  // ---------- Project detail: shortage + build ----------
  async showDetail(id, boards = 1) {
    this.mode = "detail";
    this._destroyBoard();
    const data = await api(`/api/bom/projects/${id}?boards=${boards}`);
    this.el.innerHTML = "";
    const hasPcb = !!data.has_board;      // PartsNAS's own drawing of the KiCad board
    const hasView = hasPcb;
    const panel = el("div", { class: "panel bom-panel", style: `max-width:${hasView ? "none" : "1100px"}` });
    const boardsInp = el("input", { type: "number", min: 1, value: boards, style: "width:5em",
      onchange: (e) => this.showDetail(id, Number(e.target.value) || 1) });
    const table = el("table", { class: "mini-table bom-table" });
    const rowOf = new Map();   // line id -> <tr>, for the board <-> list linking
    let pcb = null;            // our own board view
    const info = el("div", { class: "bom-info" }, "Click a line to see it on the board, or a part on the board to see the line.");
    const showLine = (ln) => {
      info.innerHTML = "";
      const where = ln.part_id ? (ln.locations.length ? ln.locations.map((l) => `${l.location}: ${l.qty}`).join(" · ") : "none in stock") : "";
      info.append(el("b", {}, ln.refdes || ""), "  ",
        ln.part_name ? `${ln.part_name}${ln.part_summary ? " — " + ln.part_summary : ""}` : (ln.unresolved_mpn || ln.value || "unresolved"),
        where ? el("div", { class: "bom-where" }, `Where: ${where} · need ${ln.needed}, have ${ln.on_hand}`) : null);
    };
    const pickLine = (ln, fromBoard) => {
      rowOf.forEach((tr) => tr.classList.remove("board-hit"));
      const tr = rowOf.get(ln.id);
      if (tr) {
        tr.classList.add("board-hit");
        if (fromBoard) tr.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
      showLine(ln);
      if (!fromBoard) {
        if (pcb) pcb.highlight(splitRefs(ln.refdes));
      }
    };
    const onBoardRefs = (refs) => {
      const hit = new Set(refs);
      const ln = data.lines.find((l) => splitRefs(l.refdes).some((r) => hit.has(r)));
      if (ln) pickLine(ln, true);
      else showLine({ refdes: refs.join(" "), part_id: null, value: "not in this BOM" });
    };
    // pick another part for a saved line: search, browse like the cart, or take the part away again
    const changeLine = (ln) => {
      let chosen = ln.part_id ? { id: ln.part_id, name: ln.part_name } : null;
      const ps = partSearch({ placeholder: "search part…", onPick: (p) => { chosen = p; } });
      if (chosen) ps.set(chosen);
      const remember = el("input", { type: "checkbox" });
      const m = modal({
        title: `Part for ${ln.refdes}`,
        confirmText: "Save",
        body: el("div", { class: "modal-body" },
          el("div", { class: "hint" }, `${[ln.value, ln.footprint].filter(Boolean).join("  ·  ")} — the BOM does not say voltage, dielectric or fuse style: choose the part this board really uses.`),
          el("div", { class: "row" }, el("label", {}, "Part"), ps.el,
            el("button", { class: "ghost", onclick: () => this._browseFor({ refdes: ln.refdes, value: ln.value, footprint: ln.footprint,
              match: { suggested_category_id: ln.suggested_category_id } }, (p) => { chosen = p; ps.set(p); }) }, "Browse…")),
          el("label", { class: "facet-opt", style: "margin:4px 0 0 6em" }, remember, " Remember for this value + footprint next time"),
          el("div", { class: "row" }, el("label", {}, ""),
            el("button", { class: "ghost", onclick: async () => {
              await api(`/api/bom/projects/${id}/lines/${ln.id}`, { method: "PATCH", body: { part_id: null } });
              m.close();
              this.showDetail(id, boards);
            } }, "No part (unresolved)"))),
        onConfirm: async () => {
          if (!chosen) throw new Error("Pick a part first");
          await api(`/api/bom/projects/${id}/lines/${ln.id}`, { method: "PATCH", body: { part_id: chosen.id, remember: remember.checked } });
          toast(`${ln.refdes}: ${chosen.name}`);
          this.showDetail(id, boards);
        },
      });
    };
    const activeLines = data.lines.filter((l) => !l.ignored);
    const placedRefs = () => activeLines.filter((l) => l.placed).flatMap((l) => splitRefs(l.refdes));
    const progress = el("span", { class: "bom-progress no-print" });
    const updateProgress = () => {
      const n = activeLines.filter((l) => l.placed).length;
      progress.textContent = `Placed ${n} / ${activeLines.length}`;
      progress.classList.toggle("done", n > 0 && n === activeLines.length);
    };
    updateProgress();
    table.append(el("tr", {}, el("th", { class: "print-only pick-col" }, "✓"),
      el("th", { class: "no-print", title: "Tick off each part as you solder it on: it turns blue on the board and the tick is kept, so a half-built board can be picked up again" }, "Placed"),
      el("th", {}, "Refdes"), el("th", {}, "Part"), el("th", {}, "Value"),
      el("th", {}, "Where it is"),
      el("th", { class: "num" }, "Per board"), el("th", { class: "num" }, `Needed (${boards})`),
      el("th", { class: "num" }, "On hand"), el("th", { class: "num" }, "Short"), el("th", { class: "no-print" }, "")));
    // a pick list: walk the shelves once instead of hunting for each line
    const firstLoc = (ln) => (ln.locations && ln.locations[0] ? ln.locations[0].location : "\uffff");
    const skipped = data.lines.filter((l) => l.ignored);
    const shown = this.showSkipped ? data.lines : data.lines.filter((l) => !l.ignored);
    const lines = this.sortByLocation
      ? [...shown].sort((a, b) => firstLoc(a).localeCompare(firstLoc(b), undefined, { numeric: true }) ||
          (a.refdes || "").localeCompare(b.refdes || "", undefined, { numeric: true }))
      : shown;
    for (const ln of lines) {
      const short = ln.short;
      const where = !ln.part_id ? "—" : ln.locations.length ? ln.locations.map((l) => `${l.location}: ${l.qty}`).join("  ·  ") : "none in stock";
      const placedBox = ln.ignored ? null : el("input", { type: "checkbox", checked: ln.placed ? "checked" : null, title: "Placed on the board",
        onclick: (e) => e.stopPropagation(),
        onchange: async (e) => {
          const want = e.target.checked;
          try {
            await api(`/api/bom/projects/${id}/lines/${ln.id}`, { method: "PATCH", body: { placed: want } });
          } catch (err) {
            e.target.checked = !want;
            return toast(err.message);
          }
          ln.placed = want;
          rowOf.get(ln.id)?.classList.toggle("bom-placed", want);
          updateProgress();
          if (pcb) pcb.setPlaced(placedRefs());
        } });
      const tr = el("tr", { class: `${hasView ? "bom-line-link" : ""}${ln.ignored ? " bom-skipped no-print" : ""}${ln.placed && !ln.ignored ? " bom-placed" : ""}`, onclick: hasView ? () => pickLine(ln, false) : null },
        el("td", { class: "print-only pick-col" }, ln.placed && !ln.ignored ? "☑" : "☐"),
        el("td", { class: "no-print" }, placedBox),
        el("td", {}, ln.refdes || ""),
        el("td", {}, ln.part_name
          ? el("div", {}, el("div", {}, ln.part_name), ln.part_summary ? el("div", { class: "hint", style: "padding:0" }, ln.part_summary) : null)
          : el("span", { class: "match-badge low" }, ln.unresolved_mpn || "unresolved")),
        el("td", {}, ln.value || ""),
        el("td", { class: ln.part_id && !ln.locations.length ? "bom-where none" : "bom-where" }, where),
        el("td", { class: "num" }, String(ln.qty_per_board)),
        el("td", { class: "num" }, String(ln.needed)),
        el("td", { class: "num" }, ln.part_id ? String(ln.on_hand) : "—"),
        el("td", { class: "num" }, short ? el("b", { style: "color:var(--danger)" }, String(short)) : (ln.part_id ? "0" : "—")),
        el("td", { class: "no-print", style: "white-space:nowrap" },
          el("button", { class: "ghost", title: "Use another part for this line", onclick: (e) => { e.stopPropagation(); changeLine(ln); } }, "Change…"),
          el("button", { class: "ghost", title: ln.ignored ? "Count this line in the build again" : "Not part of the build (hole, fiducial, logo, do-not-fit)",
            onclick: async (e) => {
              e.stopPropagation();
              await api(`/api/bom/projects/${id}/lines/${ln.id}`, { method: "PATCH", body: { ignored: !ln.ignored } });
              this.showDetail(id, boards);
            } }, ln.ignored ? "Use" : "Skip")));
      rowOf.set(ln.id, tr);
      table.append(tr);
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
    const skipChk = el("input", { type: "checkbox", checked: this.showSkipped ? "checked" : null,
      onchange: (e) => { this.showSkipped = e.target.checked; this.showDetail(id, boards); } });
    const pickFile = (accept, upload, done) => {
      const inp = el("input", { type: "file", accept });
      inp.onchange = async () => {
        if (!inp.files[0]) return;
        try {
          await upload(id, inp.files[0]);
          toast(done);
          this.showDetail(id, boards);
        } catch (e) {
          toast(e.message);
        }
      };
      inp.click();
    };
    const remove = (what, url) => async () => {
      if (!confirm(`Remove the ${what} from this project? The BOM stays.`)) return;
      await api(url, { method: "DELETE" });
      this.showDetail(id, boards);
    };

    // print: the list alone, or the board on page 1 and the list from page 2
    const printDialog = () => {
      if (!(pcb && pcb.model)) return window.print();
      const only = el("input", { type: "radio", name: "pl", checked: "checked" });
      const withBoard = el("input", { type: "radio", name: "pl" });
      const front = el("input", { type: "checkbox", checked: "checked" });
      const back = el("input", { type: "checkbox" });
      const names = el("input", { type: "checkbox", checked: "checked" });
      const opt = (input, text) => el("label", { style: "display:flex;gap:6px;align-items:center;margin:4px 0" }, input, text);
      modal({
        title: "Print pick list",
        confirmText: "Print",
        body: el("div", { class: "modal-body" },
          opt(only, "The list, from page 1"),
          opt(withBoard, "The board on page 1, the list from page 2"),
          el("div", { style: "margin:6px 0 0 24px" },
            opt(front, "Front"), opt(back, "Back"), opt(names, "Reference names on the board (C1, R2 …)")),
          el("div", { class: "hint" }, "The board is printed light, for paper, as it is turned now. Lines marked Skip are not printed.")),
        onConfirm: () => {
          if (!withBoard.checked) return void setTimeout(() => window.print(), 50);
          if (!front.checked && !back.checked) throw new Error("Choose Front and/or Back");
          const sides = [front.checked && "F", back.checked && "B"].filter(Boolean);
          const bb = pcb.model.bbox, turned = pcb.rot % 180 !== 0;
          const ratio = Math.min(1.6, Math.max(0.5, (turned ? bb[2] - bb[0] : bb[3] - bb[1]) / Math.max(1e-6, turned ? bb[3] - bb[1] : bb[2] - bb[0])));
          const imgs = sides.map((side) => el("figure", { class: "bom-print-fig" },
            el("img", { src: PcbView.renderImage(pcb.model, { side, rot: pcb.rot, refs: names.checked, width: 2000, height: Math.round(2000 * ratio) }).toDataURL("image/png") }),
            el("figcaption", {}, side === "F" ? "Front" : "Back")));
          const sheet = el("div", { class: `print-only bom-print-board${sides.length > 1 ? " two" : ""}` },
            el("h2", {}, data.name), el("div", { class: "bom-print-sub" }, `${boards} board${boards === 1 ? "" : "s"} · ${new Date().toLocaleDateString()}`), ...imgs);
          document.body.prepend(sheet);
          window.addEventListener("afterprint", () => sheet.remove(), { once: true });
          setTimeout(() => window.print(), 100);
        },
      });
    };

    // the board next to the list: the drawing of the .kicad_pcb, when one is attached
    let boardPane = null;
    if (hasPcb) {
      const host = el("div", { class: "bom-board-host" });
      boardPane = el("div", { class: "bom-board no-print" }, info, host);
      pcb = new PcbView(host, { onSelect: onBoardRefs });
      this._pcb = pcb;
      api(`/api/bom/projects/${id}/board`).then((model) => {
        if (this._pcb !== pcb) return;
        pcb.setBoard(model);
        pcb.setPlaced(placedRefs());
        if ((model.format || 1) < 2) info.textContent = "This board was saved before PartsNAS could draw text. Use Replace board… once (the same .kicad_pcb) to get the silkscreen text.";
      })
        .catch((e) => { info.textContent = `The board could not be loaded: ${e.message}`; });
    }
    const boardBtns = [];
    if (hasPcb) {
      boardBtns.push(el("button", { class: "ghost", onclick: () => pickFile(".kicad_pcb", (i, f) => this._uploadBoard(i, f), "Board updated") }, "Replace board…"),
        el("button", { class: "ghost", onclick: remove("board", `/api/bom/projects/${id}/board`) }, "Remove board"));
    } else {
      boardBtns.push(el("button", { class: "ghost", title: "The .kicad_pcb file of this project: PartsNAS draws the board next to the list",
        onclick: () => pickFile(".kicad_pcb", (i, f) => this._uploadBoard(i, f), "Board attached") }, "Attach board (.kicad_pcb)…"));
    }
    panel.append(
      el("div", { class: "no-print", style: "display:flex;align-items:center;gap:10px" },
        el("button", { class: "ghost", onclick: () => this.showList() }, "← Projects"),
        el("h2", { style: "margin:0" }, data.name),
        el("button", { class: "ghost", title: "Rename this project", onclick: () => this._renameProject(id, data.name, () => this.showDetail(id, boards)) }, "✎ Rename")),
      el("div", { class: "print-only bom-print-head" },
        el("h2", {}, data.name),
        el("div", {}, `${boards} board${boards === 1 ? "" : "s"} · pick list ${new Date().toLocaleDateString()}`)),
      el("div", { class: "panel-body" },
        el("div", { class: "row no-print" }, el("label", {}, "Boards to build"), boardsInp, buildBtn,
          el("span", { style: "flex:1" }),
          skipped.length ? el("label", { title: "Mounting holes, fiducials, logos and other lines that are not part of the build" }, skipChk, ` Show ${skipped.length} skipped`) : null,
          el("label", { title: "Order the lines by shelf, so you can collect the parts in one round" }, sortChk, " Sort by location"),
          el("button", { onclick: () => printDialog() }, "Print pick list")),
        el("div", { class: "row no-print", style: "gap:10px;align-items:center" }, progress,
          el("button", { class: "ghost", title: "Untick every Placed box (start a new board)", onclick: async () => {
            if (!activeLines.some((l) => l.placed)) return;
            if (!confirm("Clear all Placed ticks?")) return;
            await api(`/api/bom/projects/${id}/placed`, { method: "POST", body: { placed: false } });
            this.showDetail(id, boards);
          } }, "Clear placed")),
        el("div", { class: "row no-print", style: "gap:8px;align-items:center" }, ...boardBtns),
        el("div", { class: hasView ? "bom-split" : "" }, el("div", { class: "bom-lines" }, table), boardPane),
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
