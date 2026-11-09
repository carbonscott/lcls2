"""
Parity check of every PyQt GUI in psdaq other than the control GUI, by the control GUI's method.

The files: qapps.scan() lists, from source, every psdaq file outside control_gui that constructs a
QApplication.  Each one needs a spec parity/guis/<name>.json whose "file" names it:

  a GUI program with a web version
      {"file", "web": "<path the web GUI serves>", "backend": "sim-daq" | "sim-device:<stand-in>",
       "walk": {"argv": [...], "pump", "drive", "record_calls", "variants": [{"argv": ...}, ...],
                "devices": [{"module": "<campaign simulator psdaq/sim/<module>.py>", "args": [...]}]},
       "mapping": {"<row id>": {"web": "<CSS selector>", "test": "<pytest node id>[chromium]"} | {"na": "<reason>"}}}
      Rows: gui_rows.make_rows from the source sites and the offscreen walk of the running program
      (qt_walk --gui against the simulated DAQ), run by --run-walks, as check_parity --run-walk does for
      the control GUI.  No walk is kept in the tree: --run-walks writes <name>.walk.json to --walks DIR
      (default a new temporary dir) and checks with it; --walks DIR alone reads an earlier run's files.
      check_parity.check counts them exactly as for the control GUI: M = mapped rows whose
      headless-browser test passed in a --junit file, is tagged with the row (junit `parity`) and
      recorded the spec's backend and nothing else; K = "na" rows the enumerator flags (main-block,
      def-unreachable, no-object, inert) whose walk verdict is 'agree' and whose reason cites the guard;
      a mapped row the walk does not show built fails.  PASS only if M + K = N, nothing stale or invalid,
      and the walk is of the same source (sha256 of the GUI's own files).
      A backend sim-device:<name> is accepted only when <name> is a campaign simulator, a module
      psdaq/sim/<name>.py (e.g. simxpm), and the test recorded it (webgui_harness checks it runs).
  not a standalone GUI program
      {"file", "na": "<one-line reason citing every construction line>", "rule": "walk-tool" | "library-demo" |
       "no-window", ["walk": {...}]}
      walk-tool:    every construction is in a function that sets QT_QPA_PLATFORM=offscreen and the file has
                    no entry point (the parity walk itself);
      library-demo: every construction is under `if __name__ == '__main__':`, the file has no entry point,
                    other psdaq files import it, and the run-time probe (qt_walk --probe-import, run by
                    --run-walks into <name>.probe.json) shows importing it constructs no QApplication;
      no-window:    the program's own entry, walked now (the spec's "walk", against the simulated DAQ), raises
                    in its own files before QApplication.exec_ and shows no window (no GUI runs at this commit);
                    the reason cites the line that raised.
A file with no spec is a GUI program without a web version: FAIL (its source rows are counted).

Output: one line per file `file | web path or N/A reason | N/M/K | PASS|FAIL`, then the rows that keep
each failing GUI from passing; exit 0 only if every file passes.

Usage (DAQ env, PyQt5; $WD the work dir of a running daq_sim up):
    python -m psdaq.webgui.parity.check_gui_parity --run-walks --sim-daq $WD --junit FILE [--only NAME] [--details]
    python -m psdaq.webgui.parity.check_gui_parity --walks DIR --junit FILE      # the walks an earlier --run-walks wrote
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

from psdaq.webgui.parity import check_parity, gui_rows, qapps

HERE = os.path.dirname(os.path.abspath(__file__))
GUIS_DIR = os.path.join(HERE, 'guis')


def load_specs(d=GUIS_DIR):
    out = {}
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not n.endswith('.json') or n.endswith('.walk.json') or n.endswith('.probe.json'):
            continue
        with open(os.path.join(d, n)) as f:
            spec = json.load(f)
        spec['_name'] = n[:-5]
        spec['_path'] = os.path.join(d, n)
        if spec.get('file') in out:
            raise SystemExit('check_gui_parity: two specs name %s' % spec['file'])
        out[spec['file']] = spec
    return out


def walk_path(spec, d):
    return os.path.join(d, spec['_name'] + '.walk.json')


def probe_path(spec, d):
    return os.path.join(d, spec['_name'] + '.probe.json')


def check_no_window(e, spec, d, src):
    """(ok, why) for rule no-window: the program's own entry, walked now against the simulated DAQ, raised before
    QApplication.exec_ and showed no window; the reason cites the own-file line that raised."""
    p = walk_path(spec, d) if d else None
    if not p or not os.path.isfile(p):
        return False, 'no walk %s.walk.json (run with --run-walks)' % spec['_name']
    with open(p) as f:
        walk = json.load(f)
    digest = gui_rows.files_digest(src, gui_rows.own_and_libs(src, e['file'])[0]) if src else None
    if digest and walk.get('src_digest') != digest:
        return False, 'walk is of other source (%s, the tree has %s)' % (walk.get('src_digest'), digest)
    ee = walk.get('entry_error')
    if not ee or not ee.get('own_frames'):
        return False, 'the walk ran without an error in the program\'s own files (notes: %s)' % walk.get('notes', [])[:2]
    if any(ph[0] == 'exec' for ph in walk.get('phase_log', [])):
        return False, 'the walk reached QApplication.exec_: the program shows a window'
    shown = [x for x in walk.get('instances', []) if x.get('window_visible')]
    if shown:
        return False, '%d widget(s) in a visible window' % len(shown)
    at = '%s:%d' % tuple(ee['own_frames'][-1][:2])
    if at not in spec['na']:
        return False, 'na reason must cite the line that raised (%s)' % at
    return True, 'rule no-window: walk (argv %s, python %s, qt %s) of its own entry raised %s at %s (%s) before ' \
                 'QApplication.exec_; no window shown (%d widgets built, none visible)' % (
                     walk.get('argv'), walk.get('python'), walk.get('qt'), ee['type'], at, ee['message'][:120],
                     len(walk.get('instances', [])))


def check_na(e, spec, d=None, src=None):
    """(ok, why) for a not-a-GUI-program spec; d: the dir --run-walks wrote the walks and probes to (None: none)."""
    reason, rule = spec.get('na'), spec.get('rule')
    if not isinstance(reason, str) or not reason.strip() or '\n' in reason:
        return False, 'na reason must be a non-empty one-line string'
    miss = ['%s:%d' % (e['file'], s['line']) for s in e['sites'] if '%s:%d' % (e['file'], s['line']) not in reason]
    if miss:
        return False, 'na reason must cite every construction line (%s)' % ', '.join(miss)
    if rule == 'no-window':
        return check_no_window(e, spec, d, src)
    if e.get('entry'):
        return False, 'has an entry point (%s): a program' % '; '.join(e['entry'])
    if rule == 'walk-tool':
        bad = [s['line'] for s in e['sites'] if not s['offscreen']]
        if bad:
            return False, 'construction(s) at line(s) %s not in a function that sets QT_QPA_PLATFORM=offscreen' % bad
        return True, 'rule walk-tool: every construction (%s) in a function that sets QT_QPA_PLATFORM=offscreen; ' \
                     'no entry point' % ', '.join('%s:%d in %s' % (e['file'], s['line'], s['scope']) for s in e['sites'])
    if rule == 'library-demo':
        bad = [s['line'] for s in e['sites'] if not s['main_block']]
        if bad:
            return False, 'construction(s) at line(s) %s outside the __main__ block' % bad
        if not e.get('imported_by'):
            return False, 'no other psdaq file imports it: not a library'
        p = probe_path(spec, d) if d else None
        if not p or not os.path.isfile(p):
            return False, 'no run-time import probe %s.probe.json (run with --run-walks)' % spec['_name']
        with open(p) as f:
            pr = json.load(f)
        mod = qapps._module_name(e['file'])
        if pr.get('module') != mod or pr.get('error') or pr.get('qapplications_on_import') != 0:
            return False, 'import probe: module %s error %s, %s QApplication(s) on import' % (
                pr.get('module'), pr.get('error'), pr.get('qapplications_on_import'))
        return True, 'rule library-demo: imported by %s; QApplication only under __main__ (line %d); importing it ' \
                     'constructed 0 QApplications (probe, python %s)' % (', '.join(e['imported_by']), e['main_block'],
                                                                      pr.get('python'))
    return False, 'unknown na rule %r' % rule


def campaign_simulators(src):
    d = os.path.join(src, 'sim')
    return sorted(n[:-3] for n in os.listdir(d) if n.endswith('.py') and n != '__init__.py') if os.path.isdir(d) else []


def check_gui(src, e, spec, results, d=None):
    """(rep, srcinfo, walk, rows) for a GUI program spec; d: the dir --run-walks wrote the walks to (None: none)."""
    srcinfo = gui_rows.source_sites(src, e['file'])
    wp = walk_path(spec, d) if d else None
    walk = None
    note = ''
    if wp and os.path.isfile(wp):
        with open(wp) as f:
            walk = json.load(f)
        if walk.get('src_digest') != srcinfo['digest']:
            note = 'walk %s is of other source (%s, the tree has %s)' % (os.path.basename(wp), walk.get('src_digest'),
                                                                        srcinfo['digest'])
    else:
        note = 'no walk %s.walk.json (run with --run-walks)' % spec['_name']
    rows = gui_rows.make_rows(srcinfo, walk)
    backend = spec.get('backend', 'sim-daq')
    if backend.startswith('sim-device:') and backend.split(':', 1)[1] not in campaign_simulators(src):
        raise SystemExit('check_gui_parity: %s backend %s: %s is not a campaign simulator (psdaq/sim/*.py: %s)' % (
            spec['_name'], backend, backend.split(':', 1)[1], campaign_simulators(src)))
    rep = check_parity.check(rows, spec.get('mapping', {}), results, False, walk, srcinfo['digest'],
                             reconcile_fn=gui_rows.reconcile, built_fn=gui_rows.built, required_backend=backend)
    if note:
        rep['walk_note'] = note
    return rep, srcinfo, walk, rows


def run_walks(src, specs, files, sim_dir, d, only=None, python=sys.executable, log=sys.stderr):
    """Run, now, the offscreen walk (qt_walk --gui, every variant, merged) of each GUI program spec against the
    simulated DAQ of sim_dir, and the import probe of each library-demo spec, with `python` (PyQt5); write
    <name>.walk.json / <name>.probe.json to d.  One progress line per walk to log."""
    os.makedirs(d, exist_ok=True)
    for e in files:
        spec = specs.get(e['file'])
        if spec is None or (only and spec['_name'] != only):
            continue
        env = dict(os.environ)
        env['PYTHONPATH'] = os.path.dirname(src) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        if spec.get('rule') == 'library-demo':
            cmd = [python, '-m', 'psdaq.webgui.parity.qt_walk', '--probe-import', qapps._module_name(e['file']),
                   '--out', probe_path(spec, d)]
            p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
            log.write('%s: %s\n' % (spec['_name'], p.stdout.strip().splitlines()[-1] if p.stdout.strip()
                                     else 'probe exit %d' % p.returncode))
            log.flush()
            continue
        if 'walk' not in spec:
            continue
        walks = []
        variants = [{}] + spec['walk'].get('variants', [])
        devs = start_devices(spec, sim_dir, env, python, log)
        try:
            run_variants(spec, variants, sim_dir, d, env, python, log, walks)
        finally:
            for p, _ in devs:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
        merged = gui_rows.merge_walks(walks)
        merged['devices'] = [x for _, x in devs]
        with open(walk_path(spec, d), 'w') as f:
            json.dump(merged, f, indent=0, sort_keys=True)


def start_devices(spec, sim_dir, env, python, log):
    """Start the campaign simulators a spec's walk names ("devices": [{"module": "simtpr", "args": [...]}], args with
    the walk's placeholders), each `python -m psdaq.sim.<module>`, and wait for its 'ready' line."""
    out = []
    devs = spec['walk'].get('devices', [])
    if not devs:
        return out
    from psdaq.webgui.parity.qt_walk import sim_params
    params = sim_params(sim_dir)
    for dv in devs:
        args = [str(a).format(**params) for a in dv.get('args', [])]
        cmd = [python, '-m', 'psdaq.sim.' + dv['module']] + args
        p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        ready = wait_ready(p, 30)
        if ready is None:
            p.kill()
            raise SystemExit('check_gui_parity: %s did not start (%s)' % (' '.join(cmd), p.poll()))
        log.write('%s: device %s pid %d: %s\n' % (spec['_name'], dv['module'], p.pid, ready))
        log.flush()
        out.append((p, {'module': dv['module'], 'args': args, 'pid': p.pid, 'ready': ready}))
    return out


def wait_ready(p, timeout):
    """The first line of process p's output that says 'ready' (None if it exits or `timeout` s pass); the rest of its
    output is read and dropped by a thread, so the pipe never fills."""
    import queue
    import threading
    q = queue.Queue()

    def reader():
        for ln in p.stdout:
            q.put(ln)
        q.put(None)
    threading.Thread(target=reader, daemon=True).start()
    import time
    end = time.time() + timeout
    while time.time() < end:
        try:
            ln = q.get(timeout=max(0.1, end - time.time()))
        except queue.Empty:
            break
        if ln is None:
            break
        if 'ready' in ln:
            return ln.strip()
    return None


def run_variants(spec, variants, sim_dir, d, env, python, log, walks):
    for i, var in enumerate(variants):
        tmp = os.path.join(d, 'runs', '%s-%d' % (spec['_name'], i))
        os.makedirs(tmp, exist_ok=True)
        vspec = dict(spec)
        vspec['walk'] = dict(spec['walk'], **var)
        vspec.pop('_path', None)
        sp = os.path.join(tmp, 'spec.json')
        with open(sp, 'w') as f:
            json.dump(vspec, f)
        out = os.path.join(tmp, 'walk.json')
        cmd = [python, '-m', 'psdaq.webgui.parity.qt_walk', '--gui', sp, '--sim-daq', sim_dir, '--out', out,
               '--workdir', tmp]
        p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           timeout=float(vspec['walk'].get('timeout', 90)) + 60)
        lines = [ln for ln in p.stdout.splitlines() if ln.startswith('qt_walk')]
        log.write('%s variant %d %s: %s\n' % (spec['_name'], i, vspec['walk'].get('argv'), lines[-1] if lines else
                                            'exit %d: %s' % (p.returncode, p.stdout[-800:])))
        log.flush()
        if not os.path.isfile(out):
            raise SystemExit('check_gui_parity: walk of %s failed' % spec['_name'])
        with open(out) as f:
            walks.append(json.load(f))


def main(argv=None):
    ap = argparse.ArgumentParser(description='PyQt GUIs other than control_gui -> web GUI parity check')
    ap.add_argument('--src', default=qapps.default_src(), help='psdaq package dir')
    ap.add_argument('--junit', action='append', default=[], help='pytest --junitxml file (repeatable)')
    ap.add_argument('--guis', default=GUIS_DIR, help='spec dir (default %(default)s)')
    ap.add_argument('--only', help='one spec name (e.g. procstat)')
    ap.add_argument('--details', action='store_true', help='print each GUI program\'s full parity report')
    ap.add_argument('--run-walks', action='store_true',
                    help='run the offscreen walks and import probes now (PyQt5, against --sim-daq), then check')
    ap.add_argument('--walks', metavar='DIR', help='where --run-walks writes the walks and probes (default: a new '
                                                   'temporary dir); without --run-walks, read them from there')
    ap.add_argument('--walk-python', default=sys.executable, help='interpreter with PyQt5 for --run-walks')
    ap.add_argument('--sim-daq', default=os.environ.get('WEBGUI_SIM_DAQ'), help='daq_sim work dir for --run-walks')
    a = ap.parse_args(argv)
    src = os.path.abspath(a.src)
    text_only = []
    files = qapps.scan(src, text_only)
    specs = load_specs(a.guis)
    results = check_parity.load_junit(a.junit) if a.junit else None
    walks = a.walks
    if a.run_walks:
        if not a.sim_daq:
            raise SystemExit('check_gui_parity: --run-walks needs --sim-daq (or $WEBGUI_SIM_DAQ)')
        walks = walks or tempfile.mkdtemp(prefix='gui-walks-')
        run_walks(src, specs, files, a.sim_daq, walks, a.only, python=a.walk_python)
        walks_note = '%s (run now against the simulated DAQ %s)' % (walks, a.sim_daq)
    elif walks:
        walks_note = '%s (read; not run now)' % walks
    else:
        walks_note = '(none: no GUI program can pass; run with --run-walks)'
    lines, details, ok_all = [], [], True
    n_pass = 0
    for e in files:
        spec = specs.get(e['file'])
        if a.only and (spec is None or spec['_name'] != a.only):
            continue
        if e.get('parse_error'):
            lines.append('%s | cannot parse: %s | -/-/- | FAIL' % (e['file'], e['parse_error']))
            ok_all = False
            continue
        if spec is None:
            try:
                rows = gui_rows.make_rows(gui_rows.source_sites(src, e['file']), None)
                n = '%d/0/0 (source sites; no walk)' % len(rows)
            except Exception as ex:
                n = '?/0/0 (%s)' % ex
            lines.append('%s | GUI program, no web version (no parity/guis spec) | %s | FAIL' % (e['file'], n))
            ok_all = False
            continue
        if 'na' in spec:
            ok, why = check_na(e, spec, walks, src)
            lines.append('%s | N/A: %s [%s] | -/-/- | %s' % (e['file'], spec['na'], why, 'PASS' if ok else 'FAIL'))
            ok_all = ok_all and ok
            n_pass += ok
            continue
        rep, srcinfo, walk, rows = check_gui(src, e, spec, results, walks)
        ok = rep['ok']
        n_pass += ok
        ok_all = ok_all and ok
        lines.append('%s | %s | %d/%d/%d | %s' % (e['file'], spec.get('web') or '(no web path)', rep['N'], rep['M'],
                                                  rep['K'], 'PASS' if ok else 'FAIL'))
        if a.details or not ok:
            details.append(check_parity.render(rep, '--- %s (%s; own files %s; walk %s)' % (
                e['file'], spec['_name'], ', '.join(srcinfo['own']),
                ('argv %s, %s instances, elapsed %s s, python %s, qt %s' % (
                    walk.get('argv'), len(walk.get('instances', [])), walk.get('elapsed'), walk.get('python'),
                    walk.get('qt'))) if walk else 'none')))
    listed = {e['file'] for e in files}
    for f_, spec in sorted(specs.items()):
        if f_ not in listed and not a.only:
            lines.append('%s | stale spec %s: the file does not construct a QApplication | -/-/- | FAIL' % (
                f_, spec['_name']))
            ok_all = False
    print('check_gui_parity: src=%s junit=%s' % (src, ','.join(a.junit) or '(none)'))
    print('walks: %s' % walks_note)
    print('%d psdaq files outside control_gui construct a QApplication (qapps, from the syntax tree)' % len(files))
    for t in text_only:
        print('  (not listed: %s has "QApplication(" only in %s; its syntax tree constructs none)' % (
            t['file'], ('string constant(s) at line(s) %s' % ', '.join(map(str, t['string_lines'])))
            if t['string_lines'] else 'comments'))
    print('file | web path or N/A reason | N/M/K | result')
    for ln in lines:
        print(ln)
    for dt in details:
        print()
        print(dt)
    print()
    print('RESULT: %s (%d/%d files pass)' % ('PASS' if ok_all and lines else 'FAIL', n_pass, len(lines)))
    return 0 if ok_all and lines else 1


if __name__ == '__main__':
    sys.exit(main())
