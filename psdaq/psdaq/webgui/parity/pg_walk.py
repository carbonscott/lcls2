"""
The Qt side of the pyqtgraph option walk (pg_options): qt_walk --gui imports this, after pyqtgraph, for a GUI whose
spec's drive has a 'pg-options[:<W>x<H>]' step.

  tag(pi, owner)      mark the menu widgets of PlotItem pi (its ctrl Ui_Form, its ViewBox menu's two axis Ui_Forms)
                      with [owner seq, group, name]; qt_walk records the mark as the instance's 'pg'
  run(plots, pump, out, size)
                      fit every panel's ViewBox to size (W x H pixels: the web page's plot area), record the
                      baseline of every panel, then for each panel and each option of pg_options.OPTIONS: open the
                      context menu sections the actions use (popup, as a user's right click does), apply the actions,
                      record every panel's pg_state before the last action and after it, close the menus and put the
                      panel back as it was (widgets, curves, view); out['pg_options'] = {size, baseline, steps}
"""

import copy
import math

from psdaq.webgui.parity import pg_options as O

VB_KEYS = ('targetRange', 'viewRange', 'autoRange', 'autoPan', 'autoVisibleOnly', 'mouseEnabled', 'xInverted',
           'yInverted', 'logMode', 'mouseMode')


def ui_of(pi, group):
    if group == O.CTRL:
        return pi.ctrl
    return pi.vb.menu.ctrl[0 if group == 'xaxis' else 1]


def tag(pi, owner):
    """Mark the menu widgets of PlotItem pi with [owner, group, attribute name]."""
    from PyQt5 import QtWidgets
    groups = [(O.CTRL, pi.ctrl)]
    if getattr(pi.vb, 'menu', None) is not None:
        groups += [('xaxis', pi.vb.menu.ctrl[0]), ('yaxis', pi.vb.menu.ctrl[1])]
    for g, ui in groups:
        for n, w in vars(ui).items():
            if isinstance(w, QtWidgets.QWidget) and getattr(w, '_pw_seq', None) is not None:
                w._pw_pg = [owner, g, n]


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _arr(a):
    return [] if a is None else [_num(v) for v in a]


def widget(pi, ctl):
    g, n = ctl.split('.', 1)
    return getattr(ui_of(pi, g), n)


def widget_value(w):
    from PyQt5 import QtWidgets
    if isinstance(w, (QtWidgets.QAbstractButton, QtWidgets.QGroupBox)):
        if isinstance(w, QtWidgets.QGroupBox) and not w.isCheckable():
            return None
        return bool(w.isChecked())
    if isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QSlider)):
        return int(w.value())
    if isinstance(w, QtWidgets.QLineEdit):
        return w.text()
    if isinstance(w, QtWidgets.QComboBox):
        return {'index': w.currentIndex(), 'items': [w.itemText(i) for i in range(w.count())]}
    if isinstance(w, QtWidgets.QLabel):
        return w.text()
    if isinstance(w, QtWidgets.QListWidget):
        return [w.item(i).text() for i in range(w.count())]
    return None


def pg_state(pi):
    """What the panel shows: the view (ranges and the ViewBox state the menus set), the axes (grid, log), every
    curve as displayed, and every menu widget's value and enabled state."""
    vb = pi.vb
    st = vb.state
    avg = {id(p) for _, p in getattr(pi, 'avgCurves', {}).values()}
    out = {'vb': {'size': [float(vb.width()), float(vb.height())],
                  'viewRange': [[_num(v) for v in r] for r in vb.viewRange()],
                  'autoRange': [a if a is False else float(a) for a in st['autoRange']],
                  'autoPan': [bool(v) for v in st['autoPan']],
                  'autoVisibleOnly': [bool(v) for v in st['autoVisibleOnly']],
                  'mouseEnabled': [bool(v) for v in st['mouseEnabled']],
                  'xInverted': bool(st['xInverted']), 'yInverted': bool(st['yInverted'])},
           'axes': {}, 'curves': [], 'widgets': {}}
    for n in ('bottom', 'left'):
        ax = pi.getAxis(n)
        g = ax.grid
        out['axes'][n] = {'grid': False if g is False else int(g), 'logMode': bool(ax.logMode)}
    for c in pi.curves:
        rec = {'visible': bool(c.isVisible()), 'opacity': _num(c.opacity()), 'avg': id(c) in avg}
        try:
            x, y = c.getData()
            rec.update(x=_arr(x), y=_arr(y))
        except Exception as ex:             # pyqtgraph's own mapping failed (an FFT of points that share one x)
            rec.update(x=None, y=None, error=type(ex).__name__)
        out['curves'].append(rec)
    for ctl in O.CONTROLS:
        w = widget(pi, ctl)
        out['widgets'][ctl] = [widget_value(w), bool(w.isEnabled())]
    return out


def curve_style(c):
    """A curve's drawing style as pyqtgraph resolved it (what the page's bounds and padding need)."""
    import pyqtgraph as pg
    o = c.opts
    sp = c.scatter
    pen = None if o.get('pen') is None else pg.mkPen(o['pen'])     # the PlotDataItem's pen (its curve's, once drawn)
    return {'pen': None if pen is None else {'color': pen.color().name(), 'width': float(pen.widthF()),
                                             'cosmetic': bool(pen.isCosmetic())},
            'symbol': o.get('symbol'), 'symbolSize': o.get('symbolSize'),
            'curve_visible': bool(c.curve.isVisible()), 'scatter_visible': bool(sp.isVisible()),
            'curve_pxpad': float(c.curve.pixelPadding()), 'scatter_pxpad': float(sp.pixelPadding()),
            'pxpad': float(c.pixelPadding())}


def _window(plots):
    pi = plots[0]
    return pi.scene().views()[0].window()


def fix_axes(plots):
    """Fix every panel's left-axis width and bottom-axis height at the widest / tallest now (pyqtgraph widens an axis
    for longer tick labels and never narrows it back, which would move the ViewBox between options): the panels keep
    one ViewBox size and line up, as the web page's panels do.  Returns the fixed sizes."""
    lw = max(p.getAxis('left').width() for p in plots)
    bh = max(p.getAxis('bottom').height() for p in plots)
    for p in plots:
        p.getAxis('left').setWidth(int(round(lw)))
        p.getAxis('bottom').setHeight(int(round(bh)))
    return [int(round(lw)), int(round(bh))]


def fit(plots, size, pump, tries=12):
    """Resize the window until every panel's ViewBox is W x H (as near as the layout allows)."""
    if not size:
        return
    W, H = size
    win = _window(plots)
    rows = max(1, len(plots))
    for _ in range(tries):
        vb = plots[0].vb
        dw, dh = W - vb.width(), H - vb.height()
        if abs(dw) < 0.5 and abs(dh) < 0.5:
            break
        win.resize(int(round(win.width() + dw)), int(round(win.height() + dh * rows)))
        pump(0.3)


def capture(pi):
    return {'vb': copy.deepcopy({k: pi.vb.state[k] for k in VB_KEYS}),
            'widgets': {ctl: widget_value(widget(pi, ctl)) for ctl in O.CONTROLS},
            'curves': list(pi.curves), 'items': list(pi.items), 'dataItems': list(pi.dataItems),
            'data': {id(c): tuple(None if a is None else a.copy() for a in c.getOriginalDataset()) for c in pi.curves},
            'visible': {id(c): c.isVisible() for c in pi.curves},
            'menu_valid': getattr(pi.vb.menu, 'valid', True)}


def set_widget(w, v, quiet=False):
    from PyQt5 import QtWidgets
    if v is None:
        return
    if quiet:
        w.blockSignals(True)
    try:
        if isinstance(w, (QtWidgets.QAbstractButton, QtWidgets.QGroupBox)):
            if w.isChecked() != v:
                w.setChecked(v)
        elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QSlider)):
            if w.value() != v:
                w.setValue(v)
        elif isinstance(w, QtWidgets.QLineEdit):
            w.setText(v)
        elif isinstance(w, QtWidgets.QComboBox):
            if w.currentIndex() != v['index']:
                w.setCurrentIndex(v['index'])
    finally:
        if quiet:
            w.blockSignals(False)


def restore(pi, cap, pump):
    """Put panel pi back as captured: the Plot Options widgets through their setters (their signals reconfigure the
    curves as a user's clicks would), no average curves, the curves 'Forget hidden traces' removed back in place,
    the axis menus' widgets (signals blocked: they mirror the view), then the ViewBox state (its links untouched)."""
    from PyQt5 import QtWidgets
    ctrl = [c for c in O.CONTROLS if c.startswith('ctrl.')]
    radios = [c for c in ctrl if isinstance(widget(pi, c), QtWidgets.QRadioButton)]
    for c in ctrl:                               # a checked radio is set before the others (exclusive group)
        if c in radios and not cap['widgets'][c]:
            continue
        set_widget(widget(pi, c), cap['widgets'][c])
    for _, p in list(getattr(pi, 'avgCurves', {}).values()):
        pi.removeItem(p)
    pi.avgCurves = {}
    for c in cap['curves']:
        if c not in pi.curves:
            x, y = cap['data'][id(c)]
            c.setData(x=x, y=y)
            pi.addItem(c, params={})
    order = {id(c): i for i, c in enumerate(cap['curves'])}
    pi.curves.sort(key=lambda c: order.get(id(c), 1 << 30))
    pi.dataItems.sort(key=lambda c: order.get(id(c), 1 << 30))
    io = {id(c): i for i, c in enumerate(cap['items'])}
    pi.items.sort(key=lambda c: io.get(id(c), 1 << 30))
    for c in pi.curves:
        c.setVisible(cap['visible'].get(id(c), True))
    for c in O.CONTROLS:
        if not c.startswith('ctrl.'):
            set_widget(widget(pi, c), cap['widgets'][c], quiet=True)
    vb = pi.vb
    vb.state.update(copy.deepcopy(cap['vb']))
    vb._matrixNeedsUpdate = True
    vb.updateViewRange()
    vb.update()
    vb.sigStateChanged.emit(vb)
    if vb.menu is not None:
        vb.menu.valid = cap['menu_valid']
    for c in pi.curves:
        c.viewRangeChanged()
    pump(0.3)


def _menus(pi, axes):
    """Open the context menu (as a right click does: ViewBoxMenu.popup brings its axis panels up to date) and the
    axis panels `axes` uses (as a hover on 'X axis' / 'Y axis' does)."""
    from PyQt5 import QtCore
    m = pi.vb.menu
    opened = []
    m.popup(QtCore.QPoint(40, 40))
    opened.append(m)
    for a in m.actions():
        sub = a.menu()
        if sub is not None and sub.title()[:1].lower() + 'axis' in axes:
            sub.popup(QtCore.QPoint(200, 40 + 160 * len(opened)))
            opened.append(sub)
    return opened


def act(pi, a, base):
    from PyQt5 import QtWidgets
    op, ctl = a[0], a[1]
    w = widget(pi, ctl)
    if op == 'click':
        if isinstance(w, QtWidgets.QGroupBox):
            w.setChecked(not w.isChecked())      # the check box in the group's title
        else:
            w.click()
    elif op == 'set':
        w.setValue(int(a[2]))
    elif op == 'text':
        v = a[2]
        if isinstance(v, dict):
            v = O.frac_text(base['vb']['viewRange'][0 if ctl.startswith('xaxis') else 1], v['frac'])
        w.setText(v)
        w.editingFinished.emit()
    elif op == 'choose':
        w.setCurrentIndex(int(a[2]))
    else:
        raise ValueError('pg_walk: unknown action %r' % (a,))


def settle(plots, pump, limit=20.0):
    """Pump until every panel's state stops changing (pyqtgraph auto-ranges once per paint; data whose display
    depends on the view, as dynamicRangeLimit clipping of an infinite dy/dx, takes many paints), at most limit s;
    returns the seconds taken (None if it never settled)."""
    import time
    t0 = time.time()
    prev = [pg_state(p) for p in plots]
    while time.time() - t0 < limit:
        pump(0.25)
        cur = [pg_state(p) for p in plots]
        if not O.compare(prev, cur, tol=0):
            return round(time.time() - t0, 2)
        prev = cur
    return None


def run(plots, pump, out, size=None, log=None):
    axes = fix_axes(plots)
    pump(0.3)
    fit(plots, size, pump)
    pump(0.5)
    settle(plots, pump)
    base = [pg_state(p) for p in plots]
    caps = [capture(p) for p in plots]
    res = {'size': [list(p['vb']['size']) for p in base], 'requested_size': list(size) if size else None,
           'fixed_axes': {'left_width': axes[0], 'bottom_height': axes[1]},
           'baseline': base, 'styles': [[curve_style(c) for c in p.curves] for p in plots], 'steps': []}
    out['pg_options'] = res
    for i, pi in enumerate(plots):
        for opt in O.OPTIONS:
            acts = opt['actions']
            axes = sorted({a[1].split('.')[0] for a in acts} & set(O.AXES))
            step = {'plot': i, 'option': opt['name'], 'row': opt['row'], 'actions': acts, 'errors': []}
            step['start'] = [pg_state(p) for p in plots]
            opened = _menus(pi, axes)
            pump(0.2)
            step['settle'] = []
            try:
                for k, a in enumerate(acts):
                    if k == len(acts) - 1:
                        step['settle'].append(settle(plots, pump))
                        step['pre'] = [pg_state(p) for p in plots]
                    act(pi, a, base[i])
                    pump(0.15)
                if not acts:
                    step['pre'] = [pg_state(p) for p in plots]
                step['settle'].append(settle(plots, pump))
                step['post'] = [pg_state(p) for p in plots]
            except Exception as ex:
                import traceback
                step['errors'].append(traceback.format_exc()[-800:])
                step.setdefault('pre', None)
                step['post'] = [pg_state(p) for p in plots]
            for m in reversed(opened):
                m.hide()
            pump(0.1)
            for p, cap in zip(plots, caps):
                restore(p, cap, pump)
            settle(plots, pump)
            again = [pg_state(p) for p in plots]
            step['reset_diff'] = O.compare(base, again)[:5]
            res['steps'].append(step)
        if log:
            log('pg-options: panel %d: %d options' % (i, len(O.OPTIONS)))
    return res
