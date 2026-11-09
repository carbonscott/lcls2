// Renderer of the pyqtgraph sequence plots (psdaq/webgui/plots_api.py): one SVG panel per PlotItem, the curves
// PatternWaveform.add drew, pan by drag, zoom by wheel (about the cursor, both axes, as a pyqtgraph ViewBox),
// double-click for the whole range; x ranges follow setXLink.
'use strict';
const GUI = document.body.dataset.gui;
const W = 900, H = 200, ML = 70, MB = 24, MT = 8, MR = 10;
const P = [];          // panels: {rec, svg, view: {x0, x1, y0, y1}, full}
const NS = 'http://www.w3.org/2000/svg';
function sv(tag, attrs) { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; }
function fullRange(rec) {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const c of rec.curves) { for (const v of c.x) { x0 = Math.min(x0, v); x1 = Math.max(x1, v); }
                                for (const v of c.y) { y0 = Math.min(y0, v); y1 = Math.max(y1, v); } }
  if (!isFinite(x0)) { x0 = 0; x1 = 1; }
  if (x1 === x0) { x0 -= 0.5; x1 += 0.5; }
  if (rec.y_range) { [y0, y1] = rec.y_range; }                     // q0.setRange(yRange=[ymin-0.5, ymax+0.5])
  if (!isFinite(y0)) { y0 = 0; y1 = 1; }
  if (y1 === y0) { y0 -= 0.5; y1 += 0.5; }
  return { x0, x1, y0, y1 };
}
function draw(p) {
  const { svg, rec, view: v } = p; svg.replaceChildren();
  const sx = (x) => ML + (x - v.x0) / (v.x1 - v.x0) * (W - ML - MR), sy = (y) => MT + (v.y1 - y) / (v.y1 - v.y0) * (H - MT - MB);
  const clip = sv('clipPath', { id: 'clip' + P.indexOf(p) }); clip.append(sv('rect', { x: ML, y: MT, width: W - ML - MR, height: H - MT - MB }));
  svg.append(clip, sv('rect', { x: ML, y: MT, width: W - ML - MR, height: H - MT - MB, fill: 'white', stroke: '#888' }));
  const g = sv('g', { 'clip-path': `url(#clip${P.indexOf(p)})` });
  const scale = rec.x_scale || 1;
  for (let k = 0; k <= 5; k++) {                                   // ticks (and grid, q0.showGrid(True, True))
    const x = v.x0 + (v.x1 - v.x0) * k / 5, y = v.y0 + (v.y1 - v.y0) * k / 5;
    if (rec.grid && rec.grid[0]) g.append(sv('line', { x1: sx(x), x2: sx(x), y1: MT, y2: H - MB, stroke: '#ddd' }));
    if (rec.grid && rec.grid[1]) g.append(sv('line', { x1: ML, x2: W - MR, y1: sy(y), y2: sy(y), stroke: '#ddd' }));
    const tx = sv('text', { x: sx(x), y: H - 8, 'font-size': 10, 'text-anchor': 'middle' }); tx.textContent = +(x * scale).toPrecision(6); svg.append(tx);
    const ty = sv('text', { x: ML - 4, y: sy(y) + 3, 'font-size': 10, 'text-anchor': 'end' }); ty.textContent = +y.toPrecision(5); svg.append(ty);
  }
  for (const c of rec.curves) {
    if (c.pen) {
      const pts = c.x.map((x, i) => `${sx(x).toFixed(1)},${sy(c.y[i]).toFixed(1)}`).join(' ');
      g.append(sv('polyline', { points: pts, fill: 'none', stroke: c.pen.color, 'stroke-width': c.pen.width || 1 }));
    }
    if (c.symbol) {
      const s = Math.max(2, c.size || 7);
      c.x.forEach((x, i) => g.append(sv('rect', { x: sx(x) - s / 2, y: sy(c.y[i]) - s / 2, width: s, height: s,
                                                    fill: c.brush ? `rgb(${c.brush.join(',')})` : '#646464', stroke: '#646464' })));
    }
  }
  svg.append(g);
  const lab = sv('text', { x: 14, y: H / 2, 'font-size': 11, transform: `rotate(-90 14 ${H / 2})`, 'text-anchor': 'middle' });
  lab.textContent = rec.label || ''; svg.append(lab);
  Object.assign(svg.parentElement.dataset, { x0: v.x0, x1: v.x1, y0: v.y0, y1: v.y1 });
}
function linked(p) { const i = P.indexOf(p), root = p.rec.x_link === null || p.rec.x_link === undefined ? i : p.rec.x_link;
  return P.filter((q, j) => j === root || q.rec.x_link === root); }
function setX(p, x0, x1) { for (const q of linked(p)) { q.view.x0 = x0; q.view.x1 = x1; draw(q); } }
function panel(rec, i) {
  const box = document.createElement('div'); box.className = 'plotpanel'; box.dataset.parity = rec.id; box.dataset.index = i;
  box.dataset.curves = rec.curves.length; box.dataset.points = rec.curves.reduce((n, c) => n + c.x.length, 0);
  const svg = sv('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}` }); box.append(svg);
  const p = { rec, svg, full: fullRange(rec) }; p.view = { ...p.full }; P.push(p);
  const dataX = (ev) => { const r = svg.getBoundingClientRect(); return p.view.x0 + (ev.clientX - r.left - ML) / (W - ML - MR) * (p.view.x1 - p.view.x0); };
  const dataY = (ev) => { const r = svg.getBoundingClientRect(); return p.view.y1 - (ev.clientY - r.top - MT) / (H - MT - MB) * (p.view.y1 - p.view.y0); };
  svg.addEventListener('wheel', (ev) => { ev.preventDefault(); const f = ev.deltaY > 0 ? 1.25 : 0.8, x = dataX(ev), y = dataY(ev);
    p.view.y0 = y - (y - p.view.y0) * f; p.view.y1 = y + (p.view.y1 - y) * f;
    setX(p, x - (x - p.view.x0) * f, x + (p.view.x1 - x) * f); });
  let drag = null;
  svg.addEventListener('mousedown', (ev) => { drag = { x: ev.clientX, y: ev.clientY, v: { ...p.view } }; });
  window.addEventListener('mouseup', () => { drag = null; });
  svg.addEventListener('mousemove', (ev) => { if (!drag) return;
    const dx = (ev.clientX - drag.x) / (W - ML - MR) * (drag.v.x1 - drag.v.x0), dy = (ev.clientY - drag.y) / (H - MT - MB) * (drag.v.y1 - drag.v.y0);
    p.view.y0 = drag.v.y0 + dy; p.view.y1 = drag.v.y1 + dy; setX(p, drag.v.x0 - dx, drag.v.x1 - dx); });
  svg.addEventListener('dblclick', () => { p.view = { ...p.full }; setX(p, p.full.x0, p.full.x1); });   // autoRange
  return box;
}
(async () => {
  const spec = await (await fetch('/api/plots/spec?gui=' + encodeURIComponent(GUI))).json();
  if (!spec.ok) { document.getElementById('statusbar').textContent = spec.err_info; return; }
  document.getElementById('argv').textContent = spec.argv.join(' ');
  const page = document.getElementById('page');
  spec.plots.forEach((rec, i) => { rec.id = 'PatternWaveform.add.q0[' + rec.label + ']'; page.append(panel(rec, i)); });
  P.forEach(draw);
  document.body.dataset.ready = '1';
})();
