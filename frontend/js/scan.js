// Handheld USB barcode scanner support.
//
// These scanners act as a keyboard: they "type" the code very fast and send
// Enter. We watch keydown globally, collect fast bursts of printable keys, and
// on Enter fire a `partsnas:scan` CustomEvent {code}. Human typing is too slow
// to trigger it, so a focused search box still works normally.

const MAX_GAP_MS = 40; // between characters within one scan
const MIN_LEN = 3;

let buf = "";
let last = 0;
let start = 0;

export function initScanner(indicatorEl) {
  document.addEventListener("keydown", (e) => {
    const now = performance.now();

    if (e.key === "Enter") {
      const fast = buf.length >= MIN_LEN && now - start < buf.length * MAX_GAP_MS + 80;
      if (fast) {
        const code = buf;
        buf = "";
        // if the burst landed in a text field, undo it
        const t = e.target;
        if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA") && t.value.endsWith(code)) {
          t.value = t.value.slice(0, -code.length);
        }
        e.preventDefault();
        flash(indicatorEl);
        document.dispatchEvent(new CustomEvent("partsnas:scan", { detail: { code } }));
      } else {
        buf = "";
      }
      return;
    }

    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (now - last > MAX_GAP_MS) {
        buf = "";
        start = now;
      }
      buf += e.key;
      last = now;
    } else {
      buf = "";
    }
  });

  if (indicatorEl) {
    indicatorEl.title = "Handheld scanner ready — scan a barcode anywhere";
    indicatorEl.addEventListener("click", () => {
      const s = document.querySelector('.filters input[type="search"]');
      s && s.focus();
    });
  }
}

function flash(elm) {
  if (!elm) return;
  elm.classList.add("armed");
  clearTimeout(elm._t);
  elm._t = setTimeout(() => elm.classList.remove("armed"), 700);
}
