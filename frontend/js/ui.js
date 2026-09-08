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

export function modal({ title, body, confirmText = "OK", onConfirm, wide }) {
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
