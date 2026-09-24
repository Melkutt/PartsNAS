// "KiCad…" on the Parts tab: connect KiCad's symbol chooser to PartsNAS (the HTTP library) and give the parts
// the symbol / footprint names KiCad needs. Only parts that have both are shown to KiCad.
import { api } from "./api.js";
import { el, modal, toast } from "./ui.js";

/** The .kicad_httplib file that points KiCad at this PartsNAS (the address the browser is using now). */
export function httplibFile(origin) {
  return JSON.stringify({
    meta: { version: 1.0 },
    name: "PartsNAS",
    description: "Parts from PartsNAS: only parts that have a KiCad symbol and footprint",
    source: { type: "REST_API", api_version: "v1", root_url: `${origin}/api/kicad/`, timeout_parts_seconds: 60, timeout_categories_seconds: 600 },
  }, null, 2) + "\n";
}

export async function openKicadNames(onDone) {
  const data = await api("/api/kicad/suggest");
  const picked = new Set(data.proposals.map((p) => p.id));
  const count = el("span", { class: "hint", style: "padding:0" });
  const boxes = [];
  const paint = () => { count.textContent = `${picked.size} of ${data.proposals.length} selected`; };

  const table = el("table", { class: "mini-table", style: "width:100%" });
  table.append(el("tr", {}, el("th", {}, ""), el("th", {}, "Part"), el("th", {}, "Category"), el("th", {}, "Package"),
    el("th", {}, "KiCad symbol"), el("th", {}, "KiCad footprint")));
  for (const p of data.proposals) {
    const box = el("input", { type: "checkbox", checked: "checked", onchange: (e) => { e.target.checked ? picked.add(p.id) : picked.delete(p.id); paint(); } });
    boxes.push(box);
    table.append(el("tr", {}, el("td", {}, box), el("td", {}, p.name), el("td", {}, p.category), el("td", {}, p.footprint_raw || ""),
      el("td", {}, p.symbol || el("span", { class: "pill-off" }, "keeps its own")),
      el("td", {}, p.footprint || el("span", { class: "pill-off" }, "keeps its own"))));
  }
  const all = el("input", { type: "checkbox", checked: "checked", onchange: (e) => {
    boxes.forEach((b) => { b.checked = e.target.checked; });
    picked.clear();
    if (e.target.checked) data.proposals.forEach((p) => picked.add(p.id));
    paint();
  } });
  paint();

  const download = el("button", { class: "ghost", onclick: () => {
    const url = URL.createObjectURL(new Blob([httplibFile(location.origin)], { type: "application/json" }));
    const a = el("a", { href: url, download: "partsnas.kicad_httplib" });
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } }, "Download partsnas.kicad_httplib");

  const body = el("div", { class: "modal-body" },
    el("div", { class: "section-title" }, "Connect KiCad (8 or newer)"),
    el("div", { class: "hint" },
      "KiCad can list your parts in its symbol chooser and fill in value, footprint, MPN, manufacturer and datasheet when you place one. " +
      "Download the file, save it on the computer you draw on, and add it in KiCad under Preferences → Manage Symbol Libraries. " +
      `It points at ${location.origin}/api/kicad/ - the NAS must be reachable from that computer, over plain http.`),
    el("div", { class: "row" }, download),
    el("div", { class: "section-title" }, "Which parts KiCad sees"),
    el("div", { class: "hint" },
      `${data.ready} part${data.ready === 1 ? " is" : "s are"} ready: they have both a KiCad symbol and a footprint ` +
      "(each written with its library, like Device:C and Capacitor_SMD:C_0603_1608Metric). Set them by hand on a part's details, " +
      "or let PartsNAS name the standard SMD resistors, ceramic capacitors, inductors and LEDs below. " +
      `${data.other} other part${data.other === 1 ? "" : "s"} (ICs, connectors, …) still need naming by hand. A name you have typed yourself is never replaced.`),
    data.proposals.length
      ? el("div", {}, el("div", { class: "row", style: "align-items:center;gap:12px" }, el("label", { style: "display:flex;gap:6px;align-items:center" }, all, " All"), count),
        el("div", { style: "max-height:42vh;overflow:auto;margin-top:6px" }, table))
      : el("div", { class: "pill-off", style: "margin-top:8px" }, "Nothing more to name automatically."));

  modal({
    title: "KiCad",
    wide: "min(1000px, 96vw)",
    confirmText: data.proposals.length ? "Name the selected parts" : "Close",
    body,
    onConfirm: async () => {
      if (!data.proposals.length || !picked.size) return;
      const r = await api("/api/kicad/apply", { method: "POST", body: { ids: [...picked] } });
      toast(`Named ${r.updated} part${r.updated === 1 ? "" : "s"} for KiCad`);
      onDone && onDone();
    },
  });
}
