"""Headless-browser tests of /gui/seqplot, the web copy of psdaq/seq/seqplot.py (psdaq.webgui.plots_api: seqplot's own
main() with Qt stood in), on the simulated DAQ's node: two of the tree's sequence scripts (33k_35k.py on engine 0,
10k.py on engine 1) over the first 10 ms, the arguments the parity walk gave the PyQt seqplot.  Each plot's curves
are compared with the curves the PyQt seqplot drew in this session's walk, and every control of each panel's context
menu (96: 48 per panel, parity/pg_options.py) with what it did to the PyQt seqplot in the walk's option step."""

import pytest

import plots_checks as P

ARGV = ['--seq', '0:33k_35k.py', '1:10k.py', '--time', '0', '0.01']
LABELS = ['33k_35k.py', '10k.py']
ROWS = ['PatternWaveform.add.q0[%s]' % x for x in LABELS]
PARITY_ROWS = {'test_plots_show_the_pyqt_curves': ROWS, 'test_wheel_zoom_drag_pan_and_x_link': ROWS}
PARITY_ROWS.update(P.option_tests(globals(), 'sp', 'seqplot', ROWS))


@pytest.fixture(scope='module')
def sp():
    s = P.server('seqplot', ARGV)
    try:
        yield s
    finally:
        s.stop()


def test_plots_show_the_pyqt_curves(page, sp):
    P.open_page(page, sp, 'seqplot')
    P.check_curves(page, sp, 'seqplot', 'seq/seqplot.py', ROWS)
    import webgui_harness as H
    page.screenshot(path=str(H.SHOTS / 'seqplot.png'), full_page=True)


def test_wheel_zoom_drag_pan_and_x_link(page, sp):
    P.open_page(page, sp, 'seqplot')
    P.check_zoom(page, ROWS)
