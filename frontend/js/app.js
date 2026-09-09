import { initTheme } from "./theme.js";
import { api } from "./api.js";
import { Tree } from "./tree.js";
import { PartsView } from "./parts.js";
import { SuppliersView } from "./suppliers.js";
import { DesignNotesView } from "./designnotes.js";
import { QuotesView } from "./quotes.js";
import { initScanner } from "./scan.js";
import { openImport, openExport } from "./importexport.js";
import { openSettings } from "./settings.js";

const view = document.getElementById("view");
const tabs = document.getElementById("tabs");
let activeObj = null;
let pendingPartsFilter = null;
let pendingNoteQuery = "";

const TABS = {
  parts: mountParts,
  categories: () =>
    mountTree("/api/categories", "category", "Categories", "New top category", (node) =>
      gotoPartsFiltered({ category_id: node.id }),
    ),
  locations: () =>
    mountTree("/api/locations", "location", "Storage locations", "New location", (node) =>
      gotoPartsFiltered({ location_id: node.id }),
    ),
  notes: mountNotes,
  quotes: mountQuotes,
  suppliers: mountSuppliers,
};

function clearView() {
  if (activeObj && typeof activeObj.destroy === "function") activeObj.destroy();
  activeObj = null;
  view.innerHTML = "";
}

async function mountParts() {
  clearView();
  const v = new PartsView(pendingPartsFilter || {});
  pendingPartsFilter = null;
  activeObj = v;
  await v.mount(view);
}

async function mountSuppliers() {
  clearView();
  const v = new SuppliersView();
  activeObj = v;
  await v.mount(view);
}

async function mountNotes() {
  clearView();
  const v = new DesignNotesView({ q: pendingNoteQuery });
  pendingNoteQuery = "";
  activeObj = v;
  await v.mount(view);
}

async function mountQuotes() {
  clearView();
  const v = new QuotesView({});
  activeObj = v;
  await v.mount(view);
}

async function mountTree(base, noun, title, rootAddLabel, onSelect) {
  clearView();
  const panel = document.createElement("div");
  panel.className = "panel";
  panel.innerHTML = `<h2>${title}</h2><div class="panel-body"></div>`;
  view.append(panel);
  const tree = new Tree(base, { noun, rootAddLabel, onSelect });
  await tree.mount(panel.querySelector(".panel-body"));
}

function gotoPartsFiltered(filter) {
  pendingPartsFilter = filter;
  selectTab("parts");
}

function selectTab(name) {
  [...tabs.children].forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  location.hash = name;
  TABS[name]();
}

function buildTabs() {
  for (const name of Object.keys(TABS)) {
    const b = document.createElement("button");
    b.dataset.tab = name;
    b.textContent = name[0].toUpperCase() + name.slice(1);
    b.addEventListener("click", () => selectTab(name));
    tabs.append(b);
  }
}

async function main() {
  initTheme(document.getElementById("theme-switch"));
  initScanner(document.getElementById("scan-ind"));
  buildTabs();

  document.getElementById("btn-import").addEventListener("click", () => openImport(() => selectTab("parts")));
  document.getElementById("btn-export").addEventListener("click", openExport);
  document.getElementById("btn-settings").addEventListener("click", openSettings);
  document.addEventListener("partsnas:gototab", (e) => {
    const d = e.detail || {};
    if (d.tab === "notes") {
      pendingNoteQuery = d.q || "";
      selectTab("notes");
    } else if (d.q !== undefined) {
      gotoPartsFiltered({ q: d.q });
    }
  });

  try {
    const info = await api("/api/health");
    document.getElementById("ver").textContent = "v" + info.version;
  } catch {
    document.getElementById("ver").textContent = "offline";
  }

  const start = (location.hash || "#parts").slice(1);
  selectTab(TABS[start] ? start : "parts");
}

main();
