import { initTheme } from "./theme.js";
import { api } from "./api.js";
import { Tree } from "./tree.js";

const view = document.getElementById("view");
const tabs = document.getElementById("tabs");

const TABS = {
  categories: () => renderTree("/api/categories", "category", "Categories", "New top category"),
  locations: () => renderTree("/api/locations", "location", "Storage locations", "New location"),
};

let current = null;

async function renderTree(base, noun, title, rootAddLabel) {
  view.innerHTML = "";
  const panel = document.createElement("div");
  panel.className = "panel";
  panel.innerHTML = `<h2>${title}</h2><div class="panel-body"></div>`;
  view.appendChild(panel);
  const tree = new Tree(base, { noun, rootAddLabel });
  await tree.mount(panel.querySelector(".panel-body"));
}

function selectTab(name) {
  current = name;
  [...tabs.children].forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  location.hash = name;
  TABS[name]();
}

function buildTabs() {
  for (const [name, _] of Object.entries(TABS)) {
    const b = document.createElement("button");
    b.dataset.tab = name;
    b.textContent = name[0].toUpperCase() + name.slice(1);
    b.addEventListener("click", () => selectTab(name));
    tabs.appendChild(b);
  }
}

async function main() {
  initTheme(document.getElementById("theme-switch"));
  buildTabs();
  try {
    const info = await api("/api/health");
    document.getElementById("ver").textContent = "v" + info.version;
  } catch {
    document.getElementById("ver").textContent = "offline";
  }
  const start = (location.hash || "#categories").slice(1);
  selectTab(TABS[start] ? start : "categories");
}

main();
