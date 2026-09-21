// Talking to an "Interactive HTML BOM" page (https://github.com/openscopeproject/InteractiveHtmlBom,
// MIT, © qu1ck): a KiCad plugin that writes ONE html file with the whole board inside.
//
// PartsNAS never contains any of their code. It shows the file the plugin wrote and reads what the
// page itself exposes. That is a page's internals, not a documented API, so every function here is
// defensive: when something is not where it used to be it returns null / false, the board is still
// shown, and the BOM (which never depends on any of this) keeps working.

const MPN_FIELD = /^(mpn|mfr\.? ?part( ?(no|number|#))?|manufacturer part( ?(no|number|#))?|part ?number|pn)$/;

/**
 * The parts list inside a page's `pcbdata`: one line per BOM group, as
 * { refdes: "C6 C8 C10", value, footprint, mpn, qty }.
 * `pcbdata.bom.both` is a list of groups, each a list of [reference, footprintIndex];
 * `pcbdata.bom.fields[footprintIndex]` holds that component's fields in the order of `config.fields`.
 * Returns null when the data does not look like that.
 */
export function linesFromPcbdata(pcbdata, fieldNames) {
  const bom = pcbdata && pcbdata.bom;
  if (!bom || !Array.isArray(bom.both) || !bom.fields || !Array.isArray(fieldNames)) return null;
  const names = fieldNames.map((n) => String(n).trim().toLowerCase());
  const iValue = names.indexOf("value");
  const iFootprint = names.indexOf("footprint");
  const iMpn = names.findIndex((n) => MPN_FIELD.test(n));
  if (iValue < 0 && iFootprint < 0) return null;

  const lines = [];
  for (const group of bom.both) {
    if (!Array.isArray(group) || !group.length) continue;
    // every member of a group has the same fields: take them from the first one that has any
    let fields = null;
    for (const member of group) {
      const f = bom.fields[member[1]] ?? bom.fields[String(member[1])];
      if (Array.isArray(f)) { fields = f; break; }
    }
    if (!fields) return null;
    const refs = group.map((g) => String(g[0])).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    lines.push({
      refdes: refs.join(" "),
      value: iValue >= 0 ? String(fields[iValue] ?? "") : "",
      footprint: iFootprint >= 0 ? String(fields[iFootprint] ?? "") : "",
      mpn: iMpn >= 0 ? String(fields[iMpn] ?? "") : "",
      qty: group.length,
    });
  }
  return lines.length ? lines : null;
}

/** "C6 C8, C10" -> ["C6", "C8", "C10"] */
export const splitRefs = (s) => String(s || "").split(/[\s,;]+/).filter(Boolean);

/** The page's window once it has loaded its data, else null (cross-origin, not loaded, other format). */
export function boardWindow(iframe) {
  try {
    const w = iframe && iframe.contentWindow;
    return w && w.pcbdata && w.pcbdata.footprints ? w : null;
  } catch {
    return null;
  }
}

/**
 * Read the parts list out of an ibom.html file the user picked: load it in a hidden frame (it is the
 * user's own file), wait for its data, read it, throw the frame away.
 */
export function readIbomFile(file, timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const frame = document.createElement("iframe");
    frame.style.cssText = "position:fixed;left:-99999px;top:0;width:1200px;height:800px;border:0";
    let done = false;
    const finish = (fn, val) => {
      if (done) return;
      done = true;
      clearInterval(timer);
      frame.remove();
      URL.revokeObjectURL(url);
      fn(val);
    };
    const started = Date.now();
    const timer = setInterval(() => {
      const w = boardWindow(frame);
      if (w) {
        const lines = linesFromPcbdata(w.pcbdata, (w.config && w.config.fields) || []);
        return lines ? finish(resolve, { lines, title: (w.pcbdata.metadata && w.pcbdata.metadata.title) || "" })
                     : finish(reject, new Error("read the file, but could not find a parts list in it"));
      }
      if (Date.now() - started > timeoutMs) finish(reject, new Error("this does not look like an Interactive HTML BOM"));
    }, 150);
    frame.src = url;
    document.body.append(frame);
  });
}

/** Light up the components with these references on the board (and in the page's own table). */
export function highlightRefs(w, refs) {
  try {
    const wanted = new Set(refs);
    if (!wanted.size) return false;
    // 1) the page's own BOM row for that group, so its table and its checkboxes stay in step
    const rows = [...w.document.querySelectorAll("#bomtable tbody tr")];
    const row = rows.find((tr) => tr.id && [...tr.querySelectorAll("td")].some((td) => splitRefs(td.textContent).some((t) => wanted.has(t))));
    const h = row && Array.isArray(w.highlightHandlers) && w.highlightHandlers.find((x) => x.id === row.id);
    if (h && typeof h.handler === "function") {
      h.handler();
      return true;
    }
    // 2) otherwise mark the footprints directly
    const idx = w.pcbdata.footprints.map((f, i) => (wanted.has(f.ref) ? i : -1)).filter((i) => i >= 0);
    if (!idx.length) return false;
    w.highlightedFootprints = idx;
    if (typeof w.drawHighlights === "function") w.drawHighlights();
    return true;
  } catch {
    return false;
  }
}

/** Call back with the references that were just highlighted when the user clicks the board. */
export function onBoardClick(w, callback) {
  try {
    const original = w.footprintsClicked;
    if (typeof original !== "function") return false;
    w.footprintsClicked = function (...args) {
      const result = original.apply(this, args);
      try {
        callback((w.highlightedFootprints || []).map((i) => w.pcbdata.footprints[i].ref));
      } catch { /* never break the page */ }
      return result;
    };
    return true;
  } catch {
    return false;
  }
}
