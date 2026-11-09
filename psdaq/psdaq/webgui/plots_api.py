"""Web copies of the pyqtgraph plot programs: psdaq/seq/seqplot.py, psdaq/seq/seq_epixhr.py --plot and
psdaq/cas/hsdPs.py, an extension of psdaq.webgui.server started with  --seqplot '<seqplot's arguments>',
--seq-epixhr '<seq_epixhr's arguments>' and / or  --hsdps '<hsdPs's arguments>'  (relative --seq script paths are
read in --seq-dir, default psdaq/seq of this tree).

hsdPs (an HSD ADC/TIM clock phase scan): its own main() runs in a thread of the server, at start, against the PVs of
its --base HSDs (RESET, MONTRIG) and its --xpm (GroupL0Enable / GroupL0Disable), which must be loopback PVs
(netguard.require_loopback_pva_env: the campaign's simhsd and simxpm); its plotting process (multiprocessing.Process
(target=analyze)) runs as a thread with Qt stood in, so each early / late curve analyze sets is what the page shows,
live (the page polls; done once the scan joins its plotter).  <base>:SIM:PID of each --base is read once (simhsd
serves it; a real HSD does not), so a test can tell which simulator served the scan.

Each program's own main() runs here, once, at start, with its Qt replaced by stand-ins that draw nothing: a
QApplication / QMainWindow / QWidget / QVBoxLayout that do nothing and a seqplot.PatternWaveform whose
GraphicsLayoutWidget records what PatternWaveform.add (the program's code, unchanged) asks of each plot: the left
label, the grid, the y range, the x link, the bottom-axis scale, and every curve (pg PlotItem.plot): its x and y data,
its pen (colour, width) or none, its symbol.  The page (static/gui/plots.js) draws those curves in one SVG panel per
plot with a port of the pyqtgraph code a user drives: pan by drag, zoom by wheel, the x ranges linked as setXLink
links them, and the context menu (right button: View All, the X / Y axis panels, Plot Options), each of whose
controls is a row of the parity check (parity/pg_options.py).  The y range PatternWaveform.add sets is padded as
pyqtgraph pads it then: by suggestPadding of the ViewBox height while the window is not yet shown, which for the k-th
row of a new GraphicsLayoutWidget (640 x 480) is 468 / k - 28 pixels (measured, pyqtgraph 0.13.7; plots.js
constructionHeight).  seq_epixhr runs only with --test (calculate, no sequence written to an XPM) here.

Routes
  GET /api/plots/spec?gui=seqplot|seq_epixhr|hsdPs
          {title, argv, live, done, plots: [{id, label, title, grid, y_range, x_scale, x_link, curves}], sim_pid}
          id: the plot's parity row id (seqplot / seq_epixhr: PatternWaveform.add.q0[<label>]; hsdPs: analyze.pp)
"""

import argparse
import contextlib
import io
import os
import queue
import shlex
import sys
import threading
import traceback
import types

PLOT_ID = {'seqplot': lambda r: 'PatternWaveform.add.q0[%s]' % r['label'],
           'seq_epixhr': lambda r: 'PatternWaveform.add.q0[%s]' % r['label'],
           'hsdPs': lambda r: 'analyze.pp'}


class _Axis:
    def __init__(self, plot, name):
        self.plot, self.name = plot, name

    def setScale(self, s):
        self.plot.rec['x_scale' if self.name == 'bottom' else self.name + '_scale'] = float(s)


class _Plot:
    """What PatternWaveform.add asks of a pyqtgraph PlotItem."""

    def __init__(self, gl, row, col):
        self.rec = {'row': row, 'col': col, 'label': None, 'title': None, 'grid': None, 'y_range': None,
                    'x_scale': None, 'x_link': None, 'curves': []}
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

    def plot(self, x=None, y=None, pen='default', symbol=None, symbolBrush=None, symbolSize=10, symbolPen=None, **k):
        """PlotItem.plot -> a PlotDataItem as pyqtgraph 0.13.7 makes it: pen 'default' is (200,200,200) width 1,
        mkPen pens are cosmetic; symbolSize defaults to 10 (seqplot's size=2 is not a PlotDataItem option and is
        ignored), symbolPen to (200,200,200) width 1."""
        p = None
        if pen is not None and pen != 'default':
            try:
                p = {'color': pen.color().name(), 'width': pen.widthF()}
            except AttributeError:
                p = {'color': str(pen), 'width': 1}
        elif pen == 'default':
            p = {'color': '#c8c8c8', 'width': 1}
        spw = 1.0
        if symbolPen is not None:
            try:
                spw = symbolPen.widthF()
            except AttributeError:
                spw = 1.0
        c = {'x': [float(v) for v in (x if x is not None else [])],
             'y': [float(v) for v in (y if y is not None else [])],
             'x_int': _int_array(x), 'y_int': _int_array(y),     # np.array(...).dtype.kind in 'iu'
             'pen': p, 'symbol': symbol, 'symbolSize': symbolSize, 'symbolPenWidth': spw,
             'brush': list(symbolBrush) if isinstance(symbolBrush, (tuple, list)) else None,
             'ignored': sorted(k), 'version': 0}
        self.rec['curves'].append(c)
        return _Curve(c)


def _int_array(a):
    """Whether PlotDataItem.setData would hold `a` as an integer numpy array (PlotDataset then takes it as all
    finite, which decides whether pyqtgraph's dynamicRangeLimit sees an infinite dy/dx)."""
    if a is None:
        return False
    import numpy as np
    try:
        return np.asarray(a).dtype.kind in 'iu'
    except Exception:
        return False


class _Curve:
    """The PlotDataItem PlotItem.plot returns: setData replaces its data (hsdPs's analyze)."""

    def __init__(self, rec):
        self.rec = rec

    def setData(self, *a, **k):
        x, y = (a + (None, None))[:2] if len(a) >= 2 else (None, a[0] if a else None)
        x, y = k.get('x', x), k.get('y', y)
        if x is None and y is not None:
            x = range(len(y))
        self.rec['x'] = [float(v) for v in (x if x is not None else [])]
        self.rec['y'] = [float(v) for v in (y if y is not None else [])]
        self.rec['x_int'], self.rec['y_int'] = _int_array(x), _int_array(y)
        self.rec['version'] += 1


class _GL:
    def __init__(self):
        self.plots = []

    def setBackground(self, c):
        self.background = c

    def __getattr__(self, name):                   # show(), resize(), ... of the GraphicsLayoutWidget: nothing to do
        if name.startswith('__'):
            raise AttributeError(name)
        return lambda *a, **k: None

    def addPlot(self, row=None, col=None, **k):
        p = _Plot(self, row, col)
        self.plots.append(p)
        if k:                                      # PlotItem(**kargs) -> self.plot(**kargs) (hsdPs: data=[0])
            p.plot(**k)
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


def run_hsdps(argv, page):
    """hsdPs.main() with argv, in this thread: its phase scan on the (loopback) PVs, its plotter a thread with Qt
    stood in; page gets 'plots' (live), 'done' when main joins the plotter, 'error' / 'exit' if main fails."""
    import psdaq.cas.hsdPs as ps
    made = []

    class _Proc:                                    # multiprocessing.Process(target=analyze, ...) -> a thread
        def __init__(self, target=None, args=(), **k):
            self.t = threading.Thread(target=target, args=args, daemon=True, name='hsdPs-analyze')

        def start(self):
            self.t.start()

        def join(self, timeout=None):               # the scan is over (analyze itself never returns)
            page['done'] = True

    def gl():
        g = _GL()
        made.append(g)
        page['made'] = made
        return g

    class _AP(argparse.ArgumentParser):
        def parse_args(self, args=None, namespace=None):
            return super().parse_args(list(argv) if args is None else args, namespace)
    ps.Process, ps.Queue = _Proc, queue.Queue
    ps.pg = types.SimpleNamespace(Qt=types.SimpleNamespace(QtWidgets=types.SimpleNamespace(QApplication=_Nothing)),
                                  GraphicsLayoutWidget=gl, mkPen=ps.pg.mkPen)
    ps.argparse = types.SimpleNamespace(ArgumentParser=_AP)
    try:
        ps.main()
    except SystemExit as ex:
        page['exit'] = ex.code
    except Exception:
        page['error'] = traceback.format_exc()[-2000:]


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
                for r in plots:
                    r['id'] = PLOT_ID[name](r)
                self.pages[name] = {'name': name, 'argv': argv, 'title': name, 'plots': plots, 'live': False,
                                    'done': True, 'log_tail': log[-2000:], 'seq_dir': self.seq_dir}
        hs = getattr(a, 'hsdps', None)
        if hs:
            from psdaq.webgui.netguard import require_loopback_pva_env
            self.pva_conf = require_loopback_pva_env(os.environ, '--hsdps')     # NonLoopbackError: exit 2
            argv = shlex.split(hs)
            page = {'name': 'hsdPs', 'argv': argv, 'title': 'hsdPs', 'live': True, 'done': False, 'made': []}
            self.pages['hsdPs'] = page
            threading.Thread(target=run_hsdps, args=(argv, page), daemon=True, name='hsdPs').start()

    def _sim_pids(self, page):
        """<base>:SIM:PID of each --base, read once through a loopback PVA client (simhsd serves it)."""
        if 'sim_pid' not in page:
            from p4p.client.thread import Context
            bases = []
            av = page['argv']
            if '--base' in av:
                for v in av[av.index('--base') + 1:]:
                    if v.startswith('--'):
                        break
                    bases.append(v)
            out = {}
            ctx = Context('pva', conf=self.pva_conf, useenv=False)
            try:
                for b in bases:
                    try:
                        out[b] = int(ctx.get(b + ':SIM:PID', timeout=3.0))
                    except Exception as ex:
                        out[b] = 'unread: %s' % type(ex).__name__
            finally:
                ctx.close()
            page['sim_pid'] = out
        return page['sim_pid']

    def spec(self, q):
        name = q.get('gui')
        name = name[0] if isinstance(name, list) else name
        if name not in self.pages:
            return 404, {'ok': False, 'err_info': 'no plots page %r (server --seqplot / --seq-epixhr / --hsdps)' % name}
        page = self.pages[name]
        if name != 'hsdPs':
            return 200, dict(page, ok=True)
        plots = []
        for g in list(page.get('made', [])):
            for p in list(g.plots):
                r = dict(p.rec, curves=[dict(c) for c in p.rec['curves']])
                r['id'] = PLOT_ID[name](r)
                plots.append(r)
        out = {k: v for k, v in page.items() if k != 'made'}
        out.update(ok=True, plots=plots, sim_pid=self._sim_pids(page))
        return 200, out


def register(app, get_routes, post_routes):
    api = PlotsApi(app)
    app.plots_api = api
    get_routes['/api/plots/spec'] = api.spec
    return api
