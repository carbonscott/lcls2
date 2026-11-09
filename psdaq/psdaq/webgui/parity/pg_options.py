"""
The user-facing controls pyqtgraph puts on every plot panel (PlotItem), and the option walk that drives each one.

A pyqtgraph PlotItem builds, besides its axes and curves, a context menu (right button on the plot): the ViewBox's
'X axis' and 'Y axis' panels (ViewBox/axisCtrlTemplate: Link Axis, Manual with min / max, Auto with a percent, Visible
Data Only, Auto Pan Only, Invert Axis, Mouse Enabled) and the PlotItem's 'Plot Options' (PlotItem/plotConfigTemplate:
Transforms, Downsample, Average, Alpha, Grid, Points).  qt_walk records each of those Qt widgets with its owner plot
(group 'xaxis' / 'yaxis' / 'ctrl' and its Ui_Form attribute name); gui_rows names its row
'<plot row id>.<group>.<name>'.

OPTIONS lists, for every control, one option: the user actions (on the same panel) that set it, the last of which is
the control's own.  qt_walk's drive step 'pg-options' applies each option to the running PyQt program, one panel at a
time, from the program's own state (it puts the panel back after each), and records the panel state before the last
action and after it: the ViewBox state, the axes, every curve as displayed (PlotDataItem.getData(): after the
transforms, the downsampling, the clipping), and every menu widget's value (pg_state).  The web page's test applies the
same actions through the page's own menu and compares its state with the walk's.

Action forms: ['click', ctl]  ['set', ctl, value]  ['text', ctl, value | {'frac': f}]  ['choose', ctl, index]
  ctl is '<group>.<name>'; a text {'frac': f} is '%0.5g' of baseline lo + f * (hi - lo) of that axis's view range.
"""

CTRL = 'ctrl'
AXES = ('xaxis', 'yaxis')

# widgets of the two Ui_Forms (the Qt attribute name = objectName), in construction order
AXIS_WIDGETS = ['label', 'linkCombo', 'autoPercentSpin', 'autoRadio', 'manualRadio', 'minText', 'maxText',
                'invertCheck', 'mouseCheck', 'visibleOnlyCheck', 'autoPanCheck']
CTRL_WIDGETS = ['averageGroup', 'avgParamList', 'clipToViewCheck', 'maxTracesCheck', 'downsampleCheck', 'peakRadio',
                'maxTracesSpin', 'forgetTracesCheck', 'meanRadio', 'subsampleRadio', 'autoDownsampleCheck',
                'downsampleSpin', 'logYCheck', 'logXCheck', 'fftCheck', 'derivativeCheck', 'phasemapCheck',
                'pointsGroup', 'autoPointsCheck', 'xGridCheck', 'yGridCheck', 'gridAlphaSlider', 'label', 'alphaGroup',
                'autoAlphaCheck', 'alphaSlider']
# the plotConfigTemplate's group boxes and frames hold the controls; only the checkable group boxes are controls
CTRL_CONTAINERS = ['decimateGroup', 'transformGroup', 'gridGroup']

DS_MANUAL = [['click', 'ctrl.downsampleCheck'], ['click', 'ctrl.autoDownsampleCheck'], ['set', 'ctrl.downsampleSpin', 2]]


def _ctrl_options():
    o = [
        ('logXCheck', [['click', 'ctrl.logXCheck']]),
        ('logYCheck', [['click', 'ctrl.logYCheck']]),
        ('fftCheck', [['click', 'ctrl.fftCheck']]),
        ('derivativeCheck', [['click', 'ctrl.derivativeCheck']]),
        ('phasemapCheck', [['click', 'ctrl.phasemapCheck']]),
        # Downsample: with the x range wide (manual) the auto factor is > 1
        ('downsampleCheck', [['text', 'xaxis.maxText', {'frac': 40.0}], ['click', 'ctrl.downsampleCheck']]),
        ('autoDownsampleCheck', [['click', 'ctrl.downsampleCheck'], ['set', 'ctrl.downsampleSpin', 2],
                                 ['click', 'ctrl.autoDownsampleCheck']]),
        ('downsampleSpin', [['click', 'ctrl.downsampleCheck'], ['click', 'ctrl.autoDownsampleCheck'],
                            ['set', 'ctrl.downsampleSpin', 3]]),
        ('subsampleRadio', DS_MANUAL + [['click', 'ctrl.subsampleRadio']]),
        ('meanRadio', DS_MANUAL + [['click', 'ctrl.meanRadio']]),
        ('peakRadio', DS_MANUAL + [['click', 'ctrl.meanRadio'], ['click', 'ctrl.peakRadio']]),
        ('clipToViewCheck', [['text', 'xaxis.minText', {'frac': 0.3}], ['text', 'xaxis.maxText', {'frac': 0.7}],
                             ['click', 'ctrl.clipToViewCheck']]),
        ('maxTracesCheck', [['click', 'ctrl.maxTracesCheck']]),
        ('maxTracesSpin', [['click', 'ctrl.maxTracesCheck'], ['set', 'ctrl.maxTracesSpin', 1]]),
        ('averageGroup', [['click', 'ctrl.averageGroup']]),
        ('avgParamList', []),
        ('alphaSlider', [['set', 'ctrl.alphaSlider', 400]]),
        ('alphaGroup', [['set', 'ctrl.alphaSlider', 400], ['click', 'ctrl.alphaGroup']]),
        ('autoAlphaCheck', [['set', 'ctrl.alphaSlider', 400], ['click', 'ctrl.autoAlphaCheck']]),
        ('xGridCheck', [['click', 'ctrl.xGridCheck']]),
        ('yGridCheck', [['click', 'ctrl.yGridCheck']]),
        ('gridAlphaSlider', [['set', 'ctrl.gridAlphaSlider', 40]]),
        ('label', []),
        ('pointsGroup', [['click', 'ctrl.pointsGroup']]),
        ('autoPointsCheck', [['click', 'ctrl.autoPointsCheck']]),
        # last: it removes the hidden curves (the walk puts them back)
        ('forgetTracesCheck', [['click', 'ctrl.maxTracesCheck'], ['set', 'ctrl.maxTracesSpin', 1],
                               ['click', 'ctrl.forgetTracesCheck']]),
    ]
    return [{'name': 'ctrl.' + n, 'row': 'ctrl.' + n, 'actions': a} for n, a in o]


def _axis_options(ax):
    other = 'yaxis' if ax == 'xaxis' else 'xaxis'
    g = ax + '.'
    o = [
        ('label', []),
        ('linkCombo', [['choose', g + 'linkCombo', 0]]),
        ('autoPercentSpin', [['set', g + 'autoPercentSpin', 50]]),
        ('autoRadio', [['text', g + 'minText', {'frac': 0.25}], ['click', g + 'autoRadio']]),
        ('manualRadio', [['click', g + 'autoRadio'], ['click', g + 'manualRadio']]),
        ('minText', [['text', g + 'minText', {'frac': 0.25}]]),
        ('maxText', [['text', g + 'maxText', {'frac': 0.75}]]),
        ('invertCheck', [['click', g + 'invertCheck']]),
        ('mouseCheck', [['click', g + 'mouseCheck']]),
        # this axis auto-ranges over only the data inside the other axis's (narrowed, manual) range
        ('visibleOnlyCheck', [['text', other + '.minText', {'frac': 0.3}], ['text', other + '.maxText', {'frac': 0.6}],
                              ['click', g + 'autoRadio'], ['click', g + 'visibleOnlyCheck']]),
        ('autoPanCheck', [['click', g + 'autoPanCheck']]),
    ]
    return [{'name': g + n, 'row': g + n, 'actions': a} for n, a in o]


OPTIONS = _axis_options('xaxis') + _axis_options('yaxis') + _ctrl_options()
CONTROLS = ['xaxis.' + n for n in AXIS_WIDGETS] + ['yaxis.' + n for n in AXIS_WIDGETS] + ['ctrl.' + n for n in CTRL_WIDGETS]
assert sorted(o['row'] for o in OPTIONS) == sorted(CONTROLS), 'every control has one option'


def frac_text(baseline_range, frac):
    """'%0.5g' of lo + frac * (hi - lo) (what a user types into the axis panel's min / max field)."""
    lo, hi = baseline_range
    return '%0.5g' % (lo + frac * (hi - lo))


def option(name):
    return next(o for o in OPTIONS if o['name'] == name)


def compare(walk, web, tol=1e-6, path=''):
    """Differences [(path, walk value, web value)] between two pg_state snapshots (or parts): floats equal within
    tol relative to the larger magnitude (or tol absolute below 1), None == NaN, a bool only equal to a bool, lists
    element by element."""
    out = []
    if isinstance(walk, dict) and isinstance(web, dict):
        for k in sorted(set(walk) | set(web)):
            if k not in web or k not in walk:
                out.append((path + '.' + k, walk.get(k, '<absent>'), web.get(k, '<absent>')))
                continue
            out += compare(walk[k], web[k], tol, path + '.' + k)
        return out
    if isinstance(walk, (list, tuple)) and isinstance(web, (list, tuple)):
        if len(walk) != len(web):
            return [(path + '.len', len(walk), len(web))]
        for i, (a, b) in enumerate(zip(walk, web)):
            out += compare(a, b, tol, '%s[%d]' % (path, i))
            if len(out) > 20:
                break
        return out
    if isinstance(walk, bool) or isinstance(web, bool):        # False is not 0 (an autoRange off is not a fraction)
        return [] if type(walk) is type(web) and walk == web else [(path, walk, web)]
    if isinstance(walk, (int, float)) and isinstance(web, (int, float)):
        if walk != walk and web != web:
            return []
        m = max(abs(walk), abs(web), 1.0)
        return [] if abs(walk - web) <= tol * m else [(path, walk, web)]
    if walk is None and isinstance(web, float) and web != web:
        return []
    return [] if walk == web else [(path, walk, web)]
