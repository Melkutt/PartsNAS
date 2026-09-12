// Handheld USB barcode scanner support.
//
// These scanners act as a keyboard: they "type" the code very fast and send
// Enter. We watch keydown globally, collect fast bursts of printable keys, and
// on Enter fire a `partsnas:scan` CustomEvent {code}. Human typing is too slow
// to trigger it, so a focused search box still works normally.
//
// If a scan happens while a text field has focus, its characters would
// otherwise get typed into that field like any other keystrokes — visibly
// (corrupting whatever the user was doing) and invisibly (each one firing a
// real `input` event, so e.g. the Parts search box would run a live filter
// on the half-typed code before we ever see the terminating Enter). Once a
// burst is 2+ characters deep it cannot be human typing at this speed, so
// from there on we preventDefault() every keystroke — only the very first
// character of a burst can ever land in a field. On Enter we strip that one
// leaked character back out and fire a synthetic `input` event so whatever
// was listening (search box, form field, …) sees the field exactly as it
// was before the scan, not a half-updated state.

const MAX_GAP_MS = 40; // between characters within one scan
const MIN_LEN = 3;

let buf = "";
let last = 0;
let start = 0;
let leaked = 0; // characters of the current burst that reached the focused field

export function initScanner(indicatorEl) {
  document.addEventListener("keydown", (e) => {
    const now = performance.now();

    if (e.key === "Enter") {
      const fast = buf.length >= MIN_LEN && now - start < buf.length * MAX_GAP_MS + 80;
      if (fast) {
        const code = buf;
        buf = "";
        const t = e.target;
        if (leaked > 0 && t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA") && t.value.endsWith(code.slice(0, leaked))) {
          t.value = t.value.slice(0, -leaked);
          t.dispatchEvent(new Event("input", { bubbles: true }));
        }
        leaked = 0;
        e.preventDefault();
        flash(indicatorEl);
        document.dispatchEvent(new CustomEvent("partsnas:scan", { detail: { code } }));
      } else {
        buf = "";
        leaked = 0;
      }
      return;
    }

    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const continuing = buf.length > 0 && now - last <= MAX_GAP_MS;
      if (!continuing) {
        buf = "";
        start = now;
        leaked = 0;
      }
      buf += e.key;
      last = now;
      // 2nd+ character of a fast burst: too fast for a human, block it from
      // ever reaching the focused field. The 1st character can't be told
      // apart from ordinary typing yet, so it's allowed through and undone
      // above once Enter confirms this was a scan.
      if (buf.length >= 2) e.preventDefault();
      else leaked++;
    } else {
      buf = "";
      leaked = 0;
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
