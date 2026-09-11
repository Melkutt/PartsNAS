// Standalone barcode/QR label print page — opened as /label.html?ids=a,b,c
// from a part detail's "Label" button or the Parts bulk bar. Not part of the
// SPA router: kept independent so a fresh browser tab always gets a clean,
// printable sheet regardless of what else is open.
import { api } from "./api.js";
import { el } from "./ui.js";
import { applyTheme, currentTheme } from "./theme.js";

applyTheme(currentTheme());

const KEY = "partsnas.label.";
const save = (k, v) => {
  try {
    localStorage.setItem(KEY + k, v);
  } catch {
    /* private mode */
  }
};

const qs = new URLSearchParams(location.search);
const ids = (qs.get("ids") || "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

const state = {
  fmt: localStorage.getItem(KEY + "fmt") || "qr",
  width: Number(localStorage.getItem(KEY + "width")) || 40,
  cols: Number(localStorage.getItem(KEY + "cols")) || 4,
  copies: Number(localStorage.getItem(KEY + "copies")) || 1,
  cut: localStorage.getItem(KEY + "cut") !== "0",
};

const fmtSel = el(
  "select",
  { onchange: (e) => { state.fmt = e.target.value; save("fmt", state.fmt); render(); } },
  el("option", { value: "qr" }, "QR"),
  el("option", { value: "code128" }, "Barcode (Code128)"),
);
fmtSel.value = state.fmt;

const widthInp = el("input", {
  type: "number", min: 15, max: 100, value: state.width,
  onchange: (e) => { state.width = Number(e.target.value) || 40; save("width", state.width); render(); },
});
const colsInp = el("input", {
  type: "number", min: 1, max: 10, value: state.cols,
  onchange: (e) => { state.cols = Number(e.target.value) || 4; save("cols", state.cols); render(); },
});
const copiesInp = el("input", {
  type: "number", min: 1, max: 50, value: state.copies,
  onchange: (e) => { state.copies = Number(e.target.value) || 1; save("copies", state.copies); render(); },
});
const cutChk = el("input", {
  type: "checkbox", checked: state.cut ? "checked" : null,
  onchange: (e) => { state.cut = e.target.checked; save("cut", state.cut ? "1" : "0"); render(); },
});
const countTag = el("span", { id: "count" }, "");

document.body.append(
  el(
    "div",
    { class: "toolbar no-print" },
    el("label", {}, "Format", fmtSel),
    el("label", {}, "Label width (mm)", widthInp),
    el("label", {}, "Columns", colsInp),
    el("label", {}, "Copies each", copiesInp),
    el("label", {}, cutChk, "Cut lines"),
    countTag,
    el("button", { class: "primary", onclick: () => window.print() }, "🖨 Print"),
  ),
);

const sheet = el("div", { class: "sheet" });
document.body.append(el("div", { class: "sheet-wrap" }, sheet));

async function render() {
  sheet.style.setProperty("--w", `${state.width}mm`);
  sheet.style.setProperty("--cols", state.cols);
  sheet.innerHTML = "";

  if (!ids.length) {
    sheet.append(el("div", { class: "empty" },
      "No parts selected — open this page from a part's Label button, or the Parts bulk bar's Print labels… action."));
    countTag.textContent = "";
    return;
  }

  const parts = await Promise.all(ids.map((id) => api(`/api/parts/${id}`).catch(() => null)));
  let n = 0;
  for (const p of parts) {
    if (!p) continue;
    for (let i = 0; i < state.copies; i++) {
      n++;
      sheet.append(
        el(
          "div",
          { class: `label-card${state.cut ? "" : " no-cut"}` },
          el("img", { class: "label-img", src: `/api/parts/${p.id}/label.png?fmt=${state.fmt}` }),
          el("div", { class: "label-name" }, p.name),
          p.mpn && p.mpn !== p.name ? el("div", { class: "label-mpn" }, p.mpn) : null,
        ),
      );
    }
  }
  countTag.textContent = `${n} label(s)`;
}

render();
