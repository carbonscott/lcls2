"""Headless-browser tests of /gui/seqplot, the web copy of psdaq/seq/seqplot.py (psdaq.webgui.plots_api: seqplot's own
main() with Qt stood in), on the simulated DAQ's node: two of the tree's sequence scripts (10k.py on engine 0,
burst.py on engine 1) over the first 0.2 ms, the arguments the parity walk gave the PyQt seqplot.  Each plot's
curves are compared with the curves the PyQt seqplot drew in this session's walk."""

import pytest

import plots_checks as P

ARGV = ['--seq', '0:10k.py', '1:burst.py', '--time', '0', '0.0002']
ROWS = ['PatternWaveform.add.q0[10k.py]', 'PatternWaveform.add.q0[burst.py]']
PARITY_ROWS = {'test_plots_show_the_pyqt_curves': ROWS, 'test_wheel_zoom_drag_pan_and_x_link': ROWS}


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
