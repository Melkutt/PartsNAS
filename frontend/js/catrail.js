// Left-hand rail on the Parts view: a collapsible, single-select tree of
// categories OR storage locations. Selecting a node filters the results.
import { api } from "./api.js";
import { el } from "./ui.js";

const CKEY = (base) => `partsnas.railcollapsed.${base}`;

export class CatRail {
  constructor({ onSelect }) {
    this.onSelect = onSelect;
    this.mode = "categories"; // categories | locations
    this.selected = { categories: null, locations: null };
    this.collapsed = new Set(load(CKEY(this.mode)));
    this.el = el("div", { class: "rail" });
  }

  async mount(container) {
    container.append(this.el);
    await this.render();
  }

  base() {
    return this.mode === "categories" ? "/api/categories" : "/api/locations";
  }

  async render() {
    this.el.innerHTML = "";
    const seg = el("div", { class: "seg" });
    for (const m of ["categories", "locations"]) {
      seg.append(
        el("button", {
          class: this.mode === m ? "active" : "",
          onclick: () => {
            this.mode = m;
            this.collapsed = new Set(load(CKEY(m)));
            this.render();
          },
        }, m[0].toUpperCase() + m.slice(1)),
      );
    }
    this.el.append(seg);

    const scroll = el("div", { class: "rail-scroll" });
    this.forest = await api(this.base());
    const cur = this.selected[this.mode];
    scroll.append(
      this._row({ id: null, name: this.mode === "categories" ? "All categories" : "All locations", children: [] }, 0, cur),
    );
    const ul = el("ul");
    for (const n of this.forest) ul.append(this._li(n, cur));
    scroll.append(ul);
    this.el.append(scroll);
  }

  _li(node, cur) {
    const li = el("li");
    if (this.collapsed.has(node.id)) li.classList.add("collapsed");
    li.append(this._row(node, 0, cur));
    if (node.children?.length) {
      const ul = el("ul");
      for (const c of node.children) ul.append(this._li(c, cur));
      li.append(ul);
    }
    return li;
  }

  _row(node, _depth, cur) {
    const hasKids = node.children?.length;
    const tw = el("span", { class: "tw" }, hasKids ? (this.collapsed.has(node.id) ? "▸" : "▾") : "");
    if (hasKids)
      tw.addEventListener("click", (e) => {
        e.stopPropagation();
        this.collapsed.has(node.id) ? this.collapsed.delete(node.id) : this.collapsed.add(node.id);
        save(CKEY(this.mode), [...this.collapsed]);
        this.render();
      });
    const row = el(
      "div",
      {
        class: "rnode" + (cur === node.id || (cur == null && node.id == null) ? " sel" : ""),
        onclick: () => {
          this.selected[this.mode] = node.id;
          this.onSelect({ mode: this.mode, id: node.id, name: node.name });
          this.render();
        },
      },
      tw,
      el("span", { class: "nm" }, node.name),
      typeof node.part_count === "number" && node.part_count ? el("span", { class: "c" }, node.part_count) : null,
    );
    return row;
  }

  // called by PartsView when a tree node click elsewhere set the filter
  setSelected(mode, id) {
    if (mode) this.mode = mode;
    this.selected[this.mode] = id ?? null;
    this.render();
  }
}

function load(k) {
  try {
    return JSON.parse(localStorage.getItem(k)) || [];
  } catch {
    return [];
  }
}
function save(k, v) {
  try {
    localStorage.setItem(k, JSON.stringify(v));
  } catch {
    /* ignore */
  }
}
