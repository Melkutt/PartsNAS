import { initTheme } from "./theme.js";
import { api } from "./api.js";
import { Tree } from "./tree.js";
import { PartsView } from "./parts.js";
import { initScanner } from "./scan.js";
import { openImport, openExport } from "./importexport.js";

const view = document.getElementById("view");
const tabs = document.getElementById("tabs");
let active = null; // { destroy? }

const TABS = {
  parts: mountParts,
  categories: () => mountTree("/api/categories", "category", "Categories", "New top category"),
  locations: () => mountTree("/api/locations", "location", "Storage locations", "New location"),
};

function clearView() {
  if (active && typeof active.destroy === "function") active.destroy();
  active = null;
  view.innerHTML = "";
}

async function mountParts() {
  clearView();
  const v = new PartsView();
  active = v;
  await v.mount(view);
}

async function mountTree(base, noun, title, rootAddLabel) {
  clearView();
  const panel = document.createElement("div");
  panel.className = "panel";
  panel.innerHTML = `<h2>${title}</h2><div class="panel-body"></div>`;
  view.append(panel);
  const tree = new Tree(base, { noun, rootAddLabel });
  await tree.mount(panel.querySelector(".panel-body"));
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

  document.getElementById("btn-import").addEventListener("click", () =>
    openImport(() => TABS.parts && selectTab("parts")),
  );
  document.getElementById("btn-export").addEventListener("click", openExport);

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
