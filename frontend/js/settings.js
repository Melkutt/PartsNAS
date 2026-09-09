// Settings modal: supplier API credentials + live rate-limit / breaker status.
import { api } from "./api.js";
import { el, modal, toast } from "./ui.js";

export async function openSettings() {
  const rows = await api("/api/settings/providers");
  const body = el("div", { class: "modal-body" });
  body.append(
    el("p", { style: "color:var(--text-muted);margin:0" },
      "Credentials are stored on the NAS (single-user). Lookups only run when you press ‘Look up’ on a part — never in bulk. Each provider is rate-limited, disk-cached and auto-paused if it returns a block."),
  );

  const inputs = {}; // name -> { fields:{}, priceChk, priceWas }
  for (const p of rows) {
    inputs[p.name] = { fields: {}, priceWas: p.price_enabled };
    const status = p.blocked_until
      ? el("span", { style: "color:var(--warn)" }, `paused until ${new Date(p.blocked_until * 1000).toLocaleTimeString()}`)
      : el("span", { style: "color:var(--text-faint)" }, p.configured ? `ready · ${p.used_today}/${p.quota_day} today · ${p.per_min}/min` : "not configured");
    const block = el("div", { style: "border-top:1px solid var(--border);padding-top:10px;margin-top:10px" },
      el("div", { style: "display:flex;gap:8px;align-items:baseline" },
        el("b", {}, p.label),
        el("a", { href: p.website, target: "_blank", style: "font-size:12px" }, "site"),
        el("span", { style: "flex:1" }), status));
    for (const f of p.cred_fields) {
      const inp = el("input", { type: "password", style: "flex:1",
        placeholder: f.from_env ? "(set via environment)" : f.stored ? "•••••• stored — type to replace" : "paste " + f.name,
        disabled: f.from_env ? "disabled" : null });
      inputs[p.name].fields[f.name] = inp;
      block.append(el("div", { class: "row", style: "margin-top:6px" },
        el("label", { style: "min-width:100px" }, f.name.replace(/_/g, " ")), inp));
    }
    const priceChk = el("input", { type: "checkbox", checked: p.price_enabled ? "checked" : null });
    inputs[p.name].priceChk = priceChk;
    block.append(el("label", { class: "facet-opt", style: "margin-top:6px",
      title: "included when you press ‘Fetch prices from all APIs’ on a part" },
      priceChk, " search prices from here"));
    body.append(block);
  }

  modal({
    title: "Settings — supplier APIs",
    body,
    confirmText: "Save",
    onConfirm: async () => {
      let n = 0;
      for (const [name, o] of Object.entries(inputs)) {
        const creds = {};
        for (const [fld, inp] of Object.entries(o.fields)) {
          if (!inp.disabled && inp.value.trim()) creds[fld] = inp.value.trim();
        }
        const body = {};
        if (Object.keys(creds).length) body.creds = creds;
        if (o.priceChk.checked !== o.priceWas) body.price_enabled = o.priceChk.checked;
        if (Object.keys(body).length) {
          await api(`/api/settings/providers/${name}`, { method: "PUT", body });
          n++;
        }
      }
      toast(n ? `Saved ${n} provider(s)` : "No changes");
    },
  });
}
