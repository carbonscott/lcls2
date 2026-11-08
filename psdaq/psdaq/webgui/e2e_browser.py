"""Headless-browser driver for `daq_sim e2e` (psdaq.webgui.e2e).

It runs in the Playwright venv (any Python 3 with playwright and a chromium), imports nothing
from psdaq, and decides nothing: it reads one JSON command per line on stdin, performs it
in the web GUI as a user would (a click, a choice in the target-state box, a look at the
page) and prints one line per command on stdout:

    DRV {"id": <n>, "op": <op>, "ok": true|false, "t0": <iso ms>, "t1": <iso ms>, ...}

Commands:
    {"id": n, "op": "open", "url": "http://127.0.0.1:<port>/"}
    {"id": n, "op": "click", "target": "select" | "apply" | "record"}
    {"id": n, "op": "state", "value": "CONFIGURED"}       # choose it in the target-state box
    {"id": n, "op": "read"}                                # DOM readings (see READ_JS)
    {"id": n, "op": "cfg_edit", "alias": "BEAM", "device": "fakecam_0", "path": "user.sim_seed",
     "value": "0x2a2a"}                                    # the config DB editor, as a user (cfg_edit)
    {"id": n, "op": "requests"}                            # the page's /api/ requests so far (REQ_JS)
    {"id": n, "op": "shot", "path": "/abs/file.png"}
    {"id": n, "op": "quit"}
All checks and the exit code belong to the parent process.
"""

import argparse
import datetime
import json
import sys
import traceback


def P(pid):
    return '[data-parity~="%s"]' % pid


TARGETS = {
    'select': P('CGWMainPartition.but_select'),     # rollcall
    'apply': P('QWPopupTableCheck.but_apply'),      # selectPlatform + allocated
    'record': P('CGWMainControl.but_record'),
}
BOX = P('CGWMainControl.box_state')
CFG = {                                             # the config DB editor (static/ext/configeditor.js)
    'edit': P('CGWMainConfiguration.but_edit'),
    'type': P('CGWConfigSelect.but_type'), 'type_popup': P('CGWConfigSelect.on_but_type@1'),
    'dev': P('CGWConfigSelect.but_dev'), 'dev_popup': P('CGWConfigSelect.on_but_dev@1'),
    'select': P('QWDialog.but_apply'),
    'expand': P('CGWConfigEditor.but_expn'),
    'apply': P('CGWConfigEditor.but_apply'),
    'confirm': P('CGWMainConfiguration.save_dictj_in_db@1'),
    'close': P('CGWConfigEditor.but_close'),
}

READ_JS = """() => {
  const q = (s) => document.querySelector(s);
  const txt = (s) => { const e = q(s); return e ? e.textContent : null; };
  const P = (id) => '[data-parity~="' + id + '"]';
  const evt = q(P('CGWMainInfo.edi_evt'));
  const err = q(P('QWLoggerError.edi_err'));
  const errLines = err ? Array.from(err.childNodes).map((n) => n.textContent.trim())
      .filter((l) => l && !/^_+$/.test(l)) : [];
  return {
    ready: document.body.dataset.ready === '1',
    backend: txt('#backend'), conn: txt('#conn'),
    state: txt(P('CGWMainControl.but_ctrls')), transition: txt(P('CGWMainControl.but_transition')),
    recording: q(P('CGWMainControl.but_record')).getAttribute('aria-pressed'),
    box_disabled: q(P('CGWMainControl.box_state')).disabled,
    evt: evt ? evt.textContent : null,
    evt_source: evt ? evt.dataset.source : null, evt_ts: evt ? evt.dataset.ts : null,
    evt_final: evt ? evt.dataset.final : null,
    drops: txt(P('CGWMainInfo.edi_evd')),
    run_label: txt('#lab_run'), run: txt(P('CGWMainInfo.edi_run')), exp: txt(P('CGWMainInfo.edi_exp')),
    cmd_status: txt('#cmd_status'), errors: errLines,
  };
}"""


# Every /api/ request the page made, from the browser's own resource timing (start time in epoch
# seconds, so the parent can place each one in a time window); the buffer is enlarged at 'open'.
REQ_JS = """() => performance.getEntriesByType('resource')
  .filter((e) => e.name.indexOf('/api/') >= 0)
  .map((e) => [(performance.timeOrigin + e.startTime) / 1000, e.initiatorType, new URL(e.name).pathname + new URL(e.name).search])"""


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='milliseconds')


def cfg_edit(page, cmd, ms, rep):
    """Open the config DB editor from the main window, choose alias/device, change one leaf,
    Apply and confirm, then close the editor; report what the page showed at each step."""
    from playwright.sync_api import expect
    steps = rep['steps'] = []

    def mark(what):
        steps.append([now(), what])
    page.click(CFG['edit'], timeout=ms)
    page.wait_for_selector('#cfg_select', state='visible', timeout=ms)
    mark('Edit clicked: select dialog shown')
    for but, popup, value in ((CFG['type'], CFG['type_popup'], cmd['alias']),
                              (CFG['dev'], CFG['dev_popup'], cmd['device'])):
        page.click(but, timeout=ms)
        page.wait_for_selector(popup, state='visible', timeout=ms)
        page.click('%s button[data-value="%s"]' % (popup, value), timeout=ms)
        page.wait_for_selector(popup, state='hidden', timeout=ms)
        mark('chose %s' % value)
    page.click(CFG['select'], timeout=ms)
    page.wait_for_selector('#cfg_editor', state='visible', timeout=ms)
    expect(page.locator('#cfg_ed_title')).to_have_text('Config Editor for %s %s' % (cmd['alias'], cmd['device']),
                                                      timeout=ms)
    rep['title'] = page.text_content('#cfg_ed_title')
    mark('editor shown: %s' % rep['title'])
    exp = page.locator(CFG['expand'])
    if 'Expand' in (exp.text_content(timeout=ms) or ''):
        exp.click(timeout=ms)
    leaf = page.locator('#cfg_ed_tree .cfg-val[data-path="%s"]' % cmd['path'])
    rep['before'] = leaf.text_content(timeout=ms)
    leaf.click(timeout=ms)
    inp = page.locator('#cfg_ed_tree input.cfg-inline[data-path="%s"]' % cmd['path'])
    inp.fill(cmd['value'], timeout=ms)
    inp.press('Enter', timeout=ms)
    expect(leaf).to_have_text(cmd['value'], timeout=ms)
    mark('%s: %s -> %s' % (cmd['path'], rep['before'], cmd['value']))
    page.click(CFG['apply'], timeout=ms)
    page.wait_for_selector(CFG['confirm'], state='visible', timeout=ms)
    rep['confirm'] = ' '.join(page.inner_text(CFG['confirm'], timeout=ms).split())
    mark('Apply clicked: confirm dialog shown')
    page.click('#cfg_cf_ok', timeout=ms)
    mark('OK clicked')
    status = page.locator('#cfg_ed_status')
    try:
        expect(status).to_contain_text('new key', timeout=ms)
    finally:
        rep['status'] = status.inner_text(timeout=ms)
        rep['status_ok'] = status.get_attribute('data-ok')
    mark('status shown: %s' % rep['status'])
    rep['after'] = leaf.text_content(timeout=ms)
    page.click(CFG['close'], timeout=ms)
    page.wait_for_selector('#cfg_editor', state='hidden', timeout=ms)
    mark('editor closed')


def emit(d):
    sys.stdout.write('DRV ' + json.dumps(d) + '\n')
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--timeout', type=float, default=60.0, help='per-action timeout, s')
    ap.add_argument('--width', type=int, default=900)
    ap.add_argument('--height', type=int, default=1300)
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright
    ms = int(args.timeout * 1000)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--no-sandbox', '--no-proxy-server'])
        page = browser.new_page(viewport={'width': args.width, 'height': args.height})
        emit({'id': 0, 'op': 'hello', 'ok': True, 't0': now(), 't1': now(),
              'browser': 'chromium ' + browser.version, 'python': sys.version.split()[0]})
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            cmd = json.loads(line)
            op = cmd.get('op')
            rep = {'id': cmd.get('id'), 'op': op, 'ok': True, 't0': now()}
            try:
                if op == 'open':
                    page.goto(cmd['url'], timeout=ms)
                    page.evaluate('() => performance.setResourceTimingBufferSize(100000)')
                    page.wait_for_selector('body[data-ready="1"]', timeout=ms)
                elif op == 'click':
                    rep['target'] = cmd['target']
                    page.click(TARGETS[cmd['target']], timeout=ms)
                elif op == 'state':
                    rep['value'] = cmd['value']
                    page.locator(BOX).select_option(cmd['value'], timeout=ms)
                elif op == 'read':
                    rep['dom'] = page.evaluate(READ_JS)
                elif op == 'cfg_edit':
                    cfg_edit(page, cmd, ms, rep)
                elif op == 'requests':
                    rep['requests'] = page.evaluate(REQ_JS)
                elif op == 'shot':
                    page.screenshot(path=cmd['path'], full_page=True)
                    rep['path'] = cmd['path']
                elif op == 'quit':
                    rep['t1'] = now()
                    emit(rep)
                    break
                else:
                    raise ValueError('unknown op %r' % op)
            except Exception as ex:
                rep['ok'] = False
                rep['err'] = '%s: %s' % (type(ex).__name__, str(ex).splitlines()[0] if str(ex) else '')
                traceback.print_exc(file=sys.stderr)
            rep['t1'] = now()
            emit(rep)
        browser.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
