"""Checks shared by the headless-browser tests of the pvgui pages (web copies of the pvedit GUIs: deadca, partca,
xpmpatt, ...), against the simulated DAQ.  Each check drives or reads every widget of one node type on the page and
compares it with the PVs read independently of the server under test (webgui_harness.pva) and, for combo choices,
with the offscreen walk of the PyQt program (check_gui_parity.run_walks, once per session).

  by_type(PAGE)                        {node type: [ids]}
  open_page(page, s, name)             load /gui/<name>, wait for two polls
  reveal(page, PAGE, rid)              click the tabs and select the stack pages that hold widget rid
  walk_instances(spec, file)           {row id: walk instance} of the PyQt program's walk this session
  check_*(...)                         one node type each (see the docstrings)
"""

import json
import os
import subprocess
import threading
import time

from playwright.sync_api import expect

import webgui_harness as H
from psdaq.webgui.pvgui import text_of

T = H.UI_TIMEOUT


def sel(rid):
    return '[data-parity="%s"]' % rid


def by_type(PAGE):
    out = {}
    for nid, n in sorted(PAGE.nodes.items()):
        out.setdefault(n['type'], []).append(nid)
    return out


def open_page(page, s, name):
    page.goto(s.url.rstrip('/') + '/gui/' + name)
    page.wait_for_function('() => document.body.dataset.ready === "1" && +document.body.dataset.polls >= 2', timeout=T)


def paths(PAGE):
    """{node id: [('tab', tab id) | ('stack', select id, index), ...]} outermost first."""
    out = {}

    def walk(n, path):
        if n is None:
            return
        if n.get('id'):
            out.setdefault(n['id'], list(path))
        for b in n.get('bits', []):
            out[b['id']] = list(path)
        if n['type'] == 'stack':
            for i, c in enumerate(n['children']):
                walk(c, path + [('stack', n['select'], i)])
            return
        for c in n.get('children', []):
            walk(c, path)
        for r in n.get('rows', []):
            for c in r:
                walk(c, path)
        for t in n.get('tabs', []):
            walk(t['child'], path + [('tab', t['id'])])
    walk(PAGE.tree, [])
    return out


_PATHS = {}


def reveal(page, PAGE, rid, visible=True):
    key = id(PAGE)
    if key not in _PATHS:
        _PATHS[key] = paths(PAGE)
    for step in _PATHS[key].get(rid, []):
        if step[0] == 'tab':
            t = page.locator(sel(step[1]))
            if t.get_attribute('aria-selected') != 'true':
                t.click()
        else:
            s = page.locator(sel(step[1]))
            if s.input_value() != str(step[2]):
                s.select_option(str(step[2]))
    if visible:
        expect(page.locator(sel(rid))).to_be_visible()


def server_values(s, name):
    return s.get('/api/pvgui/values?gui=' + name)['values']


def wait_server(s, name, pv, want, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if server_values(s, name).get(pv) == want:
            return
        time.sleep(0.1)
    raise AssertionError('%s = %r, expected %r' % (pv, server_values(s, name).get(pv), want))


def walk_instances(spec_name, file):
    """{row id: instance of the PyQt walk} for the program `file` (rel. to psdaq), from this session's walks."""
    from psdaq.webgui.parity import check_gui_parity, gui_rows, qapps
    src = qapps.default_src()
    spec = next(s for s in check_gui_parity.load_specs().values() if s['_name'] == spec_name)
    with open(check_gui_parity.walk_path(spec, H.gui_walks())) as f:
        walk = json.load(f)
    rows = gui_rows.make_rows(gui_rows.source_sites(src, file), walk)
    inst = {x['seq']: x for x in walk['instances']}
    return {r['id']: inst.get(r.get('instance')) for r in rows}


# ------------------------------------------------------------------ checks, one per node type

def check_texts(page, PAGE, rows, timeout=20):
    """Every 'text' row shows text_of(node, value) for the value of its PV read independently now (retried until
    one read and the page agree on all rows: the simulator posts once a second)."""
    pvs = sorted(set(PAGE.nodes[r]['pv'] for r in rows))
    t0 = time.time()
    bad = None
    while time.time() - t0 < timeout:
        want = H.pva('get', pvs)
        shown = page.evaluate('(ids) => ids.map(i => { const e = document.querySelector(`[data-parity="${i}"]`); '
                              'return e ? e.textContent : null; })', rows)
        exp = [text_of(PAGE.nodes[r], want[PAGE.nodes[r]['pv']]) for r in rows]
        bad = [(r, s, e) for r, s, e in zip(rows, shown, exp) if s != e]
        if not bad:
            return want
        time.sleep(0.3)
    raise AssertionError('%d of %d displays differ from the PVs, e.g. %s' % (len(bad), len(rows), bad[:5]))


def check_pvchecks(page, s, name, PAGE, rows):
    """PvCheckBox: shows value != 0; a click puts 1 / 0; a second click puts the value back."""
    pvs = [PAGE.nodes[r]['pv'] for r in rows]
    before = H.pva('get', pvs)
    for r in rows:
        reveal(page, PAGE, r)
        cb = page.locator(sel(r))
        pv = PAGE.nodes[r]['pv']
        expect(cb).to_be_checked(checked=before[pv] != 0, timeout=T)
        cb.click()
        wait_server(s, name, pv, 0 if before[pv] else 1)
    after = H.pva('get', pvs)
    assert after == {pv: (0 if v else 1) for pv, v in before.items()}, (before, after)
    for r in rows:
        reveal(page, PAGE, r)
        page.locator(sel(r)).click()
        wait_server(s, name, PAGE.nodes[r]['pv'], before[PAGE.nodes[r]['pv']])
    assert H.pva('get', pvs) == before


def check_pvints(page, s, name, PAGE, rows, base=100):
    """PvEditInt: shows int(value); Enter puts int(text); text that is not an integer puts nothing."""
    pvs = [PAGE.nodes[r]['pv'] for r in rows]
    before = H.pva('get', pvs)
    want = {}
    try:
        for k, r in enumerate(rows):
            reveal(page, PAGE, r)
            f = page.locator(sel(r))
            pv = PAGE.nodes[r]['pv']
            expect(f).to_have_value(str(int(before[pv])), timeout=T)
            v = base + k
            f.fill(str(v))
            f.press('Enter')
            want[pv] = v
            wait_server(s, name, pv, v)
        reveal(page, PAGE, rows[0])
        f = page.locator(sel(rows[0]))
        f.fill('not a number')
        f.press('Enter')
        time.sleep(0.5)
        assert H.pva('get', pvs) == want
    finally:
        H.pva('put', [[pv, v] for pv, v in before.items()])


def check_combos(page, s, name, PAGE, rows, walk):
    """PvEditCmb: the PyQt combo's items (walk); a choice puts its index; every index of the stack selectors."""
    pvs = sorted(set(PAGE.nodes[r]['pv'] for r in rows))
    before = H.pva('get', pvs)
    try:
        for r in rows:
            n = PAGE.nodes[r]
            reveal(page, PAGE, r)
            c = page.locator(sel(r))
            opts = c.locator('option').all_inner_texts()
            assert opts == walk[r]['choices'], (r, opts, walk[r]['choices'])
            cur = int(c.input_value())
            if n['pv'].endswith('L0Select') or n['pv'].endswith('_Sequence'):
                continue                       # stack selectors: they stay where reveal() put them
            new = (cur + 1) % len(opts)
            c.select_option(str(new))
            wait_server(s, name, n['pv'], new)
            assert int(c.input_value()) == new
        for r in [x for x in rows if PAGE.nodes[x]['pv'].endswith(('L0Select', '_Sequence'))]:
            reveal(page, PAGE, r)
            c = page.locator(sel(r))
            for i in range(len(PAGE.nodes[r]['choices'])):
                c.select_option(str(i))
                wait_server(s, name, PAGE.nodes[r]['pv'], i)
            pv = PAGE.nodes[r]['pv']
            assert H.pva('get', [pv])[pv] == len(PAGE.nodes[r]['choices']) - 1
    finally:
        H.pva('put', [[pv, v] for pv, v in before.items()])


def check_maskbits(page, s, name, PAGE, rows):
    """PvMaskTab / PvDstTab: bit n of the mask PV; a click toggles it and puts the mask."""
    pvs = sorted(set(PAGE.nodes[r]['pv'] for r in rows))
    before = H.pva('get', pvs)
    expect_v = dict(before)
    try:
        for r in rows:
            pv = PAGE.nodes[r]['pv']
            bit = int(r.rsplit('#', 1)[1])
            reveal(page, PAGE, r)
            expect(page.locator(sel(r))).to_be_checked(checked=bool(expect_v[pv] & (1 << bit)), timeout=T)
            page.locator(sel(r)).click()
            expect_v[pv] ^= 1 << bit
            wait_server(s, name, pv, expect_v[pv])
        assert H.pva('get', pvs) == expect_v
    finally:
        H.pva('put', [[pv, v] for pv, v in before.items()])


class Watch:
    """Every value the PVs take while the watch runs (a p4p monitor in a subprocess, independent of the server)."""

    CODE = ('import json,sys,os,time\n'
            'from p4p.client.thread import Context\n'
            'from psdaq.webgui.netguard import require_loopback_pva_env\n'
            'c=Context("pva",conf=require_loopback_pva_env(os.environ),useenv=False)\n'
            'def cb(v,n):\n'
            '    print(json.dumps([n, None if isinstance(v,Exception) else (v.tolist() if hasattr(v,"tolist") else v)]),flush=True)\n'
            'subs=[c.monitor(n,(lambda v,n=n: cb(v,n)),notify_disconnect=True) for n in json.loads(sys.argv[1])]\n'
            'print(json.dumps(["ready",None]),flush=True)\n'
            'sys.stdin.read()\n')

    def __init__(self, pvs):
        self.seen = {pv: [] for pv in pvs}
        self.p = subprocess.Popen([H.SERVER_PYTHON, '-c', self.CODE, json.dumps(list(pvs))], env=H.server_env(),
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.ready = threading.Event()
        self.t = threading.Thread(target=self._read, daemon=True)
        self.t.start()
        if not self.ready.wait(20):
            raise RuntimeError('PV watch did not start')
        time.sleep(1.0)                        # the first (current) value of each PV

    def _read(self):
        for line in self.p.stdout:
            n, v = json.loads(line)
            if n == 'ready':
                self.ready.set()
            elif n in self.seen and v is not None:     # None: (dis)connect events of the monitor
                self.seen[n].append(v)

    def stop(self):
        self.p.stdin.close()
        self.p.wait(10)
        return self.seen


def check_pvbuttons(page, PAGE, rows):
    """PvPushButton: a click puts 1, then 0 (seen by an independent monitor of the PV)."""
    pvs = [PAGE.nodes[r]['pv'] for r in rows]
    w = Watch(pvs)
    try:
        n0 = {pv: len(v) for pv, v in w.seen.items()}
        for r in rows:
            reveal(page, PAGE, r)
            expect(page.locator(sel(r))).to_have_text(PAGE.nodes[r]['label'])
            page.locator(sel(r)).click()
            pv = PAGE.nodes[r]['pv']
            t0 = time.time()
            while time.time() - t0 < 10 and w.seen[pv][n0[pv]:][-2:] != [1, 0]:
                time.sleep(0.1)
    finally:
        seen = w.stop()
    for r in rows:
        pv = PAGE.nodes[r]['pv']
        assert seen[pv][n0[pv]:] == [1, 0], (r, seen[pv])


def check_tabs(page, PAGE, tab_ids, walk):
    """Each tab selects its panel; the titles are the PyQt QTabWidget's (walk)."""
    import re
    for t in tab_ids:
        reveal(page, PAGE, t)
        page.locator(sel(t)).click()
        expect(page.locator(sel(t))).to_have_attribute('aria-selected', 'true')
        title = re.search(r'\[(.*)\]$', t).group(1)
        assert page.locator(sel(t)).inner_text() == title
        stem = t.rsplit('.tab[', 1)[0]
        inst = next(x for k, x in walk.items() if k.startswith(stem + '.tab['))
        assert title in inst['tabs'], (t, inst['tabs'])
