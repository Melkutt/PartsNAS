// Shared bits between the single-part Label tab (partdetail.js) and the
// multi-part print sheet (label.html / labelprint.js).

// ---- one shared /label.html tab, built up incrementally ------------------
// "Open in multi-part sheet…" / bulk "Print labels…" should not each pop a
// fresh tab — the first click opens one, everything after adds into it.
let sheetWin = null;

export function addToLabelSheet(ids) {
  ids = Array.isArray(ids) ? ids : [ids];
  if (sheetWin && !sheetWin.closed) {
    sheetWin.postMessage({ type: "partsnas:add-labels", ids }, location.origin);
    try {
      sheetWin.focus();
    } catch {
      /* some browsers refuse to focus a background tab; harmless */
    }
  } else {
    const q = ids.map(encodeURIComponent).join(",");
    sheetWin = window.open(`/label.html?ids=${q}`, "partsnas-label-sheet");
  }
}

// ---- exact physical page size, for label-roll printers (DYMO etc.) -------
// A sheet printer just uses the page size already chosen in the print
// dialog, but a label printer needs the CSS page size to match the roll
// exactly or the driver mis-scales/crops. `@page` can't read a CSS custom
// property for `size`, so we inject a plain <style> with the literal value.
const STYLE_ID = "partsnas-page-size";

export function setPageSize(widthMm, heightMm) {
  let style = document.getElementById(STYLE_ID);
  if (!style) {
    style = document.createElement("style");
    style.id = STYLE_ID;
    document.head.append(style);
  }
  style.textContent = `@page { size: ${widthMm}mm ${heightMm}mm; margin: 0; }`;
}

export function clearPageSize() {
  const style = document.getElementById(STYLE_ID);
  if (style) style.textContent = "";
}

// ---- one URL builder so the preview and every print path ask the server
// for the same PNG, drawn natively at roughly the right proportions rather
// than stretched after the fact (see backend/app/labels.py).
export function labelUrl(id, fmt, codeHmm) {
  const u = `/api/parts/${id}/label.png?fmt=${fmt}`;
  return fmt === "code128" ? `${u}&h=${codeHmm}` : u;
}
