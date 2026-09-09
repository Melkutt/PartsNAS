// Settings modal: supplier API keys + live rate-limit / breaker status.
import { api } from "./api.js";
import { el, modal, toast } from "./ui.js";

export async function openSettings() {
  const rows = await api("/api/settings/providers");
  const body = el("div", { class: "modal-body" });
  body.append(
    el("p", { style: "color:var(--text-muted);margin:0" },
      "API keys are stored on the NAS (single-user). Lookups only run when you press ‘Look up’ on a part — never in bulk. Each provider is rate-limited, disk-cached and auto-paused if it returns a block."),
  );

  const inputs = {};
  for (const p of rows) {
    const key = el("input", { type: "password", placeholder: p.from_env ? "(set via environment)" : p.has_stored_key ? "•••••• (stored) — type to replace" : "paste API key",
      disabled: p.from_env ? "disabled" : null, style: "flex:1" });
    inputs[p.name] = key;
    const status = p.blocked_until
      ? el("span", { style: "color:var(--warn)" }, `paused until ${new Date(p.blocked_until * 1000).toLocaleTimeString()}`)
      : el("span", { style: "color:var(--text-faint)" }, p.configured ? `ready · ${p.used_today}/${p.quota_day} today · ${p.per_min}/min` : "no key");
    body.append(
      el("div", { style: "border-top:1px solid var(--border);padding-top:10px;margin-top:10px" },
        el("div", { style: "display:flex;gap:8px;align-items:baseline" },
          el("b", {}, p.label),
          el("a", { href: p.website, target: "_blank", style: "font-size:12px" }, "site"),
          el("span", { style: "flex:1" }), status),
        el("div", { class: "row", style: "margin-top:6px" }, key,
          p.from_env ? null : el("button", { class: "ghost", onclick: () => save(p.name, "") }, "clear")),
      ),
    );
  }

  async function save(name, val) {
    await api(`/api/settings/providers/${name}`, { method: "PUT", body: { api_key: val } });
  }

  modal({
    title: "Settings — supplier APIs",
    body,
    confirmText: "Save keys",
    onConfirm: async () => {
      let n = 0;
      for (const [name, inp] of Object.entries(inputs)) {
        if (!inp.disabled && inp.value.trim()) { await save(name, inp.value.trim()); n++; }
      }
      toast(n ? `Saved ${n} key(s)` : "No changes");
    },
  });
}
