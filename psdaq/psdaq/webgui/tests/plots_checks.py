"""Checks shared by the headless-browser tests of the pyqtgraph plot pages (/gui/seqplot, /gui/seq_epixhr): the
curves the page draws are the curves the PyQt program drew in this session's offscreen walk (qt_walk records each
pyqtgraph PlotItem's curves), and pan / zoom move the x range of every linked plot."""

import pytest
from playwright.sync_api import expect

import webgui_harness as H
import pvgui_checks as C


def server(name, argv):
    sim = H.sim_daq()
    if sim is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    flag = {'seqplot': '--seqplot', 'seq_epixhr': '--seq-epixhr'}[name]
    s = H.gui_server([flag, ' '.join(argv)], lambda s, sim: sim.alive())
    assert s.backend == 'sim-daq', (s.backend, s.backend_why)
    return s


def open_page(page, s, name):
    page.goto(s.url.rstrip('/') + '/gui/' + name)
    page.wait_for_function('() => document.body.dataset.ready === "1"', timeout=H.UI_TIMEOUT)


def check_curves(page, s, name, file, rows):
    spec = s.get('/api/plots/spec?gui=' + name)
    walk = C.walk_instances(name, file)
    got = {'PatternWaveform.add.q0[%s]' % p['label']: p for p in spec['plots']}
    assert sorted(got) == sorted(rows), (sorted(got), rows)
    for rid in rows:
        x, p = walk[rid], got[rid]
        assert x is not None and x['text'] == p['label'], (rid, x and x['text'])
        assert len(x['curves']) == len(p['curves']), (rid, len(x['curves']), len(p['curves']))
        for k, (a, b) in enumerate(zip(x['curves'], p['curves'])):
            assert a['n'] == len(b['x']) and a['x'] == b['x'][:len(a['x'])] and a['y'] == b['y'][:len(a['y'])], \
                (rid, k, a['n'], len(b['x']), a['x'][:5], b['x'][:5])
            assert a['symbol'] == b['symbol'], (rid, k, a['symbol'], b['symbol'])
        if x.get('y_range') and p.get('y_range'):
            assert abs(x['y_range'][0] - p['y_range'][0]) < 1 and abs(x['y_range'][1] - p['y_range'][1]) < 1, \
                (rid, x['y_range'], p['y_range'])
        box = page.locator(C.sel(rid))
        expect(box).to_be_visible()
        assert int(box.get_attribute('data-curves')) == len(p['curves'])
        assert int(box.get_attribute('data-points')) == sum(len(c['x']) for c in p['curves'])
        assert box.locator('text').filter(has_text=p['label']).count() == 1
    return got


def xr(page, rid):
    b = page.locator(C.sel(rid))
    return float(b.get_attribute('data-x0')), float(b.get_attribute('data-x1'))


def check_zoom(page, rows):
    full = {r: xr(page, r) for r in rows}
    box = page.locator(C.sel(rows[0]) + ' svg')
    bb = box.bounding_box()
    page.mouse.move(bb['x'] + bb['width'] * 0.5, bb['y'] + bb['height'] * 0.5)
    page.mouse.wheel(0, -120)                                  # zoom in about the cursor
    page.wait_for_timeout(200)
    z = {r: xr(page, r) for r in rows}
    assert z[rows[0]][1] - z[rows[0]][0] < 0.95 * (full[rows[0]][1] - full[rows[0]][0]), (full, z)
    assert all(z[r] == z[rows[0]] for r in rows), z            # setXLink: every plot follows
    page.mouse.down()
    page.mouse.move(bb['x'] + bb['width'] * 0.3, bb['y'] + bb['height'] * 0.5)
    page.mouse.up()
    d = {r: xr(page, r) for r in rows}
    assert d[rows[0]][0] > z[rows[0]][0] and all(d[r] == d[rows[0]] for r in rows), (z, d)     # dragged left: pan
    box.dblclick()
    page.wait_for_timeout(200)
    assert {r: xr(page, r) for r in rows} == full                # autoRange
