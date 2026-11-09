// Web copy of pyqtgraph plot panels (psdaq/webgui/plots_api.py runs the PyQt program's own plotting code with Qt
// stood in and serves what it asked of each PlotItem).  Each panel is a port of the pyqtgraph 0.13.7 code a user
// drives: the ViewBox (auto range with its padding and pixel padding, X link, mouse pan / wheel zoom, invert), the
// PlotDataItem display pipeline (FFT, dy/dx, Y vs Y', log, clip to view, downsampling) and the context menu the right
// button opens: View All, the X / Y axis panels (ViewBoxMenu, axisCtrlTemplate) and Plot Options (PlotItem's
// plotConfigTemplate: Transforms, Downsample, Average, Alpha, Grid, Points).  Each menu control is a model of its Qt
// widget (value, enabled, the signals Qt emits) wired to the same handlers as in pyqtgraph; data-parity = its row id.
// window.PLOTS.snapshot(i) is the panel's state in the shape of parity/pg_walk.pg_state.
'use strict';
const GUI = document.body.dataset.gui;
const ML = 64, MR = 12, MT = 8, MB = 28;          // margins around the plot area (the ViewBox)
const P = [];
const LOG = [];
const esc = (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
function tag(name, attrs, body) {
  return '<' + name + Object.entries(attrs).map(([k, v]) => ` ${k}="${esc(v)}"`).join('') + '>' + (body || '') + '</' + name + '>';
}
class PyError extends Error { constructor(type, msg) { super(type + ': ' + msg); this.pytype = type; } }
const clip = (v, a, b) => Math.min(Math.max(v, a), b);
const fin = Number.isFinite;

// ------------------------------------------------------------------ numeric helpers (numpy semantics)
function fmtG(v, prec = 5) {                       // Python '%0.<prec>g'
  if (!fin(v)) return v !== v ? 'nan' : (v > 0 ? 'inf' : '-inf');
  if (v === 0) return Object.is(v, -0) ? '-0' : '0';
  const e = Math.floor(Math.log10(Math.abs(v)));
  let s;
  let exp = Number(Math.abs(v).toExponential(prec - 1).split('e')[1]);
  if (exp < -4 || exp >= prec) {
    s = v.toExponential(prec - 1);
    let [m, x] = s.split('e');
    if (m.includes('.')) m = m.replace(/0+$/, '').replace(/\.$/, '');
    const xs = Number(x);
    s = m + 'e' + (xs < 0 ? '-' : '+') + String(Math.abs(xs)).padStart(2, '0');
  } else {
    s = v.toFixed(Math.max(0, prec - 1 - exp));
    if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '');
  }
  void e;
  return s;
}
function nanmin(a) { let m = NaN; for (const v of a) if (v === v && !(v >= m)) m = v; return m; }
function nanmax(a) { let m = NaN; for (const v of a) if (v === v && !(v <= m)) m = v; return m; }
function percentile(d, q) {                        // numpy.percentile, linear interpolation
  const s = Float64Array.from(d).sort(), n = s.length, i = q / 100 * (n - 1), lo = Math.floor(i), hi = Math.ceil(i);
  return lo === hi ? s[lo] : s[lo] + (s[hi] - s[lo]) * (i - lo);
}
function bisectLeft(a, x) { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] < x) lo = m + 1; else hi = m; } return lo; }
function diff(a) { const o = new Float64Array(Math.max(0, a.length - 1)); for (let i = 0; i + 1 < a.length; i++) o[i] = a[i + 1] - a[i]; return o; }
function searchGuess(key, arr, guess) {                       // numpy binary_search_with_guess (xp need not be sorted)
  const len = arr.length;
  let imin = 0, imax = len;
  if (key > arr[len - 1]) return len;
  if (key < arr[0]) return -1;
  if (len <= 4) { let i = 1; for (; i < len && key >= arr[i]; ++i); return i - 1; }
  if (guess > len - 3) guess = len - 3;
  if (guess < 1) guess = 1;
  if (key < arr[guess]) {
    if (key < arr[guess - 1]) { imax = guess - 1; if (guess > 8 && key >= arr[guess - 8]) imin = guess - 8; }
    else return guess - 1;
  } else {
    if (key < arr[guess + 1]) return guess;
    if (key < arr[guess + 2]) return guess + 1;
    imin = guess + 2;
    if (guess < len - 8 - 1 && key < arr[guess + 8]) imax = guess + 8;
  }
  while (imin < imax) { const m = imin + ((imax - imin) >> 1); if (key >= arr[m]) imin = m + 1; else imax = m; }
  return imin - 1;
}
function interp(xs, xp, fp) {                                   // numpy.interp (compiled_base.c arr_interp)
  const n = xp.length, out = new Float64Array(xs.length), lval = fp[0], rval = fp[n - 1];
  if (n === 1) { for (let i = 0; i < xs.length; i++) out[i] = xs[i] < xp[0] ? lval : xs[i] > xp[0] ? rval : fp[0]; return out; }
  const slopes = new Float64Array(n - 1);
  for (let i = 0; i < n - 1; i++) slopes[i] = (fp[i + 1] - fp[i]) / (xp[i + 1] - xp[i]);
  let j = 0;
  for (let i = 0; i < xs.length; i++) {
    const x = xs[i];
    if (x !== x) { out[i] = x; continue; }
    j = searchGuess(x, xp, j);
    if (j === -1) out[i] = lval;
    else if (j === n) out[i] = rval;
    else if (j === n - 1) out[i] = fp[j];
    else if (xp[j] === x) out[i] = fp[j];
    else {
      const sl = slopes[j];
      out[i] = sl * (x - xp[j]) + fp[j];
      if (out[i] !== out[i]) { out[i] = sl * (x - xp[j + 1]) + fp[j + 1]; if (out[i] !== out[i] && fp[j] === fp[j + 1]) out[i] = fp[j]; }
    }
  }
  return out;
}
function linspace(a, b, n) {                                    // numpy.linspace(a, b, n): i * step + a, last = b
  const o = new Float64Array(n), step = (b - a) / (n - 1);
  for (let i = 0; i < n; i++) o[i] = i * step + a;
  if (n > 1) o[n - 1] = b;
  return o;
}
function fourier(x, y) {                           // PlotDataItem._fourierTransform
  const dx = diff(x);
  if (!dx.length) throw new PyError('IndexError', 'index 0 is out of bounds for axis 0 with size 0');
  let uniform = true;
  for (const v of dx) if (Math.abs(v - dx[0]) > Math.abs(dx[0]) / 1000) { uniform = false; break; }
  if (!uniform) { const x2 = linspace(x[0], x[x.length - 1], x.length); y = interp(x2, x, y); x = x2; }
  const n = y.length, m = Math.floor(n / 2) + 1, re = new Float64Array(m), im = new Float64Array(m);
  for (let k = 0; k < m; k++) { let a = 0, b = 0; for (let j = 0; j < n; j++) { const t = -2 * Math.PI * k * j / n; a += y[j] * Math.cos(t); b += y[j] * Math.sin(t); } re[k] = a / n; im[k] = b / n; }
  const d = (x[x.length - 1] - x[0]) / (x.length - 1);
  if (n * d === 0) throw new PyError('ZeroDivisionError', 'float division by zero');
  const fx = Float64Array.from({ length: m }, (_, k) => k / (n * d));
  return [fx, Float64Array.from({ length: m }, (_, k) => Math.hypot(re[k], im[k]))];
}

// ------------------------------------------------------------------ Qt widget models (value, enabled, signals)
class QW {
  constructor(p, ctl, kind, o = {}) {
    Object.assign(this, { p, ctl, kind, own: true, group: null, handlers: {}, el: null }, o);
    p.w[ctl] = this;
  }
  on(sig, fn) { (this.handlers[sig] = this.handlers[sig] || []).push(fn); }
  emit(sig, ...a) {                                // a Python exception in a slot is printed; Qt carries on
    for (const fn of this.handlers[sig] || []) {
      try { fn(...a); } catch (e) { LOG.push(`${this.ctl}.${sig}: ${e.message}`); console.warn(e); if (!(e instanceof PyError)) throw e; }
    }
  }
  enabled() { return this.own && (!this.group || this.p.w[this.group].value === true); }
  setChecked(v) {
    if (this.kind === 'radio') {
      if (this.value === v) return;
      if (!v) return;                              // an auto-exclusive radio cannot be unchecked
      this.value = true;
      const other = this.peers.map((c) => this.p.w[c]).find((w) => w !== this && w.value);
      if (other) { other.value = false; other.emit('toggled', false); }
      this.emit('toggled', true);
    } else if (this.value !== v) {
      this.value = v; this.emit('toggled', v);
    }
    render(this.p);
  }
  click() {                                        // QAbstractButton.click (a user's click)
    if (!this.enabled()) return;
    if (this.kind === 'radio') { if (!this.value) this.setChecked(true); } else this.setChecked(!this.value);
    this.emit('clicked', this.value);
    render(this.p);
  }
  setValue(v) {
    v = clip(Math.trunc(v), this.min, this.max);
    if (v === this.value) return;
    this.value = v; this.emit('valueChanged', v); render(this.p);
  }
  setText(t) { this.value = String(t); }
  setCurrentIndex(i) { if (i === this.value.index) return; this.value = { ...this.value, index: i }; this.emit('currentIndexChanged', i); }
  state() {
    if (this.kind === 'combo') return { index: this.value.index, items: this.value.items.slice() };
    if (this.kind === 'list') return this.value.slice();
    return this.value;
  }
}

// ------------------------------------------------------------------ a panel: PlotItem + ViewBox + its PlotDataItems
const AXW = ['label', 'linkCombo', 'autoPercentSpin', 'autoRadio', 'manualRadio', 'minText', 'maxText', 'invertCheck',
             'mouseCheck', 'visibleOnlyCheck', 'autoPanCheck'];
const CTRLW = ['averageGroup', 'avgParamList', 'clipToViewCheck', 'maxTracesCheck', 'downsampleCheck', 'peakRadio',
               'maxTracesSpin', 'forgetTracesCheck', 'meanRadio', 'subsampleRadio', 'autoDownsampleCheck', 'downsampleSpin',
               'logYCheck', 'logXCheck', 'fftCheck', 'derivativeCheck', 'phasemapCheck', 'pointsGroup', 'autoPointsCheck',
               'xGridCheck', 'yGridCheck', 'gridAlphaSlider', 'label', 'alphaGroup', 'autoAlphaCheck', 'alphaSlider'];
const CONTROLS = AXW.map((n) => 'xaxis.' + n).concat(AXW.map((n) => 'yaxis.' + n), CTRLW.map((n) => 'ctrl.' + n));

function newPanel(i, W, H) {
  const p = { i, W, H, w: {}, curves: [], items: [], avgCurves: new Map(), open: new Set(), menuValid: true,
              vb: { tr: [[0, 1], [0, 1]], vr: [[0, 1], [0, 1]], autoRange: [1.0, 1.0], autoPan: [false, false],
                    autoVisibleOnly: [false, false], mouseEnabled: [true, true], xInverted: false, yInverted: false,
                    logMode: [false, false], needsUpdate: false, updating: false, linked: [null, null],
                    defaultPadding: 0.02 },
              axes: { bottom: { grid: false, logMode: false }, left: { grid: false, logMode: false } } };
  for (const ax of ['xaxis', 'yaxis']) {                        // axisCtrlTemplate
    const g = ax + '.';
    new QW(p, g + 'label', 'label', { value: 'Link Axis:' });
    new QW(p, g + 'linkCombo', 'combo', { value: { index: 0, items: [''] } });
    new QW(p, g + 'autoPercentSpin', 'spin', { value: 100, min: 1, max: 100, suffix: '%' });
    new QW(p, g + 'autoRadio', 'radio', { value: true, peers: [g + 'autoRadio', g + 'manualRadio'] });
    new QW(p, g + 'manualRadio', 'radio', { value: false, peers: [g + 'autoRadio', g + 'manualRadio'] });
    new QW(p, g + 'minText', 'line', { value: '0' });
    new QW(p, g + 'maxText', 'line', { value: '0' });
    new QW(p, g + 'invertCheck', 'check', { value: false });
    new QW(p, g + 'mouseCheck', 'check', { value: true });
    new QW(p, g + 'visibleOnlyCheck', 'check', { value: false });
    new QW(p, g + 'autoPanCheck', 'check', { value: false });
  }
  const c = 'ctrl.', dsr = [c + 'peakRadio', c + 'meanRadio', c + 'subsampleRadio'];   // plotConfigTemplate
  new QW(p, c + 'averageGroup', 'group', { value: false, title: 'Average' });
  new QW(p, c + 'avgParamList', 'list', { value: [], group: c + 'averageGroup' });
  new QW(p, c + 'clipToViewCheck', 'check', { value: false });
  new QW(p, c + 'maxTracesCheck', 'check', { value: false });
  new QW(p, c + 'downsampleCheck', 'check', { value: false });
  new QW(p, c + 'peakRadio', 'radio', { value: true, peers: dsr });
  new QW(p, c + 'maxTracesSpin', 'spin', { value: 0, min: 0, max: 99, suffix: '' });
  new QW(p, c + 'forgetTracesCheck', 'check', { value: false });
  new QW(p, c + 'meanRadio', 'radio', { value: false, peers: dsr });
  new QW(p, c + 'subsampleRadio', 'radio', { value: false, peers: dsr });
  new QW(p, c + 'autoDownsampleCheck', 'check', { value: true });
  new QW(p, c + 'downsampleSpin', 'spin', { value: 1, min: 1, max: 100000, suffix: 'x' });
  for (const n of ['logYCheck', 'logXCheck', 'fftCheck', 'derivativeCheck', 'phasemapCheck']) new QW(p, c + n, 'check', { value: false });
  new QW(p, c + 'pointsGroup', 'group', { value: true, title: 'Points' });
  new QW(p, c + 'autoPointsCheck', 'check', { value: true, group: c + 'pointsGroup' });
  new QW(p, c + 'xGridCheck', 'check', { value: false });
  new QW(p, c + 'yGridCheck', 'check', { value: false });
  new QW(p, c + 'gridAlphaSlider', 'slider', { value: 128, min: 0, max: 255 });
  new QW(p, c + 'label', 'label', { value: 'Opacity' });
  new QW(p, c + 'alphaGroup', 'group', { value: true, title: 'Alpha' });
  new QW(p, c + 'autoAlphaCheck', 'check', { value: false, group: c + 'alphaGroup' });
  new QW(p, c + 'alphaSlider', 'slider', { value: 1000, min: 0, max: 1000, group: c + 'alphaGroup' });
  wireMenus(p);
  updateMenuState(p);                                           // ViewBoxMenu.__init__ ends with updateState()
  return p;
}
const W_ = (p, n) => p.w[n];

// ------------------------------------------------------------------ PlotDataItem
function newCurve(rec) {
  return { x0: Float64Array.from(rec.x), y0: Float64Array.from(rec.y), pen: rec.pen || null, shadowPen: rec.shadowPen || null,
           symbol: rec.symbol || null, symbolSize: rec.symbolSize == null ? 10 : rec.symbolSize,
           symbolPenWidth: rec.symbolPenWidth == null ? 1 : rec.symbolPenWidth, brush: rec.brush || null,
           o: { fft: false, logMode: [false, false], deriv: false, phase: false, ds: 1, autoDs: false, dsMethod: 'peak',
                clip: false, alphaHint: 1.0, alphaMode: false },
           visible: true, isAvg: false, drawn: null, sb: [null, null], meta: rec.meta || {},
           xInt: !!rec.x_int, yInt: !!rec.y_int,                // numpy int arrays: PlotDataset takes them as all finite
           disp: null, xvChanged: false, yvChanged: false, drlLast: [0.0, 0.0] };
}
function mapped(c) {                                            // the mapping part of _getDisplayDataset
  let x = c.x0, y = c.y0;
  if (c.o.fft) { [x, y] = fourier(x, y); if (c.o.logMode[0]) { x = x.slice(1); y = y.slice(1); } }
  if (c.o.deriv) { const dy = diff(c.y0), dx = diff(c.x0); y = dy.map((v, i) => v / dx[i]); x = x.slice(0, x.length - 1); }
  if (c.o.phase) { const dy = diff(c.y0), dx = diff(c.x0); x = c.y0.slice(0, c.y0.length - 1); y = dy.map((v, i) => v / dx[i]); }
  let xf = c.xInt ? true : null, yf = c.yInt ? true : null;     // PlotDataset(x, y, dataset.xAllFinite, ...)
  if (c.o.deriv || c.o.phase) { if (c.o.phase) xf = c.yInt ? true : xf; }
  if (c.o.logMode[0]) { x = x.map((v) => { const l = Math.log10(v); return fin(l) ? l : NaN; }); xf = x.every(fin); }
  if (c.o.logMode[1]) { y = y.map((v) => { const l = Math.log10(v); return fin(l) ? l : NaN; }); yf = y.every(fin); }
  return { x: Float64Array.from(x), y: Float64Array.from(y), xf, yf };
}
function arrayBounds(a, allFinite) {                            // PlotDataset._getArrayBounds (np.min / np.max)
  const v = allFinite ? a : a.filter(fin);
  if (!v.length) return [NaN, NaN];                             // ValueError: no finite values
  let mn = Infinity, mx = -Infinity;
  for (const t of v) { if (t !== t) return [NaN, NaN]; if (t < mn) mn = t; if (t > mx) mx = t; }
  return [mn, mx];
}
function display(p, c) {                                        // PlotDataItem._getDisplayDataset (may raise)
  if (!c.x0.length && !c.y0.length) return { x: new Float64Array(0), y: new Float64Array(0) };   // no dataset
  if (c.disp && !(c.xvChanged && c.o.clip) && !(c.xvChanged && c.o.autoDs) && !c.yvChanged) return c.disp;
  const m = mapped(c);
  let x = m.x, y = m.y, ds = c.o.ds;
  const vr = p.vb.vr;
  if (c.o.autoDs) {
    const fx = m.xf === true ? x : x.filter(fin);
    if (fx.length > 1) {
      const dx = (fx[fx.length - 1] - fx[0]) / (fx.length - 1);
      if (dx !== 0 && p.W !== 0) { const f = Math.max(1.0, Math.abs((vr[0][1] - vr[0][0]) / dx / (p.W * 5.0))); if (fin(f)) ds = Math.trunc(f); }
    }
  }
  if (c.o.clip && p.vb.autoRange[0] === false && x.length > 1) {
    const x0 = clip(bisectLeft(x, vr[0][0]) - ds, 0, x.length), x1 = clip(bisectLeft(x, vr[0][1]) + ds, x0, x.length);
    x = x.slice(x0, x1); y = y.slice(x0, x1);
  }
  if (ds > 1) {
    if (c.o.dsMethod === 'subsample') { x = x.filter((_, i) => i % ds === 0); y = y.filter((_, i) => i % ds === 0); }
    else {
      const n = Math.floor(x.length / ds), st = Math.floor(ds / 2), nx = [], ny = [];
      for (let k = 0; k < n; k++) {
        const seg = y.slice(k * ds, k * ds + ds);
        if (c.o.dsMethod === 'mean') { nx.push(x[st + k * ds]); ny.push(seg.reduce((a, b) => a + b, 0) / ds); }
        else { nx.push(x[st + k * ds], x[st + k * ds]); ny.push(Math.max(...seg), Math.min(...seg)); }
      }
      x = Float64Array.from(nx); y = Float64Array.from(ny);
    }
  }
  const vh = vr[1][1] - vr[1][0], L = 1e6, hy = 3.0;              // dynamicRangeLimit 1e6, dynamicRangeHyst 3
  const [ymn, ymx] = arrayBounds(m.y, m.yf === true);           // _datasetMapped.dataRect(): its y extent
  if (vh > 0 && !(ymx < vr[1][0]) && !(ymn > vr[1][1]) && (ymx - ymn) > 2 * hy * L * vh) {
    let good = false;
    if (c.disp) {
      const top = -(c.drlLast[0] - vr[1][1]) / vh, bot = (c.drlLast[1] - vr[1][0]) / vh;
      if (top >= L / hy && top <= L * hy && bot >= L / hy && bot <= L * hy) { x = c.disp.x; y = c.disp.y; good = true; }
    }
    if (!good) {
      const lo = vr[1][1] - L * vh, hi = vr[1][0] + L * vh;
      y = Float64Array.from(y, (v) => (v !== v ? v : Math.min(Math.max(v, lo), hi)));
      c.drlLast = [lo, hi];
    }
  }
  c.disp = { x, y }; c.xvChanged = false; c.yvChanged = false;
  return c.disp;
}
function invalidate(c) { c.disp = null; }
function updateItems(p, c) {                                    // PlotDataItem.updateItems: what its curve / scatter hold
  c.drawn = display(p, c);
  c.sb = [null, null];
  informBounds(p);                                              // their setData informs the ViewBox
}
function informBounds(p) { if (p.vb.autoRange[0] !== false || p.vb.autoRange[1] !== false) p.vb.needsUpdate = true; }
function setCurveOpt(p, c, k, v) {                              // setFftMode / setDerivativeMode / setPhasemapMode / setLogMode
  if (JSON.stringify(c.o[k]) === JSON.stringify(v)) return;
  c.o[k] = v; invalidate(c); updateItems(p, c); informBounds(p);
}
function setDownsampling(p, c, ds, auto, method) {
  let ch = false;
  if (c.o.ds !== ds) { c.o.ds = ds; ch = true; }
  if (c.o.autoDs !== auto) { c.o.autoDs = auto; ch = true; }
  if (c.o.dsMethod !== method) { c.o.dsMethod = method; ch = true; }
  if (ch) { invalidate(c); updateItems(p, c); }
}
function setClipToView(p, c, v) { if (c.o.clip === v) return; c.o.clip = v; invalidate(c); updateItems(p, c); }
function setAlpha(c, a, auto) { c.o.alphaHint = a; c.o.alphaMode = auto; }
function dataBounds(c, ax, frac, ortho) {                       // PlotDataItem.dataBounds -> curve / scatter
  if (!c.drawn) return [null, null];
  const d = ax === 0 ? c.drawn.x : c.drawn.y, d2 = ax === 0 ? c.drawn.y : c.drawn.x;
  if (c.pen) {
    let v = d;
    if (ortho) v = v.filter((_, i) => d2[i] >= ortho[0] && d2[i] <= ortho[1]);
    if (!v.length) return [null, null];
    if (frac >= 1.0) {
      let b = [nanmin(v), nanmax(v)];
      if (!fin(b[0]) && b[0] === b[0] || !fin(b[1]) && b[1] === b[1]) { const f = v.filter(fin); if (!f.length) return [null, null]; b = [Math.min(...f), Math.max(...f)]; }
      return b;
    }
    const f = v.filter(fin); if (!f.length) return [null, null];
    return [percentile(f, 50 * (1 - frac)), percentile(f, 50 * (1 + frac))];
  }
  if (c.symbol) {                                               // ScatterPlotItem.dataBounds (its bounds cache too)
    if (frac >= 1.0 && !ortho && c.sb[ax]) return c.sb[ax];
    let v = d;
    if (ortho) { v = v.filter((_, i) => d2[i] >= ortho[0] && d2[i] <= ortho[1]); if (!v.length) return [null, null]; }
    if (!v.length) return [null, null];
    if (frac >= 1.0) { c.sb[ax] = [nanmin(v), nanmax(v)]; return c.sb[ax]; }
    return [percentile(v.filter(fin), 50 * (1 - frac)), percentile(v.filter(fin), 50 * (1 + frac))];
  }
  return [null, null];
}
function pixelPadding(c) {
  if (!c.x0.length && !c.y0.length) return 0;                   // no dataset: its curve and scatter are hidden
  if (c.pen) return Math.max(c.pen.width * 0.7072, c.shadowPen ? c.shadowPen.width * 0.7072 : 0);
  if (c.symbol) return (c.symbolSize + c.symbolPenWidth) * 0.7072;
  return 0;
}

// ------------------------------------------------------------------ ViewBox
function suggestPadding(p, ax) {
  const l = ax === 0 ? p.W : p.H, d = p.vb.defaultPadding;
  return l > 0 ? clip(50 * d / Math.sqrt(l), d, Math.max(0.1, d)) : d;
}
const axisShown = (p) => p.menu && !p.menu.hidden && (p.open.has('xaxis') || p.open.has('yaxis'));
function stateChanged(p) {                                      // sigStateChanged -> ViewBoxMenu.viewStateChanged
  p.menuValid = false;
  if (axisShown(p)) updateMenuState(p);                         // (only while an axis panel is on screen)
}
function enableAutoRange(p, axis, enable) {
  if (enable === true) enable = 1.0;
  for (const ax of axis === null ? [0, 1] : [axis]) {
    if (p.vb.autoRange[ax] !== enable) {
      if (enable === false && p.vb.needsUpdate) updateAutoRange(p);
      p.vb.autoRange[ax] = enable;
      p.vb.needsUpdate = p.vb.needsUpdate || enable !== false;
    }
  }
  stateChanged(p);
}
function effectiveLimits(p) {                                   // ViewBox._effectiveLimits (log mode: a double's range)
  return [0, 1].map((ax) => p.vb.logMode[ax] ? [Math.max(-1e307, -307.6), Math.min(1e307, 308.2)] : [-1e307, 1e307]);
}
function setRange(p, ranges, padding = null, disableAutoRange = true) {   // ranges: {0: [a, b], 1: [a, b]}
  const changed = [false, false], limits = effectiveLimits(p);
  if (disableAutoRange) {
    const xo = 0 in ranges ? false : null, yo = 1 in ranges ? false : null;
    if (xo !== null) enableAutoRange(p, 0, false);
    if (yo !== null) enableAutoRange(p, 1, false);
    changed.push(true);
  }
  for (const ax of Object.keys(ranges).map(Number)) {
    let mn = Math.min(...ranges[ax]), mx = Math.max(...ranges[ax]), preserve = false;
    if (mn === mx) { preserve = true; let dy = p.vb.vr[ax][1] - p.vb.vr[ax][0]; if (dy === 0) dy = 1; mn -= dy * 0.5; mx += dy * 0.5; }
    const q = (mn + mx) * 1.5e-15;
    if (mx - mn < 2 * q) { mn -= q; mx += q; }
    if (!fin(mn) || !fin(mx)) throw new PyError('Exception', `Cannot set range [${mn}, ${mx}]`);
    if (!preserve) { const pad = padding === null ? suggestPadding(p, ax) : padding, d = (mx - mn) * pad; mn -= d; mx += d; }
    const lim = limits[ax], maxRng = lim[1] - lim[0];             // ViewBox limits (xLimits [-1e307, 1e307])
    if (mx - mn > maxRng) { const d = maxRng - (mx - mn); mn -= d / 2; mx += d / 2; }
    if (mn < lim[0]) { const d = lim[0] - mn; mn = lim[0]; mx += d; }
    else if (mx > lim[1]) { const d = lim[1] - mx; mx = lim[1]; mn += d; }
    if (p.vb.tr[ax][0] !== mn || p.vb.tr[ax][1] !== mx) { p.vb.tr[ax] = [mn, mx]; changed[ax] = true; }
  }
  updateViewRange(p);
  if (changed.some(Boolean)) {
    if (changed[0] && p.vb.autoVisibleOnly[1] && p.vb.autoRange[0] !== false) p.vb.needsUpdate = true;
    else if (changed[1] && p.vb.autoVisibleOnly[0] && p.vb.autoRange[1] !== false) p.vb.needsUpdate = true;
    stateChanged(p);
  }
}
function updateViewRange(p) {
  const vr = [p.vb.tr[0].slice(), p.vb.tr[1].slice()], limits = effectiveLimits(p);
  for (const ax of [0, 1]) {                                    // the view obeys the limits
    const lim = limits[ax], maxRng = lim[1] - lim[0];
    if (maxRng < vr[ax][1] - vr[ax][0]) { vr[ax][1] = vr[ax][0] + maxRng; p.vb.tr[ax] = vr[ax].slice(); }
    if (vr[ax][0] < lim[0]) { const d = lim[0] - vr[ax][0]; vr[ax][0] += d; vr[ax][1] += d; p.vb.tr[ax] = vr[ax].slice(); }
    if (vr[ax][1] > lim[1]) { const d = vr[ax][1] - lim[1]; vr[ax][0] -= d; vr[ax][1] -= d; p.vb.tr[ax] = vr[ax].slice(); }
  }
  const th = [0, 1].map((a) => (vr[a][1] - vr[a][0]) * 1e-9);
  const changed = [0, 1].map((a) => Math.abs(vr[a][0] - p.vb.vr[a][0]) > th[a] || Math.abs(vr[a][1] - p.vb.vr[a][1]) > th[a]);
  p.vb.vr = vr;
  if (changed.some(Boolean)) {
    for (const ax of [0, 1]) {                                  // inform the view this one links to
      const t = p.vb.linked[ax];
      if (changed[ax] && t !== null) linkedViewChanged(P[t], p, ax);
    }
    for (const ax of [0, 1]) if (changed[ax]) emitRangeChanged(p, ax);
    viewRangeChanged(p, changed);
  }
}
function emitRangeChanged(p, ax) {                              // sigX/YRangeChanged -> the views linked to this one
  for (const q of P) if (q !== p && q.vb.linked[ax] === p.i) linkedViewChanged(q, p, ax);
}
function viewRangeChanged(p, changed) {                         // PlotDataItem.viewRangeChanged of every item
  for (const c of p.items) {
    let need = false;
    if (changed[0]) { c.xvChanged = true; if (c.o.clip || c.o.autoDs) { c.disp = null; need = true; } }
    if (changed[1]) { c.yvChanged = true; need = true; }        // dynamicRangeLimit (1e6, not None)
    if (need) { try { updateItems(p, c); } catch (e) { if (!(e instanceof PyError)) throw e; LOG.push('viewRangeChanged: ' + e.message); } }
  }
}
function linkedViewChanged(p, view, ax) {                       // panels line up pixel for pixel (same plot-area x)
  if (p.linksBlocked || !view) return;
  const r = view.vb.vr[ax];
  view.linksBlocked = true;
  try { enableAutoRange(p, ax, false); setRange(p, { [ax]: [r[0], r[1]] }, 0); }
  finally { view.linksBlocked = false; }
}
function childrenBounds(p, frac, ortho) {
  const ib = [];
  for (const c of p.items) {
    if (!c.visible) continue;
    let xr = dataBounds(c, 0, frac[0], ortho[0]), yr = dataBounds(c, 1, frac[1], ortho[1]);
    const px = pixelPadding(c);
    let useX = true, useY = true;
    if (xr === null || (xr[0] === null && xr[1] === null) || !fin(xr[0]) || !fin(xr[1])) { useX = false; xr = [0, 0]; }
    if (yr === null || (yr[0] === null && yr[1] === null) || !fin(yr[0]) || !fin(yr[1])) { useY = false; yr = [0, 0]; }
    if (!useX && !useY) continue;
    ib.push({ l: Math.min(xr[0], xr[1]), r: Math.max(xr[0], xr[1]), t: Math.min(yr[0], yr[1]), b: Math.max(yr[0], yr[1]), useX, useY, px });
  }
  const range = [null, null];
  for (const b of ib) {
    if (b.useY) range[1] = range[1] ? [Math.min(b.t, range[1][0]), Math.max(b.b, range[1][1])] : [b.t, b.b];
    if (b.useX) range[0] = range[0] ? [Math.min(b.l, range[0][0]), Math.max(b.r, range[0][1])] : [b.l, b.r];
  }
  if (p.W > 0 && range[0]) { const s = (range[0][1] - range[0][0]) / p.W;
    for (const b of ib) if (b.px && b.useX) { range[0][0] = Math.min(range[0][0], b.l - b.px * s); range[0][1] = Math.max(range[0][1], b.r + b.px * s); } }
  if (p.H > 0 && range[1]) { const s = (range[1][1] - range[1][0]) / p.H;
    for (const b of ib) if (b.px && b.useY) { range[1][0] = Math.min(range[1][0], b.t - b.px * s); range[1][1] = Math.max(range[1][1], b.b + b.px * s); } }
  return range;
}
function updateAutoRange(p) {
  const vb = p.vb;
  if (vb.updating) return;
  vb.updating = true;
  try {
    if (!vb.autoRange.some((a) => a !== false)) return;
    const target = [vb.vr[0].slice(), vb.vr[1].slice()];
    const fracs = vb.autoRange.map((a) => typeof a === 'boolean' ? 1.0 : a);
    let child = null;
    const order = vb.autoVisibleOnly[0] === true ? [1, 0] : [0, 1], args = {};
    for (const ax of order) {
      if (vb.autoRange[ax] === false) continue;
      if (vb.autoVisibleOnly[ax]) { const o = [null, null]; o[ax] = target[1 - ax]; child = childrenBounds(p, fracs, o); }
      else if (child === null) child = childrenBounds(p, fracs, [null, null]);
      const xr = child[ax];
      if (xr) {
        if (vb.autoPan[ax]) { const x = (xr[0] + xr[1]) * 0.5, w2 = (target[ax][1] - target[ax][0]) / 2; child[ax] = [x - w2, x + w2]; }
        else { const wp = (xr[1] - xr[0]) * suggestPadding(p, ax); child[ax] = [xr[0] - wp, xr[1] + wp]; }
        target[ax] = child[ax]; args[ax] = target[ax];
      }
    }
    for (const k of Object.keys(args)) if (!fin(args[k][0]) || !fin(args[k][1])) delete args[k];
    if (Object.keys(args).length) setRange(p, args, 0.0, false);
  } finally { vb.needsUpdate = false; vb.updating = false; }
}
function settle() {                                             // paints until nothing moves: each paint runs the
  for (let k = 0; k < 1000; k++) {                              // pending auto range (prepareForPaint), then a new view
    let any = false;                                            // transform informs the ViewBox (childGroup itemChange)
    for (const p of P) if (p.vb.needsUpdate) { any = true; updateAutoRange(p); }
    for (const p of P) {
      const key = JSON.stringify([p.vb.vr, p.vb.xInverted, p.vb.yInverted, p.W, p.H]);
      const flat = p.vb.vr[0][1] === p.vb.vr[0][0] || p.vb.vr[1][1] === p.vb.vr[1][0];
      if (key !== p.matrixKey && !flat) { p.matrixKey = key; informBounds(p); any = any || p.vb.needsUpdate; }
    }
    if (!any) break;
  }
}
function autoRangeAll(p) {                                      // ViewBox.autoRange (View All)
  const r = childrenBounds(p, [1.0, 1.0], [null, null]), tr = p.vb.tr;
  setRange(p, { 0: r[0] || tr[0].slice(), 1: r[1] || tr[1].slice() }, null);
}
function scaleBy(p, s, center) {
  const tr = p.vb.tr, r = {};
  for (const ax of [0, 1]) if (s[ax] !== null) r[ax] = [center[ax] + (tr[ax][0] - center[ax]) * s[ax], center[ax] + (tr[ax][1] - center[ax]) * s[ax]];
  if (Object.keys(r).length) setRange(p, r, 0);
}
function translateBy(p, t) {
  const tr = p.vb.tr, r = {};
  for (const ax of [0, 1]) if (t[ax] !== null) r[ax] = [tr[ax][0] + t[ax], tr[ax][1] + t[ax]];
  if (Object.keys(r).length) setRange(p, r, 0);
}
function setMouseEnabled(p, ax, b) { p.vb.mouseEnabled[ax] = b; stateChanged(p); }
function invertAxis(p, ax, inv) { const k = ax ? 'yInverted' : 'xInverted'; if (p.vb[k] === inv) return; p.vb[k] = inv; stateChanged(p); emitRangeChanged(p, ax); }
function setAutoPan(p, ax, b) { p.vb.autoPan[ax] = b; }
function setAutoVisible(p, ax, b) { p.vb.autoVisibleOnly[ax] = b; if (b === true) p.vb.autoVisibleOnly[1 - ax] = false; updateAutoRange(p); }

// ------------------------------------------------------------------ PlotItem: the Plot Options handlers
function alphaState(p) {
  const en = W_(p, 'ctrl.alphaGroup').value; let auto = W_(p, 'ctrl.autoAlphaCheck').value;
  let a = W_(p, 'ctrl.alphaSlider').value / 1000;
  if (auto) a = 1.0;
  if (!en) { auto = false; a = 1.0; }
  return [a, auto];
}
function downsampleMode(p) {
  const on = W_(p, 'ctrl.downsampleCheck').value, ds = on ? W_(p, 'ctrl.downsampleSpin').value : 1;
  const auto = on && W_(p, 'ctrl.autoDownsampleCheck').value;
  const m = W_(p, 'ctrl.subsampleRadio').value ? 'subsample' : W_(p, 'ctrl.meanRadio').value ? 'mean' : 'peak';
  return [ds, auto, m];
}
function addItem(p, c, skipAverage) {                           // PlotItem.addItem
  p.items.push(c); p.curves.push(c);
  informBounds(p);
  setCurveOpt(p, c, 'logMode', [W_(p, 'ctrl.logXCheck').value, W_(p, 'ctrl.logYCheck').value]);
  const [a, auto] = alphaState(p); setAlpha(c, a, auto);
  setCurveOpt(p, c, 'fft', W_(p, 'ctrl.fftCheck').value);
  const [ds, au, m] = downsampleMode(p); setDownsampling(p, c, ds, au, m);
  setClipToView(p, c, W_(p, 'ctrl.clipToViewCheck').value);
  if (c.drawn === null) updateItems(p, c);
  updateDecimation(p);
  if (W_(p, 'ctrl.averageGroup').value && !skipAverage) addAvgCurve(p, c);
}
function removeItem(p, c) {
  p.items = p.items.filter((x) => x !== c);
  if (p.curves.includes(c)) { p.curves = p.curves.filter((x) => x !== c); updateDecimation(p); }
  informBounds(p);
}
function updateDecimation(p) {
  if (!W_(p, 'ctrl.maxTracesCheck').value) return;
  const n = W_(p, 'ctrl.maxTracesSpin').value;
  if (W_(p, 'ctrl.forgetTracesCheck').value) {               // self.curves[:-numCurves] ([:-0] is empty)
    for (const c of n === 0 ? [] : p.curves.slice(0, Math.max(0, p.curves.length - n))) { c.x0 = new Float64Array(0); c.y0 = new Float64Array(0); c.drawn = null; c.cleared = true; removeItem(p, c); }
  }
  p.curves.slice().reverse().forEach((c, i) => { c.visible = i < n; });   // show / hide: no new auto range
}
function addAvgCurve(p, curve) {
  const key = '';                                               // no avgParamList entries: one average of all curves
  if (!p.avgCurves.has(key)) {
    const c = newCurve({ x: [], y: [], pen: { color: '#00c800', width: 1 }, shadowPen: { color: '#000000', width: 4 } });
    c.isAvg = true; c.drawn = { x: new Float64Array(0), y: new Float64Array(0) }; c.empty = true;
    setAlpha(c, 1.0, false);
    addItem(p, c, true);
    p.avgCurves.set(key, [0, c]);
  }
  const e = p.avgCurves.get(key); e[0] += 1;
  if (!curve.x0.length && !curve.y0.length)                     // getData() is (None, None): setData(None, None) raises
    throw new PyError('TypeError', 'When passing two unnamed arguments, both must be a list or array of values.');
  const [n, plot] = e, d = display(p, curve);
  if (!plot.empty && d.y.length === plot.y0.length) {
    setData(p, plot, plot.x0, plot.y0.map((v, i) => v * (n - 1) / n + d.y[i] * 1.0 / n));
  } else setData(p, plot, d.x, d.y);
}
function setData(p, c, x, y, xInt, yInt) {
  c.x0 = Float64Array.from(x); c.y0 = Float64Array.from(y); c.empty = false;
  if (xInt !== undefined) { c.xInt = !!xInt; c.yInt = !!yInt; }
  invalidate(c); updateItems(p, c); informBounds(p);
}
function recomputeAverages(p) {
  if (!W_(p, 'ctrl.averageGroup').value) return;
  for (const [, [, c]] of p.avgCurves) removeItem(p, c);
  p.avgCurves = new Map();
  for (let k = 0; k < p.curves.length; k++) addAvgCurve(p, p.curves[k]);     // the list grows as it goes (as in Python)
}
function wireMenus(p) {
  const on = (n, sig, fn) => W_(p, n).on(sig, fn);
  const c = 'ctrl.';
  const updateAlpha = () => { const [a, auto] = alphaState(p); for (const k of p.curves) setAlpha(k, a * a, auto); };
  for (const [n, s] of [['alphaGroup', 'toggled'], ['alphaSlider', 'valueChanged'], ['autoAlphaCheck', 'toggled']]) on(c + n, s, updateAlpha);
  const updateGrid = () => { const a = W_(p, c + 'gridAlphaSlider').value;
    p.axes.bottom.grid = W_(p, c + 'xGridCheck').value ? a : false; p.axes.left.grid = W_(p, c + 'yGridCheck').value ? a : false; };
  for (const [n, s] of [['xGridCheck', 'toggled'], ['yGridCheck', 'toggled'], ['gridAlphaSlider', 'valueChanged']]) on(c + n, s, updateGrid);
  on(c + 'fftCheck', 'toggled', (b) => { for (const k of p.curves.slice()) setCurveOpt(p, k, 'fft', b); enableAutoRange(p, null, true); recomputeAverages(p); });
  const updateLog = () => { const x = W_(p, c + 'logXCheck').value, y = W_(p, c + 'logYCheck').value;
    for (const k of p.items.slice()) setCurveOpt(p, k, 'logMode', [x, y]);
    p.axes.bottom.logMode = x; p.axes.left.logMode = y; p.vb.logMode = [x, y];
    enableAutoRange(p, null, true); recomputeAverages(p); };
  on(c + 'logXCheck', 'toggled', updateLog); on(c + 'logYCheck', 'toggled', updateLog);
  on(c + 'derivativeCheck', 'toggled', (b) => { for (const k of p.items.slice()) setCurveOpt(p, k, 'deriv', b); enableAutoRange(p, null, true); recomputeAverages(p); });
  on(c + 'phasemapCheck', 'toggled', (b) => { for (const k of p.items.slice()) setCurveOpt(p, k, 'phase', b); enableAutoRange(p, null, true); recomputeAverages(p); });
  const updateDs = () => { const [ds, auto, m] = downsampleMode(p), cl = W_(p, c + 'clipToViewCheck').value;
    for (const k of p.curves.slice()) { setDownsampling(p, k, ds, auto, m); setClipToView(p, k, cl); } recomputeAverages(p); };
  for (const [n, s] of [['downsampleSpin', 'valueChanged'], ['downsampleCheck', 'toggled'], ['autoDownsampleCheck', 'toggled'],
                        ['subsampleRadio', 'toggled'], ['meanRadio', 'toggled'], ['clipToViewCheck', 'toggled']]) on(c + n, s, updateDs);
  on(c + 'averageGroup', 'toggled', (b) => { if (b) recomputeAverages(p); for (const [, [, k]] of p.avgCurves) k.visible = b; });
  on(c + 'maxTracesCheck', 'toggled', (b) => { if (b) updateDecimation(p); else { for (const k of p.curves) k.visible = true; } });
  on(c + 'forgetTracesCheck', 'toggled', () => updateDecimation(p));
  on(c + 'maxTracesSpin', 'valueChanged', () => updateDecimation(p));
  ['xaxis', 'yaxis'].forEach((g, ax) => {                       // ViewBoxMenu
    on(g + '.mouseCheck', 'toggled', (b) => setMouseEnabled(p, ax, b));
    on(g + '.manualRadio', 'clicked', () => enableAutoRange(p, ax, false));
    const rangeText = () => { W_(p, g + '.manualRadio').setChecked(true);
      const vals = p.vb.vr[ax].slice();
      [g + '.minText', g + '.maxText'].forEach((n, i) => { const v = pyFloat(W_(p, n).value); if (v !== null) vals[i] = v; });
      setRange(p, { [ax]: vals }, 0); };
    on(g + '.minText', 'editingFinished', rangeText); on(g + '.maxText', 'editingFinished', rangeText);
    on(g + '.autoRadio', 'clicked', () => enableAutoRange(p, ax, W_(p, g + '.autoPercentSpin').value * 0.01));
    on(g + '.autoPercentSpin', 'valueChanged', (v) => { W_(p, g + '.autoRadio').setChecked(true); enableAutoRange(p, ax, v * 0.01); });
    on(g + '.linkCombo', 'currentIndexChanged', () => { /* only the empty name: no named views to link to */ });
    on(g + '.autoPanCheck', 'toggled', (b) => setAutoPan(p, ax, b));
    on(g + '.visibleOnlyCheck', 'toggled', (b) => setAutoVisible(p, ax, b));
    on(g + '.invertCheck', 'toggled', (b) => invertAxis(p, ax, b));
  });
}
function pyFloat(t) {                                           // Python float(text)
  const s = String(t).trim();
  if (/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(s)) return Number(s);
  if (/^[+-]?(inf|infinity)$/i.test(s)) return s.startsWith('-') ? -Infinity : Infinity;
  if (/^[+-]?nan$/i.test(s)) return NaN;
  return null;
}
function updateMenuState(p) {                                   // ViewBoxMenu.updateState (setters emit, as in Qt)
  for (const ax of [0, 1]) {
    const g = ['xaxis', 'yaxis'][ax] + '.', tr = p.vb.tr[ax];
    W_(p, g + 'minText').setText(fmtG(tr[0])); W_(p, g + 'maxText').setText(fmtG(tr[1]));
    const a = p.vb.autoRange[ax];
    if (a !== false) { W_(p, g + 'autoRadio').setChecked(true); if (a !== true) W_(p, g + 'autoPercentSpin').setValue(Math.trunc(a * 100)); }
    else W_(p, g + 'manualRadio').setChecked(true);
    W_(p, g + 'mouseCheck').setChecked(p.vb.mouseEnabled[ax]);
    W_(p, g + 'autoPanCheck').setChecked(p.vb.autoPan[ax]);
    W_(p, g + 'visibleOnlyCheck').setChecked(p.vb.autoVisibleOnly[ax]);
    W_(p, g + 'invertCheck').setChecked(ax ? p.vb.yInverted : p.vb.xInverted);
  }
  p.menuValid = true;
}

// ------------------------------------------------------------------ building the panels (PatternWaveform.add)
function constructionHeight(k) { return 468 / k - 28; }         // ViewBox height when the k-th row is added (see plots_api)
function build(spec, W, H) {
  spec.plots.forEach((rec, i) => {
    const p = newPanel(i, W, H);
    p.rec = rec; p.id = rec.id;
    P.push(p);
    if (rec.grid) { W_(p, 'ctrl.xGridCheck').setChecked(!!rec.grid[0]); W_(p, 'ctrl.yGridCheck').setChecked(!!rec.grid[1]); }
    for (const cr of rec.curves) addItem(p, newCurve(cr), false);
    if (rec.y_range) {                                          // q0.setRange(yRange=...) while the window is unshown
      const H0 = p.H; p.H = constructionHeight(i + 1);
      setRange(p, { 1: rec.y_range.slice() }, null);
      p.H = H0;
    }
    if (rec.x_link !== null && rec.x_link !== undefined) {      // q0.setXLink(self.q0)
      p.vb.linked[0] = rec.x_link;
      const v = P[rec.x_link];
      if (v.vb.autoRange[0] !== false) { enableAutoRange(p, 0, false); linkedViewChanged(p, v, 0); }
      else if (p.vb.autoRange[0] === false) linkedViewChanged(p, v, 0);
      stateChanged(p);
    }
  });
  settle();
}

// ------------------------------------------------------------------ drawing
function ticks(a, b, n = 6) {
  const lo = Math.min(a, b), hi = Math.max(a, b), span = hi - lo;
  if (!(span > 0) || !fin(span)) return [lo];
  const raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), st = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const out = []; for (let v = Math.ceil(lo / st) * st; v <= hi + 1e-9 * span; v += st) out.push(v);
  return out;
}
function draw(p) {
  const { W, H } = p, v = p.vb.vr, out = [], g = [], MT = p.mt;
  const sx = (x) => ML + (p.vb.xInverted ? (v[0][1] - x) : (x - v[0][0])) / (v[0][1] - v[0][0]) * W;
  const sy = (y) => MT + (p.vb.yInverted ? (y - v[1][0]) : (v[1][1] - y)) / (v[1][1] - v[1][0]) * H;
  out.push(tag('clipPath', { id: 'clip' + p.i }, tag('rect', { x: ML, y: MT, width: W, height: H })));
  out.push(tag('rect', { x: ML, y: MT, width: W, height: H, fill: 'white', stroke: '#888' }));
  const scale = p.rec.x_scale || 1, lab = (val, log) => log ? fmtG(Math.pow(10, val), 4) : String(+val.toPrecision(6));
  for (const x of ticks(v[0][0], v[0][1])) {
    if (p.axes.bottom.grid !== false) g.push(tag('line', { x1: sx(x), x2: sx(x), y1: MT, y2: MT + H, stroke: '#000', 'stroke-opacity': (p.axes.bottom.grid / 255).toFixed(3) }));
    out.push(tag('text', { x: sx(x), y: MT + H + 16, 'font-size': 10, 'text-anchor': 'middle' }, esc(lab(x * scale, p.axes.bottom.logMode))));
  }
  for (const y of ticks(v[1][0], v[1][1], 4)) {
    if (p.axes.left.grid !== false) g.push(tag('line', { x1: ML, x2: ML + W, y1: sy(y), y2: sy(y), stroke: '#000', 'stroke-opacity': (p.axes.left.grid / 255).toFixed(3) }));
    out.push(tag('text', { x: ML - 4, y: sy(y) + 3, 'font-size': 10, 'text-anchor': 'end' }, esc(lab(y, p.axes.left.logMode))));
  }
  for (const c of p.curves) {
    if (!c.visible || !c.drawn) continue;
    const parts = [];
    if (c.pen) {
      let seg = [];
      const flush = () => { if (seg.length) parts.push(tag('polyline', { points: seg.join(' '), fill: 'none', stroke: c.pen.color, 'stroke-width': c.pen.width })); seg = []; };
      c.drawn.x.forEach((x, j) => { const y = c.drawn.y[j]; if (fin(x) && fin(y)) seg.push(`${sx(x).toFixed(1)},${sy(y).toFixed(1)}`); else flush(); });
      flush();
    }
    if (c.symbol) {
      const s = c.symbolSize, fill = c.brush ? `rgb(${c.brush.join(',')})` : '#646464';
      c.drawn.x.forEach((x, j) => { const y = c.drawn.y[j]; if (fin(x) && fin(y)) parts.push(tag('rect', { x: sx(x) - s / 2, y: sy(y) - s / 2, width: s, height: s, fill, stroke: '#c8c8c8' })); });
    }
    g.push(tag('g', { opacity: c.o.alphaHint }, parts.join('')));
  }
  out.push(tag('g', { 'clip-path': `url(#clip${p.i})` }, g.join('')));
  out.push(tag('text', { x: 14, y: MT + H / 2, 'font-size': 11, transform: `rotate(-90 14 ${MT + H / 2})`, 'text-anchor': 'middle' }, esc(p.rec.label || '')));
  if (p.rec.title) out.push(tag('text', { x: ML + W / 2, y: 15, 'font-size': 13, 'text-anchor': 'middle' }, esc(p.rec.title)));
  p.svg.innerHTML = out.join('');
  Object.assign(p.box.dataset, { x0: v[0][0], x1: v[0][1], y0: v[1][0], y1: v[1][1],
    curves: p.curves.length, points: p.curves.reduce((n, c) => n + (c.drawn ? c.drawn.x.length : 0), 0) });
  p.autoBtn.hidden = p.vb.autoRange.every((a) => a !== false);
}
function render(p) {                                            // widget models -> their DOM elements
  if (!p || !p.box) return;
  for (const [ctl, w] of Object.entries(p.w)) {
    const e = w.el; if (!e) continue;
    e.disabled = !w.enabled();
    if (w.kind === 'check' || w.kind === 'radio' || w.kind === 'group') e.checked = w.value;
    else if (w.kind === 'spin' || w.kind === 'slider') { if (document.activeElement !== e) e.value = w.value; }
    else if (w.kind === 'line') { if (document.activeElement !== e) e.value = w.value; }
    else if (w.kind === 'combo') { e.innerHTML = w.value.items.map((t, k) => tag('option', { value: k }, esc(t))).join(''); e.value = String(w.value.index); }
    void ctl;
  }
}
function redraw() { settle(); for (const p of P) { draw(p); render(p); } }

// ------------------------------------------------------------------ the context menu
function ctlEl(p, ctl, text) {
  const w = p.w[ctl], rid = p.id + '.' + ctl, wrap = document.createElement('label');
  wrap.className = 'pgctl'; let e;
  if (w.kind === 'check' || w.kind === 'radio' || w.kind === 'group') {
    e = document.createElement('input'); e.type = w.kind === 'radio' ? 'radio' : 'checkbox';
    e.addEventListener('click', () => act(() => w.click()));    // render() then sets .checked from the model
    wrap.append(e, ' ' + text);
  } else if (w.kind === 'spin' || w.kind === 'slider') {
    e = document.createElement('input'); e.type = w.kind === 'spin' ? 'number' : 'range'; e.min = w.min; e.max = w.max;
    e.addEventListener('input', () => { if (e.value !== '') act(() => w.setValue(Number(e.value))); });
    wrap.append(text ? text + ' ' : '', e, w.suffix || '');
  } else if (w.kind === 'line') {
    e = document.createElement('input'); e.type = 'text'; e.size = 8;
    const fin_ = () => act(() => { w.setText(e.value); w.emit('editingFinished'); });
    e.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') fin_(); });
    e.addEventListener('change', fin_);
    wrap.append(e);
  } else if (w.kind === 'combo') {
    e = document.createElement('select');
    e.addEventListener('change', () => act(() => w.setCurrentIndex(Number(e.value))));
    wrap.append(text ? text + ' ' : '', e);
  } else if (w.kind === 'label') {
    e = document.createElement('span'); e.textContent = w.value; wrap.append(e);
  } else if (w.kind === 'list') {
    e = document.createElement('select'); e.multiple = true; e.size = 3; wrap.append(e);
  }
  e.dataset.parity = rid; w.el = e;
  return wrap;
}
function section(p, key, title, body) {
  const s = document.createElement('div'); s.className = 'pgsec'; s.dataset.section = key;
  const h = document.createElement('button'); h.type = 'button'; h.className = 'pgsech'; h.textContent = title + ' ▸';
  h.dataset.menu = p.id + ':' + key;
  const b = document.createElement('div'); b.className = 'pgsecb'; b.hidden = true; b.append(...body);
  h.addEventListener('click', () => { b.hidden = !b.hidden; if (b.hidden) p.open.delete(key); else p.open.add(key); });
  s.append(h, b);
  return s;
}
function axisPanel(p, g) {
  const r = (...e) => { const d = document.createElement('div'); d.className = 'row'; d.append(...e); return d; };
  return [r(ctlEl(p, g + '.manualRadio', 'Manual'), ctlEl(p, g + '.minText'), ctlEl(p, g + '.maxText')),
          r(ctlEl(p, g + '.autoRadio', 'Auto'), ctlEl(p, g + '.autoPercentSpin')),
          r(ctlEl(p, g + '.visibleOnlyCheck', 'Visible Data Only')), r(ctlEl(p, g + '.autoPanCheck', 'Auto Pan Only')),
          r(ctlEl(p, g + '.invertCheck', 'Invert Axis')), r(ctlEl(p, g + '.mouseCheck', 'Mouse Enabled')),
          r(ctlEl(p, g + '.label'), ctlEl(p, g + '.linkCombo'))];
}
function menu(p) {
  const m = document.createElement('div'); m.className = 'pgmenu'; m.hidden = true; m.dataset.menu = p.id;
  const c = 'ctrl.', r = (...e) => { const d = document.createElement('div'); d.className = 'row'; d.append(...e); return d; };
  const va = document.createElement('button'); va.type = 'button'; va.textContent = 'View All'; va.className = 'pgsech';
  va.addEventListener('click', () => act(() => autoRangeAll(p)));
  const grp = (n, title, body) => { const f = document.createElement('fieldset'); const l = document.createElement('legend');
    l.append(ctlEl(p, c + n, title)); f.append(l, ...body); return f; };
  const opts = [
    section(p, 'transforms', 'Transforms', [r(ctlEl(p, c + 'fftCheck', 'Power Spectrum (FFT)')), r(ctlEl(p, c + 'logXCheck', 'Log X')),
      r(ctlEl(p, c + 'logYCheck', 'Log Y')), r(ctlEl(p, c + 'derivativeCheck', 'dy/dx')), r(ctlEl(p, c + 'phasemapCheck', "Y vs. Y'"))]),
    section(p, 'downsample', 'Downsample', [r(ctlEl(p, c + 'downsampleCheck', 'Downsample')),
      r(ctlEl(p, c + 'downsampleSpin'), ctlEl(p, c + 'autoDownsampleCheck', 'Auto')), r(ctlEl(p, c + 'subsampleRadio', 'Subsample')),
      r(ctlEl(p, c + 'meanRadio', 'Mean')), r(ctlEl(p, c + 'peakRadio', 'Peak')), r(ctlEl(p, c + 'clipToViewCheck', 'Clip to View')),
      r(ctlEl(p, c + 'maxTracesCheck', 'Max Traces:'), ctlEl(p, c + 'maxTracesSpin')), r(ctlEl(p, c + 'forgetTracesCheck', 'Forget hidden traces'))]),
    section(p, 'average', 'Average', [grp('averageGroup', 'Average', [ctlEl(p, c + 'avgParamList')])]),
    section(p, 'alpha', 'Alpha', [grp('alphaGroup', 'Alpha', [r(ctlEl(p, c + 'autoAlphaCheck', 'Auto'), ctlEl(p, c + 'alphaSlider'))])]),
    section(p, 'grid', 'Grid', [r(ctlEl(p, c + 'xGridCheck', 'Show X Grid')), r(ctlEl(p, c + 'yGridCheck', 'Show Y Grid')),
      r(ctlEl(p, c + 'label'), ctlEl(p, c + 'gridAlphaSlider'))]),
    section(p, 'points', 'Points', [grp('pointsGroup', 'Points', [r(ctlEl(p, c + 'autoPointsCheck', 'Auto'))])])];
  const po = section(p, 'options', 'Plot Options', opts);
  m.append(va, section(p, 'xaxis', 'X axis', axisPanel(p, 'xaxis')), section(p, 'yaxis', 'Y axis', axisPanel(p, 'yaxis')), po);
  return m;
}
function act(fn) {                                              // a user action, then the paint that follows it
  try { fn(); } catch (e) { LOG.push(String(e.message || e)); console.warn(e); if (!(e instanceof PyError)) throw e; }
  redraw();
}

// ------------------------------------------------------------------ panels in the page, mouse
function mount(p) {
  p.mt = MT + (p.rec.title ? 18 : 0);                            // PlotItem.setTitle: a title row above the view
  const MT_ = p.mt;
  const box = document.createElement('div'); box.className = 'plotpanel'; box.dataset.parity = p.id; box.dataset.index = p.i;
  box.innerHTML = tag('svg', { width: ML + p.W + MR, height: MT_ + p.H + MB, viewBox: `0 0 ${ML + p.W + MR} ${MT_ + p.H + MB}` });
  const svg = box.firstElementChild; p.svg = svg; p.box = box;
  const ab = document.createElement('button'); ab.type = 'button'; ab.className = 'pgauto'; ab.textContent = 'A'; ab.title = 'auto range';
  ab.dataset.menu = p.id + ':auto';
  ab.addEventListener('click', () => act(() => { enableAutoRange(p, null, true); }));   // PlotItem.autoBtnClicked
  p.autoBtn = ab;
  p.menu = menu(p);
  box.append(ab, p.menu);
  const pos = (ev) => { const r = svg.getBoundingClientRect(), v = p.vb.vr;
    const fx = (ev.clientX - r.left - ML) / p.W, fy = (ev.clientY - r.top - MT_) / p.H;
    return [p.vb.xInverted ? v[0][1] - fx * (v[0][1] - v[0][0]) : v[0][0] + fx * (v[0][1] - v[0][0]),
            p.vb.yInverted ? v[1][0] + fy * (v[1][1] - v[1][0]) : v[1][1] - fy * (v[1][1] - v[1][0])]; };
  svg.addEventListener('wheel', (ev) => { ev.preventDefault();                       // ViewBox.wheelEvent
    const s = Math.pow(1.02, ev.deltaY / 8), m = p.vb.mouseEnabled;
    act(() => { p.vb.tr = [p.vb.vr[0].slice(), p.vb.vr[1].slice()]; scaleBy(p, [m[0] ? s : null, m[1] ? s : null], pos(ev)); }); });
  let drag = null;
  svg.addEventListener('mousedown', (ev) => { if (ev.button === 0) drag = { x: ev.clientX, y: ev.clientY }; });
  window.addEventListener('mouseup', () => { drag = null; });
  svg.addEventListener('mousemove', (ev) => { if (!drag) return;                    // ViewBox.mouseDragEvent (pan mode)
    const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y, v = p.vb.vr, m = p.vb.mouseEnabled;
    drag = { x: ev.clientX, y: ev.clientY };
    const tx = -dx * (v[0][1] - v[0][0]) / p.W * (p.vb.xInverted ? -1 : 1), ty = dy * (v[1][1] - v[1][0]) / p.H * (p.vb.yInverted ? -1 : 1);
    act(() => { p.vb.tr = [v[0].slice(), v[1].slice()]; translateBy(p, [m[0] ? tx : null, m[1] ? ty : null]); }); });
  svg.addEventListener('dblclick', () => act(() => autoRangeAll(p)));                 // View All
  svg.addEventListener('contextmenu', (ev) => { ev.preventDefault();          // ViewBox.raiseContextMenu -> menu.popup
    for (const q of P) if (q !== p) q.menu.hidden = true;
    p.menu.hidden = false; p.menu.style.left = (ev.offsetX + 4) + 'px'; p.menu.style.top = (ev.offsetY + 4) + 'px';
    if (!p.menuValid) act(() => updateMenuState(p)); });
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { p.menu.hidden = true; } });
  return box;
}
function snapshot(p) {                                          // parity/pg_walk.pg_state, of this panel
  const num = (v) => (fin(v) ? v : null);
  const curves = p.curves.map((c) => {
    const r = { visible: c.visible, opacity: c.o.alphaHint, avg: c.isAvg };
    try { const d = c.cleared ? null : display(p, c); r.x = d ? Array.from(d.x, num) : []; r.y = d ? Array.from(d.y, num) : []; }
    catch (e) { if (!(e instanceof PyError)) throw e; r.x = null; r.y = null; r.error = e.pytype; }
    return r;
  });
  const widgets = {};
  for (const ctl of CONTROLS) widgets[ctl] = [p.w[ctl].state(), p.w[ctl].enabled()];
  return { vb: { size: [p.W, p.H], viewRange: p.vb.vr.map((r) => r.map(num)), autoRange: p.vb.autoRange.slice(),
                 autoPan: p.vb.autoPan.slice(), autoVisibleOnly: p.vb.autoVisibleOnly.slice(), mouseEnabled: p.vb.mouseEnabled.slice(),
                 xInverted: p.vb.xInverted, yInverted: p.vb.yInverted },
           axes: { bottom: { ...p.axes.bottom }, left: { ...p.axes.left } }, curves, widgets };
}
window.PLOTS = { panels: P, log: LOG, snapshot: (i) => snapshot(P[i]), snapshots: () => P.map(snapshot),
                 styles: () => P.map((p) => p.curves.map((c) => ({ pen: c.pen, symbol: c.symbol, symbolSize: c.symbolSize, pxpad: pixelPadding(c) }))) };
(async () => {
  const q = new URLSearchParams(location.search), sz = (q.get('vb') || '720x180').split('x').map(Number);
  let spec = await (await fetch('/api/plots/spec?gui=' + encodeURIComponent(GUI))).json();
  if (!spec.ok) { document.getElementById('statusbar').textContent = spec.err_info; return; }
  while (spec.live && !spec.plots.length && !spec.error) {      // hsdPs: its plotter has not made the plot yet
    document.getElementById('statusbar').textContent = 'waiting for the plot';
    await new Promise((r) => setTimeout(r, 500));
    spec = await (await fetch('/api/plots/spec?gui=' + encodeURIComponent(GUI))).json();
  }
  document.getElementById('argv').textContent = spec.argv.join(' ');
  spec.plots.forEach((rec) => { rec.id = rec.id || ('PatternWaveform.add.q0[' + rec.label + ']'); });
  build(spec, sz[0], sz[1]);
  const page = document.getElementById('page');
  for (const p of P) page.append(mount(p));
  redraw();
  document.addEventListener('click', (ev) => { if (!ev.target.closest('.pgmenu')) for (const p of P) p.menu.hidden = true; });
  document.body.dataset.done = spec.done ? '1' : '0';
  document.body.dataset.ready = '1';
  if (spec.live) live(spec);
})();
function live(spec) {                                           // hsdPs: analyze's setData calls, as they come
  const seen = spec.plots.map((r) => r.curves.map((c) => c.version));
  let after = 0;
  const poll = async () => {
    try {
      const sp = await (await fetch('/api/plots/spec?gui=' + encodeURIComponent(GUI))).json();
      sp.plots.forEach((r, i) => r.curves.forEach((cr, k) => {
        const p = P[i], c = p && p.curves.filter((x) => !x.isAvg)[k];
        if (c && seen[i] && cr.version !== seen[i][k]) { seen[i][k] = cr.version; act(() => setData(p, c, cr.x, cr.y, cr.x_int, cr.y_int)); }
      }));
      document.getElementById('statusbar').textContent = sp.error ? sp.error : sp.done ? 'scan done' : 'scanning';
      if (sp.done) after += 1;
      document.body.dataset.done = sp.done && after > 1 ? '1' : '0';
    } catch (e) { LOG.push('live: ' + e); console.warn(e); }
    if (after < 3) setTimeout(poll, 1000);
  };
  setTimeout(poll, 500);
}
