"""Checks shared by the headless-browser tests of the pyqtgraph plot pages (/gui/seqplot, /gui/seq_epixhr): the
curves the page draws are the curves the PyQt program drew in this session's offscreen walk (qt_walk records each
pyqtgraph PlotItem's curves), pan / zoom move the x range of every linked plot, and each control of a panel's context
menu (parity/pg_options.py) does on the page what it did to the PyQt program in the walk's option step
(qt_walk 'pg-options': the same actions, the panels' state before the last action and after it)."""

import json

import pytest
from playwright.sync_api import expect

import webgui_harness as H
import pvgui_checks as C
from psdaq.webgui.parity import pg_options as O


def server(name, argv):
    sim = H.sim_daq()
    if sim is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    flag = {'seqplot': '--seqplot', 'seq_epixhr': '--seq-epixhr'}[name]
    s = H.gui_server([flag, ' '.join(argv)], lambda s, sim: sim.alive())
    assert s.backend == 'sim-daq', (s.backend, s.backend_why)
    return s


def open_page(page, s, name, size=None):
    """Load the page; size [W, H]: the plot-area size of every panel (the walk's ViewBox size, ?vb=WxH)."""
    page.goto(s.url.rstrip('/') + '/gui/' + name + ('?vb=%rx%r' % tuple(size) if size else ''))
    page.wait_for_function('() => document.body.dataset.ready === "1"', timeout=H.UI_TIMEOUT)
    # a live page (hsdPs: its scan runs in the server) is compared once its program is done
    page.wait_for_function('() => document.body.dataset.done === "1"', timeout=max(H.UI_TIMEOUT, 120000))


def check_curves(page, s, name, file, rows):
    spec = s.get('/api/plots/spec?gui=' + name)
    walk = C.walk_instances(name, file)
    got = {p['id']: p for p in spec['plots']}
    assert sorted(got) == sorted(rows), (sorted(got), rows)
    for rid in rows:
        x, p = walk[rid], got[rid]
        assert x is not None and x['text'] == p['label'], (rid, x and x['text'])
        assert len(x['curves']) == len(p['curves']), (rid, len(x['curves']), len(p['curves']))
        for k, (a, b) in enumerate(zip(x['curves'], p['curves'])):
            assert a['n'] == len(b['x']) and a['x'] == b['x'][:len(a['x'])] and a['y'] == b['y'][:len(a['y'])], \
                (rid, k, a['n'], len(b['x']), a['x'][:5], b['x'][:5])
            assert a['symbol'] == b['symbol'], (rid, k, a['symbol'], b['symbol'])
        box = page.locator(C.sel(rid))
        expect(box).to_be_visible()
        if x.get('vb_size') and page.url.find('?vb=') < 0:
            open_page(page, s, name, x['vb_size'])         # the walk's ViewBox size: the same padding
            box = page.locator(C.sel(rid))
        for k, ax in (('x_range', 'x'), ('y_range', 'y')):   # the view as pyqtgraph set it (the padded y range)
            if x.get(k):
                web = [float(box.get_attribute('data-%s0' % ax)), float(box.get_attribute('data-%s1' % ax))]
                assert all(abs(a - b) <= 1e-6 * max(1.0, abs(a)) for a, b in zip(x[k], web)), (rid, k, x[k], web)
        assert int(box.get_attribute('data-curves')) == len(p['curves'])
        assert int(box.get_attribute('data-points')) == sum(len(c['x']) for c in p['curves'])
        if p['label']:
            assert box.locator('text').filter(has_text=p['label']).count() == 1
        if p.get('title'):
            assert box.locator('text').filter(has_text=p['title']).count() == 1
    from psdaq.webgui.parity import check_gui_parity
    spec = next(x for x in check_gui_parity.load_specs().values() if x['_name'] == name)
    with open(check_gui_parity.walk_path(spec, H.gui_walks())) as f:
        pg = json.load(f).get('pg_options')
    if pg:                                          # each curve's drawing style as pyqtgraph resolved it
        web = page.evaluate('() => window.PLOTS.styles()')
        for i, (ws, ps) in enumerate(zip(pg['styles'], web)):
            assert len(ws) == len(ps), (i, ws, ps)
            for a, b in zip(ws, ps):
                assert a['symbol'] == b['symbol'] and (a['symbol'] is None or a['symbolSize'] == b['symbolSize']), (i, a, b)
                assert abs(a['pxpad'] - b['pxpad']) < 1e-9, (i, a, b)
                assert (a['pen'] is None) == (b['pen'] is None), (i, a, b)
                if a['pen']:
                    assert a['pen']['color'] == b['pen']['color'] and a['pen']['width'] == b['pen']['width'], (i, a, b)
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


# ------------------------------------------------------------------ the context-menu controls (pg_options)

SECTION = {}                     # ctrl widget -> the Plot Options section that holds it
for _sec, _names in (('transforms', 'fftCheck logXCheck logYCheck derivativeCheck phasemapCheck'),
                     ('downsample', 'downsampleCheck downsampleSpin autoDownsampleCheck subsampleRadio meanRadio '
                                    'peakRadio clipToViewCheck maxTracesCheck maxTracesSpin forgetTracesCheck'),
                     ('average', 'averageGroup avgParamList'), ('alpha', 'alphaGroup autoAlphaCheck alphaSlider'),
                     ('grid', 'xGridCheck yGridCheck gridAlphaSlider label'), ('points', 'pointsGroup autoPointsCheck')):
    for _n in _names.split():
        SECTION[_n] = _sec


def walk_options(spec_name):
    """(walk, its pg_options record, {panel index: plot row id}) of this session's walk of the program."""
    from psdaq.webgui.parity import check_gui_parity, gui_rows, qapps
    spec = next(x for x in check_gui_parity.load_specs().values() if x['_name'] == spec_name)
    with open(check_gui_parity.walk_path(spec, H.gui_walks())) as f:
        walk = json.load(f)
    pg = walk.get('pg_options')
    assert pg, 'the walk of %s has no pg-options step' % spec_name
    rows = gui_rows.make_rows(gui_rows.source_sites(qapps.default_src(), spec['file']), walk)
    ids = {r['instance']: r['id'] for r in rows if r['kind'] == 'plot'}
    return walk, pg, {i: ids[seq] for i, seq in enumerate(pg['plots'])}


def snapshots(page):
    return page.evaluate('() => window.PLOTS.snapshots()')


def same(walk_state, web_state, what):
    d = O.compare(walk_state, web_state)
    assert not d, '%s: the page differs from the PyQt program (walk): %s' % (what, json.dumps(d[:6])[:1500])


def _open_sections(page, pid, acts, row):
    """Right-click the panel (pyqtgraph's context menu; it brings the axis panels up to date), then open the axis
    panels and Plot Options sections the actions and the row use."""
    box = page.locator(C.sel(pid))
    box.locator('svg').click(button='right', position={'x': 200, 'y': 60})
    menu = box.locator('.pgmenu')
    expect(menu).to_be_visible()
    ctls = [a[1] for a in acts] + [row]
    for g in ('xaxis', 'yaxis'):
        if any(c.startswith(g + '.') for c in ctls):
            menu.locator('[data-menu="%s:%s"]' % (pid, g)).click()
    secs = []
    for c in ctls:
        if c.startswith('ctrl.') and SECTION[c.split('.', 1)[1]] not in secs:
            secs.append(SECTION[c.split('.', 1)[1]])
    if secs:
        menu.locator('[data-menu="%s:options"]' % pid).click()
        for k in secs:
            menu.locator('[data-menu="%s:%s"]' % (pid, k)).click()


def _do(page, pid, a, base):
    el = page.locator(C.sel('%s.%s' % (pid, a[1])))
    expect(el).to_be_visible()
    if a[0] == 'click':
        el.click()
    elif a[0] == 'set':
        el.fill(str(a[2]))
    elif a[0] == 'text':
        v = a[2]
        if isinstance(v, dict):
            v = O.frac_text(base['vb']['viewRange'][0 if a[1].startswith('xaxis') else 1], v['frac'])
        el.fill(v)
        el.press('Enter')
    elif a[0] == 'choose':
        el.select_option(index=int(a[2]))
    else:
        raise ValueError(a)


def check_option(page, s, name, panel, option):
    """Option `option` (pg_options) on panel `panel`: the page starts as the PyQt program's walk started that step
    (every panel), the same actions through the page's menu leave every panel as they left the PyQt program's, before
    the last action and after it (view ranges and ViewBox state, axes, each curve as displayed, every menu widget's
    value and enabled state), and the control's own element is on screen."""
    walk, pg, pids = walk_options(name)
    st = next(x for x in pg['steps'] if x['plot'] == panel and x['option'] == option)
    assert not st['errors'], st['errors']
    assert st['reset_diff'] == [], st['reset_diff']
    pid = pids[panel]
    open_page(page, s, name, pg['size'][panel])
    same(st['start'], snapshots(page), 'start')
    acts = st['actions']
    _open_sections(page, pid, acts, st['row'])
    if not acts:
        same(st['pre'], snapshots(page), 'menu open')
    for k, a in enumerate(acts):
        if k == len(acts) - 1:
            same(st['pre'], snapshots(page), 'before %s' % (a,))
        _do(page, pid, a, st['start'][panel])
    same(st['post'], snapshots(page), 'after %s' % (acts[-1:] or 'opening the menu'))
    rid = '%s.%s' % (pid, st['row'])
    expect(page.locator(C.sel(rid))).to_be_visible()
    if not acts:                                    # a display: the page shows the text the walk saw
        x = C.walk_instances(name, walk['file'])[rid]
        el = page.locator(C.sel(rid))
        if x['base'] == 'QLabel':
            expect(el).to_have_text(x['text'])
        else:
            assert el.is_disabled() == (not x['enabled']), (rid, x['enabled'])
    return st


def option_tests(namespace, fixture, name, plot_ids):
    """Define in namespace one test per (panel, option): test_menu_<panel>_<group>_<control>(page, <fixture>);
    returns PARITY_ROWS entries {test: [row]} (row '<plot row id>.<group>.<control>')."""
    rows = {}
    for i, pid in enumerate(plot_ids):
        for o in O.OPTIONS:
            tn = 'test_menu_%d_%s' % (i, o['name'].replace('.', '_'))
            ns = {'_check': check_option}
            exec('def %s(page, %s):\n    _check(page, %s, %r, %d, %r)\n' % (tn, fixture, fixture, name, i, o['name']), ns)
            namespace[tn] = ns[tn]
            rows[tn] = ['%s.%s' % (pid, o['row'])]
    return rows
