"""
Parity check of every PyQt GUI in psdaq other than the control GUI, by the control GUI's method.

The files: qapps.scan() lists, from source, every psdaq file outside control_gui that constructs a
QApplication.  Each one needs a spec parity/guis/<name>.json whose "file" names it:

  a GUI program with a web version
      {"file", "web": "<path the web GUI serves>", "backend": "sim-daq" | "sim-device:<stand-in>",
       "walk": {"argv": [...], "pump", "drive", "record_calls", "variants": [{"argv": ...}, ...]},
       "mapping": {"<row id>": {"web": "<CSS selector>", "test": "<pytest node id>[chromium]"} | {"na": "<reason>"}}}
      Rows: gui_rows.make_rows from the source sites and the saved offscreen walk
      (parity/guis/<name>.walk.json, written by --run-walks from qt_walk --gui against the simulated DAQ).
      check_parity.check counts them exactly as for the control GUI: M = mapped rows whose
      headless-browser test passed in a --junit file, is tagged with the row (junit `parity`) and
      recorded the spec's backend and nothing else; K = "na" rows the enumerator flags (main-block,
      def-unreachable, no-object, inert) whose walk verdict is 'agree' and whose reason cites the guard;
      a mapped row the walk does not show built fails.  PASS only if M + K = N, nothing stale or invalid,
      and the walk is of the same source (sha256 of the GUI's own files).
      A backend sim-device:<name> is accepted only when <name> is a campaign simulator, a module
      psdaq/sim/<name>.py (e.g. simxpm), and the test recorded it (webgui_harness checks it runs).
  not a standalone GUI program
      {"file", "na": "<one-line reason citing every construction line>", "rule": "walk-tool" | "library-demo"}
      walk-tool:    every construction is in a function that sets QT_QPA_PLATFORM=offscreen and the file has
                    no entry point (the parity walk itself);
      library-demo: every construction is under `if __name__ == '__main__':`, the file has no entry point,
                    other psdaq files import it, and the run-time probe (parity/guis/<name>.probe.json,
                    qt_walk --probe-import) shows importing it constructs no QApplication.
A file with no spec is a GUI program without a web version: FAIL (its source rows are counted).

Output: one line per file `file | web path or N/A reason | N/M/K | PASS|FAIL`, then the rows that keep
each failing GUI from passing; exit 0 only if every file passes.

Usage:
    python -m psdaq.webgui.parity.check_gui_parity [--src DIR] [--junit FILE ...] [--only NAME] [--details]
    python -m psdaq.webgui.parity.check_gui_parity --run-walks --sim-daq $WD [--only NAME]   # DAQ env, PyQt5
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


def walk_path(spec, d=GUIS_DIR):
    return os.path.join(d, spec['_name'] + '.walk.json')


def probe_path(spec, d=GUIS_DIR):
    return os.path.join(d, spec['_name'] + '.probe.json')


def check_na(e, spec, d=GUIS_DIR):
    """(ok, why) for a not-a-GUI-program spec."""
    reason, rule = spec.get('na'), spec.get('rule')
    if not isinstance(reason, str) or not reason.strip() or '\n' in reason:
        return False, 'na reason must be a non-empty one-line string'
    miss = ['%s:%d' % (e['file'], s['line']) for s in e['sites'] if '%s:%d' % (e['file'], s['line']) not in reason]
    if miss:
        return False, 'na reason must cite every construction line (%s)' % ', '.join(miss)
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
        p = probe_path(spec, d)
        if not os.path.isfile(p):
            return False, 'no run-time import probe %s (run --run-walks)' % os.path.relpath(p, HERE)
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


def check_gui(src, e, spec, results, d=GUIS_DIR):
    """(rep, srcinfo, walk, note) for a GUI program spec."""
    srcinfo = gui_rows.source_sites(src, e['file'])
    wp = walk_path(spec, d)
    walk = None
    note = ''
    if os.path.isfile(wp):
        with open(wp) as f:
            walk = json.load(f)
        if walk.get('src_digest') != srcinfo['digest']:
            note = 'walk %s is of other source (%s, the tree has %s)' % (os.path.basename(wp), walk.get('src_digest'),
                                                                        srcinfo['digest'])
    else:
        note = 'no walk %s (run --run-walks)' % os.path.basename(wp)
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


def run_walks(src, specs, files, sim_dir, only=None, python=sys.executable, d=GUIS_DIR):
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
            print(p.stdout.strip().splitlines()[-1] if p.stdout.strip() else 'probe exit %d' % p.returncode)
            continue
        if 'walk' not in spec:
            continue
        walks = []
        variants = [{}] + spec['walk'].get('variants', [])
        for i, var in enumerate(variants):
            tmp = tempfile.mkdtemp(prefix='gui-walk-')
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
            print('%s variant %d %s: %s' % (spec['_name'], i, vspec['walk'].get('argv'), lines[-1] if lines else
                                            'exit %d: %s' % (p.returncode, p.stdout[-800:])))
            if not os.path.isfile(out):
                raise SystemExit('check_gui_parity: walk of %s failed' % spec['_name'])
            with open(out) as f:
                walks.append(json.load(f))
        merged = gui_rows.merge_walks(walks)
        with open(walk_path(spec, d), 'w') as f:
            json.dump(merged, f, indent=0, sort_keys=True)
        print('%s: walk saved to %s' % (spec['_name'], walk_path(spec, d)))


def main(argv=None):
    ap = argparse.ArgumentParser(description='PyQt GUIs other than control_gui -> web GUI parity check')
    ap.add_argument('--src', default=qapps.default_src(), help='psdaq package dir')
    ap.add_argument('--junit', action='append', default=[], help='pytest --junitxml file (repeatable)')
    ap.add_argument('--guis', default=GUIS_DIR, help='spec dir (default %(default)s)')
    ap.add_argument('--only', help='one spec name (e.g. procstat)')
    ap.add_argument('--details', action='store_true', help='print each GUI program\'s full parity report')
    ap.add_argument('--run-walks', action='store_true', help='run the offscreen walks / import probes (PyQt5) and save')
    ap.add_argument('--sim-daq', default=os.environ.get('WEBGUI_SIM_DAQ'), help='daq_sim work dir for --run-walks')
    a = ap.parse_args(argv)
    src = os.path.abspath(a.src)
    text_only = []
    files = qapps.scan(src, text_only)
    specs = load_specs(a.guis)
    if a.run_walks:
        if not a.sim_daq:
            raise SystemExit('check_gui_parity: --run-walks needs --sim-daq (or $WEBGUI_SIM_DAQ)')
        run_walks(src, specs, files, a.sim_daq, a.only, d=a.guis)
        return 0
    results = check_parity.load_junit(a.junit) if a.junit else None
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
            ok, why = check_na(e, spec, a.guis)
            lines.append('%s | N/A: %s [%s] | -/-/- | %s' % (e['file'], spec['na'], why, 'PASS' if ok else 'FAIL'))
            ok_all = ok_all and ok
            n_pass += ok
            continue
        rep, srcinfo, walk, rows = check_gui(src, e, spec, results, a.guis)
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
