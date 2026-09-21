// Reference designators as KiCad writes them in a BOM line: "C6 C8, C10".
export const splitRefs = (s) => String(s || "").split(/[\s,;]+/).filter(Boolean);
