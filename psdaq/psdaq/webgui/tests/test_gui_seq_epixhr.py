"""Headless-browser tests of /gui/seq_epixhr, the web copy of psdaq/seq/seq_epixhr.py --plot (psdaq.webgui.plots_api:
seq_epixhr's own main() with --test, so nothing is written to an XPM, and Qt stood in), on the simulated DAQ's node,
with --rate 1000 (with the default rate, seq_epixhr --test --plot raises in seqplot's simulation of its sequence).
The plot's curves are compared with the curves the PyQt seq_epixhr --test --plot drew in this session's walk, and
every control of the panel's context menu (48, parity/pg_options.py) with what it did to the PyQt seq_epixhr in the
walk's option step."""

import pytest

import plots_checks as P

ARGV = ['--test', '--plot', '--rate', '1000']   # the default rate's --plot raises in seqplot's simulation
ROWS = ['PatternWaveform.add.q0[epixhr]']
PARITY_ROWS = {'test_plot_shows_the_pyqt_curves': ROWS, 'test_wheel_zoom_drag_pan': ROWS}
PARITY_ROWS.update(P.option_tests(globals(), 'se', 'seq_epixhr', ROWS))


@pytest.fixture(scope='module')
def se():
    s = P.server('seq_epixhr', ARGV)
    try:
        yield s
    finally:
        s.stop()


def test_plot_shows_the_pyqt_curves(page, se):
    P.open_page(page, se, 'seq_epixhr')
    P.check_curves(page, se, 'seq_epixhr', 'seq/seq_epixhr.py', ROWS)
    import webgui_harness as H
    page.screenshot(path=str(H.SHOTS / 'seq_epixhr.png'), full_page=True)


def test_wheel_zoom_drag_pan(page, se):
    P.open_page(page, se, 'seq_epixhr')
    P.check_zoom(page, ROWS)
