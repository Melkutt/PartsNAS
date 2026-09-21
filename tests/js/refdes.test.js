import { assertEquals as eq } from "https://deno.land/std@0.224.0/assert/mod.ts";
import { splitRefs } from "../../frontend/js/refdes.js";

Deno.test("splitRefs splits a BOM line's references", () => {
  eq(splitRefs("C6 C8, C10"), ["C6", "C8", "C10"]);
  eq(splitRefs(""), []);
  eq(splitRefs(null), []);
});

import { compactRefs } from "../../frontend/js/refdes.js";

Deno.test("references are written as ranges on the printed list", () => {
  eq(compactRefs("C10 C11 C13 C17 C18 C19 C20 C21 C22 C23 C26 C27 C3 C30 C35 C36 C37 C38 C39 C4 C5 C6 C7 C8"),
    ["C3-8", "C10-11", "C13", "C17-23", "C26-27", "C30", "C35-39"]);
  eq(compactRefs("C1 C12 C32 C9"), ["C1", "C9", "C12", "C32"]);
  eq(compactRefs("R2 R1 C1 R3"), ["C1", "R1-3"]);
  eq(compactRefs("12V 3V3 5V"), ["12V", "3V3", "5V"]);
  eq(compactRefs("U1 12V U1"), ["U1", "12V"]);
  eq(compactRefs(""), []);
});
