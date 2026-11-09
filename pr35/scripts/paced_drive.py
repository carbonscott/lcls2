#!/usr/bin/env python3
"""Drive the DAQ web GUI at a pace a person can follow, for browser recordings that reviewers watch.

usage: paced_drive.py URL OUTDIR [--events 1100] [--highlight 1.2] [--gap 2.7] [--detector fakecam_0] [--flow gui]

The run (--flow control, the default): Select, the ID of a two-segment detector clicked twice (expand, then
collapse), Apply, Record on, CONNECTED .. RUNNING in the state box, wait for --events on the page, then
PAUSED .. RESET.
--flow gui: the web copies of the other PyQt GUIs on the same server (gui_flow below): /gui/procstat (sort,
a procServ console, a log file, Restart refused for a local process), /gui/groupca (an inhibit checkbox, an
interval field and a destination-mask bit written to simxpm's PVs, Clear, Run on), /gui/pvant (the group's
NumL0Acc counting), groupca Run off and every PV put back, pvant again (the count stopped).  Each action is
confirmed from the server's API (procstat status, the PV values its PV Access client reads from simxpm).

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


def gui_flow(pg, url, act, note, shot, until):
    """--flow gui: /gui/procstat, /gui/groupca and /gui/pvant of one server.  Returns (ok, extra for result.json)."""
    base = url.rstrip('/')
    S = lambda rid: '[data-parity="%s"]' % rid
    click = lambda loc: loc.click()
    say = lambda m: print(f'{iso(time.time())} {m}', flush=True)
    extra = {}

    # ---- /gui/procstat: the processes of the daq_sim .cnf, as procstat shows them
    pg.goto(base + '/gui/procstat', timeout=60000)
    until(lambda: pg.locator('#procRows tr').count() >= 4, 60)
    st = api(base, '/api/procstat/status')
    extra['procstat_before'] = {r['showId']: r['status'] for r in st['rows']}
    say(f'open /gui/procstat -> cnf {st["cnf"]}; rows {extra["procstat_before"]}')
    pg.wait_for_timeout(1200)
    shot('procstat')
    ids = lambda: pg.locator('#procRows td[data-col="0"]').all_inner_texts()
    TH = P('Ui_mainWindow.tableProcStat.col[ID]')
    srt = lambda: pg.locator(TH).get_attribute('aria-sort')
    ok = act('procstat: click the ID column: sort by ID', TH, click,
             lambda: (until(lambda: srt() == 'ascending' and ids() == sorted(ids()), 10), f'aria-sort {srt()}, rows {ids()}'))
    ok &= act('procstat: click ID again: the other order', TH, click,
              lambda: (until(lambda: srt() == 'descending' and ids() == sorted(ids(), reverse=True), 10),
                       f'aria-sort {srt()}, rows {ids()}'))
    B = {k: P('Ui_mainWindow.pushButton%s' % k) for k in ('Console', 'Logfile', 'Restart')}
    pressed = lambda k: pg.locator(B[k]).get_attribute('aria-pressed')
    cell = lambda uid, col: '#procRows tr[data-id="%s"] td[data-col="%d"]' % (uid, col)
    title = lambda: (pg.text_content('#viewerTitle') or '').strip()
    text = lambda: pg.text_content('#viewerText') or ''
    ok &= act('procstat: Open Console mode', B['Console'], click,
              lambda: (until(lambda: pressed('Console') == 'true', 10), f'Open Console aria-pressed {pressed("Console")}'))
    ok &= act("procstat: click teb0's status: its procServ console", cell('teb0', 1), click,
              lambda: (until(lambda: 'console: teb0' in title() and '@@@ Welcome to procServ' in text(), 30),
                       f'viewer "{title()[:70]}"; "@@@ Welcome to procServ" shown: {"@@@ Welcome to procServ" in text()}'))
    shot('procstat-console')
    ok &= act('procstat: View Logfile mode', B['Logfile'], click,
              lambda: (until(lambda: pressed('Logfile') == 'true' and pressed('Console') == 'false', 10),
                       f'View Logfile aria-pressed {pressed("Logfile")}'))
    ok &= act('procstat: click fakecam_0: its log file', cell('fakecam_0', 0), click,
              lambda: (until(lambda: 'log: fakecam_0' in title() and len(text().strip()) > 0, 30),
                       f'viewer "{title()[:90]}"; {len(text().splitlines())} lines'))
    shot('procstat-logfile')
    ok &= act('procstat: Restart mode', B['Restart'], click,
              lambda: (until(lambda: pressed('Restart') == 'true', 10), f'Restart aria-pressed {pressed("Restart")}'))
    BOX = P('WinProcStat.msgBox')
    ok &= act('procstat: click control: a local process', cell('control', 0), click,
              lambda: (until(lambda: pg.locator(BOX).is_visible(), 15),
                       f'dialog "{(pg.text_content("#msgBoxTitle") or "").strip()}": '
                       f'{(pg.text_content("#msgBoxText") or "").strip()}'))
    shot('procstat-restart-refused')
    ok &= act('procstat: OK: nothing was restarted', '#msgBoxOk', click,
              lambda: (until(lambda: not pg.locator(BOX).is_visible(), 10),
                       f'dialog closed; rows {{{", ".join("%s: %s" % (r["showId"], r["status"]) for r in api(base, "/api/procstat/status")["rows"])}}}'))

    # ---- /gui/groupca: group <platform> of simxpm's XPM PVs
    lst = {g['name']: g['argv'] for g in api(base, '/api/pvgui/list')['pages']}
    pvbase, xpm, grp = lst['groupca'][:3]
    PB = '%s:XPM:%s:PART:%s:' % (pvbase, xpm, grp)
    vals = lambda: api(base, '/api/pvgui/values?gui=groupca')['values']
    ready = '() => document.body.dataset.ready === "1" && +document.body.dataset.polls >= 2'
    pg.goto(base + '/gui/groupca', timeout=60000)
    pg.wait_for_function(ready, timeout=60000)
    PVS = [PB + 'InhEnable0', PB + 'InhInterval0', PB + 'DstSelect_Mask']
    v0 = vals()
    before = {pv: v0.get(pv) for pv in PVS}
    extra['groupca_before'] = before
    say(f'open /gui/groupca {pvbase} {xpm} {grp} -> {len(v0)} PVs; before: {before}')
    pg.wait_for_timeout(1200)
    TAB = lambda t: S('Ui_MainWindow.tw.tab[%s]' % t)
    sel_tab = lambda t: pg.locator(TAB(t)).get_attribute('aria-selected') == 'true'
    ok &= act(f'groupca: tab Group {grp}', TAB('Group %s' % grp), click,
              lambda: (until(lambda: sel_tab('Group %s' % grp), 10), f'tab Group {grp} selected: {sel_tab("Group %s" % grp)}'))
    CB = S('addGroup.LblCheckBox[%sInhEnable0]' % PB)
    INT = S('addGroup.LblEditInt@2[%sInhInterval0]' % PB)
    MB = S('addGroup.LblEditDst[%sDstSelect_Mask]#3' % PB)
    pvis = lambda pv: f'{pv.split(":")[-1]} = {vals().get(pv)}'

    def flip_cb(back):
        want = before[PB + 'InhEnable0'] if back else (0 if before[PB + 'InhEnable0'] else 1)
        return act(f'groupca: Inhibit 0 enable checkbox: {PB}InhEnable0 -> {want}', CB, click,
                   lambda: (until(lambda: vals().get(PB + 'InhEnable0') == want and
                                  pg.locator(CB).is_checked() == bool(want), 10), 'PV ' + pvis(PB + 'InhEnable0')))

    def set_int(value):
        return act(f'groupca: type {value} in Inhibit 0 interval, Enter: {PB}InhInterval0', INT,
                   lambda loc: (loc.fill(str(value)), loc.press('Enter')),
                   lambda: (until(lambda: vals().get(PB + 'InhInterval0') == value, 10), 'PV ' + pvis(PB + 'InhInterval0')))

    def flip_bit(back):
        want = before[PB + 'DstSelect_Mask'] if back else before[PB + 'DstSelect_Mask'] ^ (1 << 3)
        return act(f'groupca: destination mask bit 3: {PB}DstSelect_Mask -> {want}', MB, click,
                   lambda: (until(lambda: vals().get(PB + 'DstSelect_Mask') == want, 10), 'PV ' + pvis(PB + 'DstSelect_Mask')))
    ok &= flip_cb(False)
    ok &= set_int(77)
    mask_ok = pg.locator(MB).is_visible()
    if mask_ok:
        ok &= flip_bit(False)
    else:
        say('destination mask bit 3 not shown on this tab: skipped')
    shot('groupca-group-written')
    ok &= act('groupca: tab Events', TAB('Events'), click,
              lambda: (until(lambda: sel_tab('Events'), 10), f'tab Events selected: {sel_tab("Events")}'))
    ACC = S('PvGroupStats.PvDbl[%sNumL0Acc]' % PB)
    RUN = S('PvGroupStats.runb')
    ok &= act(f'groupca: Clear: reset group {grp} counters', S('PvGroupStats.b[Clear]'), click,
              lambda: (until(lambda: vals().get(PB + 'NumL0Acc') == 0 and pg.locator(ACC).input_value() == '0.0000', 10),
                       'PV ' + pvis(PB + 'NumL0Acc') + f', page {pg.locator(ACC).input_value()}'))
    say(f'groupca before Run: page Run checked {pg.locator(RUN).is_checked()}, server Run state '
        f'{api(base, "/api/pvgui/values?gui=groupca")["computed"].get("check:PvGroupStats.runb")}')
    ok &= act(f'groupca: Run: enable group {grp} L0 triggers in simxpm', RUN, click,
              lambda: (until(lambda: pg.locator(RUN).is_checked() and (vals().get(PB + 'NumL0Acc') or 0) > 0, 15),
                       f'Run checked {pg.locator(RUN).is_checked()}; PV ' + pvis(PB + 'NumL0Acc')))
    note(f'groupca: group {grp} accepting L0 triggers: NumL0Acc counts', ACC)
    pg.wait_for_timeout(2500)
    say(f'groupca running: page NumL0Acc {pg.locator(ACC).input_value()}, PV ' + pvis(PB + 'NumL0Acc'))
    shot('groupca-running')

    # ---- /gui/pvant: the same counter in pvant's grid, while groupca's Run is on
    PV_CELL = S('PvScalarTable.PvInt[%s:XPM:%s:PART:%s:NumL0Acc]' % (pvbase, xpm, grp))
    cellv = lambda: pg.locator(PV_CELL).input_value()
    pg.goto(base + '/gui/pvant', timeout=60000)
    pg.wait_for_function(ready, timeout=60000)
    note(f'pvant: PART:{grp} NumL0Acc, still counting', PV_CELL)
    a = cellv()
    pg.wait_for_timeout(2500)
    b = cellv()
    extra['pvant_running'] = [a, b]
    say(f'pvant while running: PART:{grp} NumL0Acc {a} -> {b} in 2.5 s')
    shot('pvant-running')

    # ---- back to groupca: Run off, every PV put back
    pg.goto(base + '/gui/groupca', timeout=60000)
    pg.wait_for_function(ready, timeout=60000)
    ok &= act(f'groupca: Run again: disable group {grp}', RUN, click,
              lambda: (until(lambda: not pg.locator(RUN).is_checked(), 10), f'Run checked {pg.locator(RUN).is_checked()}'))
    pg.wait_for_timeout(2000)
    n1 = vals().get(PB + 'NumL0Acc')
    pg.wait_for_timeout(1500)
    n2 = vals().get(PB + 'NumL0Acc')
    extra['groupca_count_final'] = n2
    say(f'groupca after Run off: PV NumL0Acc {n1} -> {n2} in 1.5 s (stopped: {n1 == n2}); page {pg.locator(ACC).input_value()}')
    ok &= n1 == n2
    ok &= act(f'groupca: tab Group {grp}', TAB('Group %s' % grp), click,
              lambda: (until(lambda: sel_tab('Group %s' % grp), 10), f'tab Group {grp} selected: {sel_tab("Group %s" % grp)}'))
    ok &= flip_cb(True)
    ok &= set_int(int(before[PB + 'InhInterval0']))
    if mask_ok:
        ok &= flip_bit(True)
    after = {pv: vals().get(pv) for pv in PVS}
    extra['groupca_after'] = after
    say(f'groupca PVs put back: {after == before} ({after})')
    ok &= after == before
    shot('groupca-put-back')

    # ---- pvant again: the count stopped
    pg.goto(base + '/gui/pvant', timeout=60000)
    pg.wait_for_function(ready, timeout=60000)
    note(f'pvant: PART:{grp} NumL0Acc, stopped', PV_CELL)
    pg.wait_for_timeout(1500)
    c = cellv()
    pg.wait_for_timeout(1500)
    d = cellv()
    extra['pvant_count_final'] = d
    say(f'pvant after Run off: PART:{grp} NumL0Acc {c} -> {d} (stopped: {c == d}; groupca PV {n2})')
    ok &= c == d and str(int(n2)) == d.strip()
    shot('pvant-stopped')
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
        if flow == 'gui':
            ok, extra = gui_flow(pg, url, act, note, shot, until)
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
    if flow == 'gui':
        print(f'GUI_FLOW_OK={bool(ok)}  ' + '  '.join(f'{k}={extra[k]}' for k in ('groupca_count_final', 'pvant_count_final')
                                                   if k in extra), flush=True)
    else:
        print(f'PAGE_EVENTS_FINAL={v2}  ALL_STATES_OK={bool(ok)}', flush=True)
    print(f'ACTIONS={len(acts)}  MIN_HIGHLIGHT_TO_ACT={min(holds):.3f} s  MIN_GAP_BETWEEN_ACTS={min(gaps):.3f} s', flush=True)
    return 0 if ok else 1


sys.exit(main())
