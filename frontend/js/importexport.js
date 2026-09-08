// Import (PartsBox .xlsx, dry-run then commit) and Export (CSV / XLSX) actions.
import { el, modal, toast } from "./ui.js";

export function openImport(onDone) {
  const fileInput = el("input", { type: "file", accept: ".xlsx,.xlsm" });
  const out = el("div", { class: "pre", hidden: "hidden" });
  let parsedOk = false;

  const dryBtn = el("button", { onclick: () => send(true) }, "Dry run");
  const body = el(
    "div",
    { class: "modal-body" },
    el("div", {}, "Import a PartsBox spreadsheet export (Komponenter + Förvaringplatser sheets)."),
    el("div", { class: "row" }, el("label", {}, "File"), fileInput),
    el("div", { class: "row" }, dryBtn),
    out,
  );

  const m = modal({
    title: "Import from PartsBox",
    body,
    confirmText: "Import for real",
    onConfirm: async () => {
      if (!parsedOk) {
        await send(true);
        return false; // keep open; make them see the dry run first
      }
      await send(false);
      onDone && onDone();
    },
  });
  m.okBtn.disabled = true;

  async function send(dry) {
    const f = fileInput.files[0];
    if (!f) {
      toast("Pick a file first");
      return;
    }
    const fd = new FormData();
    fd.append("file", f);
    fd.append("dry_run", dry ? "true" : "false");
    const res = await fetch("/api/import/partsbox", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) {
      out.hidden = false;
      out.textContent = "Error: " + (data.detail || res.statusText);
      return;
    }
    out.hidden = false;
    out.textContent = summarise(data);
    parsedOk = true;
    m.okBtn.disabled = false;
    if (!dry) {
      toast(`Imported: ${data.created} new, ${data.updated} updated, ${data.stock_entries} stock rows`);
    }
  }

  function summarise(d) {
    const lines = [
      `${d.committed ? "IMPORTED" : "DRY RUN — nothing written yet"}`,
      ``,
      `parts created:     ${d.created}`,
      `parts updated:     ${d.updated}`,
      `meta rows skipped: ${d.skipped_meta}`,
      `stock entries:     ${d.stock_entries}`,
      `locations created: ${d.locations_created}`,
    ];
    if (d.warnings?.length) lines.push(``, `warnings:`, ...d.warnings.map((w) => "  - " + w));
    if (d.review?.length) {
      lines.push(``, `needs manual stock split (${d.review.length}):`);
      for (const r of d.review) lines.push(`  - ${r.part} (${r.qty} @ ${r.location || "?"}) — ${r.note}`);
    }
    return lines.join("\n");
  }
}

export function openExport() {
  const body = el(
    "div",
    { class: "modal-body" },
    el("div", {}, "Download the full parts list with on-hand quantities and per-location breakdown."),
    el(
      "div",
      { class: "row" },
      el("button", { class: "primary", onclick: () => go("/api/export/parts.csv") }, "Parts — CSV"),
      el("button", { class: "primary", onclick: () => go("/api/export/parts.xlsx") }, "Parts — XLSX"),
    ),
  );
  const m = modal({ title: "Export", body, confirmText: "Close", onConfirm: () => {} });
  function go(url) {
    window.location = url;
    m.close();
  }
}
