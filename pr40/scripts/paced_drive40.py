#!/usr/bin/env python3
"""Drive the DAQ web GUI at a pace a person can follow, for browser recordings that reviewers watch.

usage: paced_drive40.py URL OUTDIR [--highlight 1.2] [--gap 2.7] --flow gui40

--flow gui40 (gui40_flow below): the web copies PR #40 adds, on one daq_webgui, against their backends: seqplot and
seq_epixhr (the plot panels and pyqtgraph's context menu: Plot Options and the axis panels), hsdPs (its phase scan,
run by the server against simhsd and a simxpm, then a menu control), configdb_GUI (the config DB stand-in: select,
edit, Apply, the confirm dialog, the write) and xpmpva (two simxpms: a link loopback box and a group mask written on
XPM 5, the XPM selector, a loopback box on XPM 6).  Plot actions are confirmed from the page's own model
(window.PLOTS), xpmpva writes from the server's API (the values its PV Access client reads), configdb_GUI from the
page's log and its re-read.  What the run writes and leaves is saved in OUTDIR/writes.json for a read-back on the node
by a separate client.  (--flow control, the control GUI run of paced_drive.py, is kept unchanged.)

Pacing, for every action:
  1. the target element gets a red CSS outline and a fixed caption box names the action;
  2. both stay for at least --highlight seconds, and longer if needed so that the action comes at least
     --gap seconds after the previous one;
  3. then the action runs (click, select or typed text), the outline goes, and the driver waits for the page to show
     the action's effect before it starts the next highlight.
The video is Playwright's recording of the page at real speed (OUTDIR/*.webm). Every action is one JSON
line in OUTDIR/actions.jsonl: {n, action, selector, highlight_start, act_time, end, ...}, times in epoch
seconds (plus ISO copies). At the end it prints the action count, min(act_time - highlight_start) and the
smallest gap between consecutive act_times (pace_check.py recomputes them from the log).
"""
import datetime, json, os, subprocess, sys, time
from playwright.sync_api import sync_playwright

# --- as tunnel_drive.py ---------------------------------------------------------------------------
CHROME = os.path.expanduser('~/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome')
P = lambda pid: '[data-parity~="%s"]' % pid
BOX = P('CGWMainControl.box_state')
STATE = P('CGWMainControl.but_ctrls')
EVT = P('CGWMainInfo.edi_evt')
SELECT = P('CGWMainPartition.but_select')
APPLY = P('QWPopupTableCheck.but_apply')
RECORD = P('CGWMainControl.but_record')
ERRWIN = 'QWLoggerError.edi_err'
# ---------------------------------------------------------------------------------------------------

HL_JS = """(el, a) => {
  el.scrollIntoView({block: 'nearest'});
  window.__pacedEl = el;
  window.__pacedPrev = [el.style.outline, el.style.outlineOffset, el.style.boxShadow];
  el.style.outline = '4px solid ' + a.color; el.style.outlineOffset = '2px';
  el.style.boxShadow = '0 0 0 9px ' + a.halo;
  let cap = document.getElementById('paced-caption');
  if (!cap) { cap = document.createElement('div'); cap.id = 'paced-caption'; document.body.appendChild(cap); }
  cap.innerHTML = '';
  const t = document.createElement('div'); t.textContent = a.caption; cap.appendChild(t);
  const s = document.createElement('div'); s.textContent = a.sub;
  s.style.cssText = 'font:400 13px/1.3 DejaVu Sans Mono, monospace; opacity:.8; margin-top:3px'; cap.appendChild(s);
  Object.assign(cap.style, {position: 'fixed', left: '50%', transform: 'translateX(-50%)', zIndex: '2147483647',
    background: 'rgba(18,18,18,.93)', color: '#fff', font: '600 19px/1.3 DejaVu Sans, sans-serif',
    padding: '9px 18px', border: '3px solid ' + a.color, borderRadius: '7px', pointerEvents: 'none',
    maxWidth: '88%', textAlign: 'center', display: 'block', boxShadow: '0 4px 18px rgba(0,0,0,.45)'});
  const r = el.getBoundingClientRect();
  if (r.bottom < window.innerHeight - 170) { cap.style.top = ''; cap.style.bottom = '18px'; }
  else { cap.style.bottom = ''; cap.style.top = '18px'; }
  return true;
}"""
UNHL_JS = """() => {
  const el = window.__pacedEl, p = window.__pacedPrev;
  if (el && p) { el.style.outline = p[0]; el.style.outlineOffset = p[1]; el.style.boxShadow = p[2]; }
  window.__pacedEl = null;
  const cap = document.getElementById('paced-caption'); if (cap) cap.style.display = 'none';
}"""


def iso(t):
    return datetime.datetime.fromtimestamp(t).astimezone().isoformat(timespec='milliseconds')


def api(base, path):
    """GET a JSON route of the server under test (no proxy)."""
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(base.rstrip('/') + path, timeout=10) as r:
        return json.loads(r.read().decode())


def gui40_flow(pg, url, act, note, shot, until):
    """--flow gui40: the web copies PR #40 adds, on one server: /gui/seqplot (panel 0's context menu: Plot Options >
    Transforms > Log Y, Grid > Show Y Grid, X axis min / max typed, then View All; panel 1 follows the X range, as
    setXLink makes it), /gui/seq_epixhr (Power Spectrum (FFT), Y axis > Invert Axis), /gui/hsdPs (the phase scan the
    server ran against simhsd and a simxpm; Grid > Show X / Y Grid), /gui/configdb_GUI (the config DB stand-in: tst/BEAM,
    fakecam_0 + fakecam_1, user.sim_seed, 10794, Read-only off, Apply, OK: the write) and /gui/xpmpva (simxpm XPM 5: tab
    AMC0, LinkLoopback2, LinkGroupMask2 = group 3; the XPM selector to XPM 6 (Kcu1500): tab QSFP0, LinkLoopback1).
    Plot actions are confirmed from the page's model (window.PLOTS.snapshot, the shape of the walk's pg_state), xpmpva
    writes from the server's API (its PV Access client), configdb_GUI from the page's log and its re-read of the DB."""
    import re
    base = url.rstrip('/')
    S = lambda rid: '[data-parity="%s"]' % rid
    click = lambda loc: loc.click()
    say = lambda m: print(f'{iso(time.time())} {m}', flush=True)
    W = {}
    extra = {'writes': W}
    ok = True
    only = [x for x in os.environ.get('GUI40_ONLY', '').split(',') if x]    # rehearsals: only these pages
    run = lambda name: not only or name in only

    # ------------------------------------------------------------------ the plot pages
    def open_plots(name):
        pg.goto(base + '/gui/' + name, timeout=60000)
        pg.wait_for_function('() => document.body.dataset.ready === "1"', timeout=180000)
        pg.wait_for_function('() => document.body.dataset.done === "1"', timeout=300000)
        pg.wait_for_timeout(1500)
        return pg.evaluate('() => window.PLOTS.panels.map((p) => p.id)')

    snap = lambda i: pg.evaluate('(i) => window.PLOTS.snapshot(i)', i)
    fmt = lambda r: '[%.4g, %.4g]' % tuple(r)

    def menu(name, pid, i):
        m = S(pid) + ' .pgmenu'
        return act(f'{name}: right-click plot {i}: the context menu', S(pid) + ' svg',
                   lambda loc: loc.click(button='right', position={'x': 200, 'y': 60}),
                   lambda: (until(lambda: pg.locator(m).first.is_visible(), 10),
                            f'menu shown {pg.locator(m).first.is_visible()}'))

    def section(name, pid, key, title):
        sel = S(pid) + ' [data-menu="%s:%s"]' % (pid, key)
        body = sel + ' + .pgsecb'
        return act(f'{name}: menu "{title}"', sel, click,
                   lambda: (until(lambda: pg.locator(body).first.is_visible(), 10),
                            f'section {title} open {pg.locator(body).first.is_visible()}'))

    def ctl(name, pid, i, c, label, prop, desc):
        """A check box of the menu: confirmed when its widget and the model property prop(snapshot) both flipped."""
        w0 = snap(i)['widgets'][c][0]
        lab = f'{label}: {"on" if not w0 else "off"}'
        return act(f'{name}: plot {i}: {lab}', S(pid + '.' + c), click,
                   lambda: (until(lambda: snap(i)['widgets'][c][0] is (not w0) and bool(prop(snap(i))) is (not w0), 10),
                            f'{c.split(".")[-1]} {w0} -> {snap(i)["widgets"][c][0]}; ' + desc(snap(i))))

    def typed(name, pid, i, c, label, text, check, desc):
        def do(loc):
            loc.fill(text)
            loc.press('Enter')
        return act(f'{name}: plot {i}: {label}: type {text}, Enter', S(pid + '.' + c), do,
                   lambda: (until(lambda: check(), 10), desc()))

    # ---- /gui/seqplot: the program's own sequence engine on 33k_35k.py and 10k.py
    if run('seqplot'):
        pids = open_plots('seqplot')
        s0, s1 = snap(0), snap(1)
        x0 = s0['vb']['viewRange'][0]
        say(f'open /gui/seqplot: panels {pids}; x range {fmt(x0)} (panel 1 {fmt(s1["vb"]["viewRange"][0])}); '
            f'curves {len(s0["curves"])} + {len(s1["curves"])}')
        p0 = pids[0]
        ok &= menu('seqplot', p0, 0)
        ok &= section('seqplot', p0, 'options', 'Plot Options')
        ok &= section('seqplot', p0, 'transforms', 'Transforms')
        ok &= ctl('seqplot', p0, 0, 'ctrl.logYCheck', 'Log Y', lambda s: s['axes']['left']['logMode'],
                  lambda s: f'left axis logMode {s["axes"]["left"]["logMode"]}; y range {fmt(s["vb"]["viewRange"][1])}')
        ok &= section('seqplot', p0, 'grid', 'Grid')
        ok &= ctl('seqplot', p0, 0, 'ctrl.yGridCheck', 'Show Y Grid', lambda s: s['axes']['left']['grid'] not in (False, None, 0),
                  lambda s: f'left axis grid {s["axes"]["left"]["grid"]}')
        shot('seqplot-logy-grid')
        ok &= section('seqplot', p0, 'xaxis', 'X axis')
        lo, hi = x0[0] + 0.2 * (x0[1] - x0[0]), x0[0] + 0.4 * (x0[1] - x0[0])
        tlo, thi = '%.4g' % lo, '%.4g' % hi
        near = lambda a, b: abs(a - b) <= 1e-9 + 1e-6 * abs(b)
        ok &= typed('seqplot', p0, 0, 'xaxis.minText', 'X axis min', tlo,
                    lambda: near(snap(0)['vb']['viewRange'][0][0], float(tlo)),
                    lambda: f'panel 0 x {fmt(snap(0)["vb"]["viewRange"][0])}')
        ok &= typed('seqplot', p0, 0, 'xaxis.maxText', 'X axis max', thi,
                    lambda: near(snap(0)['vb']['viewRange'][0][1], float(thi)) and
                    snap(1)['vb']['viewRange'][0] == snap(0)['vb']['viewRange'][0],
                    lambda: f'panel 0 x {fmt(snap(0)["vb"]["viewRange"][0])}, panel 1 x {fmt(snap(1)["vb"]["viewRange"][0])} '
                            f'(setXLink)')
        shot('seqplot-xrange')
        va = S(p0) + ' .pgmenu > button.pgsech'
        ok &= act('seqplot: plot 0: View All', va, click,
                  lambda: (until(lambda: all(near(a, b) for a, b in zip(snap(0)['vb']['viewRange'][0], x0)), 10),
                           f'panel 0 x {fmt(snap(0)["vb"]["viewRange"][0])}, panel 1 x {fmt(snap(1)["vb"]["viewRange"][0])}'))
        extra['seqplot'] = {'panels': pids, 'x0': x0, 'typed': [tlo, thi]}

    # ---- /gui/seq_epixhr: seq_epixhr --test --plot --rate 1000
    if run('seq_epixhr'):
        pids = open_plots('seq_epixhr')
        s0 = snap(0)
        say(f'open /gui/seq_epixhr: panels {pids}; x range {fmt(s0["vb"]["viewRange"][0])}; curves {len(s0["curves"])}')
        p0 = pids[0]
        ok &= menu('seq_epixhr', p0, 0)
        ok &= section('seq_epixhr', p0, 'options', 'Plot Options')
        ok &= section('seq_epixhr', p0, 'transforms', 'Transforms')
        ok &= ctl('seq_epixhr', p0, 0, 'ctrl.fftCheck', 'Power Spectrum (FFT)',
                  lambda s: s['widgets']['ctrl.fftCheck'][0],
                  lambda s: f'x range {fmt(s["vb"]["viewRange"][0])}')
        ok &= section('seq_epixhr', p0, 'yaxis', 'Y axis')
        ok &= ctl('seq_epixhr', p0, 0, 'yaxis.invertCheck', 'Y axis: Invert Axis', lambda s: s['vb']['yInverted'],
                  lambda s: f'yInverted {s["vb"]["yInverted"]}')
        shot('seq_epixhr-fft-inverted')

    # ---- /gui/hsdPs: the phase scan the server ran with hsdPs's own main() against simhsd and simxpm XPM 7
    if run('hsdPs'):
        pids = open_plots('hsdPs')
        sp = api(base, '/api/plots/spec?gui=hsdPs')
        npts = [len(c['x']) for p in sp.get('plots', []) for c in p['curves']]
        say(f'open /gui/hsdPs: argv {" ".join(sp.get("argv", []))}; done {sp.get("done")}, error {sp.get("error")}; '
            f'simhsd pid {sp.get("sim_pid")}; curves {len(npts)} with {npts} points; statusbar '
            f'{pg.text_content("#statusbar")!r}')
        note('hsdPs: the scan ran in the server (phases 0, 8, 16): early and late fractions per phase', S(pids[0]))
        pg.wait_for_timeout(2500)
        pg.evaluate(UNHL_JS)
        shot('hsdps-scan')
        p0 = pids[0]
        ok &= menu('hsdPs', p0, 0)
        ok &= section('hsdPs', p0, 'options', 'Plot Options')
        ok &= section('hsdPs', p0, 'grid', 'Grid')
        ok &= ctl('hsdPs', p0, 0, 'ctrl.xGridCheck', 'Show X Grid', lambda s: s['axes']['bottom']['grid'] not in (False, None, 0),
                  lambda s: f'bottom axis grid {s["axes"]["bottom"]["grid"]}')
        ok &= ctl('hsdPs', p0, 0, 'ctrl.yGridCheck', 'Show Y Grid', lambda s: s['axes']['left']['grid'] not in (False, None, 0),
                  lambda s: f'left axis grid {s["axes"]["left"]["grid"]}')
        a = sp.get('argv', [])
        if '--range' in a and '--base' in a:
            r0, r1, st = (int(v) for v in a[a.index('--range') + 1:a.index('--range') + 4])
            W['scan:%s:RESET.mmcmphase' % a[a.index('--base') + 1]] = list(range(r0, r1, st))[-1]

    # ---- /gui/configdb_GUI: the config DB stand-in (configdb_server --seed-gui on 127.0.0.1:47321)
    if run('configdb_GUI'):
        G = 'ConfigdbGUI._build_ui.'
        SEED = '#params tr[data-path="user.sim_seed"] td'
        pg.goto(base + '/gui/configdb_GUI', timeout=60000)
        pg.wait_for_function('() => document.body.dataset.ready === "1"', timeout=60000)
        until(lambda: pg.locator('#hutches tr').count() > 0, 30)
        pg.wait_for_timeout(1200)
        say(f'open /gui/configdb_GUI: target {pg.text_content(S(G + "target_label"))!r}; '
            f'hutch/alias rows {pg.locator("#hutches tr").count()}')
        ok &= act('configdb_GUI: alias tst / BEAM', '#hutches tr[data-alias="BEAM"]', click,
                  lambda: (until(lambda: pg.locator('#devices tr').count() >= 3, 15),
                           f'detectors {[d for d in pg.locator("#devices tr").evaluate_all("(rs) => rs.map((r) => r.dataset.device)")]}'))
        for k, d in enumerate(('fakecam_0', 'fakecam_1')):
            ok &= act(f'configdb_GUI: {"Ctrl-click" if k else "click"} detector {d}', '#devices tr[data-device="%s"]' % d,
                      (lambda loc: loc.click(modifiers=['Control'])) if k else click,
                      lambda d=d: (until(lambda: pg.locator('#devices tr[data-device="%s"].sel' % d).count() == 1, 15),
                                   f'{d} selected'))
        ok &= act('configdb_GUI: expand "user *"', '#params tr[data-node="/user *"] .tw', click,
                  lambda: (until(lambda: pg.locator('#params tr[data-path="user.sim_seed"]').first.is_visible(), 15),
                           'user.sim_seed shown'))
        ok &= act('configdb_GUI: parameter user.sim_seed', '#params tr[data-path="user.sim_seed"]', click,
                  lambda: (until(lambda: (pg.text_content(S(G + 'path_label')) or '').strip() == 'user.sim_seed', 15),
                           f'path {pg.text_content(S(G + "path_label"))!r}; values '
                           f'{pg.locator(SEED).all_text_contents()}'))
        ok &= act('configdb_GUI: type 10794 in the value field', S(G + 'value_edit'), lambda loc: loc.fill('10794'),
                  lambda: (pg.locator(S(G + 'value_edit')).input_value() == '10794',
                           f'value field {pg.locator(S(G + "value_edit")).input_value()!r}'))
        ok &= act('configdb_GUI: Read-only off (writing on)', S(G + 'write_box'), click,
                  lambda: (until(lambda: not pg.locator(S(G + 'write_box')).is_checked() and
                                 pg.locator(S(G + 'apply_button')).is_enabled(), 15),
                           f'Read-only checked {pg.locator(S(G + "write_box")).is_checked()}; Apply enabled '
                           f'{pg.locator(S(G + "apply_button")).is_enabled()}; target {pg.text_content(S(G + "target_label"))!r}'))
        ok &= act('configdb_GUI: Apply', S(G + 'apply_button'), click,
                  lambda: (until(lambda: pg.locator('#confirm').is_visible(), 15),
                           f'confirm: {(pg.text_content("#confirmHead") or "").strip()!r}; rows '
                           f'{pg.locator("#confirmRows tr").evaluate_all("(rs) => rs.map((r) => [...r.cells].map((c) => c.textContent))")}'))
        shot('configdb-confirm')
        log = S(G + 'log')
        ok &= act('configdb_GUI: OK: write', '#confirmOk', click,
                  lambda: (until(lambda: '1 written, 0 failed, 0 skipped' in (pg.text_content(log) or '') and
                                 pg.locator('#params tr[data-path="user.sim_seed"] td').nth(2).text_content() == '10794', 40),
                           f'log {[l for l in (pg.text_content(log) or "").splitlines() if "written" in l or "writing" in l][-2:]}; '
                           f're-read {pg.locator(SEED).all_text_contents()}'))
        shot('configdb-written')
        for d in ('fakecam_0', 'fakecam_1'):
            W['cdb:tst/BEAM/%s:user.sim_seed' % d] = 10794

    # ---- /gui/xpmpva: simxpm XPM 5 (xtpg: ATCA, CuTiming, AMC0/AMC1) and XPM 6 (Kcu1500: QSFP0/QSFP1)
    if run('xpmpva'):
        spec = api(base, '/api/pvgui/spec?gui=xpmpva')
        paths, nodes = {}, {}

        def walkt(n, path):
            if n is None:
                return
            if n.get('id'):
                paths.setdefault(n['id'], list(path))
                nodes.setdefault(n['id'], n)
            if n['type'] == 'stack':
                for i, c in enumerate(n['children']):
                    walkt(c, path + [('stack', n['select'], i)])
                return
            for c in n.get('children', []):
                walkt(c, path)
            for r in n.get('rows', []):
                for c in r:
                    walkt(c, path)
            for t in n.get('tabs', []):
                paths.setdefault(t['id'], list(path))
                walkt(t['child'], path + [('tab', t['id'])])
        walkt(spec['tree'], [])
        find = lambda pv, typ: next(k for k, n in nodes.items() if n.get('pv') == pv and n['type'] == typ)
        def vals():
            """the server's values (its PV Access client); the page's ~2400 PVs make this read slow, so wait and retry"""
            import urllib.request
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for k in range(4):
                try:
                    with op.open(base + '/api/pvgui/values?gui=xpmpva', timeout=60) as r:
                        return json.loads(r.read().decode())['values']
                except Exception as e:
                    say(f'values API: {type(e).__name__}; retry {k + 1}')
            raise RuntimeError('values API did not answer')
        V = lambda v: v['value'] if isinstance(v, dict) and 'value' in v and not isinstance(v['value'], dict) else v

        def reveal(rid):
            r = True
            for step in paths[rid]:
                if step[0] == 'tab':
                    t = pg.locator(S(step[1]))
                    if t.get_attribute('aria-selected') != 'true':
                        title = re.search(r'\.tab\[(.*)\](#\d+)?$', step[1]).group(1)
                        r &= act(f'xpmpva: tab {title}', S(step[1]), click,
                                 lambda t=t, title=title: (until(lambda: t.get_attribute('aria-selected') == 'true', 10),
                                                           f'tab {title} selected'))
                else:
                    s = pg.locator(S(step[1]))
                    if s.input_value() != str(step[2]):
                        label = s.locator('option').nth(step[2]).text_content()
                        r &= act(f'xpmpva: XPM selector: {label}', S(step[1]),
                                 lambda loc, i=step[2]: loc.select_option(str(i)),
                                 lambda s=s, i=step[2], label=label: (until(lambda: s.input_value() == str(i), 10),
                                                                      f'{label} shown'))
            return r

        def write(label, rid, do, want, shown):
            """An action that writes the widget's PV: confirmed by the server's reply to the page's put (the PV and value it
            put through its PV Access client), then by the page showing it after its next polls; recorded for the read-back."""
            pv = nodes[rid]['pv']
            res = {}

            def do2(loc):
                with pg.expect_response(lambda r: '/api/pvgui/put' in r.url, timeout=60000) as ri:
                    do(loc)
                res['rep'] = ri.value.json()

            def confirm():
                rep = res.get('rep') or {}
                puts = rep.get('puts') or []
                ok = bool(rep.get('ok')) and bool(puts) and puts[-1] == [pv, want]
                ok = ok and until(lambda: shown(pg.locator(S(rid))), 15)
                return ok, (f'server put {puts[-1][0]} = {puts[-1][1]} (ok {rep.get("ok")}); page shows it' if puts
                            else f'server reply {rep}')
            r = act(f'xpmpva: {label}', S(rid), do2, confirm, sub=f'{S(rid)}  {pv}')
            W['pv:' + pv] = want
            return r

        pg.goto(base + '/gui/xpmpva', timeout=60000)
        pg.wait_for_function('() => document.body.dataset.ready === "1" && +document.body.dataset.polls >= 2', timeout=60000)
        pg.wait_for_timeout(1200)
        v0 = vals()
        say(f'open /gui/xpmpva {spec.get("argv")}: FwBuild XPM 5 {V(v0.get("DAQ:SIM:XPM:5:FwBuild"))!r}, '
            f'XPM 6 {V(v0.get("DAQ:SIM:XPM:6:FwBuild"))!r}; page polls so far {pg.get_attribute("body", "data-polls")}')
        lb5 = find('DAQ:SIM:XPM:5:LinkLoopback2', 'pvcheck')
        gm5 = find('DAQ:SIM:XPM:5:LinkGroupMask2', 'groupmask')
        lb6 = find('DAQ:SIM:XPM:6:LinkLoopback1', 'pvcheck')
        ok &= reveal(lb5)
        b = pg.locator(S(lb5)).is_checked()
        ok &= write('XPM 5 LinkLoopback2 box', lb5, click, 0 if b else 1, lambda loc, b=b: loc.is_checked() is (not b))
        ok &= write('XPM 5 LinkGroupMask2: group 3', gm5, lambda loc: loc.select_option('4'), 8,
                    lambda loc: loc.input_value() == '4')
        shot('xpmpva-xpm5-amc0')
        ok &= reveal(lb6)
        b = pg.locator(S(lb6)).is_checked()
        ok &= write('XPM 6 LinkLoopback1 box', lb6, click, 0 if b else 1, lambda loc, b=b: loc.is_checked() is (not b))
        pg.wait_for_timeout(1500)
        shot('xpmpva-xpm6-qsfp0')
    say(f'writes left for the read-back on the node: {json.dumps(W)}')
    return bool(ok), extra


def main():
    url, out = sys.argv[1], sys.argv[2]
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
    events = int(arg('--events', '1100'))
    HL = float(arg('--highlight', '1.2'))
    GAP = float(arg('--gap', '2.7'))
    det = arg('--detector', 'fakecam_0')
    flow = arg('--flow', 'control')
    os.makedirs(out, exist_ok=True)
    W, H = 960, 1180
    log = open(os.path.join(out, 'actions.jsonl'), 'w')
    acts, shots = [], []
    last = {'act': None}
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME, headless=True, args=['--no-proxy-server'])
        t_ctx = time.time()
        ctx = b.new_context(viewport={'width': W, 'height': H}, record_video_dir=out,
                            record_video_size={'width': W, 'height': H})
        pg = ctx.new_page()
        print(f'{iso(time.time())} browser: headless Chromium {b.version} on {os.uname().nodename}, URL {url}; '
              f'highlight >= {HL} s, gap >= {GAP} s', flush=True)

        def state():
            return (pg.text_content(STATE) or '').strip()

        def evt():
            e = pg.locator(EVT)
            return e.text_content(), e.get_attribute('data-final'), e.get_attribute('data-source')

        def until(pred, timeout=60):
            t0 = time.time()
            while time.time() - t0 < timeout:
                if pred():
                    return True
                pg.wait_for_timeout(100)
            return False

        def shot(tag):
            p = os.path.join(out, f'{len(shots) + 1:02d}-{tag}.png')
            try:
                pg.screenshot(path=p, full_page=False)      # viewport only: no resize, so the video is not disturbed
                shots.append(p)
            except Exception as e:
                print(f'{iso(time.time())} screenshot {tag}: {str(e).splitlines()[0]}', flush=True)

        def act(action, sel, do, confirm, sub=None):
            """Highlight sel, hold, do(locator), then wait for confirm() -> (ok, text)."""
            loc = pg.locator(sel).first
            loc.wait_for(state='visible', timeout=60000)
            hs = time.time()
            loc.evaluate(HL_JS, {'caption': action, 'sub': sub or sel, 'color': '#ff2d55',
                                 'halo': 'rgba(255,45,85,.28)'})
            t_act = max(hs + HL, last['act'] + GAP if last['act'] else 0.0)
            while time.time() < t_act:
                pg.wait_for_timeout(max(10, int((t_act - time.time()) * 1000)))
            at = time.time()
            do(loc)
            pg.wait_for_timeout(350)                          # the outline stays a moment on what was clicked
            pg.evaluate(UNHL_JS)
            ok, res = confirm()
            end = time.time()
            rec = {'n': len(acts) + 1, 'action': action, 'selector': sel, 'highlight_start': round(hs, 3),
                   'act_time': round(at, 3), 'end': round(end, 3), 'hold_s': round(at - hs, 3),
                   'gap_s': round(at - last['act'], 3) if last['act'] else None, 'ok': ok, 'result': res,
                   'highlight_start_iso': iso(hs), 'act_time_iso': iso(at), 'end_iso': iso(end)}
            log.write(json.dumps(rec) + '\n'); log.flush()
            acts.append(rec)
            last['act'] = at
            gap = f'{rec["gap_s"]:5.2f}' if rec['gap_s'] is not None else '    -'
            print(f'{rec["act_time_iso"]} #{rec["n"]:<2} {action:<52} hold {rec["hold_s"]:.2f} s  gap {gap} s'
                  f'  -> {res} {"OK" if ok else "FAILED"}', flush=True)
            return ok

        def note(text, sel):
            """A caption with a blue outline while the driver waits (not an action; not in actions.jsonl)."""
            pg.locator(sel).first.evaluate(HL_JS, {'caption': text, 'sub': sel, 'color': '#2d8cff',
                                                   'halo': 'rgba(45,140,255,.25)'})

        def st_is(target):
            return lambda: (until(lambda: state().upper() == target.upper()), f'page state {state()}')

        click = lambda loc: loc.click()
        choose = lambda target: (lambda loc: loc.select_option(target))
        row = lambda alias: '#select_table tr[data-alias="%s"]' % alias
        ID = row(det) + ' ' + P('CGWMainPartition.w_select.id')
        seg2 = det.rsplit('_', 1)[0] + '_1'

        extra = {}
        if flow == 'gui40':
            ok, extra = gui40_flow(pg, url, act, note, shot, until)
            v = v2 = None
            errs = []
        else:
            pg.goto(url, timeout=60000)
            pg.wait_for_selector('body[data-ready="1"]', timeout=60000)
            print(f'{iso(time.time())} open -> page ready; state {state()}; backend {pg.text_content("#backend")!r}', flush=True)
            pg.wait_for_timeout(1500)
            shot('open')
            ok = act('Click Select: open the partition selection', SELECT, click,
                     lambda: (until(lambda: state().upper() == 'UNALLOCATED') and
                              until(lambda: pg.locator(row(det)).is_visible()), f'page state {state()}, select table shown'))
            ok &= act(f'Click the ID of {det}: expand its 2 segments', ID, click,
                      lambda: (until(lambda: pg.locator(row(seg2)).is_visible(), 15),
                               f'{seg2} row shown: {pg.locator(row(seg2)).is_visible()}'),
                      sub=f'{row(det)} {P("CGWMainPartition.w_select.id")}')
            shot('segments-expanded')
            ok &= act(f'Click the ID of {det} again: collapse the segments', ID, click,
                      lambda: (until(lambda: not pg.locator(row(seg2)).is_visible(), 15),
                               f'{seg2} row shown: {pg.locator(row(seg2)).is_visible()}'),
                      sub=f'{row(det)} {P("CGWMainPartition.w_select.id")}')
            shot('segments-collapsed')
            ok &= act('Click Apply: allocate the partition', APPLY, click, st_is('ALLOCATED'))
            rec = pg.locator(RECORD)
            if rec.get_attribute('aria-pressed') != 'true':
                ok &= act('Click Record: turn recording on', RECORD, click,
                          lambda: (until(lambda: rec.get_attribute('aria-pressed') == 'true', 30),
                                   f'record aria-pressed {rec.get_attribute("aria-pressed")}'))
            shot('allocated-record-on')
            for s in ('CONNECTED', 'CONFIGURED', 'STARTING', 'PAUSED', 'RUNNING'):
                ok &= act(f'Choose {s} in the state box', BOX, choose(s), st_is(s))
            note(f'RUNNING: waiting until the page shows >= {events} events', EVT)
            t1 = time.time()
            while time.time() - t1 < 180:
                v, fin, src = evt()
                if v and v.isdigit() and int(v) >= events:
                    break
                pg.wait_for_timeout(200)
            print(f'{iso(time.time())} RUNNING: page events {v} (source {src}) >= {events}', flush=True)
            pg.wait_for_timeout(600)
            pg.evaluate(UNHL_JS)
            shot('running')
            ok &= act('Choose PAUSED in the state box: Disable', BOX, choose('PAUSED'), st_is('PAUSED'))
            until(lambda: evt()[1] == '1', 20)
            pg.wait_for_timeout(1500)
            v, fin, src = evt()
            print(f'{iso(time.time())} after Disable: page events {v}, data-final {fin}, source {src}', flush=True)
            shot('disabled')
            for s in ('STARTING', 'CONFIGURED', 'CONNECTED', 'ALLOCATED', 'RESET'):
                ok &= act(f'Choose {s} in the state box', BOX, choose(s), st_is(s))
            pg.wait_for_timeout(2000)
            v2, fin2, _ = evt()
            errs = pg.evaluate("""(id) => { const e = document.querySelector('[data-parity~="' + id + '"]');
                return e ? Array.from(e.childNodes).map(n => n.textContent.trim()).filter(l => l && !/^_+$/.test(l)) : []; }""",
                               ERRWIN)
            print(f'{iso(time.time())} after RESET: page events {v2}, data-final {fin2}; error window lines: {len(errs)} {errs[:3]}',
                  flush=True)
            shot('reset')
        vid = pg.video.path()
        ctx.close()
        t_close = time.time()
        b.close()
    log.close()
    dur = None
    try:
        dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', vid],
                                   capture_output=True, text=True).stdout.strip())
    except Exception:
        pass
    holds = [a['act_time'] - a['highlight_start'] for a in acts]
    gaps = [b_['act_time'] - a['act_time'] for a, b_ in zip(acts, acts[1:])]
    res = {'flow': flow, 'events_after_disable': v, 'events_after_reset': v2, 'ok': bool(ok), 'video': str(vid),
           'video_s': dur, 'wall_s': round(t_close - t_ctx, 2), 'actions': len(acts),
           'min_highlight_to_act_s': round(min(holds), 3), 'min_gap_s': round(min(gaps), 3), 'shots': shots,
           'error_window_lines': errs}
    res.update(extra)
    json.dump(res, open(os.path.join(out, 'result.json'), 'w'), indent=1)
    print(f'video {os.path.basename(vid)}: {dur if dur is None else round(dur, 1)} s; browser context open {res["wall_s"]} s '
          f'(real speed: the video spans the whole context)', flush=True)
    if flow == 'gui40':
        json.dump(extra['writes'], open(os.path.join(out, 'writes.json'), 'w'))
        print(f'GUI_FLOW_OK={bool(ok)}  WRITES={len(extra["writes"])} values -> {os.path.join(out, "writes.json")}', flush=True)
    else:
        print(f'PAGE_EVENTS_FINAL={v2}  ALL_STATES_OK={bool(ok)}', flush=True)
    print(f'ACTIONS={len(acts)}  MIN_HIGHLIGHT_TO_ACT={min(holds):.3f} s  MIN_GAP_BETWEEN_ACTS={min(gaps):.3f} s', flush=True)
    return 0 if ok else 1


sys.exit(main())
