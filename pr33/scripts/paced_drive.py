#!/usr/bin/env python3
"""Drive the DAQ web GUI at a pace a person can follow, for browser recordings that reviewers watch.

usage: paced_drive.py URL OUTDIR [--events 1100] [--highlight 1.2] [--gap 2.7] [--detector fakecam_0]

The run: Select, the ID of a two-segment detector clicked twice (expand, then collapse), Apply, Record on,
CONNECTED .. RUNNING in the state box, wait for --events on the page, then PAUSED .. RESET.

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


def main():
    url, out = sys.argv[1], sys.argv[2]
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
    events = int(arg('--events', '1100'))
    HL = float(arg('--highlight', '1.2'))
    GAP = float(arg('--gap', '2.7'))
    det = arg('--detector', 'fakecam_0')
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
    res = {'events_after_disable': v, 'events_after_reset': v2, 'ok': bool(ok), 'video': str(vid),
           'video_s': dur, 'wall_s': round(t_close - t_ctx, 2), 'actions': len(acts),
           'min_highlight_to_act_s': round(min(holds), 3), 'min_gap_s': round(min(gaps), 3), 'shots': shots,
           'error_window_lines': errs}
    json.dump(res, open(os.path.join(out, 'result.json'), 'w'), indent=1)
    print(f'video {os.path.basename(vid)}: {dur if dur is None else round(dur, 1)} s; browser context open {res["wall_s"]} s '
          f'(real speed: the video spans the whole context)', flush=True)
    print(f'PAGE_EVENTS_FINAL={v2}  ALL_STATES_OK={bool(ok)}', flush=True)
    print(f'ACTIONS={len(acts)}  MIN_HIGHLIGHT_TO_ACT={min(holds):.3f} s  MIN_GAP_BETWEEN_ACTS={min(gaps):.3f} s', flush=True)
    return 0 if ok else 1


sys.exit(main())
