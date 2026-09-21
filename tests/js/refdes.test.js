import { assertEquals as eq } from "https://deno.land/std@0.224.0/assert/mod.ts";
import { splitRefs } from "../../frontend/js/refdes.js";

Deno.test("splitRefs splits a BOM line's references", () => {
  eq(splitRefs("C6 C8, C10"), ["C6", "C8", "C10"]);
  eq(splitRefs(""), []);
  eq(splitRefs(null), []);
});
