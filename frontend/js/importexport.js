// Import (PartsBox .xlsx or a PartsNAS backup .zip) and Export (CSV / XLSX / full backup).
import { el, modal, toast } from "./ui.js";

export function openImport(onDone) {
  const fileInput = el("input", { type: "file", accept: ".xlsx,.xlsm,.zip" });
  const out = el("div", { class: "pre", hidden: "hidden" });
  let parsedOk = false;

  // backup mode is chosen when the file is a .zip
  const modeSel = el("select", {},
    el("option", { value: "merge" }, "merge — only add missing parts"),
    el("option", { value: "update" }, "update — also overwrite existing"),
    el("option", { value: "replace" }, "replace — overwrite + wipe attrs/suppliers/images"));
  const modeRow = el("div", { class: "row", hidden: "hidden" }, el("label", {}, "Backup mode"), modeSel);
  fileInput.addEventListener("change", () => {
    const isZip = (fileInput.files[0]?.name || "").toLowerCase().endsWith(".zip");
    modeRow.hidden = !isZip;
    parsedOk = false;
    m.okBtn.disabled = true;
    out.hidden = true;
  });

  const dryBtn = el("button", { onclick: () => send(true) }, "Dry run");
  const body = el("div", { class: "modal-body" },
    el("div", {}, "PartsBox spreadsheet export (.xlsx) or a PartsNAS backup (.zip)."),
    el("div", { class: "row" }, el("label", {}, "File"), fileInput),
    modeRow,
    el("div", { class: "row" }, dryBtn),
    out,
  );

  const m = modal({
    title: "Import",
    body,
    confirmText: "Import for real",
    onConfirm: async () => {
      if (!parsedOk) { await send(true); return false; }
      await send(false);
      onDone && onDone();
    },
  });
  m.okBtn.disabled = true;

  function isZip() {
    return (fileInput.files[0]?.name || "").toLowerCase().endsWith(".zip");
  }

  async function send(dry) {
    const f = fileInput.files[0];
    if (!f) return toast("Pick a file first");
    const fd = new FormData();
    fd.append("file", f);
    fd.append("dry_run", dry ? "true" : "false");
    const url = isZip() ? "/api/import/backup" : "/api/import/partsbox";
    if (isZip()) fd.append("mode", modeSel.value);
    const res = await fetch(url, { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) {
      out.hidden = false;
      out.textContent = "Error: " + (data.detail || res.statusText);
      return;
    }
    out.hidden = false;
    out.textContent = (isZip() ? summariseBackup : summarise)(data);
    parsedOk = true;
    m.okBtn.disabled = false;
    if (!dry) toast("Import done");
  }

  function summarise(d) {
    const lines = [
      d.committed ? "IMPORTED" : "DRY RUN — nothing written yet", "",
      `parts created:     ${d.created}`,
      `parts updated:     ${d.updated}`,
      `meta rows skipped: ${d.skipped_meta}`,
      `stock entries:     ${d.stock_entries}`,
      `locations created: ${d.locations_created}`,
    ];
    if (d.warnings?.length) lines.push("", "warnings:", ...d.warnings.map((w) => "  - " + w));
    if (d.review?.length) {
      lines.push("", `needs manual stock split (${d.review.length}):`);
      for (const r of d.review) lines.push(`  - ${r.part} (${r.qty} @ ${r.location || "?"}) — ${r.note}`);
    }
    return lines.join("\n");
  }

  function summariseBackup(d) {
    const lines = [
      d.dry_run ? `DRY RUN — nothing written (mode: ${d.mode})` : `IMPORTED (mode: ${d.mode})`, "",
      `parts created:      ${d.created}`,
      `parts updated:      ${d.updated}`,
      `parts skipped:      ${d.skipped}`,
      `categories created: ${d.categories_created}`,
      `locations created:  ${d.locations_created}`,
      `supplier links:     ${d.supplier_links}`,
      `images:             ${d.images}`,
      `design notes:       ${d.design_notes}`,
    ];
    if (d.warnings?.length) lines.push("", "warnings:", ...d.warnings.map((w) => "  - " + w));
    return lines.join("\n");
  }
}

export function openExport() {
  const onlySup = el("input", { type: "checkbox" });
  const body = el("div", { class: "modal-body" },
    el("div", {}, el("b", {}, "Spreadsheet"), " — flat parts list (on-hand + per-location + tags)."),
    el("div", { class: "row" },
      el("button", { class: "primary", onclick: () => go("/api/export/parts.csv") }, "Parts — CSV"),
      el("button", { class: "primary", onclick: () => go("/api/export/parts.xlsx") }, "Parts — XLSX")),
    el("div", { style: "margin-top:12px" }, el("b", {}, "Full backup (.zip)"),
      " — everything: attributes, tags, suppliers, images, stock, design notes. Re-importable."),
    el("label", { class: "facet-opt" }, onlySup, " only parts that have a supplier link"),
    el("div", { class: "row" },
      el("button", { class: "primary", onclick: () => go(`/api/export/backup.zip${onlySup.checked ? "?only_with_supplier=true" : ""}`) }, "Backup — ZIP")),
  );
  const m = modal({ title: "Export", body, confirmText: "Close", onConfirm: () => {} });
  function go(url) {
    window.location = url;
    m.close();
  }
}
