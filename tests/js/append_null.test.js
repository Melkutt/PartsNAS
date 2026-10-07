// The DOM's own `node.append(null)` writes the text "null" into the page (the `el()` helper skips null children,
// `append()` does not). The Parts toolbar showed a stray "null" next to "+ New part" in the quote cart because
// of `bar.append(..., cond ? null : button, ...)`. Pass an empty spread instead: `...(cond ? [] : [button])`.
//   deno test --allow-read --allow-run tests/js
const dir = new URL("../../frontend/js/", import.meta.url);

Deno.test("no .append() call is handed a conditional null", () => {
  const bad = [];
  for (const entry of Deno.readDirSync(dir)) {
    if (!entry.isFile || !entry.name.endsWith(".js")) continue;
    const lines = Deno.readTextFileSync(new URL(entry.name, dir)).split("\n");
    lines.forEach((line, i) => {
      if (!/\.append\(/.test(line) || !/\?\s*null\s*:|:\s*null\s*[,)]/.test(line)) return;
      // `.append(...[a, cond ? b : null].filter(Boolean))` (as in bom.js) drops the nulls first, so it is fine
      if (/\.filter\(Boolean\)/.test(lines.slice(i, i + 3).join("\n"))) return;
      bad.push(`${entry.name}:${i + 1}`);
    });
  }
  if (bad.length) throw new Error(`append() with a possible null argument (renders the word "null"):\n${bad.join("\n")}`);
});
