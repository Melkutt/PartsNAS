// Minimal DOM helpers: element factory, modal, toast, flat category/location options.
import { api } from "./api.js";

export function el(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

export function modal({ title, body, confirmText = "OK", onConfirm, onClose, wide }) {
  const back = el("div", { class: "modal-back" });
  const box = el("div", { class: "modal" });
  if (wide) box.style.width = "min(760px, 94vw)";
  const actions = el("div", { class: "actions" });
  const cancel = el("button", { onclick: close }, "Cancel");
  const ok = el("button", { class: "primary", onclick: doConfirm }, confirmText);
  actions.append(cancel, ok);
  box.append(el("h3", {}, title), body, actions);
  back.append(box);
  back.addEventListener("mousedown", (e) => e.target === back && close());
  document.addEventListener("keydown", esc);
  document.body.append(back);

  function close() {
    document.removeEventListener("keydown", esc);
    back.remove();
    onClose && onClose();
  }
  function esc(e) {
    if (e.key === "Escape") close();
  }
  async function doConfirm() {
    ok.disabled = true;
    try {
      const keep = onConfirm ? await onConfirm() : undefined;
      if (keep !== false) close();
    } catch (err) {
      alert(err.message);
    } finally {
      ok.disabled = false;
    }
  }
  return { close, box, okBtn: ok };
}

// <select> that also lets the user type a brand-new option via a small
// dialog, added to the SAME dropdown from then on (not just a one-off
// value) - preserves whatever case they typed. `onChange(value)` fires
// whenever the committed value changes, including right after an add.
// The returned <select>'s own `.value` always works normally; call
// `.setOptions([...])` to (re)supply the option list once it's ready
// (e.g. after an async fetch) without losing the current selection.
export function selectWithAdd(value, options, onChange, { addLabel = "+ Add new…", addTitle = "Add a new option" } = {}) {
  const ADD = "__add_new__";
  const sel = el("select", {});
  let list = [...options];
  const fill = (v) => {
    sel.innerHTML = "";
    sel.append(el("option", { value: "" }, "—"));
    for (const o of list) if (o) sel.append(el("option", { value: o }, o));
    sel.append(el("option", { value: ADD }, addLabel));
    sel.value = v || "";
  };
  if (value && !list.includes(value)) list.push(value);
  fill(value);
  sel.setOptions = (opts) => {
    const cur = sel.value === ADD ? value : sel.value;
    list = [...opts];
    if (cur && !list.includes(cur)) list.push(cur);
    fill(cur);
  };
  sel.addEventListener("change", () => {
    if (sel.value !== ADD) {
      value = sel.value;
      onChange && onChange(value);
      return;
    }
    const prev = value;
    const nameInp = el("input", { type: "text", placeholder: "e.g. Blade" });
    modal({
      title: addTitle,
      body: el("div", { class: "modal-body" }, el("div", { class: "row" }, el("label", {}, "Name"), nameInp)),
      confirmText: "Add",
      onConfirm: () => {
        const name = nameInp.value.trim();
        if (!name) throw new Error("Enter a name");
        // reuse an existing entry's casing instead of creating a near-duplicate
        const existing = list.find((o) => o.toLowerCase() === name.toLowerCase());
        const final = existing || name;
        if (!list.includes(final)) list.push(final);
        value = final;
        fill(final);
        onChange && onChange(final);
      },
      onClose: () => { if (sel.value === ADD) fill(prev); },
    });
  });
  return sel;
}

export function spinner(text, big) {
  return el("div", { class: "busy-row" }, el("span", { class: "spin" + (big ? " lg" : "") }), text || "Working…");
}

// disable a button and show a spinner inside it while `fn` runs
export async function withBusy(btn, fn) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = "";
  btn.append(el("span", { class: "spin" }), " " + label);
  try {
    return await fn();
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

export function toast(text, { actionText, onAction, timeout = 6000 } = {}) {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const t = el("div", { class: "toast" }, el("span", {}, text));
  if (actionText) {
    t.append(
      el("button", {
        onclick: () => {
          t.remove();
          onAction && onAction();
        },
      }, actionText),
    );
  }
  t.append(el("button", { class: "ghost", onclick: () => t.remove() }, "✕"));
  document.body.append(t);
  if (timeout) setTimeout(() => t.remove(), timeout);
}

// A text input that searches parts and calls onPick({id, name, mpn}) on select.
// Returns { el, get, set }. `get()` -> the picked part or null.
export function partSearch({ placeholder = "search part…", onPick } = {}) {
  const wrap = el("div", { style: "position:relative;flex:1" });
  const input = el("input", { type: "text", placeholder, style: "width:100%" });
  const list = el("div", {
    style:
      "position:absolute;left:0;right:0;top:100%;z-index:70;background:var(--surface);" +
      "border:1px solid var(--border-strong);border-radius:6px;max-height:220px;overflow:auto;display:none",
  });
  wrap.append(input, list);
  let picked = null;
  let t;
  let seq = 0; // bumped on every keystroke: a slower, older answer must not overwrite a newer one

  input.addEventListener("input", () => {
    picked = null;
    clearTimeout(t);
    seq++;
    const q = input.value.trim();
    if (!q) return void (list.style.display = "none");
    t = setTimeout(async () => {
      const mine = seq;
      const data = await api(`/api/parts?q=${encodeURIComponent(q)}&limit=12`);
      if (mine !== seq) return;
      list.innerHTML = "";
      for (const p of data.items) {
        const row = el(
          "div",
          {
            style: "padding:6px 9px;cursor:pointer;border-bottom:1px solid var(--border)",
            onmouseenter: (e) => (e.target.style.background = "var(--surface-raised)"),
            onmouseleave: (e) => (e.target.style.background = ""),
            onclick: () => {
              picked = { id: p.id, name: p.name, mpn: p.mpn };
              input.value = p.name + (p.mpn && p.mpn !== p.name ? `  (${p.mpn})` : "");
              list.style.display = "none";
              onPick && onPick(picked);
            },
          },
          `${p.name}${p.mpn && p.mpn !== p.name ? "  ·  " + p.mpn : ""}  —  ${p.on_hand} on hand`,
        );
        list.append(row);
      }
      list.style.display = data.items.length ? "block" : "none";
    }, 200);
  });
  input.addEventListener("blur", () => setTimeout(() => (list.style.display = "none"), 150));

  return {
    el: wrap,
    get: () => picked,
    set: (p) => {
      picked = p;
      input.value = p ? p.name : "";
    },
  };
}

// flat, indented <option> list for a category or location tree
export async function treeOptions(base, { includeBlank = "—" } = {}) {
  const forest = await api(base);
  const opts = [];
  if (includeBlank) opts.push(el("option", { value: "" }, includeBlank));
  const walk = (nodes, depth) => {
    for (const n of nodes) {
      opts.push(el("option", { value: n.id }, `${"  ".repeat(depth)}${n.name}`));
      walk(n.children || [], depth + 1);
    }
  };
  walk(forest, 0);
  return opts;
}
