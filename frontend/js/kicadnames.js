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

const short = (fp) => String(fp || "").split(":").pop();

/** `scope` = {id, name} of the category picked in the Parts list: only parts in it (and below it) are considered. */
export async function openKicadNames(onDone, scope = null) {
  const cat = scope && scope.id ? `&category_id=${scope.id}` : "";
  let prefer = (await api("/api/kicad/prefs")).prefer;     // remembered on the server: new parts use it too
  let data = await api(`/api/kicad/suggest?prefer=${prefer}${cat}`);
  const picked = new Set();
  const count = el("span", { class: "hint", style: "padding:0" });
  const listHost = el("div");
  const summary = el("div", { class: "hint" });
  let boxes = [];

  const paint = () => { count.textContent = `${picked.size} of ${data.proposals.length} selected`; };
  const render = () => {
    picked.clear();
    data.proposals.filter((p) => !p.assumed).forEach((p) => picked.add(p.id));     // a guess is never ticked for you
    boxes = [];
    summary.textContent =
      (data.scope ? `Only parts in ${data.scope} (and below it) are considered. ` : "Every part is considered - pick a category in the list on the left first to narrow it down. ") +
      `${data.ready} part${data.ready === 1 ? " is" : "s are"} ready: they have both a KiCad symbol and a footprint ` +
      "(each written with its library, like Device:C and Capacitor_SMD:C_0603_1608Metric). Set them by hand on a part's details, " +
      "or let PartsNAS name them below: standard SMD resistors, ceramic capacitors, inductors and LEDs from category and size, and ICs, transistors and diodes from the footprint rules (Settings). " +
      `${data.other} other part${data.other === 1 ? "" : "s"} (ICs, connectors, …) still need naming by hand. A name you have typed yourself is never replaced.`;
    listHost.innerHTML = "";
    if (!data.proposals.length) {
      listHost.append(el("div", { class: "pill-off", style: "margin-top:8px" }, "Nothing more to name automatically."));
      return;
    }
    const table = el("table", { class: "mini-table", style: "width:100%" });
    table.append(el("tr", {}, el("th", {}, ""), el("th", {}, "Part"), el("th", {}, "Package"), el("th", {}, "Rule"),
      el("th", {}, "KiCad symbol"), el("th", {}, "Default footprint"), el("th", {}, "Also offered")));
    for (const p of data.proposals) {
      const box = el("input", { type: "checkbox", checked: p.assumed ? null : "checked", onchange: (e) => { e.target.checked ? picked.add(p.id) : picked.delete(p.id); paint(); } });
      boxes.push(box);
      const keeps = el("span", { class: "pill-off" }, "keeps its own");
      table.append(el("tr", {}, el("td", {}, box), el("td", {}, p.name, el("div", { class: "hint", style: "padding:0" }, p.category)),
        el("td", {}, p.package || p.footprint_raw || ""),
        el("td", {}, p.rule ? el("span", { class: "hint", style: "padding:0",
          title: p.assumed ? "Only a guess of the common variant: check it before you tick it" : "A certain rule" }, (p.assumed ? "⚠ " : "") + p.rule) : ""),
        el("td", {}, p.symbol || keeps.cloneNode(true)),
        el("td", {}, p.footprint ? short(p.footprint) : keeps),
        el("td", {}, p.alts.length ? p.alts.map((a) => el("div", {}, short(a))) : el("span", { class: "pill-off" }, "—"))));
    }
    const all = el("input", { type: "checkbox", checked: data.proposals.some((p) => p.assumed) ? null : "checked", onchange: (e) => {
      boxes.forEach((b) => { b.checked = e.target.checked; });
      picked.clear();
      if (e.target.checked) data.proposals.forEach((p) => picked.add(p.id));
      paint();
    } });
    listHost.append(el("div", { class: "row", style: "align-items:center;gap:12px" }, el("label", { style: "display:flex;gap:6px;align-items:center" }, all, " All"), count),
      el("div", { style: "max-height:40vh;overflow:auto;margin-top:6px" }, table));
    paint();
  };

  const preferSel = el("select", { onchange: async (e) => {
    prefer = e.target.value;
    await api("/api/kicad/prefs", { method: "PUT", body: { prefer } });
    data = await api(`/api/kicad/suggest?prefer=${prefer}${cat}`);
    render();
  } }, el("option", { value: "hand" }, "hand-solder pads"), el("option", { value: "standard" }, "standard pads"));
  preferSel.value = prefer;

  const download = el("button", { class: "ghost", onclick: () => {
    const url = URL.createObjectURL(new Blob([httplibFile(location.origin)], { type: "application/json" }));
    const a = el("a", { href: url, download: "partsnas.kicad_httplib" });
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } }, "Download partsnas.kicad_httplib");

  render();
  const body = el("div", { class: "modal-body" },
    el("div", { class: "section-title" }, "Connect KiCad (8 or newer)"),
    el("div", { class: "hint" },
      "KiCad can list your parts in its symbol chooser and fill in value, footprint, MPN, manufacturer and datasheet when you place one. " +
      "Download the file, save it on the computer you draw on, and add it in KiCad under Preferences → Manage Symbol Libraries. " +
      `It points at ${location.origin}/api/kicad/ - the NAS must be reachable from that computer, over plain http.`),
    el("div", { class: "row" }, download),
    el("div", { class: "section-title" }, "Which parts KiCad sees"),
    summary,
    el("div", { class: "row", style: "align-items:center;gap:8px" },
      el("label", { style: "display:flex;gap:6px;align-items:center" }, "Default footprint:", preferSel),
      el("span", { class: "hint", style: "padding:0" }, "the other kind is offered too, as its own entry in KiCad's chooser. Also used for parts you add from now on.")),
    listHost);

  modal({
    title: scope && scope.name ? `KiCad - ${scope.name}` : "KiCad - all parts",
    wide: "min(1100px, 96vw)",
    confirmText: "Name the selected parts",
    body,
    onConfirm: async () => {
      if (!data.proposals.length || !picked.size) return;
      const r = await api("/api/kicad/apply", { method: "POST", body: { ids: [...picked], prefer, category_id: scope && scope.id ? scope.id : null } });
      toast(`Named ${r.updated} part${r.updated === 1 ? "" : "s"} for KiCad`);
      onDone && onDone();
    },
  });
}
