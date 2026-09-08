// Theme switch: Light / Gray / Dark.
// Gray is the default. Choice is stored per-browser now; later it also syncs to
// the server so every device hitting the NAS shows the same theme.
const KEY = "partsnas.theme";
const THEMES = ["light", "gray", "dark"];

export function initTheme(mountEl) {
  applyTheme(currentTheme());
  if (mountEl) renderSwitch(mountEl);
}

export function currentTheme() {
  const saved = localStorage.getItem(KEY);
  if (THEMES.includes(saved)) return saved;
  // first visit: honour a dark OS preference, otherwise Gray
  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) return "dark";
  return "gray";
}

export function applyTheme(name) {
  document.documentElement.setAttribute("data-theme", name);
  try {
    localStorage.setItem(KEY, name);
  } catch {
    /* private mode */
  }
}

function renderSwitch(el) {
  el.className = "seg";
  el.innerHTML = "";
  const labels = { light: "Light", gray: "Gray", dark: "Dark" };
  for (const t of THEMES) {
    const b = document.createElement("button");
    b.textContent = labels[t];
    b.dataset.theme = t;
    b.addEventListener("click", () => {
      applyTheme(t);
      mark(el);
    });
    el.appendChild(b);
  }
  mark(el);
}

function mark(el) {
  const now = document.documentElement.getAttribute("data-theme");
  el.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.theme === now));
}
