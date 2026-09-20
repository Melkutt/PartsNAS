// deno test --allow-read tests/js
import { ohmsOf, resistorBands, toleranceOf } from "../../frontend/js/colorcode.js";

const names = (r) => r && r.bands.map((b) => b.name).join(" ");
function eq(actual, expected, msg = "") {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${msg}\n  expected: ${JSON.stringify(expected)}\n  actual:   ${JSON.stringify(actual)}`);
  }
}

Deno.test("the textbook values", () => {
  eq(names(resistorBands(4700, 5)), "yellow violet red gold", "4k7 5 %");
  eq(names(resistorBands(100, 5)), "brown black brown gold", "100R 5 %");
  eq(names(resistorBands(10, 5)), "brown black black gold", "10R 5 %");
  eq(names(resistorBands(1000000, 10)), "brown black green silver", "1M 10 %");
  eq(names(resistorBands(330, 5)), "orange orange brown gold", "330R");
  eq(names(resistorBands(22, 5)), "red red black gold", "22R");
});

Deno.test("precise resistors get five bands", () => {
  eq(names(resistorBands(3300, 1)), "orange orange black brown brown", "3k3 1 %");
  eq(names(resistorBands(100, 1)), "brown black black black brown", "100R 1 %");
  eq(names(resistorBands(49.9, 1)), "yellow white white gold brown", "49R9 1 %");
  eq(names(resistorBands(536, 1)), "green orange blue black brown", "536R 1 %");
  eq(resistorBands(3300, 1).count, 5);
  eq(resistorBands(3300, 5).count, 4);
});

Deno.test("under 10 ohm uses gold / silver as the multiplier", () => {
  eq(names(resistorBands(4.7, 5)), "yellow violet gold gold", "4R7");
  eq(names(resistorBands(0.18, 5)), "brown grey silver gold", "0R18");
  eq(names(resistorBands(5.6, 5)), "green blue gold gold", "5R6");
});

Deno.test("a value that needs a third digit is drawn with five bands even at 5 %", () => {
  eq(resistorBands(536, 5).count, 5);
});

Deno.test("what cannot be drawn returns null, and tolerance is optional", () => {
  eq(resistorBands(0, 5), null);
  eq(resistorBands(-3, 5), null);
  eq(resistorBands(NaN, 5), null);
  eq(resistorBands(123456, 5), null);                       // needs 6 digits
  eq(names(resistorBands(4700)), "yellow violet red", "unknown tolerance: digits + multiplier only");
  eq(resistorBands(4700).note.includes("unknown"), true);
  eq(names(resistorBands(4700, 20)), "yellow violet red");
});

Deno.test("the app's own value notation", () => {
  eq(ohmsOf("3k3"), 3300);
  eq(ohmsOf("4R7"), 4.7);
  eq(ohmsOf("0R18"), 0.18);
  eq(ohmsOf("100k"), 100000);
  eq(ohmsOf("1M"), 1000000);
  eq(ohmsOf("abc"), null);
  eq(toleranceOf("±1%"), 1);
  eq(toleranceOf("5 %"), 5);
  eq(toleranceOf("0.5"), 0.5);
  eq(toleranceOf(""), null);
  eq(names(resistorBands(ohmsOf("3k3"), toleranceOf("±1%"))), "orange orange black brown brown");
});
