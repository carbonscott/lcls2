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


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='milliseconds')


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
                    page.wait_for_selector('body[data-ready="1"]', timeout=ms)
                elif op == 'click':
                    rep['target'] = cmd['target']
                    page.click(TARGETS[cmd['target']], timeout=ms)
                elif op == 'state':
                    rep['value'] = cmd['value']
                    page.locator(BOX).select_option(cmd['value'], timeout=ms)
                elif op == 'read':
                    rep['dom'] = page.evaluate(READ_JS)
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
