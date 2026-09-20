// Every frontend module must at least parse. One missing bracket in order.js blanked the whole app
// (the tab bar never rendered), and nothing but opening the page would have noticed.
//   deno test --allow-read --allow-run tests/js
const dir = new URL("../../frontend/js/", import.meta.url);

for (const entry of Deno.readDirSync(dir)) {
  if (!entry.isFile || !entry.name.endsWith(".js")) continue;
  Deno.test(`parses: ${entry.name}`, async () => {
    const { stderr } = await new Deno.Command(Deno.execPath(), {
      args: ["check", new URL(entry.name, dir).pathname.replace(/^\/([A-Za-z]:)/, "$1")],
      stdout: "null",
      stderr: "piped",
    }).output();
    const text = new TextDecoder().decode(stderr);
    if (/SyntaxError/.test(text)) throw new Error(text.split("\n").slice(0, 8).join("\n"));
  });
}
