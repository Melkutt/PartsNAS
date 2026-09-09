// Tiny fetch wrapper. Everything is same-origin under /api.
export async function api(path, { method = "GET", body } = {}) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const res = await fetch(path, opt);
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // Non-JSON body (e.g. a proxy error page or a bare "Internal Server Error").
    if (!res.ok) {
      const snippet = text.trim().slice(0, 300);
      throw new Error(snippet || res.statusText || `HTTP ${res.status}`);
    }
    return text;
  }
  if (!res.ok) {
    const msg = data && (data.detail || data.message) ? data.detail || data.message : res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}
