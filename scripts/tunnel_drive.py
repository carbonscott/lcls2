#!/usr/bin/env python3
"""Drive the DAQ web GUI from this machine through an ssh tunnel, as a user would.

usage: tunnel_drive.py URL OUTDIR [--events 1100] [--edit-seed 0x2a2a] [--shots-only]
Clicks: (optional config edit) Select, Apply, record on, CONNECTED ... RUNNING, waits for
--events on the page, 2 s more, then PAUSED ... RESET. Prints one line per action with the
time and what the page shows; records a video and screenshots into OUTDIR.
Selectors are the page's data-parity ids (same as psdaq/psdaq/webgui/e2e_browser.py).
"""
import datetime, json, os, sys, time
from playwright.sync_api import sync_playwright, expect

CHROME = os.path.expanduser('~/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome')
P = lambda pid: '[data-parity~="%s"]' % pid
BOX = P('CGWMainControl.box_state')
STATE = P('CGWMainControl.but_ctrls')
EVT = P('CGWMainInfo.edi_evt')
CFG = {
    'edit': P('CGWMainConfiguration.but_edit'),
    'type': P('CGWConfigSelect.but_type'), 'type_popup': P('CGWConfigSelect.on_but_type@1'),
    'dev': P('CGWConfigSelect.but_dev'), 'dev_popup': P('CGWConfigSelect.on_but_dev@1'),
    'select': P('QWDialog.but_apply'), 'expand': P('CGWConfigEditor.but_expn'),
    'apply': P('CGWConfigEditor.but_apply'), 'confirm': P('CGWMainConfiguration.save_dictj_in_db@1'),
    'close': P('CGWConfigEditor.but_close'),
}


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='milliseconds')


def main():
    url, out = sys.argv[1], sys.argv[2]
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
    events = int(arg('--events', '1100'))
    edit = arg('--edit-seed', None)
    os.makedirs(out, exist_ok=True)
    W, H = 960, 1180
    n_shot = [0]
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME, headless=True, args=['--no-proxy-server'])
        ctx = b.new_context(viewport={'width': W, 'height': H}, record_video_dir=out,
                            record_video_size={'width': W, 'height': H})
        pg = ctx.new_page()
        print(f'{now()} browser: headless Chromium {b.version} on {os.uname().nodename}, URL {url}', flush=True)

        def shot(tag):
            n_shot[0] += 1
            p = os.path.join(out, f'{n_shot[0]:02d}-{tag}.png')
            for k in range(4):                     # a screenshot failure must not stop the run
                try:
                    pg.screenshot(path=p, full_page=(k < 2))
                    return p
                except Exception as e:
                    print(f'{now()} screenshot {tag} try {k + 1}: {str(e).splitlines()[0]}', flush=True)
                    pg.wait_for_timeout(300)
            return None

        def state():
            return (pg.text_content(STATE) or '').strip()

        def evt():
            e = pg.locator(EVT)
            return e.text_content(), e.get_attribute('data-final'), e.get_attribute('data-source')

        def wait_state(target, timeout=60):
            t0 = time.time()
            while time.time() - t0 < timeout:
                if state().upper() == target.upper():
                    return True
                pg.wait_for_timeout(100)
            return False

        t0 = now()
        pg.goto(url, timeout=60000)
        pg.wait_for_selector('body[data-ready="1"]', timeout=60000)
        print(f'{t0} open -> page ready; state {state()}; backend {pg.text_content("#backend")!r}', flush=True)
        shot('open')

        if edit:
            pg.click(CFG['edit'])
            pg.wait_for_selector('#cfg_select', state='visible')
            for but, popup, value in ((CFG['type'], CFG['type_popup'], 'BEAM'), (CFG['dev'], CFG['dev_popup'], 'fakecam_0')):
                pg.click(but)
                pg.wait_for_selector(popup, state='visible')
                pg.click('%s button[data-value="%s"]' % (popup, value))
                pg.wait_for_selector(popup, state='hidden')
            pg.click(CFG['select'])
            pg.wait_for_selector('#cfg_editor', state='visible')
            ex = pg.locator(CFG['expand'])
            if 'Expand' in (ex.text_content() or ''):
                ex.click()
            leaf = pg.locator('#cfg_ed_tree .cfg-val[data-path="user.sim_seed"]')
            leaf.scroll_into_view_if_needed()
            before = leaf.text_content()
            print(f'{now()} config editor: {pg.text_content("#cfg_ed_title")}; user.sim_seed = {before}', flush=True)
            shot('cfg-editor')
            leaf.click()
            inp = pg.locator('#cfg_ed_tree input.cfg-inline[data-path="user.sim_seed"]')
            inp.fill(edit)
            inp.press('Enter')
            expect(leaf).to_have_text(edit)
            shot('cfg-edited')
            pg.click(CFG['apply'])
            pg.wait_for_selector(CFG['confirm'], state='visible')
            print(f'{now()} Apply -> dialog: {" ".join(pg.inner_text(CFG["confirm"]).split())!r}', flush=True)
            shot('cfg-confirm')
            pg.click('#cfg_cf_ok')
            st = pg.locator('#cfg_ed_status')
            expect(st).to_contain_text('new key', timeout=30000)
            print(f'{now()} OK -> editor status: {st.inner_text()!r}; user.sim_seed now {leaf.text_content()}', flush=True)
            shot('cfg-saved')
            pg.click(CFG['close'])
            pg.wait_for_selector('#cfg_editor', state='hidden')

        def click(sel, label, target):
            t = now()
            pg.click(sel)
            ok = wait_state(target)
            print(f'{t} click {label:<10} -> page state {state():<12} {"OK" if ok else "TIMEOUT"} ({now()})', flush=True)
            return ok

        ok = click(P('CGWMainPartition.but_select'), 'Select', 'UNALLOCATED')
        pg.wait_for_selector(P('QWPopupTableCheck.but_apply'), state='visible')
        shot('rollcall')
        ok &= click(P('QWPopupTableCheck.but_apply'), 'Apply', 'ALLOCATED')
        rec = pg.locator(P('CGWMainControl.but_record'))
        if rec.get_attribute('aria-pressed') != 'true':
            rec.click()
            expect(rec).to_have_attribute('aria-pressed', 'true')
        print(f'{now()} recording on (aria-pressed {rec.get_attribute("aria-pressed")})', flush=True)

        def choose(target):
            t = now()
            pg.locator(BOX).select_option(target)
            good = wait_state(target)
            print(f'{t} choose {target:<11} -> page state {state():<12} {"OK" if good else "TIMEOUT"} ({now()})', flush=True)
            return good

        for s in ('CONNECTED', 'CONFIGURED', 'STARTING', 'PAUSED', 'RUNNING'):
            ok &= choose(s)
        t1 = time.time()
        while time.time() - t1 < 120:
            v, fin, src = evt()
            if v and v.isdigit() and int(v) >= events:
                break
            pg.wait_for_timeout(200)
        print(f'{now()} RUNNING: page events {v} (source {src}) >= {events}', flush=True)
        shot('running')
        pg.wait_for_timeout(2000)
        print(f'{now()} RUNNING +2 s: page events {evt()[0]}', flush=True)
        ok &= choose('PAUSED')
        t1 = time.time()
        while time.time() - t1 < 20 and evt()[1] != '1':
            pg.wait_for_timeout(200)
        pg.wait_for_timeout(1500)
        v, fin, src = evt()
        print(f'{now()} after Disable: page events {v}, data-final {fin}, source {src}', flush=True)
        shot('disabled')
        for s in ('STARTING', 'CONFIGURED', 'CONNECTED', 'ALLOCATED', 'RESET'):
            ok &= choose(s)
        v2, fin2, _ = evt()
        errs = pg.evaluate("""() => { const e = document.querySelector('[data-parity~="QWLoggerError.edi_err"]');
            return e ? Array.from(e.childNodes).map(n => n.textContent.trim()).filter(l => l && !/^_+$/.test(l)) : []; }""")
        print(f'{now()} after RESET: page events {v2}, data-final {fin2}; error window lines: {len(errs)} {errs[:3]}', flush=True)
        shot('reset')
        vid = pg.video.path()
        ctx.close()
        b.close()
        print(f'PAGE_EVENTS_FINAL={v2}  ALL_STATES_OK={ok}  video {os.path.basename(vid)}', flush=True)
        json.dump({'events': v2, 'ok': ok, 'video': str(vid)}, open(os.path.join(out, 'result.json'), 'w'))
        return 0 if ok else 1


sys.exit(main())
