// Standalone barcode/QR label print page — opened as /label.html?ids=a,b,c
// from a part detail's "Open in multi-part sheet…" or the Parts bulk bar's
// "Print labels…". Not part of the SPA router: kept independent so a fresh
// browser tab always gets a clean, printable sheet regardless of what else
// is open.
//
// Both of those entry points route through labelcommon.js's
// addToLabelSheet(), which reuses this one tab (via a named window) and
// posts new ids into it instead of opening a new tab each time — so you can
// browse to several different components and build up one sheet.
import { api } from "./api.js";
import { el, toast } from "./ui.js";
import { applyTheme, currentTheme } from "./theme.js";
import { setPageSize, clearPageSize, labelUrl } from "./labelcommon.js";

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
let ids = (qs.get("ids") || "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

const state = {
  fmt: localStorage.getItem(KEY + "fmt") || "qr",
  lw: Number(localStorage.getItem(KEY + "lw")) || 40,
  cols: Number(localStorage.getItem(KEY + "cols")) || 4,
  copies: Number(localStorage.getItem(KEY + "copies")) || 1,
  cut: localStorage.getItem(KEY + "cut") !== "0",
  printer: localStorage.getItem(KEY + "printer") === "1",
  lh: Number(localStorage.getItem(KEY + "lh")) || 25,
  codeH: Number(localStorage.getItem(KEY + "codeH")) || 10,
};

const fmtSel = el(
  "select",
  { onchange: (e) => { state.fmt = e.target.value; save("fmt", state.fmt); syncModeVisibility(); render(); } },
  el("option", { value: "qr" }, "QR"),
  el("option", { value: "code128" }, "Barcode (Code128)"),
);
fmtSel.value = state.fmt;

const lwInp = el("input", {
  type: "number", min: 5, max: 300, value: state.lw,
  onchange: (e) => { state.lw = Number(e.target.value) || 40; save("lw", state.lw); render(); },
});
const codeHInp = el("input", {
  type: "number", min: 2, max: 100, value: state.codeH,
  onchange: (e) => { state.codeH = Number(e.target.value) || 10; save("codeH", state.codeH); render(); },
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
const printerChk = el("input", {
  type: "checkbox", checked: state.printer ? "checked" : null,
  onchange: (e) => { state.printer = e.target.checked; save("printer", state.printer ? "1" : "0"); syncModeVisibility(); render(); },
});
const lhInp = el("input", {
  type: "number", min: 5, max: 300, value: state.lh,
  onchange: (e) => { state.lh = Number(e.target.value) || 25; save("lh", state.lh); render(); },
});
const countTag = el("span", { id: "count" }, "");

const codeHLabel = el("label", {}, "Barcode height (mm)", codeHInp);
const sheetOnlyLabels = [
  el("label", {}, "Columns", colsInp),
  el("label", {}, cutChk, "Cut lines"),
];
const printerOnlyLabels = [
  el("label", {}, "Page height (mm)", lhInp),
];
function syncModeVisibility() {
  codeHLabel.hidden = state.fmt !== "code128";
  for (const l of sheetOnlyLabels) l.hidden = state.printer;
  for (const l of printerOnlyLabels) l.hidden = !state.printer;
}

document.body.append(
  el(
    "div",
    { class: "toolbar no-print" },
    el("label", {}, "Format", fmtSel),
    el("label", {}, "Width (mm)", lwInp),
    codeHLabel,
    ...sheetOnlyLabels,
    ...printerOnlyLabels,
    el("label", {}, "Copies each", copiesInp),
    el("label", { title: "One label per printed page, exact size — for a DYMO or similar label printer instead of a laid-out sheet" },
      printerChk, "Label printer"),
    countTag,
    el("button", { class: "ghost", onclick: clearAll }, "Clear"),
    el("button", { class: "primary", onclick: doPrint }, "🖨 Print"),
  ),
);
syncModeVisibility();

document.body.append(
  el("div", { class: "hint no-print", style: "padding:8px 16px 0" },
    "Each code encodes the part's MPN, or its internal id for parts with no MPN — either way scanning it (e.g. into the “New part” MPN field) resolves straight back to this part. " +
    "Opening this from another part adds to this same sheet instead of a new tab, until you close it or hit Clear."),
);

const sheet = el("div", { class: "sheet" });
document.body.append(el("div", { class: "sheet-wrap" }, sheet));

function doPrint() {
  if (state.printer) setPageSize(state.lw, state.lh);
  else clearPageSize();
  window.print();
}

function clearAll() {
  ids = [];
  history.replaceState(null, "", "/label.html");
  render();
}

// Another tab (a part's "Open in multi-part sheet…", or the Parts bulk
// bar's "Print labels…") adds to this sheet instead of opening a new one.
window.addEventListener("message", (e) => {
  if (e.origin !== location.origin || e.data?.type !== "partsnas:add-labels") return;
  const added = (e.data.ids || []).filter((id) => id && !ids.includes(id));
  if (!added.length) return;
  ids.push(...added);
  history.replaceState(null, "", `/label.html?ids=${ids.map(encodeURIComponent).join(",")}`);
  toast(`Added ${added.length} part(s) to this sheet`);
  render();
});

async function render() {
  sheet.style.setProperty("--w", `${state.lw}mm`);
  sheet.style.setProperty("--cols", state.cols);
  sheet.style.setProperty("--lh", `${state.lh}mm`);
  sheet.style.setProperty("--codeh", `${state.codeH}mm`);
  sheet.classList.toggle("printer-mode", state.printer);
  sheet.innerHTML = "";

  if (!ids.length) {
    sheet.append(el("div", { class: "empty" },
      "No parts on this sheet yet — open this page from a part's Open in multi-part sheet… button, or the Parts bulk bar's Print labels… action."));
    countTag.textContent = "";
    return;
  }

  const parts = await Promise.all(ids.map((id) => api(`/api/parts/${id}`).catch(() => null)));
  let n = 0;
  for (const p of parts) {
    if (!p) continue;
    for (let i = 0; i < state.copies; i++) {
      n++;
      const cls = state.printer ? "label-card printer-mode" : `label-card${state.cut ? "" : " no-cut"}`;
      sheet.append(
        el(
          "div",
          { class: cls },
          el("img", { class: `label-img ${state.fmt === "qr" ? "is-qr" : "is-barcode"}`, src: labelUrl(p.id, state.fmt, state.codeH) }),
          el("div", { class: "label-name" }, p.name),
          p.mpn && p.mpn !== p.name ? el("div", { class: "label-mpn" }, p.mpn) : null,
        ),
      );
    }
  }
  countTag.textContent = `${n} label(s)`;
}

render();
