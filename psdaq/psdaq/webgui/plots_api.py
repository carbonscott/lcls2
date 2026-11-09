"""Web copies of the pyqtgraph sequence plots: psdaq/seq/seqplot.py and psdaq/seq/seq_epixhr.py --plot, an extension of
psdaq.webgui.server started with  --seqplot '<seqplot's arguments>'  and / or  --seq-epixhr '<seq_epixhr's arguments>'
(relative --seq script paths are read in --seq-dir, default psdaq/seq of this tree).

Each program's own main() runs here, once, at start, with its Qt replaced by stand-ins that draw nothing: a
QApplication / QMainWindow / QWidget / QVBoxLayout that do nothing and a seqplot.PatternWaveform whose
GraphicsLayoutWidget records what PatternWaveform.add (the program's code, unchanged) asks of each plot: the left
label, the grid, the y range, the x link, the bottom-axis scale, and every curve (pg PlotItem.plot): its x and y data,
its pen (colour, width) or none, its symbol.  The page draws those curves in one SVG panel per plot (pan by drag,
zoom by wheel, double-click for the whole range, x ranges linked as setXLink links them).  seq_epixhr runs only with
--test (calculate, no sequence written to an XPM) here.

Routes
  GET /api/plots/spec?gui=seqplot|seq_epixhr     {title, argv, plots: [{label, grid, y_range, x_scale, x_link, curves}]}
"""

import contextlib
import io
import os
import shlex
import sys
import types


class _Axis:
    def __init__(self, plot, name):
        self.plot, self.name = plot, name

    def setScale(self, s):
        self.plot.rec['x_scale' if self.name == 'bottom' else self.name + '_scale'] = float(s)


class _Plot:
    """What PatternWaveform.add asks of a pyqtgraph PlotItem."""

    def __init__(self, gl, row, col):
        self.rec = {'row': row, 'col': col, 'label': None, 'grid': None, 'y_range': None, 'x_scale': None,
                    'x_link': None, 'curves': []}
        self.gl = gl

    def setLabel(self, axis, text=None, **k):
        if axis == 'left':
            self.rec['label'] = text

    def showGrid(self, x=None, y=None, **k):
        self.rec['grid'] = [bool(x), bool(y)]

    def setRange(self, xRange=None, yRange=None, **k):
        if yRange is not None:
            self.rec['y_range'] = [float(v) for v in yRange]
        if xRange is not None:
            self.rec['x_range'] = [float(v) for v in xRange]

    def getAxis(self, name):
        return _Axis(self, name)

    def setXLink(self, other):
        self.rec['x_link'] = self.gl.plots.index(other)

    def setTitle(self, t):
        self.rec['title'] = t

    def plot(self, x=None, y=None, pen='default', symbol=None, symbolBrush=None, pxMode=None, size=None, **k):
        p = None
        if pen is not None and pen != 'default':
            try:
                p = {'color': pen.color().name(), 'width': pen.widthF()}
            except AttributeError:
                p = {'color': str(pen), 'width': 1}
        elif pen == 'default':
            p = {'color': '#c8c8c8', 'width': 1}
        self.rec['curves'].append({'x': [float(v) for v in (x if x is not None else [])],
                                   'y': [float(v) for v in (y if y is not None else [])],
                                   'pen': p, 'symbol': symbol, 'size': size,
                                   'brush': list(symbolBrush) if isinstance(symbolBrush, (tuple, list)) else None})
        return self


class _GL:
    def __init__(self):
        self.plots = []

    def setBackground(self, c):
        self.background = c

    def addPlot(self, row=None, col=None, **k):
        p = _Plot(self, row, col)
        self.plots.append(p)
        return p


class _Nothing:
    """QApplication, QMainWindow, QWidget, QVBoxLayout: accept everything, draw nothing; exec_ returns."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: 0


def _qt():
    return types.SimpleNamespace(QApplication=_Nothing, QMainWindow=_Nothing, QWidget=_Nothing, QVBoxLayout=_Nothing)


def _waveform_class(seqplot, made):
    class PatternWaveform(seqplot.PatternWaveform):
        def __init__(self):                                    # PatternWaveform.__init__ without the Qt widget
            self.gl = _GL()
            self.gl.setBackground('w')
            self.index = 0
            self.q0 = None
            self.q = []
            made.append(self)
    return PatternWaveform


@contextlib.contextmanager
def _patched(mod, **attrs):
    old = {k: getattr(mod, k) for k in attrs}
    for k, v in attrs.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


def run_program(name, argv, seq_dir):
    """Run seqplot.main / seq_epixhr.main with argv, Qt stood in; (plots, stdout)."""
    import psdaq.seq.seqplot as seqplot
    made = []
    out = io.StringIO()
    old_argv, old_cwd = sys.argv, os.getcwd()
    try:
        os.chdir(seq_dir)                                      # relative --seq paths, as the program sees them
        sys.argv = [name] + list(argv)
        with contextlib.redirect_stdout(out):
            if name == 'seqplot':
                with _patched(seqplot, QtWidgets=_qt(), PatternWaveform=_waveform_class(seqplot, made)):
                    seqplot.main()
            else:
                import psdaq.seq.seq_epixhr as epix
                if '--test' not in argv or '--plot' not in argv:
                    raise SystemExit('--seq-epixhr: the web copy runs seq_epixhr only with --test --plot (no XPM write)')
                with _patched(epix, QtWidgets=_qt()), _patched(seqplot, PatternWaveform=_waveform_class(seqplot, made)):
                    epix.main()
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
    plots = [p.rec for w in made for p in w.gl.plots]
    return plots, out.getvalue()


class PlotsApi:
    def __init__(self, app):
        a = app.args
        import psdaq
        self.seq_dir = getattr(a, 'seq_dir', None) or os.path.join(os.path.dirname(os.path.abspath(psdaq.__file__)),
                                                                    'seq')
        self.pages = {}
        for name, spec in (('seqplot', getattr(a, 'seqplot', None)), ('seq_epixhr', getattr(a, 'seq_epixhr', None))):
            if spec:
                argv = shlex.split(spec)
                plots, log = run_program(name, argv, self.seq_dir)
                self.pages[name] = {'name': name, 'argv': argv, 'title': name, 'plots': plots,
                                    'log_tail': log[-2000:], 'seq_dir': self.seq_dir}

    def spec(self, q):
        name = q.get('gui')
        name = name[0] if isinstance(name, list) else name
        if name not in self.pages:
            return 404, {'ok': False, 'err_info': 'no plots page %r (server --seqplot / --seq-epixhr)' % name}
        return 200, dict(self.pages[name], ok=True)


def register(app, get_routes, post_routes):
    api = PlotsApi(app)
    app.plots_api = api
    get_routes['/api/plots/spec'] = api.spec
    return api
