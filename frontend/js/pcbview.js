// A KiCad board drawn in the browser: pan, zoom, turn, flip to the back side, light up parts.
// The model comes from backend/app/kicadpcb.py (outline, footprints with pads, silkscreen / fab lines, copper),
// already in board coordinates, so this file only draws. Nothing here needs KiCad or any third-party code.
//
// The functions before `class PcbView` are pure (no DOM) and are tested in tests/js/pcbview.test.js.

// ------------------------------------------------------------------ geometry (pure)
/** Turn (x, y) counter-clockwise on screen (y down) - the way KiCad turns things. */
export function rotateCcw(x, y, deg) {
  if (!deg) return [x, y];
  const a = (deg * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
  return [x * c + y * s, -x * s + y * c];
}

/** The polygon of a pad, in board coordinates, as [x0, y0, x1, y1, ...]. Circles are left to the caller. */
export function padPolygon(pad) {
  if (pad.poly && pad.poly.length >= 6) return pad.poly;
  const hw = pad.w / 2, hh = pad.h / 2;
  let local;
  if (pad.s === "oval" || pad.s === "roundrect") {
    const r = pad.s === "oval" ? Math.min(hw, hh) : Math.min(hw, hh) * 2 * (pad.rr ?? 0.25);
    local = roundedRect(hw, hh, Math.min(r, hw, hh), 6);
  } else {
    local = [-hw, -hh, hw, -hh, hw, hh, -hw, hh];
  }
  const out = [];
  for (let i = 0; i < local.length; i += 2) {
    const [rx, ry] = rotateCcw(local[i], local[i + 1], pad.r || 0);
    out.push(pad.x + rx, pad.y + ry);
  }
  return out;
}

function roundedRect(hw, hh, r, steps) {
  const pts = [];
  const corner = (cx, cy, from) => {
    for (let i = 0; i <= steps; i++) {
      const a = from + (i / steps) * (Math.PI / 2);
      pts.push(cx + r * Math.cos(a), cy + r * Math.sin(a));
    }
  };
  corner(hw - r, hh - r, 0);
  corner(-hw + r, hh - r, Math.PI / 2);
  corner(-hw + r, -hh + r, Math.PI);
  corner(hw - r, -hh + r, 1.5 * Math.PI);
  return pts;
}

/** Points along the arc that runs from `s` through `m` to `e` (KiCad's start / mid / end). */
export function arcPoints(sx, sy, mx, my, ex, ey, stepDeg = 6) {
  const d = 2 * (sx * (my - ey) + mx * (ey - sy) + ex * (sy - my));
  if (Math.abs(d) < 1e-9) return [sx, sy, ex, ey];                       // three points on a line
  const s2 = sx * sx + sy * sy, m2 = mx * mx + my * my, e2 = ex * ex + ey * ey;
  const cx = (s2 * (my - ey) + m2 * (ey - sy) + e2 * (sy - my)) / d;
  const cy = (s2 * (ex - mx) + m2 * (sx - ex) + e2 * (mx - sx)) / d;
  const r = Math.hypot(sx - cx, sy - cy);
  const a0 = Math.atan2(sy - cy, sx - cx), am = Math.atan2(my - cy, mx - cx), a1 = Math.atan2(ey - cy, ex - cx);
  const twoPi = Math.PI * 2;
  const norm = (a) => ((a % twoPi) + twoPi) % twoPi;
  // go the way that passes through the middle point
  const ccw = norm(am - a0) < norm(a1 - a0);
  const sweep = ccw ? norm(a1 - a0) : -norm(a0 - a1);
  const n = Math.max(2, Math.ceil(Math.abs(sweep) / ((stepDeg * Math.PI) / 180)));
  const out = [];
  for (let i = 0; i <= n; i++) {
    const a = a0 + (sweep * i) / n;
    out.push(cx + r * Math.cos(a), cy + r * Math.sin(a));
  }
  return out;
}

/**
 * The outline as closed loops of points: lines and arcs that meet end to end are chained, circles / rects /
 * polygons are loops of their own. Loops that could not be closed are dropped.
 */
export function edgeLoops(edge, tol = 0.02) {
  const loops = [];
  const open = [];
  for (const p of edge) {
    if (p[0] === "c") {
      const pts = [];
      for (let i = 0; i < 48; i++) pts.push(p[1] + p[3] * Math.cos((i / 48) * 2 * Math.PI), p[2] + p[3] * Math.sin((i / 48) * 2 * Math.PI));
      loops.push(pts);
    } else if (p[0] === "p") {
      loops.push(p[1].slice());
    } else if (p[0] === "l") {
      open.push([p[1], p[2], p[3], p[4]]);
    } else if (p[0] === "a") {
      open.push(arcPoints(p[1], p[2], p[3], p[4], p[5], p[6]));
    }
  }
  const near = (ax, ay, bx, by) => Math.abs(ax - bx) <= tol && Math.abs(ay - by) <= tol;
  while (open.length) {
    let chain = open.shift().slice();
    let grew = true;
    while (grew) {
      grew = false;
      const hx = chain[chain.length - 2], hy = chain[chain.length - 1];
      for (let i = 0; i < open.length; i++) {
        const seg = open[i], n = seg.length;
        if (near(hx, hy, seg[0], seg[1])) chain = chain.concat(seg.slice(2));
        else if (near(hx, hy, seg[n - 2], seg[n - 1])) {
          const rev = [];
          for (let k = n - 4; k >= 0; k -= 2) rev.push(seg[k], seg[k + 1]);
          chain = chain.concat(rev);
        } else continue;
        open.splice(i, 1);
        grew = true;
        break;
      }
    }
    if (chain.length >= 6 && near(chain[0], chain[1], chain[chain.length - 2], chain[chain.length - 1])) loops.push(chain);
  }
  return loops;
}

/** board (mm) -> screen (px). `view`: {bbox, rot (0/90/180/270, clockwise), flip, scale, panX, panY, w, h} */
export function boardToScreen(view, x, y) {
  const cx = (view.bbox[0] + view.bbox[2]) / 2, cy = (view.bbox[1] + view.bbox[3]) / 2;
  let px = x - cx, py = y - cy;
  if (view.flip) px = -px;                                    // looking at the back: mirror left-right
  const a = ((view.rot || 0) * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
  const rx = px * c - py * s, ry = px * s + py * c;           // clockwise on screen
  return [view.w / 2 + view.panX + rx * view.scale, view.h / 2 + view.panY + ry * view.scale];
}

export function screenToBoard(view, sx, sy) {
  const rx = (sx - view.w / 2 - view.panX) / view.scale, ry = (sy - view.h / 2 - view.panY) / view.scale;
  const a = (-(view.rot || 0) * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
  let px = rx * c - ry * s;
  const py = rx * s + ry * c;
  if (view.flip) px = -px;
  const cx = (view.bbox[0] + view.bbox[2]) / 2, cy = (view.bbox[1] + view.bbox[3]) / 2;
  return [px + cx, py + cy];
}

/** The scale (px per mm) that makes the board fill the view with a margin. */
export function fitScale(bbox, rot, w, h, margin = 24) {
  const bw = bbox[2] - bbox[0], bh = bbox[3] - bbox[1];
  const turned = rot % 180 !== 0;
  const ew = turned ? bh : bw, eh = turned ? bw : bh;
  return Math.max(0.01, Math.min((w - 2 * margin) / Math.max(ew, 1e-6), (h - 2 * margin) / Math.max(eh, 1e-6)));
}

/** The reference of the part under a board point, on the side being looked at (through-hole parts count on both). */
export function hitFootprint(model, x, y, side) {
  let best = null, bestRank = Infinity;
  for (const f of model.footprints) {
    const [x0, y0, x1, y1] = f.bbox;
    const visible = f.side === side || f.attr.includes("through_hole") || f.pads.some((p) => p.L === "FB");
    if (!visible || x < x0 - 0.15 || x > x1 + 0.15 || y < y0 - 0.15 || y > y1 + 0.15) continue;
    // a part on this side beats one from the other side; among those, the smallest box (the small part on top of a big one)
    const rank = (f.side === side ? 0 : 1e6) + Math.max(x1 - x0, 0.1) * Math.max(y1 - y0, 0.1);
    if (rank < bestRank) {
      best = f;
      bestRank = rank;
    }
  }
  return best ? best.ref : null;
}

/** The stroke width of a drawing primitive (its position differs by kind). */
export function primWidth(p) {
  return p[0] === "p" ? p[2] : p[0] === "c" ? p[4] : p[p.length - 1];
}

// ------------------------------------------------------------------ drawing
// on paper: light board, dark lines, no copper - it is a map for finding parts, not a picture of the board
const PRINT_COLORS = {
  board: "#f1f5ee", boardEdge: "#111111", copperF: "#cfcfcf", copperB: "#cfcfcf", pad: "#4a4a4a", padB: "#4a4a4a",
  hole: "#ffffff", silk: "#000000", fab: "#777777", crtyd: "#999999", via: "#bbbbbb", hi: "#39ff14", hiFill: "rgba(57,255,20,0.3)", placed: "#4a4a4a",
  bg: "#ffffff", label: "#000000",
};

const COLORS = {
  board: "#1d3b2a", boardEdge: "#e6d36a", copperF: "#b03a3a", copperB: "#3a5fb0", pad: "#c9a227", padB: "#8fa8c9",
  hole: "#0e1a13", silk: "#ece8d8", fab: "#7d8a96", crtyd: "#4f7a6a", via: "#9aa0a6", hi: "#39ff14", hiFill: "rgba(57,255,20,0.22)", placed: "#4da3ff", placedFill: "rgba(77,163,255,0.16)", bg: "#12191a", label: "rgba(255,255,255,0.85)",
};

export class PcbView {
  /**
   * @param {HTMLElement} host   an element with a size; the view fills it
   * @param {{onSelect?: (refs: string[]) => void}} opts
   */
  constructor(host, opts = {}) {
    this.host = host;
    this.onSelect = opts.onSelect || (() => {});
    this.model = null;
    this.side = "F";
    this.rot = 0;
    this.scale = 1;
    this.panX = 0;
    this.panY = 0;
    this.highlighted = new Set();
    this.placed = new Set();          // parts already soldered on: drawn in blue, so what is left stands out
    this.show = { silk: true, fab: false, pads: true, tracks: true, zones: true, refs: false };
    this._raf = 0;
    this._loops = [];

    host.classList.add("pcbview");
    this.canvas = document.createElement("canvas");
    this.canvas.className = "pcbview-canvas";
    this.bar = this._buildBar();
    host.append(this.bar, this.canvas);
    this.ctx = this.canvas.getContext("2d");
    this.canvas.pcbView = this;   // handy for debugging and tests
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(host);
    this._ro.observe(this.canvas);
    this._wire();
  }

  destroy() {
    this._ro.disconnect();
    cancelAnimationFrame(this._raf);
    this.host.innerHTML = "";
    this.host.classList.remove("pcbview");
  }

  setBoard(model) {
    this.model = model;
    this._loops = edgeLoops(model.edge || []);
    this.side = "F";
    this.rot = 0;
    this.fit();
  }

  /** Is this part seen from the side being looked at? (a through-hole part shows from both) */
  _seen(f) {
    return f.side === this.side || f.pads.some((p) => p.L === "FB");
  }

  /** Light up the parts with these references (an array or a Set). */
  highlight(refs) {
    this.highlighted = new Set(refs);
    this.draw();
  }

  /** Mark the parts with these references as placed (an array or a Set). */
  setPlaced(refs) {
    this.placed = new Set(refs);
    this.draw();
  }

  fit() {
    if (!this.model) return;
    const { w, h } = this._size();
    this.scale = fitScale(this.model.bbox, this.rot, w, h);
    this.panX = 0;
    this.panY = 0;
    this.draw();
  }

  _size() {
    const r = this.canvas.getBoundingClientRect();
    return { w: Math.max(50, r.width), h: Math.max(50, r.height) };
  }

  _view() {
    const { w, h } = this._size();
    return { bbox: this.model.bbox, rot: this.rot, flip: this.side === "B", scale: this.scale, panX: this.panX, panY: this.panY, w, h };
  }

  // the canvas' pixel buffer must match the size it is shown at, or everything is a blurry 300 x 150 picture
  _syncBacking() {
    const dpr = this._dpr();
    const { w, h } = this._size();
    const bw = Math.round(w * dpr), bh = Math.round(h * dpr);
    if (this.canvas.width !== bw || this.canvas.height !== bh) {
      this.canvas.width = bw;
      this.canvas.height = bh;
      return true;
    }
    return false;
  }

  _resize() {
    const changed = this._syncBacking();
    if (this.model && changed) { this.fit(); return; }
    this.draw();
  }

  _buildBar() {
    const bar = document.createElement("div");
    bar.className = "pcbview-bar";
    const btn = (label, title, fn) => {
      const b = document.createElement("button");
      b.className = "ghost";
      b.textContent = label;
      b.title = title;
      b.onclick = fn;
      bar.append(b);
      return b;
    };
    this.sideBtn = btn("Front", "Look at the other side of the board", () => {
      this.side = this.side === "F" ? "B" : "F";
      this.sideBtn.textContent = this.side === "F" ? "Front" : "Back";
      this.draw();
    });
    btn("⟲", "Turn 90° counter-clockwise", () => { this.rot = (this.rot + 270) % 360; this.fit(); });
    btn("⟳", "Turn 90° clockwise", () => { this.rot = (this.rot + 90) % 360; this.fit(); });
    btn("Fit", "Show the whole board", () => this.fit());
    for (const [key, label, title] of [["silk", "Silk", "Silkscreen"], ["fab", "Fab", "Fabrication drawing"], ["pads", "Pads", "Pads"],
                                       ["tracks", "Tracks", "Copper tracks and vias"], ["zones", "Zones", "Copper pours"], ["refs", "Refs", "Reference names"]]) {
      const l = document.createElement("label");
      l.title = title;
      const c = document.createElement("input");
      c.type = "checkbox";
      c.checked = this.show[key];
      c.onchange = () => { this.show[key] = c.checked; this.draw(); };
      l.append(c, " " + label);
      bar.append(l);
    }
    return bar;
  }

  _wire() {
    const cv = this.canvas;
    let drag = null;
    cv.addEventListener("pointerdown", (e) => {
      cv.setPointerCapture(e.pointerId);
      drag = { x: e.clientX, y: e.clientY, panX: this.panX, panY: this.panY, moved: false };
    });
    cv.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
      if (drag.moved) { this.panX = drag.panX + dx; this.panY = drag.panY + dy; this.draw(); }
    });
    cv.addEventListener("pointerup", (e) => {
      if (drag && !drag.moved && this.model) {
        const r = cv.getBoundingClientRect();
        const [bx, by] = screenToBoard(this._view(), e.clientX - r.left, e.clientY - r.top);
        const ref = hitFootprint(this.model, bx, by, this.side);
        this.highlighted = new Set(ref ? [ref] : []);
        this.draw();
        this.onSelect(ref ? [ref] : []);
      }
      drag = null;
    });
    cv.addEventListener("wheel", (e) => {
      if (!this.model) return;
      e.preventDefault();
      const r = cv.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
      const before = screenToBoard(this._view(), sx, sy);
      this.scale = Math.min(400, Math.max(0.5, this.scale * (e.deltaY < 0 ? 1.18 : 1 / 1.18)));
      const after = boardToScreen(this._view(), before[0], before[1]);   // keep the point under the cursor where it was
      this.panX += sx - after[0];
      this.panY += sy - after[1];
      this.draw();
    }, { passive: false });
  }

  /**
   * Silkscreen / fab text. KiCad's own stroke font is not available here, so it is set in Courier New (a monospaced
   * face, like KiCad's text) at the same height and, via the width setting, the same width: the size on the board
   * is the size in the file. The text is drawn in a frame of millimetres whose axes are the text's own along / down
   * directions mapped to the screen, so turning and flipping the board, and mirrored text on the back, come out right.
   */
  _drawTexts(prims, color, P) {
    const ctx = this.ctx;
    const K = 100;                                              // draw at 100x and scale down: tiny font sizes are unreliable
    for (const t of prims) {
      if (t[0] !== "t") continue;
      const [, text, x, y, ang, h, w, th, hj, vj, mirror, bold] = t;
      const o = P(x, y);
      const [ux, uy] = rotateCcw(1, 0, ang), [dx, dy] = rotateCcw(0, 1, ang);
      const a = P(x + ux, y + uy), d = P(x + dx, y + dy);
      ctx.save();
      ctx.transform(a[0] - o[0], a[1] - o[1], d[0] - o[0], d[1] - o[1], o[0], o[1]);
      ctx.scale(1 / K, 1 / K);
      if (mirror) ctx.scale(-1, 1);
      const em = h * 1.3 * K;                                   // Courier New's capitals are ~0.57 em tall: 1.3 x gives ~0.75 of the height
      ctx.font = `${bold || th >= 0.2 ? 700 : 600} ${em}px "Courier New", Courier, monospace`;
      ctx.fillStyle = color;
      ctx.textAlign = hj < 0 ? "left" : hj > 0 ? "right" : "center";
      ctx.textBaseline = "middle";
      const lines = String(text).split("\n");
      const lineH = h * 1.55 * K;
      const top = vj < 0 ? 0 : vj > 0 ? -lines.length * lineH : (-lines.length * lineH) / 2;
      ctx.scale(w / (h || 1), 1);
      lines.forEach((ln, i) => ctx.fillText(ln, 0, top + lineH * (i + 0.5)));
      ctx.restore();
    }
  }

  /**
   * The board as a picture, for printing: `palette: "print"` is white paper with dark lines, and the reference
   * names are drawn on every part so a printed board can be read without the screen.
   * @returns {HTMLCanvasElement}
   */
  static renderImage(model, { side = "F", rot = 0, width = 2000, height = 1400, refs = true, palette = "print", highlighted = [] } = {}) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const r = Object.create(PcbView.prototype);
    Object.assign(r, {
      canvas, ctx: canvas.getContext("2d"), model, _loops: edgeLoops(model.edge || []), side, rot, panX: 0, panY: 0,
      highlighted: new Set(highlighted), placed: new Set(), _raf: 0, _fixedDpr: 1, labelScale: width / 1100,
      show: { silk: true, fab: false, pads: true, tracks: palette !== "print", zones: false, refs },
      colors: palette === "print" ? PRINT_COLORS : null,
    });
    r._size = () => ({ w: width, h: height });
    r.scale = fitScale(model.bbox, rot, width, height, 40);
    r._paint();
    return canvas;
  }

  draw() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => { this._raf = 0; this._paint(); });
  }

  _dpr() {
    return this._fixedDpr || window.devicePixelRatio || 1;
  }

  _paint() {
    const C = this.colors || COLORS;
    this._syncBacking();
    const ctx = this.ctx, dpr = this._dpr();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const { w, h } = this._size();
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, w, h);
    if (!this.model) return;
    const view = this._view();
    const P = (x, y) => boardToScreen(view, x, y);
    const path = (pts, close) => {
      ctx.beginPath();
      for (let i = 0; i < pts.length; i += 2) {
        const [sx, sy] = P(pts[i], pts[i + 1]);
        i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy);
      }
      if (close) ctx.closePath();
    };
    const px = (mm, min = 1) => Math.max(min, mm * this.scale);
    const front = this.side === "F";
    const copper = front ? "F.Cu" : "B.Cu";
    const m = this.model;

    // the board
    if (this._loops.length) {
      ctx.beginPath();
      for (const loop of this._loops) {
        for (let i = 0; i < loop.length; i += 2) {
          const [sx, sy] = P(loop[i], loop[i + 1]);
          i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy);
        }
        ctx.closePath();
      }
      ctx.fillStyle = C.board;
      ctx.fill("evenodd");
      ctx.strokeStyle = C.boardEdge;
      ctx.lineWidth = px(0.15, 1);
      ctx.stroke();
    } else {
      const [a, b] = [P(m.bbox[0], m.bbox[1]), P(m.bbox[2], m.bbox[3])];
      ctx.fillStyle = C.board;
      ctx.fillRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
    }

    // copper
    if (this.show.zones) {
      ctx.fillStyle = front ? "rgba(176,58,58,0.32)" : "rgba(58,95,176,0.32)";
      for (const pts of (m.zones && m.zones[copper]) || []) { path(pts, true); ctx.fill(); }
    }
    if (this.show.tracks) {
      ctx.strokeStyle = front ? C.copperF : C.copperB;
      ctx.lineCap = "round";
      for (const t of (m.tracks && m.tracks[copper]) || []) {
        ctx.lineWidth = px(t[t.length - 1] || 0.2, 1);
        if (t[0] === "l") { path([t[1], t[2], t[3], t[4]], false); ctx.stroke(); }
        else if (t[0] === "a") { path(arcPoints(t[1], t[2], t[3], t[4], t[5], t[6]), false); ctx.stroke(); }
      }
      ctx.fillStyle = C.via;
      for (const v of m.vias || []) {
        const [sx, sy] = P(v[0], v[1]);
        ctx.beginPath(); ctx.arc(sx, sy, px(v[2] / 2, 1.5), 0, 6.2832); ctx.fill();
        ctx.fillStyle = C.hole;
        ctx.beginPath(); ctx.arc(sx, sy, px(v[3] / 2, 0.7), 0, 6.2832); ctx.fill();
        ctx.fillStyle = C.via;
      }
    }

    // drawings of the side being looked at
    const sideLayer = (name) => (m.gfx && m.gfx[(front ? "F." : "B.") + name]) || [];
    const drawPrims = (prims, color, minWidth) => {
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      for (const p of prims) {
        if (p[0] === "t") continue;                       // text is drawn by drawTexts
        ctx.lineWidth = px(primWidth(p) || 0.1, minWidth);
        if (p[0] === "l") { path([p[1], p[2], p[3], p[4]], false); ctx.stroke(); }
        else if (p[0] === "a") { path(arcPoints(p[1], p[2], p[3], p[4], p[5], p[6]), false); ctx.stroke(); }
        else if (p[0] === "p") { path(p[1], true); p[3] ? ctx.fill() : ctx.stroke(); }
        else if (p[0] === "c") {
          const [sx, sy] = P(p[1], p[2]);
          ctx.beginPath(); ctx.arc(sx, sy, Math.max(0.5, p[3] * this.scale), 0, 6.2832);
          p[4] ? ctx.fill() : ctx.stroke();
        }
      }
    };
    if (this.show.fab) { drawPrims(sideLayer("Fab"), C.fab, 0.6); this._drawTexts(sideLayer("Fab"), C.fab, P); }

    // pads (a through-hole pad shows from both sides)
    if (this.show.pads) {
      for (const f of m.footprints) {
        const hi = this.highlighted.has(f.ref) && this._seen(f);
        const done = this.placed.has(f.ref);
        for (const pad of f.pads) {
          if (pad.L !== "FB" && pad.L !== this.side) continue;
          ctx.fillStyle = hi ? C.hi : done ? C.placed : pad.L === "FB" || front ? C.pad : C.padB;
          if (pad.s === "circle" && !pad.poly) {
            const [sx, sy] = P(pad.x, pad.y);
            ctx.beginPath(); ctx.arc(sx, sy, Math.max(0.8, (pad.w / 2) * this.scale), 0, 6.2832); ctx.fill();
          } else {
            path(padPolygon(pad), true); ctx.fill();
          }
          if (pad.d) {
            const [sx, sy] = P(pad.x, pad.y);
            ctx.fillStyle = C.hole;
            ctx.beginPath(); ctx.arc(sx, sy, Math.max(0.5, (pad.d / 2) * this.scale), 0, 6.2832); ctx.fill();
          }
        }
      }
    }
    if (this.show.silk) { drawPrims(sideLayer("SilkS"), C.silk, 0.8); this._drawTexts(sideLayer("SilkS"), C.silk, P); }

    // parts already placed: a faint blue box
    ctx.lineJoin = "round";
    if (C.placedFill) {
      for (const f of m.footprints) {
        if (!this.placed.has(f.ref) || !this._seen(f)) continue;
        const [x0, y0, x1, y1] = f.bbox, pad = 0.3;
        path([x0 - pad, y0 - pad, x1 + pad, y0 - pad, x1 + pad, y1 + pad, x0 - pad, y1 + pad], true);
        ctx.fillStyle = C.placedFill;
        ctx.fill();
        ctx.strokeStyle = C.placed;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }

    // the parts being looked for
    for (const f of m.footprints) {
      if (!this.highlighted.has(f.ref) || !this._seen(f)) continue;
      const [x0, y0, x1, y1] = f.bbox, pad = 0.4;
      const pts = [x0 - pad, y0 - pad, x1 + pad, y0 - pad, x1 + pad, y1 + pad, x0 - pad, y1 + pad];
      path(pts, true);
      ctx.fillStyle = C.hiFill;
      ctx.fill();
      ctx.strokeStyle = C.hi;
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // reference names
    const labelAll = this.show.refs;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const f of m.footprints) {
      const hi = this.highlighted.has(f.ref) && this._seen(f);
      if (!hi && !labelAll) continue;
      if (!this._seen(f)) continue;
      const [sx, sy] = P((f.bbox[0] + f.bbox[2]) / 2, (f.bbox[1] + f.bbox[3]) / 2);
      const size = (this.labelScale || 1) * Math.max(9, Math.min(15, (Math.min(f.bbox[2] - f.bbox[0], f.bbox[3] - f.bbox[1]) * this.scale) * 0.7));
      ctx.font = `600 ${hi ? Math.max(12, size) : size}px sans-serif`;
      ctx.fillStyle = hi ? "#000" : C.label;
      if (hi || this.colors) {                       // a halo keeps the name readable over pads and silkscreen
        ctx.lineJoin = "round";
        ctx.lineWidth = (hi ? 3 : 4) * (this.labelScale || 1);
        ctx.strokeStyle = hi ? C.hi : "#ffffff";
        ctx.strokeText(f.ref, sx, sy);
      }
      ctx.fillText(f.ref, sx, sy);
    }
  }
}
