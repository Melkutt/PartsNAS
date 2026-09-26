// Import (PartsBox .xlsx or a PartsNAS backup .zip) and Export (CSV / XLSX / full backup).
import { el, modal, toast } from "./ui.js";

export function openImport(onDone) {
  const fileInput = el("input", { type: "file", accept: ".xlsx,.xlsm,.xls,.csv,.zip" });
  const out = el("div", { class: "pre", hidden: "hidden" });
  let parsedOk = false;

  // format is chosen when the file isn't a .zip (which is always a backup)
  const formatSel = el("select", {},
    el("option", { value: "partsbox" }, "PartsBox export"),
    el("option", { value: "mouser" }, "Mouser order history"),
    el("option", { value: "kit" }, "Component kit list (Part Number, Case Size, Value, ...)"));
  const formatRow = el("div", { class: "row" }, el("label", {}, "Format"), formatSel);

  // backup mode is chosen when the file is a .zip
  const modeSel = el("select", {},
    el("option", { value: "merge" }, "merge — only add missing parts"),
    el("option", { value: "update" }, "update — also overwrite existing"),
    el("option", { value: "replace" }, "replace — overwrite + wipe attrs/suppliers/images"));
  const modeRow = el("div", { class: "row", hidden: "hidden" }, el("label", {}, "Backup mode"), modeSel);
  fileInput.addEventListener("change", () => {
    const name = (fileInput.files[0]?.name || "").toLowerCase();
    const zip = name.endsWith(".zip");
    modeRow.hidden = !zip;
    formatRow.hidden = zip;
    if (!zip) formatSel.value = name.endsWith(".csv") ? "kit" : name.endsWith(".xls") ? "mouser" : "partsbox";
    parsedOk = false;
    m.okBtn.disabled = true;
    out.hidden = true;
  });

  const dryBtn = el("button", { onclick: () => send(true) }, "Dry run");
  const body = el("div", { class: "modal-body" },
    el("div", {}, "A PartsBox spreadsheet export, a Mouser order-history export (My Account → Order History → Download), a vendor kit-list sheet (KEMET-style: Part Number/Case Size/Value/Tolerance/Voltage/Dielectric/Quantity), or a PartsNAS backup (.zip)."),
    el("div", { class: "row" }, el("label", {}, "File"), fileInput),
    formatRow,
    modeRow,
    el("div", { class: "row" }, dryBtn),
    out,
    el("div", { style: "margin-top:14px;padding-top:10px;border-top:1px solid var(--border)" },
      el("button", { class: "ghost", onclick: () => { m.close(); openRestoreSnapshot(); } },
        "Restore a snapshot instead…"),
      el("span", { class: "hint", style: "padding:0 0 0 6px" }, "replaces everything with an exact earlier copy")),
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

  function endpoint() {
    if (isZip()) return "/api/import/backup";
    if (formatSel.value === "mouser") return "/api/import/mouser-order";
    if (formatSel.value === "kit") return "/api/import/kit-list";
    return "/api/import/partsbox";
  }

  async function send(dry) {
    const f = fileInput.files[0];
    if (!f) return toast("Pick a file first");
    const fd = new FormData();
    fd.append("file", f);
    fd.append("dry_run", dry ? "true" : "false");
    const url = endpoint();
    if (isZip()) fd.append("mode", modeSel.value);
    const res = await fetch(url, { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) {
      out.hidden = false;
      out.textContent = "Error: " + (data.detail || res.statusText);
      return;
    }
    out.hidden = false;
    const summariser = isZip() ? summariseBackup
      : formatSel.value === "mouser" ? summariseMouser
      : formatSel.value === "kit" ? summariseKit
      : summarise;
    out.textContent = summariser(data);
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

  function summariseMouser(d) {
    const lines = [
      d.committed ? "IMPORTED" : "DRY RUN — nothing written yet", "",
      `parts created:      ${d.created} (into Unsorted)`,
      `parts updated:      ${d.updated}`,
      `stock entries:      ${d.stock_entries}`,
      `supplier links:     ${d.supplier_links}`,
      `rows with no MPN:   ${d.skipped_no_mpn}`,
      `already imported:   ${d.already_imported} (same order line seen before — skipped, not double-counted)`,
    ];
    if (d.warnings?.length) lines.push("", "warnings:", ...d.warnings.map((w) => "  - " + w));
    return lines.join("\n");
  }

  function summariseKit(d) {
    const lines = [
      d.committed ? "IMPORTED" : "DRY RUN — nothing written yet", "",
      `parts created:      ${d.created} (into Unsorted)`,
      `already in database: ${d.already_exists} (left untouched)`,
      `rows with no part #: ${d.skipped_no_mpn}`,
    ];
    if (d.warnings?.length) lines.push("", "warnings:", ...d.warnings.map((w) => "  - " + w));
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
      `API creds restored: ${(d.creds_restored || []).join(", ") || "none"}`,
    ];
    if (d.warnings?.length) lines.push("", "warnings:", ...d.warnings.map((w) => "  - " + w));
    return lines.join("\n");
  }
}

// Put a snapshot back: replaces the database and every file. The server checks
// every checksum first and saves the current state to data/backups/ before it
// touches anything; the typed word is a second guard against a stray click.
export function openRestoreSnapshot() {
  const fileInput = el("input", { type: "file", accept: ".zip" });
  const word = el("input", { type: "text", placeholder: "REPLACE" });
  const out = el("div", { class: "pre", hidden: "hidden" });
  const body = el("div", { class: "modal-body" },
    el("div", { class: "repl-banner" }, el("b", {}, "This replaces EVERYTHING "),
      "— all parts, invoices, customers, settings and images become exactly what the snapshot contained. " +
      "Whatever is here now is saved to a safety snapshot on the server first."),
    el("div", { class: "row" }, el("label", {}, "Snapshot"), fileInput),
    el("div", { class: "row" }, el("label", {}, "Type REPLACE"), word),
    out);
  modal({
    title: "Restore snapshot",
    body,
    confirmText: "Restore",
    onConfirm: async () => {
      const f = fileInput.files[0];
      if (!f) throw new Error("pick a snapshot file first");
      if (word.value.trim() !== "REPLACE") throw new Error('type "REPLACE" exactly to confirm');
      const send = (allowNewer) => {
        const fd = new FormData();
        fd.append("file", f);
        fd.append("confirm", "REPLACE");
        if (allowNewer) fd.append("allow_newer", "YES");
        return fetch("/api/import/snapshot", { method: "POST", body: fd });
      };
      let res = await send(false);
      let data = await res.json();
      // made by a NEWER PartsNAS than this one: say so and let the user decide (nothing has been touched yet)
      if (res.status === 409 && data.detail && data.detail.code === "newer_snapshot") {
        if (!confirm(`${data.detail.message}

Restore anyway?`)) throw new Error("restore cancelled - nothing was changed");
        res = await send(true);
        data = await res.json();
      }
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : (data.detail && data.detail.message) || res.statusText);
      out.hidden = false;
      out.textContent = `Restored snapshot from ${data.snapshot_created} (${data.files} files).\n` +
        `Your previous state was saved on the server as ${data.safety_snapshot}.\nReloading…`;
      setTimeout(() => location.reload(), 2500);
      return false; // keep the dialog open, showing the result, until the reload
    },
  });
}

export function openExport() {
  const onlySup = el("input", { type: "checkbox" });
  const withKeys = el("input", { type: "checkbox" });
  const body = el("div", { class: "modal-body" },
    el("div", {}, el("b", {}, "Spreadsheet"), " — flat parts list (on-hand + per-location + tags)."),
    el("div", { class: "row" },
      el("button", { class: "primary", onclick: () => go("/api/export/parts.csv") }, "Parts — CSV"),
      el("button", { class: "primary", onclick: () => go("/api/export/parts.xlsx") }, "Parts — XLSX")),
    el("div", { style: "margin-top:12px;padding:10px;border:1px solid var(--accent);border-radius:6px" },
      el("b", {}, "Snapshot (.zip) — exact copy of everything"),
      el("div", { class: "hint", style: "padding:4px 0 8px" },
        "The database and every file, verbatim, as it is right now — invoices, customers, settings, images, logo, all of it. " +
        "Restore puts the whole thing back. Contains your supplier API keys: keep the file private."),
      el("button", { class: "primary", onclick: () => go("/api/export/snapshot.zip") }, "Snapshot — ZIP")),
    el("div", { style: "margin-top:14px" }, el("b", {}, "Portable backup (.zip)"),
      " — parts, suppliers, images, stock, design notes, quotes and customers as data you can merge into another database. Not an exact copy."),
    el("label", { class: "facet-opt" }, onlySup, " only parts that have a supplier link"),
    el("label", { class: "facet-opt", title: "Mouser key, Digi-Key client id/secret — keep the file private" },
      withKeys, " include supplier API keys ⚠"),
    el("div", { class: "row" },
      el("button", { class: "primary", onclick: () => {
        const p = new URLSearchParams();
        if (onlySup.checked) p.set("only_with_supplier", "true");
        if (withKeys.checked) p.set("include_secrets", "true");
        go(`/api/export/backup.zip${p.toString() ? "?" + p : ""}`);
      } }, "Backup — ZIP")),
  );
  const m = modal({ title: "Export", body, confirmText: "Close", onConfirm: () => {} });
  function go(url) {
    window.location = url;
    m.close();
  }
}
