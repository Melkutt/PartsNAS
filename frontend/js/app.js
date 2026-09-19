import { initTheme } from "./theme.js";
import { api } from "./api.js";
import { Tree } from "./tree.js";
import { PartsView } from "./parts.js";
import { SuppliersView } from "./suppliers.js";
import { CustomersView } from "./customers.js";
import { DesignNotesView } from "./designnotes.js";
import { QuotesView } from "./quotes.js";
import { BomView } from "./bom.js";
import { AboutView } from "./about.js";
import { OrderView } from "./order.js";
import { initScanner } from "./scan.js";
import { openImport, openExport } from "./importexport.js";
import { openSettings } from "./settings.js";

const view = document.getElementById("view");
const tabs = document.getElementById("tabs");
let activeObj = null;
let pendingPartsFilter = null;
let pendingNoteQuery = "";
let pendingShop = null; // {quoteId}: open Parts as a shopping cart for that quote
let pendingOpenQuote = null; // open the Quotes tab straight on this quote

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
  order: mountOrder,
  notes: mountNotes,
  customers: mountCustomers,
  quotes: mountQuotes,
  bom: mountBom,
  suppliers: mountSuppliers,
  about: mountAbout,
};

function clearView() {
  if (activeObj && typeof activeObj.destroy === "function") activeObj.destroy();
  activeObj = null;
  view.innerHTML = "";
}

async function mountParts() {
  clearView();
  const v = new PartsView({ ...(pendingPartsFilter || {}), shop: pendingShop });
  pendingPartsFilter = null;
  pendingShop = null;
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

async function mountCustomers() {
  clearView();
  const v = new CustomersView();
  activeObj = v;
  await v.mount(view);
}

async function mountQuotes() {
  clearView();
  const v = new QuotesView({ openId: pendingOpenQuote });
  pendingOpenQuote = null;
  activeObj = v;
  await v.mount(view);
}

async function mountOrder() {
  clearView();
  const v = new OrderView();
  activeObj = v;
  await v.mount(view);
}

// "Order (3)" on the tab itself, so running low is visible from anywhere
async function updateOrderBadge() {
  const btn = tabs.querySelector('[data-tab="order"]');
  if (!btn) return;
  try {
    const { count, out } = await api("/api/order/count");
    btn.innerHTML = "Order";
    if (count) {
      const b = document.createElement("span");
      b.className = "tab-badge" + (out ? " out" : "");
      b.textContent = count;
      b.title = `${count} part(s) at or below Min stock` + (out ? `, ${out} out of stock` : "");
      btn.append(" ", b);
    }
  } catch { /* offline: leave the plain label */ }
}

async function mountBom() {
  clearView();
  const v = new BomView();
  activeObj = v;
  await v.mount(view);
}

async function mountAbout() {
  clearView();
  const v = new AboutView();
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
  updateOrderBadge();
}

const TAB_LABELS = { bom: "BOM" };

function buildTabs() {
  for (const name of Object.keys(TABS)) {
    const b = document.createElement("button");
    b.dataset.tab = name;
    b.textContent = TAB_LABELS[name] || name[0].toUpperCase() + name.slice(1);
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
  document.addEventListener("partsnas:orderchanged", updateOrderBadge);
  window.addEventListener("focus", updateOrderBadge);
  document.addEventListener("partsnas:shop", (e) => {
    pendingShop = { quoteId: e.detail.quoteId };
    selectTab("parts");
  });
  document.addEventListener("partsnas:openquote", (e) => {
    pendingOpenQuote = e.detail.id;
    selectTab("quotes");
  });
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
