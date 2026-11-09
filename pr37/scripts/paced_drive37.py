#!/usr/bin/env python3
"""Drive the DAQ web GUI at a pace a person can follow, for browser recordings that reviewers watch.

usage: paced_drive37.py URL OUTDIR [--highlight 1.2] [--gap 2.7] --flow gui37

--flow gui37 (gui37_flow below): the web copies of PR #37's GUIs on one daq_webgui, against the simulated DAQ and the
campaign device simulators: partca, groupca (Run on), xpmpatt, deadca, tprca, dtica, detector_protection_monitor,
datadev_monitor, hsdpva, groupca (Run off).  Each action is confirmed from the server's API.
The PVs the run writes and leaves are saved in OUTDIR/writes.json for a read-back on the node by a separate client.
(--flow control, the control GUI run of paced_drive.py, is kept unchanged.)

Pacing, for every action:
  1. the target element gets a red CSS outline and a fixed caption box names the action;
  2. both stay for at least --highlight seconds, and longer if needed so that the action comes at least
     --gap seconds after the previous one;
  3. then the action runs (click or select), the outline goes, and the driver waits for the page to show
     the action's effect (the state, the rows, the button) before it starts the next highlight.
The video is Playwright's recording of the page at real speed (OUTDIR/*.webm). Every action is one JSON
line in OUTDIR/actions.jsonl: {n, action, selector, highlight_start, act_time, end, ...}, times in epoch
seconds (plus ISO copies). At the end it prints the action count, min(act_time - highlight_start) and the
smallest gap between consecutive act_times (pace_check.py recomputes them from the log).
Browser launch and the page's data-parity selectors are those of tunnel_drive.py.
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


def gui37_flow(pg, url, act, note, shot, until):
    """--flow gui37: the web copies this PR adds, on one server: /gui/partca (collection panel Auto connect and Reset
    against the control at 127.0.0.1; InhEnable1, L0Delay, L0Select and an AC timeslot box written to simxpm),
    /gui/groupca (Run: group 5 L0 triggers on), /gui/xpmpatt (group 5 shows partca's L0Select; PATT stats and
    coincidences count), /gui/deadca, /gui/tprca (simtpr: CH0 destination box 3, CH0 MODE), /gui/dtica (simdti: slot 4
    partition box, a forward-mask box), /gui/detector_protection_monitor (simdetprot: the trip dialog, Dismiss reopens
    it), /gui/datadev_monitor (simdatadev: Refresh All), /gui/hsdpva (simhsd: CONFIG readoutGroup typed and Applied,
    base B), groupca Run off.  Each write is confirmed from the server's API (the values its PV Access client reads)
    with one API read per check: while the hsdpva page is open the server answers in seconds, so hsdpva comes last."""
    base = url.rstrip('/')
    S = lambda rid: '[data-parity="%s"]' % rid
    click = lambda loc: loc.click()
    say = lambda m: print(f'{iso(time.time())} {m}', flush=True)
    extra = {'writes': {}}
    W = extra['writes']
    ready = '() => document.body.dataset.ready === "1" && +document.body.dataset.polls >= 2'
    vals = lambda gui: api(base, '/api/pvgui/values?gui=' + gui)['values']
    V = lambda v: v['value'] if isinstance(v, dict) and 'value' in v and not isinstance(v['value'], dict) else v

    def field(v, f):
        if isinstance(v, dict) and f in v:
            return v[f]
        if isinstance(v, dict) and isinstance(v.get('value'), dict):
            return v['value'].get(f)
        return None

    def poll(gui, pred, timeout=20, every=300):
        """Read the server's values of page gui until pred(values) (one API read per try); (ok, last values)."""
        t0, v = time.time(), {}
        while time.time() - t0 < timeout:
            v = vals(gui)
            if pred(v):
                return True, v
            pg.wait_for_timeout(every)
        return False, v

    def open_gui(name, cond=ready):
        pg.goto(base + '/gui/' + name, timeout=60000)
        pg.wait_for_function(cond, timeout=60000)
        pg.wait_for_timeout(1200)

    def write(action, sel, do, gui, pv, want, f=None, timeout=20, every=300):
        """An action that writes pv (or its field f): confirmed when the server reads want; recorded in W."""
        get = (lambda v: field(v.get(pv), f)) if f else (lambda v: V(v.get(pv)))
        before = get(vals(gui))
        res = {}

        def confirm():
            ok, v = poll(gui, lambda v: get(v) == want, timeout, every)
            res['v'] = get(v)
            return ok, f'PV {pv.split(":")[-1]}{"." + f if f else ""} {before} -> {res["v"]}'
        ok = act(action, sel, do, confirm)
        W[pv + ('.' + f if f else '')] = res.get('v')
        return ok

    ok = True
    # ---- /gui/partca: group 5 of simxpm; the collection panel against the simulated DAQ's control
    PB = 'DAQ:SIM:XPM:0:PART:5:'
    open_gui('partca')
    st = lambda: api(base, '/api/status').get('state')
    say(f'open /gui/partca {PB[:-1]}; control state {st()}')
    shot('partca')
    COLL = 'Ui_MainWindow.collectionWidget'
    items = lambda k: pg.locator(S('%s#%d' % (COLL, k)) + ' li').all_inner_texts()
    ok &= act('partca: collection panel: Auto connect (rollcall, alloc, connect)', S(COLL + '[Auto connect]'), click,
              lambda: (until(lambda: len(items(0)) >= 1, 90),
                       f'lists: {items(0)} | {items(1)} | {items(2)}; control state {st()}'))
    shot('partca-collection')
    ok &= act('partca: collection panel: Reset', S(COLL + '[Reset]'), click,
              lambda: (until(lambda: all(len(items(k)) == 0 for k in range(3)) and st() == 'reset', 60),
                       f'lists emptied: {[len(items(k)) for k in range(3)]}; control state {st()}'))
    pg.wait_for_timeout(1500)
    INH = S('Ui_MainWindow.LblCheckBox@2[%sInhEnable1]' % PB)
    want = 0 if V(vals('partca').get(PB + 'InhEnable1')) else 1
    ok &= write(f'partca: Inhibit 1 enable: {PB}InhEnable1 -> {want}', INH, click, 'partca', PB + 'InhEnable1', want)
    ok &= write(f'partca: type 77 in L0Delay, Enter: {PB}L0Delay', S('Ui_MainWindow.LblEditInt@1[%sL0Delay]' % PB),
                lambda loc: (loc.fill('77'), loc.press('Enter')), 'partca', PB + 'L0Delay', 77)
    BIT2 = S('Ui_MainWindow.LblEditEvt[%sL0Select_ACTimeslot]#2' % PB)
    ok &= write(f'partca: L0Select: AC Rate: {PB}L0Select -> 1', S('Ui_MainWindow.LblEditEvt[%sL0Select]' % PB),
                lambda loc: loc.select_option('1'), 'partca', PB + 'L0Select', 1)
    ts0 = V(vals('partca').get(PB + 'L0Select_ACTimeslot'))
    ok &= write(f'partca: AC timeslot box 2: {PB}L0Select_ACTimeslot -> {ts0 ^ 4}', BIT2, click, 'partca',
                PB + 'L0Select_ACTimeslot', ts0 ^ 4)
    shot('partca-written')

    # ---- /gui/groupca: Run on (group 5 L0 triggers in simxpm), so xpmpatt has counts to show
    open_gui('groupca')
    RUN = S('PvGroupStats.runb')
    TEV = S('Ui_MainWindow.tw.tab[Events]')
    ok &= act('groupca: tab Events', TEV, click,
              lambda: (until(lambda: pg.locator(TEV).get_attribute('aria-selected') == 'true', 10), 'tab Events selected'))
    ok &= act('groupca: Run: enable group 5 L0 triggers in simxpm', RUN, click,
              lambda: (lambda r: (r[0] and pg.locator(RUN).is_checked(),
                                  f'Run checked {pg.locator(RUN).is_checked()}; PV NumL0Acc = {r[1].get(PB + "NumL0Acc")}'))(
                  poll('groupca', lambda v: (v.get(PB + 'NumL0Acc') or 0) > 0, 15)))

    # ---- /gui/xpmpatt: group 5 shows what partca wrote; pattern statistics count group 5's L0Accepts
    open_gui('xpmpatt')
    XC = S('addGroup.LblEditEvt[%sL0Select]' % PB)
    ok &= act('xpmpatt: tab Group 5', S('Ui_MainWindow.tw.tab[Group 5]'), click,
              lambda: (until(lambda: pg.locator(XC).is_visible() and pg.locator(XC).input_value() == '1', 10),
                       f'group 5 L0Select shows {pg.locator(XC).locator("option:checked").inner_text()!r} '
                       f'(index {pg.locator(XC).input_value()}): what partca wrote'))
    SUM5 = S('PatternTab.PvTableDisplay[DAQ:SIM:XPM:0:PATT:GROUPS]#5')
    ok &= act('xpmpatt: tab Stats: L0Accepts per group, last second', S('Ui_MainWindow.PatternTab.tab[Stats]'), click,
              lambda: (lambda r: (r[0] and pg.locator(SUM5).is_visible(),
                                  f'PATT:GROUPS Sum {field(r[1].get("DAQ:SIM:XPM:0:PATT:GROUPS"), "Sum")}; '
                                  f'page group 5 {pg.locator(SUM5).inner_text()!r}'))(
                  poll('xpmpatt', lambda v: (field(v.get('DAQ:SIM:XPM:0:PATT:GROUPS'), 'Sum') or [0] * 8)[5] > 0, 15)))
    shot('xpmpatt-stats')
    C55 = S('PatternTab.w[DAQ:SIM:XPM:0:PATT:COINC]#30')
    c55 = lambda v: (field(v.get('DAQ:SIM:XPM:0:PATT:COINC'), 'Coinc') or [0] * 36)[30]
    ok &= act('xpmpatt: tab Coincidences: group pairs', S('Ui_MainWindow.PatternTab.tab[Coincidences]'), click,
              lambda: (lambda r: (r[0] and pg.locator(C55).is_visible(),
                                  f'PATT:COINC (5,5) = {c55(r[1])}; page {pg.locator(C55).inner_text()!r}'))(
                  poll('xpmpatt', lambda v: c55(v) > 0, 15)))

    # ---- /gui/deadca: group 5 dead fraction per link, named by simxpm's LinkLabel<n>
    open_gui('deadca')
    note('deadca: DeadFLnk of group 5 per link, labels from LinkLabel<n>', S('Ui_MainWindow.PvDblArrayW#0'))
    pg.wait_for_timeout(2500)
    labels = pg.evaluate('() => Array.from(document.querySelectorAll("td, span, div")).map(e => e.childElementCount ? "" : '
                         'e.textContent.trim()).filter(t => /^(fakecam|teb|control|tst)/.test(t)).slice(0, 6)')
    say(f'deadca: link labels on the page {labels}; DeadFLnk cell 0 {pg.locator(S("Ui_MainWindow.PvDblArrayW#0")).inner_text()!r}')
    shot('deadca')

    # ---- /gui/tprca: simtpr
    open_gui('tprca')
    DST = 'DAQ:SIM:TPR:CH0:DESTNS'
    ok &= act('tprca: tab CH0', S('Ui_MainWindow.tw.tab[CH0]'), click,
              lambda: (until(lambda: pg.locator(S('PvDstTab.chkB[%s]#3' % DST)).is_visible(), 10), 'CH0 shown'))
    ok &= write(f'tprca: destination box 3: {DST} -> 8', S('PvDstTab.chkB[%s]#3' % DST), click, 'tprca', DST, 8)
    MODE = 'DAQ:SIM:TPR:CH0:MODE'
    mw = 1 if V(vals('tprca').get(MODE)) != 1 else 2
    ok &= write(f'tprca: CH0 mode: {MODE} -> {mw}', S('Ui_MainWindow.PvEditCmb@3[%s]' % MODE),
                lambda loc: loc.select_option(str(mw)), 'tprca', MODE, mw)
    shot('tprca-ch0')
    FR = S('Ui_MainWindow.PvDbl@1[DAQ:SIM:TPR:FRAMERATE]')
    ok &= act('tprca: tab Input: the link, simtpr counting', S('Ui_MainWindow.tw.tab[Input]'), click,
              lambda: (until(lambda: pg.locator(FR).is_visible(), 10),
                       f'FRAMERATE {pg.locator(FR).input_value()!r}, '
                       f'RXCLKRATE {pg.locator(S("Ui_MainWindow.PvDbl@2[DAQ:SIM:TPR:RXCLKRATE]")).input_value()!r}'))

    # ---- /gui/dtica: simdti
    open_gui('dtica')
    D4 = 'DAQ:SIM:DTI:4:'
    BOX = S('PvEditCheckList.cb#69')                       # slot 4 UsLinkPartition0, index 6: puts 5
    ok &= act('dtica: allocation tab Slot-4', S('Ui_MainWindow.alloctab.tab[Slot-4]'), click,
              lambda: (until(lambda: pg.locator(BOX).is_visible(), 10), 'slot 4 allocation shown'))
    ok &= write(f'dtica: upstream link 0, partition box 6: {D4}UsLinkPartition0 -> 5', BOX, click, 'dtica',
                D4 + 'UsLinkPartition0', 5)
    FW = [D4 + 'UsLinkFwdMask%d' % i for i in range(7)]
    fw = lambda v: [V(v.get(p)) or 0 for p in FW]
    f0 = fw(vals('dtica'))
    ok &= act('dtica: downstream link 3 forwarded to upstream link 2', S('DtiAllocation.cb#66'), click,
              lambda: (lambda r: (r[0], f'UsLinkFwdMask0-6 {f0} -> {fw(r[1])}'))(
                  poll('dtica', lambda v: fw(v)[2] & 8 and not any(m & 8 for k, m in enumerate(fw(v)) if k != 2), 20)))
    W[D4 + 'UsLinkFwdMask2'] = fw(vals('dtica'))[2]
    shot('dtica-alloc')
    CELL = S('DtiStatistics.PvIntTable@1#56')
    ok &= act('dtica: statistics tab Slot-4', S('Ui_MainWindow.statstab.tab[Slot-4]'), click,
              lambda: (until(lambda: pg.locator(CELL).is_visible(), 10), f'UsWrFifoD cell {pg.locator(CELL).inner_text()!r}'))
    a = pg.locator(CELL).inner_text(); pg.wait_for_timeout(2500); b = pg.locator(CELL).inner_text()
    say(f'dtica slot 4 statistics: a UsWrFifoD cell {a!r} -> {b!r} in 2.5 s (simdti counts)')

    # ---- /gui/detector_protection_monitor: simdetprot (Channel Access); it tripped once, 60 s after it started
    open_gui('detector_protection_monitor', '() => document.body.dataset.ready === "1" && +document.body.dataset.polls >= 2 '
             '&& document.body.dataset.connected === "1"')
    DLG = S('MonitorMW.detector_protection_activated.msg_box')
    note('detector_protection_monitor: hot pixels in % of the trip count; the trip dialog', S('MonitorProgressBar._pix_over_threshold_bar'))
    pg.wait_for_timeout(2000)
    st_ = api(base, '/api/dpm/status')
    say(f'dpm: bar {pg.locator("#pct").inner_text()!r}; dialog shown {pg.locator(DLG).is_visible()} '
        f'{pg.locator("#dlg-title").inner_text()!r} {pg.locator("#dlg-text").inner_text()!r}; server: sim_pid {st_.get("sim_pid")}, '
        f'connected {st_.get("connected")}')
    shot('dpm-tripped')
    n0 = int(pg.locator(DLG).get_attribute('data-n') or 0)
    ok &= act('detector_protection_monitor: Dismiss. (BLOCKED is still set: it reopens)', '#dlg-button', click,
              lambda: (until(lambda: pg.locator(DLG).is_visible() and int(pg.locator(DLG).get_attribute('data-n') or 0) > n0, 20),
                       f'dialog shown again: n {n0} -> {pg.locator(DLG).get_attribute("data-n")}'))

    # ---- /gui/datadev_monitor: simdatadev's simulated nodes, no ssh
    open_gui('datadev_monitor')
    TS = S('MainWindow._build_ui._ts_label')
    ok &= act('datadev_monitor: Refresh All (80 simulated nodes)', S('MainWindow._build_ui._refresh_btn'), click,
              lambda: (until(lambda: pg.locator(TS).inner_text().startswith('Last refresh:'), 90),
                       f'{pg.locator(TS).inner_text()!r}; status bar {pg.locator("#statusbar").inner_text()!r}; '
                       f'checks run {api(base, "/api/datadev/status").get("targets_run")}'))
    shot('datadev-refreshed')

    # ---- /gui/hsdpva: simhsd (last: while this page is open the server is slow to answer)
    open_gui('hsdpva')
    HA = 'DAQ:SIM:HSD:1_1B:A'
    TIM = S('PvScalarBox.w@2[%s:MONTIMING]#0' % HA)
    ok &= act('hsdpva: tab Timing', S('Ui_MainWindow.maintab.tab[Timing]#0'), click,
              lambda: (until(lambda: pg.locator(TIM).is_visible(), 10), f'MONTIMING timframecnt shown {pg.locator(TIM).inner_text()!r}'))
    pg.wait_for_timeout(1500)
    say(f'hsdpva Timing: timframecnt {pg.locator(TIM).inner_text()!r} (simhsd counts)')
    RG = S('PvScalarBox.w@1[%s:CONFIG]#0' % HA)
    ok &= act('hsdpva: tab Config', S('Ui_MainWindow.maintab.tab[Config]#0'), click,
              lambda: (until(lambda: pg.locator(RG).is_visible(), 10), f'readoutGroup field shows {pg.locator(RG).input_value()!r}'))
    rgw = 3 if pg.locator(RG).input_value() != '3' else 4
    ok &= act(f'hsdpva: type {rgw} in readoutGroup', RG, lambda loc: loc.fill(str(rgw)),
              lambda: (until(lambda: pg.locator(RG).input_value() == str(rgw), 10), f'field {pg.locator(RG).input_value()!r}'))
    ok &= write(f'hsdpva: Apply: put the whole {HA}:CONFIG', S('PvScalarBox.b[%s:CONFIG]' % HA), click, 'hsdpva',
                HA + ':CONFIG', rgw, f='readoutGroup', timeout=60, every=1000)
    shot('hsdpva-config')
    ok &= act('hsdpva: base selector: B', S('Ui_MainWindow.tabsel[%s]' % HA), lambda loc: loc.select_option('1'),
              lambda: (until(lambda: pg.locator(S('Ui_MainWindow.maintab.tab[Config]#1')).is_visible(), 10),
                       'base DAQ:SIM:HSD:1_1B:B tabs shown'))

    # ---- groupca: Run off
    open_gui('groupca')
    ok &= act('groupca: Run again: disable group 5', RUN, click,
              lambda: (until(lambda: not pg.locator(RUN).is_checked(), 10), f'Run checked {pg.locator(RUN).is_checked()}'))
    pg.wait_for_timeout(2000)
    n1 = vals('groupca').get(PB + 'NumL0Acc'); pg.wait_for_timeout(1500); n2 = vals('groupca').get(PB + 'NumL0Acc')
    say(f'groupca after Run off: PV NumL0Acc {n1} -> {n2} in 1.5 s (stopped: {n1 == n2})')
    ok &= n1 == n2
    W[PB + 'NumL0Acc'] = n2
    say(f'writes left in the simulators for the read-back: {json.dumps(W)}')
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
        if flow == 'gui37':
            ok, extra = gui37_flow(pg, url, act, note, shot, until)
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
    if flow == 'gui37':
        json.dump(extra['writes'], open(os.path.join(out, 'writes.json'), 'w'))
        print(f'GUI_FLOW_OK={bool(ok)}  WRITES={len(extra["writes"])} PVs -> {os.path.join(out, "writes.json")}', flush=True)
    else:
        print(f'PAGE_EVENTS_FINAL={v2}  ALL_STATES_OK={bool(ok)}', flush=True)
    print(f'ACTIONS={len(acts)}  MIN_HIGHLIGHT_TO_ACT={min(holds):.3f} s  MIN_GAP_BETWEEN_ACTS={min(gaps):.3f} s', flush=True)
    return 0 if ok else 1


sys.exit(main())
