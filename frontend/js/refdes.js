// Reference designators as KiCad writes them in a BOM line: "C6 C8, C10".
export const splitRefs = (s) => String(s || "").split(/[\s,;]+/).filter(Boolean);

/**
 * A BOM line's references as short lines for the printed list: "C3 C4 C5 C6 C7 C8 C10 C11" -> ["C3-8", "C10-11"].
 * Runs of consecutive numbers with the same letters become a range, other references stay as they are; references
 * that are not letters + number (like "12V") are kept last, in the order they came.
 */
export function compactRefs(refs) {
  const list = Array.isArray(refs) ? refs : splitRefs(refs);
  const byPrefix = new Map();
  const other = [];
  for (const r of list) {
    const m = /^(\D+?)(\d+)$/.exec(r);
    if (!m) { if (!other.includes(r)) other.push(r); continue; }
    if (!byPrefix.has(m[1])) byPrefix.set(m[1], new Set());
    byPrefix.get(m[1]).add(Number(m[2]));
  }
  const out = [];
  for (const prefix of [...byPrefix.keys()].sort((a, b) => a.localeCompare(b))) {
    const nums = [...byPrefix.get(prefix)].sort((a, b) => a - b);
    for (let i = 0; i < nums.length;) {
      let j = i;
      while (j + 1 < nums.length && nums[j + 1] === nums[j] + 1) j++;
      out.push(j > i ? `${prefix}${nums[i]}-${nums[j]}` : `${prefix}${nums[i]}`);
      i = j + 1;
    }
  }
  return [...out, ...other];
}
