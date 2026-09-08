// Reusable tree view for the category and storage-location trees.
// Same widget, different endpoint. Inline add-child / rename / delete.
import { api } from "./api.js";

const COLLAPSE_KEY = (base) => `partsnas.collapsed.${base}`;

export class Tree {
  constructor(base, { noun = "item", rootAddLabel } = {}) {
    this.base = base; // "/api/categories" | "/api/locations"
    this.noun = noun;
    this.rootAddLabel = rootAddLabel || `New ${noun}`;
    this.el = document.createElement("div");
    this.collapsed = new Set(load(COLLAPSE_KEY(base)));
  }

  async mount(container) {
    container.appendChild(this.el);
    await this.reload();
  }

  async reload() {
    this.forest = await api(this.base);
    this.render();
  }

  render() {
    this.el.innerHTML = "";
    const bar = document.createElement("div");
    bar.className = "hint";
    bar.innerHTML = `Hover a row for actions. `;
    const addRoot = document.createElement("button");
    addRoot.className = "ghost";
    addRoot.textContent = `+ ${this.rootAddLabel}`;
    addRoot.addEventListener("click", () => this.create(null));
    bar.appendChild(addRoot);
    this.el.appendChild(bar);

    const ul = document.createElement("ul");
    ul.className = "tree";
    for (const n of this.forest) ul.appendChild(this.renderNode(n));
    this.el.appendChild(ul);
  }

  renderNode(node) {
    const li = document.createElement("li");
    const hasKids = node.children && node.children.length > 0;
    const isCollapsed = this.collapsed.has(node.id);
    if (isCollapsed) li.classList.add("collapsed");

    const row = document.createElement("div");
    row.className = "node";

    const tw = document.createElement("span");
    tw.className = "twisty";
    tw.textContent = hasKids ? (isCollapsed ? "▸" : "▾") : "";
    if (hasKids)
      tw.addEventListener("click", () => {
        this.collapsed.has(node.id) ? this.collapsed.delete(node.id) : this.collapsed.add(node.id);
        save(COLLAPSE_KEY(this.base), [...this.collapsed]);
        this.render();
      });
    row.appendChild(tw);

    const label = document.createElement("span");
    label.className = "label";
    label.textContent = node.name;
    label.addEventListener("dblclick", () => this.startRename(node, label));
    row.appendChild(label);

    if (node.is_unsorted) {
      const b = document.createElement("span");
      b.className = "badge";
      b.textContent = "default";
      row.appendChild(b);
    }
    if (typeof node.part_count === "number" && node.part_count > 0) {
      const c = document.createElement("span");
      c.className = "count";
      c.textContent = node.part_count;
      row.appendChild(c);
    }

    const actions = document.createElement("span");
    actions.className = "actions";
    actions.appendChild(btn("+ sub", () => this.create(node.id)));
    actions.appendChild(btn("rename", () => this.startRename(node, label)));
    if (!node.is_unsorted) actions.appendChild(btn("delete", () => this.remove(node), "danger"));
    row.appendChild(actions);

    li.appendChild(row);

    if (hasKids) {
      const ul = document.createElement("ul");
      for (const c of node.children) ul.appendChild(this.renderNode(c));
      li.appendChild(ul);
    }
    return li;
  }

  startRename(node, labelEl) {
    const input = document.createElement("input");
    input.type = "text";
    input.value = node.name;
    labelEl.textContent = "";
    labelEl.appendChild(input);
    input.focus();
    input.select();
    const commit = async () => {
      const name = input.value.trim();
      if (name && name !== node.name) {
        try {
          await api(`${this.base}/${node.id}`, { method: "PATCH", body: { name } });
        } catch (e) {
          alert(e.message);
        }
      }
      this.reload();
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") commit();
      if (e.key === "Escape") this.render();
    });
    input.addEventListener("blur", commit);
  }

  async create(parentId) {
    const name = prompt(`Name of new ${this.noun}:`);
    if (!name || !name.trim()) return;
    try {
      await api(this.base, { method: "POST", body: { name: name.trim(), parent_id: parentId } });
      if (parentId != null) this.collapsed.delete(parentId);
      await this.reload();
    } catch (e) {
      alert(e.message);
    }
  }

  async remove(node) {
    const kids = node.children && node.children.length;
    const extra = kids ? `\n${kids} sub-${this.noun}(s) and any parts move up one level.` : "";
    if (!confirm(`Delete "${node.name}"?${extra}`)) return;
    try {
      await api(`${this.base}/${node.id}`, { method: "DELETE" });
      await this.reload();
    } catch (e) {
      alert(e.message);
    }
  }
}

function btn(text, onClick, cls) {
  const b = document.createElement("button");
  b.textContent = text;
  if (cls) b.className = cls;
  b.addEventListener("click", onClick);
  return b;
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
