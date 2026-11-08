"""`daq_sim e2e`: the end-to-end test of the hardware-free DAQ, driven through the web GUI.

    daq_sim e2e [-w WORKDIR] [--events 1000] [--break kill-drp] [--browser-python PATH] [--keep-up]

It brings the DAQ up with the web GUI (`daq_sim up --webgui --detach`, which runs the
fail-closed preflight first), or uses the one already up in WORKDIR, and starts a headless
chromium (psdaq/webgui/e2e_browser.py, run by the Playwright venv's python).  The driver only
clicks and reports what the page shows; every check and the exit code are here, in the DAQ
env's python, from this process's own reads:

  1. its own PV Access read of simxpm's NumL0Acc reaches events * 1.1 while RUNNING, before
     it lets the driver click down from RUNNING;
  2. its own DaqControl.getState returns every state the driver clicked (one at a time, up
     reset -> unallocated -> ... -> running, and down running -> ... -> allocated -> reset),
     the page shows each, and control's status stream carries no error (nor its log a
     KeyError);
  3. after Disable, #edi_evt has data-final="1", its data-ts is later than the time control
     reported the Disable, and two consecutive readings are equal;
  4. the number on the page is ^\\d+$;
  5. after the click down to RESET the page still shows that number (data-final="1");
  6. page == TEB_WrtCt (Prometheus, read in CONFIGURED after Disable) == psana2 events ==
     psana2 events with the detector's data >= events, and page == its own NumL0Acc read
     after Disable; the run number on the page is control's run number.

It prints each transition as `<STATE> clicked <iso ms> reported <iso ms>`, a final table and
`E2E PASS` (exit 0) or the failed assertions and `E2E FAIL` (exit 1).  `--break kill-drp`
SIGKILLs the DRP once RUNNING, to show that the test fails.  At the end it runs
`daq_sim down` unless --keep-up.
"""

import argparse
import datetime
import getpass
import glob
import json
import math
import os
import queue
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.request

from psdaq.sim import daq_sim as ds

UP = ['UNALLOCATED', 'ALLOCATED', 'CONNECTED', 'CONFIGURED', 'STARTING', 'PAUSED', 'RUNNING']
DOWN = ['PAUSED', 'STARTING', 'CONFIGURED', 'CONNECTED', 'ALLOCATED', 'RESET']   # box: no RESET from unallocated
DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'e2e_browser.py')
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def now():
    return ds.now()


def iso(epoch):
    return datetime.datetime.fromtimestamp(epoch).astimezone().isoformat(timespec='milliseconds')


def say(*a):
    print(f'{now()} e2e:', *a, flush=True)


class Fail(ds.Fail):
    pass


# --- browser venv --------------------------------------------------------------------------

def browser_python(args):
    if args.browser_python:
        return args.browser_python
    if os.environ.get('DAQ_SIM_BROWSER_PYTHON'):
        return os.environ['DAQ_SIM_BROWSER_PYTHON']
    u = getpass.getuser()
    root = os.environ.get('AGENTIFY_WEBTEST', f'/sdf/scratch/users/{u[0]}/{u}/agentify-webtest')
    return os.path.join(root, 'venv', 'bin', 'python')


def check_browser(args):
    """(python, PLAYWRIGHT_BROWSERS_PATH, version line); Fail with what to do if unusable."""
    py = browser_python(args)
    how = ('create it as in psdaq/psdaq/sim/RUNBOOK.md §3c (uv venv + pip install '
           'playwright pytest-playwright + playwright install chromium, on sdfiana025), then pass '
           '--browser-python <venv>/bin/python')
    if not os.path.isfile(py) or not os.access(py, os.X_OK):
        raise Fail(f'browser venv: no python at {py}; {how}')
    bpath = args.browsers_path or os.environ.get('PLAYWRIGHT_BROWSERS_PATH') or \
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(py))), 'browsers')
    chromes = glob.glob(os.path.join(bpath, 'chromium*', 'chrome-linux*', 'chrome')) + \
        glob.glob(os.path.join(bpath, 'chromium_headless_shell*', 'chrome-headless-shell-linux*', 'chrome-headless-shell'))
    if not chromes:
        raise Fail(f'browser venv: no chromium under PLAYWRIGHT_BROWSERS_PATH={bpath}; {how} '
                   '(or pass --browsers-path)')
    r = subprocess.run([py, '-I', '-c', 'import sys, importlib.metadata as m; '
                        'print(sys.version.split()[0], "playwright", m.version("playwright"))'],
                       capture_output=True, text=True, timeout=60, env=browser_env(bpath))
    if r.returncode != 0:
        err = (r.stderr.strip().splitlines() or ['?'])[-1][-200:]
        raise Fail(f'browser venv: {py} cannot import playwright ({err}); {how}')
    return py, bpath, f'{py} (Python {r.stdout.strip()}), chromium {chromes[0]}'


def browser_env(bpath):
    env = dict(os.environ)
    for k in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP'):
        env.pop(k, None)
    env['PLAYWRIGHT_BROWSERS_PATH'] = bpath
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
        env[k] = 'http://127.0.0.1:9'           # dead proxy; chromium itself runs --no-proxy-server
    env['NO_PROXY'] = env['no_proxy'] = 'localhost,127.0.0.1'
    return env


class Driver:
    """The browser driver subprocess: one JSON command per line in, one DRV line per command out."""

    def __init__(self, py, bpath, log, timeout):
        self.timeout = timeout
        self.n = 0
        self.q = queue.Queue()
        self.err = open(log, 'a')
        self.p = subprocess.Popen([py, '-I', DRIVER, '--timeout', str(timeout)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=self.err, text=True, bufsize=1,
                                  env=browser_env(bpath))
        threading.Thread(target=self._read, daemon=True).start()
        hello = self._wait(0, 120)
        say(f'driver up (pid {self.p.pid}): {hello.get("browser")}, Python {hello.get("python")}')

    def _read(self):
        for line in self.p.stdout:
            line = line.rstrip('\n')
            if line.startswith('DRV '):
                try:
                    self.q.put(json.loads(line[4:]))
                    continue
                except ValueError:
                    pass
            print(f'  driver> {line}', flush=True)
        self.q.put(None)

    def _wait(self, n, timeout):
        end = time.monotonic() + timeout
        while True:
            try:
                rep = self.q.get(timeout=max(0.1, end - time.monotonic()))
            except queue.Empty:
                raise Fail(f'driver: no answer to command {n} in {timeout:.0f} s')
            if rep is None:
                raise Fail(f'driver exited (code {self.p.poll()}); see its log')
            if rep.get('id') == n:
                return rep

    def do(self, op, quiet=False, **kw):
        self.n += 1
        cmd = dict(kw, id=self.n, op=op)
        self.p.stdin.write(json.dumps(cmd) + '\n')
        self.p.stdin.flush()
        rep = self._wait(self.n, self.timeout + 30)
        if not quiet:
            print('  DRV ' + json.dumps(rep), flush=True)
        return rep

    def read(self):
        rep = self.do('read', quiet=True)
        d = rep.get('dom') or {}
        print(f'  DOM {rep["t1"]} state={d.get("state")} transition={d.get("transition")} evt={d.get("evt")!r} '
              f'source={d.get("evt_source")} ts={d.get("evt_ts")} final={d.get("evt_final")} '
              f'run_label={d.get("run_label")!r} run={d.get("run")} exp={d.get("exp")} rec={d.get("recording")} '
              f'errors={d.get("errors")}', flush=True)
        return rep['t1'], d

    def close(self):
        try:
            if self.p.poll() is None:
                self.do('quit', quiet=True)
                self.p.wait(20)
        except Exception:
            pass
        if self.p.poll() is None:
            self.p.kill()
        self.err.close()


# --- the DAQ -------------------------------------------------------------------------------

def daq_is_up(state):
    return bool(state) and not state.get('down') and \
        all(ds.pid_alive(s['pid']) for s in state.get('services', {}).values())


def bring_up(args, work):
    """Use the DAQ up in work.dir, or start one with the web GUI; return (state, started_here)."""
    state = work.load()
    if daq_is_up(state):
        say(f'using the DAQ already up in {work.dir} (up pid {state.get("up_pid")}, started {state.get("started")})')
        pf = work.path('logs', 'preflight.log')
        last = open(pf).read().strip().splitlines()[-1:] if os.path.exists(pf) else []
        say(f'its preflight: {last[0] if last else "(no logs/preflight.log)"}')
        if not last or 'PREFLIGHT PASS' not in last[0]:
            raise Fail(f'the running DAQ has no passing preflight in {pf}')
        if 'webgui' not in state['services'] or not ds.pid_alive(state['services']['webgui']['pid']):
            env = dict(os.environ)
            env[ds.TAG] = work.dir
            ds.start_webgui(work, state, env)
            state = work.load()
        return state, False
    up = argparse.Namespace(**vars(args))
    up.webgui, up.detach = True, True
    say('bringing the DAQ up: daq_sim up --webgui --detach (preflight first)')
    if ds.cmd_up(up) != 0:
        raise Fail('daq_sim up failed (see above)')
    return work.load(), True


def control_log(work):
    logs = sorted(glob.glob(work.path('pmlogs', '*', '*', '*control.log')), key=os.path.getmtime)
    return logs[-1] if logs else None


def find_drp(state):
    """PID of the detector DRP process (procmgr reports it, or the procServ that holds it)."""
    det = ds.DETECTOR + '_0'
    pid = (state.get('procs') or {}).get(det)
    if pid is None:
        return None, ''
    if os.path.basename(ds.cmdline(pid).split(' ')[0]) == 'drp':
        return pid, ds.cmdline(pid)
    for d in os.listdir('/proc'):                  # a child of procServ
        if d.isdigit():
            try:
                with open(f'/proc/{d}/stat') as f:
                    ppid = int(f.read().rsplit(')', 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            if ppid == pid and os.path.basename(ds.cmdline(int(d)).split(' ')[0]) == 'drp':
                return int(d), ds.cmdline(int(d))
    return pid, ds.cmdline(pid)


# --- the test ------------------------------------------------------------------------------

class Run:
    def __init__(self, args, work, state):
        self.args, self.work, self.state = args, work, state
        self.plat = state['platform']
        self.pv = ds.count_pv(self.plat)
        self.rows = []              # (STATE, clicked, reported, shown, ok)
        self.res = {}               # assertion number -> (ok, text)
        self.info = {}
        self.msgs = []
        self.stop = threading.Event()

    def check(self, n, ok, text):
        if n in self.res and not self.res[n][0]:
            return False            # keep the first failure of an assertion
        self.res[n] = (bool(ok), text)
        say(f'assertion {n} {"PASS" if ok else "FAIL"}: {text}')
        return bool(ok)

    def monitor(self):
        from psdaq.control.DaqControl import DaqControl
        mon = DaqControl(host='localhost', platform=self.plat, timeout=1000)
        mon.front_sub.setsockopt(ds.zmq_rcvtimeo(), 500)
        while not self.stop.is_set():
            try:
                m = mon.front_sub.recv_json()
            except Exception:
                continue
            key = m.get('header', {}).get('key')
            if key in ('error', 'warning', 'fileReport'):
                body = m.get('body', {})
                self.msgs.append((now(), key, body.get('err_info', body.get('path'))))
                print(f'{now()} control [{key}] {self.msgs[-1][2]}', flush=True)
        mon.context.destroy(0)

    def pv_count(self):
        v = ds.pv_get(self.pv)
        return None if isinstance(v, str) else int(v)

    def wait_state(self, dc, target, timeout):
        """Poll our own DaqControl.getState until it returns target; (state, reported iso)."""
        end, got = time.monotonic() + timeout, None
        while time.monotonic() < end:
            got = dc.getState()
            if got == target:
                return got, now(), time.time()
            time.sleep(0.1)
        return got, None, None

    def wait_dom(self, drv, pred, timeout, period=0.5):
        end = time.monotonic() + timeout
        while True:
            t, d = drv.read()
            if pred(d) or time.monotonic() > end:
                return t, d
            time.sleep(period)

    def go(self, drv, dc, label, action):
        """One user action, then our own read-back of control's state and the page's."""
        target = label.lower()
        rep = action()
        clicked = rep.get('t1')
        if not rep.get('ok'):
            self.rows.append((label, clicked, None, None, False))
            return self.check(2, False, f'driver could not do {label}: {rep.get("err")}')
        got, reported, epoch = self.wait_state(dc, target, self.args.timeout)
        t, d = self.wait_dom(drv, lambda d: (d.get('state') or '').upper() == label, 15)
        shown = t if (d.get('state') or '').upper() == label else None
        ok = reported is not None and shown is not None
        self.rows.append((label, clicked, reported, shown, ok))
        print(f'{label} clicked {clicked} reported {reported} (page shows it {shown})', flush=True)
        if not ok:
            return self.check(2, False, f'{label}: control getState -> {got!r}'
                                         f'{"" if reported else f" after {self.args.timeout} s"}; '
                                         f'page shows {d.get("state")!r}')
        self.info[f't_{target}'] = epoch
        return True

    def run(self, drv):
        from psdaq.control.DaqControl import DaqControl
        a = self.args
        dc = DaqControl(host='localhost', platform=self.plat, timeout=a.timeout * 1000)
        mt = threading.Thread(target=self.monitor, daemon=True)
        mt.start()
        time.sleep(0.5)
        try:
            return self._run(drv, dc)
        finally:
            self.stop.set()
            mt.join(2)
            dc.context.destroy(0)

    def _run(self, drv, dc):
        a = self.args
        need = int(math.ceil(a.events * 1.1))
        url = ds.webgui_url(self.state)
        start = dc.getState()
        say(f'control state at start: {start}; web GUI {url}; counter PV {self.pv}; need >= {need} L1Accepts')
        if start != 'reset':
            return self.check(2, False, f'control is in {start!r} at the start, expected reset')
        meta = json.loads(_OPENER.open(url + 'api/meta', timeout=10).read())
        say(f'web GUI backend {meta.get("backend")}, events source {meta.get("events_source")}')
        rep = drv.do('open', url=url)
        if not rep['ok']:
            return self.check(2, False, f'the page did not load: {rep.get("err")}')
        t, d = drv.read()
        if d.get('backend') != 'backend: daqcontrol' or (d.get('state') or '').upper() != 'RESET':
            return self.check(2, False, f'page shows {d.get("backend")!r} state {d.get("state")!r}')
        drv.do('shot', path=os.path.join(a.shots, 'e2e-00-reset.png'))

        # --- up, one state at a time ---
        steps = [('UNALLOCATED', lambda: drv.do('click', target='select')),
                 ('ALLOCATED', lambda: drv.do('click', target='apply'))]
        steps += [(s, (lambda s=s: drv.do('state', value=s))) for s in UP[2:]]
        for label, action in steps:
            if not self.go(drv, dc, label, action):
                return False
            if label == 'ALLOCATED':                      # record ON, as a user would before Configure
                rep = drv.do('click', target='record')
                end, rec = time.monotonic() + 15, None
                while time.monotonic() < end:     # our own read-back of control's recording flag
                    rec = dc.getStatus()[3]
                    if rec is True:
                        break
                    time.sleep(0.1)
                t, d = self.wait_dom(drv, lambda d: d.get('recording') == 'true', 15)
                print(f'RECORD clicked {rep.get("t1")} reported recording={rec} (page aria-pressed '
                      f'{d.get("recording")})', flush=True)
                if rec is not True or d.get('recording') != 'true':
                    return self.check(2, False, f'record ON: control recording={rec!r}, page {d.get("recording")!r}')

        # --- running ---
        st = dc.getStatus()
        self.info['run_control'], self.info['experiment'] = st[7], st[6]
        t, d = drv.read()
        self.info['run_dom'], self.info['exp_dom'] = d.get('run'), d.get('exp')
        drv.do('shot', path=os.path.join(a.shots, 'e2e-01-running.png'))
        if a.breakage == 'kill-drp':
            pid, cmd = find_drp(self.state)
            say(f'--break kill-drp: SIGKILL pid {pid}: {cmd[:160]}')
            if pid:
                os.kill(pid, signal.SIGKILL)
            self.info['killed'] = f'{pid} {cmd[:80]}'
        end = time.monotonic() + need / max(self.state['rate'], 1.) * 3 + 30
        count = None
        while time.monotonic() < end:
            count = self.pv_count()
            if count is not None and count >= need:
                break
            time.sleep(0.5)
        self.info['count_running'] = count
        say(f'own read {self.pv} = {count} at {now()}')
        self.check(1, count is not None and count >= need,
                   f'own NumL0Acc read {count} {">=" if (count or 0) >= need else "<"} {need} while RUNNING, '
                   f'before the click down')
        t, d = drv.read()
        self.check(4, re.fullmatch(r'\d+', d.get('evt') or '') is not None,
                   f'page events {d.get("evt")!r} while RUNNING parse as ^\\d+$')

        # --- down: Disable ---
        if not self.go(drv, dc, 'PAUSED', lambda: drv.do('state', value='PAUSED')):
            return False
        t_dis = self.info['t_paused']
        self.info['count_after_disable'] = self.pv_count()
        t1, d1 = self.wait_dom(drv, lambda d: d.get('evt_final') == '1', 20)
        time.sleep(1.2)
        t2, d2 = drv.read()
        ts = float(d2.get('evt_ts') or 0)
        self.info.update(gui=d2.get('evt'), gui_ts=ts, gui_final=d2.get('evt_final'), gui_source=d2.get('evt_source'))
        self.check(3, d1.get('evt_final') == '1' and d2.get('evt_final') == '1' and ts > t_dis and
                   d1.get('evt') == d2.get('evt'),
                   f'after Disable (reported {iso(t_dis)}): data-final {d1.get("evt_final")},{d2.get("evt_final")}; '
                   f'data-ts {iso(ts) if ts else None} {">" if ts > t_dis else "<="} Disable; readings at {t1} and '
                   f'{t2}: {d1.get("evt")!r} {"==" if d1.get("evt") == d2.get("evt") else "!="} {d2.get("evt")!r}; '
                   f'source {d2.get("evt_source")}')
        self.check(4, re.fullmatch(r'\d+', d2.get('evt') or '') is not None,
                   f'page events {d2.get("evt")!r} parse as ^\\d+$')
        drv.do('shot', path=os.path.join(a.shots, 'e2e-02-paused.png'))

        for label in DOWN[1:]:
            if not self.go(drv, dc, label, lambda label=label: drv.do('state', value=label)):
                return False
            if label == 'CONFIGURED':                     # DAQ counters live until Unconfigure
                counts = {}
                for port in ds.prometheus_targets(self.work.path('prom')):
                    for k, v in ds.scrape(port, ds.COUNTERS).items():
                        counts[k.split('{')[0]] = int(v)
                self.info['prom'] = counts
                self.info['count_configured'] = self.pv_count()
                say(f'in CONFIGURED: Prometheus {counts}; own NumL0Acc {self.info["count_configured"]}')
        t, d = drv.read()
        self.info['gui_after_reset'] = d.get('evt')
        self.check(5, d.get('evt') == self.info['gui'] and d.get('evt_final') == '1',
                   f'after RESET the page shows {d.get("evt")!r} (data-final {d.get("evt_final")}), '
                   f'after Disable it showed {self.info["gui"]!r}')
        drv.do('shot', path=os.path.join(a.shots, 'e2e-03-reset.png'))
        self.info['dom_errors'] = d.get('errors')
        return True

    def finish(self):
        """Assertions 2 (stream/log part) and 6, after the clicks."""
        a, info = self.args, self.info
        errors = [m for m in self.msgs if m[1] == 'error']
        log = control_log(self.work)
        keyerr = 0
        if log:
            with open(log, errors='replace') as f:
                keyerr = sum(1 for line in f if 'KeyError' in line)
        info['control_log'] = f'{log} ({keyerr} KeyError lines)'
        if 2 not in self.res:
            self.check(2, len(self.rows) == len(UP) + len(DOWN) and all(r[4] for r in self.rows)
                       and not errors and keyerr == 0,
                       f'control read back {sum(1 for r in self.rows if r[4])}/{len(UP) + len(DOWN)} clicked states; '
                       f'{len(errors)} error message(s) on control\'s status stream; {keyerr} KeyError line(s) in '
                       f'the control log')
        elif errors:
            say(f'{len(errors)} error message(s) on control\'s status stream: {[e[2] for e in errors]}')
        run = info.get('run_control')
        exp = info.get('experiment')
        if 'gui' in info and isinstance(run, int) and run > 0:
            if str(run) != str(info.get('run_dom')) or exp != info.get('exp_dom'):
                self.check(6, False, f'page run {info.get("run_dom")} exp {info.get("exp_dom")} != control run {run} '
                                     f'exp {exp}')
            ps = ds._psana_counts(self.work, self.state, exp, run)
            info.update(ps)
            gui = int(info['gui']) if re.fullmatch(r'\d+', info.get('gui') or '') else None
            teb = info.get('prom', {}).get('TEB_WrtCt')
            vals = [gui, teb, ps.get('psana2 events'), ps.get('psana2 with data')]
            direct = info.get('count_after_disable')
            ok = None not in vals and len(set(vals)) == 1 and gui >= a.events and gui == direct and \
                ps.get('psana2 checks') == 'PASS'
            self.check(6, ok, f'page {gui} == TEB_WrtCt {teb} == psana2 events {ps.get("psana2 events")} == '
                              f'with data {ps.get("psana2 with data")} >= {a.events}: '
                              f'{None not in vals and len(set(vals)) == 1 and (gui or 0) >= a.events}; '
                              f'page == own NumL0Acc after Disable {direct}: {gui == direct}; '
                              f'psana2 checks {ps.get("psana2 checks")}; run {run} (page {info.get("run_dom")})')
        for n in range(1, 7):
            if n not in self.res:
                self.res[n] = (False, 'not reached')


def table(r, header):
    info = r.info
    print('=' * 100, flush=True)
    print('E2E summary  ' + header, flush=True)
    print('transitions (driver click -> own DaqControl.getState read-back):', flush=True)
    for label, clicked, reported, shown, ok in r.rows:
        print(f'  {label:<12} clicked {clicked} reported {reported}  {"OK" if ok else "FAIL"}', flush=True)
    ts = info.get('gui_ts')
    rows = [
        ('web GUI #edi_evt (page)', f'{info.get("gui")}  data-final {info.get("gui_final")}  data-ts '
                                    f'{iso(ts) if ts else None}  source {info.get("gui_source")}'),
        ('web GUI after RESET', info.get('gui_after_reset')),
        ('own NumL0Acc read, RUNNING', info.get('count_running')),
        ('own NumL0Acc read, after Disable', info.get('count_after_disable')),
        ('own NumL0Acc read, CONFIGURED', info.get('count_configured')),
        ('TEB_WrtCt (Prometheus, CONFIGURED)', (info.get('prom') or {}).get('TEB_WrtCt')),
        ('TEB_EvtCt', (info.get('prom') or {}).get('TEB_EvtCt')),
        ('psana2 events', info.get('psana2 events')),
        ('psana2 events with data', info.get('psana2 with data')),
        ('psana2 checks', info.get('psana2 checks')),
        ('psana2 seq', info.get('psana2 seq')),
        ('xtc2 file', info.get('xtc2 file')),
        ('run (page / control)', f'{info.get("run_dom")} / {info.get("run_control")}  experiment '
                                 f'{info.get("exp_dom")} / {info.get("experiment")}'),
        ('control log', info.get('control_log')),
    ]
    if 'killed' in info:
        rows.append(('--break kill-drp killed', info['killed']))
    print('counts:', flush=True)
    for k, v in rows:
        print(f'  {k:<36} {v}', flush=True)
    print('assertions:', flush=True)
    for n in range(1, 7):
        ok, text = r.res[n]
        print(f'  {n} {"PASS" if ok else "FAIL"}  {text}', flush=True)


def cmd_e2e(args):
    t0 = time.time()
    host = socket.gethostname()
    ds.check_host(args.any_host)
    work = ds.Work(args.workdir)
    try:
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10).stdout.strip()
    except OSError:
        sha = ''
    dev = subprocess.run('ls /dev/datadev* /dev/pcie_adc* /dev/tpr* 2>&1', shell=True, capture_output=True,
                         text=True).stdout.strip()
    header = (f'host {host}  Slurm job {os.environ.get("SLURM_JOB_ID")} step {os.environ.get("SLURM_STEP_ID")}  '
              f'git HEAD of cwd {sha or "(none)"}  workdir {work.dir}  events {args.events}  '
              f'break {args.breakage}')
    say(header)
    say(f'devices: {dev}')
    py, bpath, line = check_browser(args)
    say(f'browser venv OK: {line}')
    os.makedirs(work.dir, exist_ok=True)
    args.shots = os.path.abspath(args.shots or work.path('e2e-shots'))
    os.makedirs(args.shots, exist_ok=True)
    state, started_here = bring_up(args, work)
    r = Run(args, work, state)
    drv = None
    try:
        drv = Driver(py, bpath, work.path('logs', 'e2e-driver.log'), args.timeout)
        r.run(drv)
    except Exception as e:
        r.check(2, False, f'stopped: {type(e).__name__}: {e}')
    finally:
        if drv is not None:
            drv.close()
    try:
        r.finish()
    except Exception as e:
        r.check(6, False, f'count checks stopped: {type(e).__name__}: {e}')
        for n in range(1, 7):
            r.res.setdefault(n, (False, 'not reached'))
    down = None
    if not args.keep_up:
        say('daq_sim down')
        down = ds.teardown(work)
    ok = all(r.res[n][0] for n in range(1, 7))
    table(r, header + f'  run {r.info.get("run_control")}  took {time.time() - t0:.0f} s  '
                      f'down {"clean" if down else ("NOT clean" if down is False else "skipped (--keep-up)")}')
    if down is False:
        print('E2E FAIL: daq_sim down was not clean', flush=True)
        ok = False
    if ok:
        print('E2E PASS', flush=True)
    else:
        failed = [n for n in range(1, 7) if not r.res[n][0]]
        for n in failed:
            print(f'E2E FAIL: assertion {n}: {r.res[n][1]}', flush=True)
        print('E2E FAIL', flush=True)
    if args.keep_up and started_here:
        say(f'--keep-up: the DAQ stays up while this process runs (it holds the Slurm step); '
            f'web GUI {ds.webgui_url(state)}; Ctrl-C or daq_sim down -w {work.dir} ends it')
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, lambda *x: stop.set())
        while not stop.wait(2):
            st = work.load()
            if st is None or st.get('down') == 'done':
                break
        if (work.load() or {}).get('down') != 'done':
            ds.teardown(work)
    return 0 if ok else 1
