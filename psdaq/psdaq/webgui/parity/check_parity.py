"""
Parity check: PyQt control GUI affordances (enumerated live from the PyQt
source by enumerate_pyqt) against the web GUI mapping, the web GUI's
headless-browser test results and the offscreen PyQt runtime walk (qt_walk).

Inputs
  rows      computed from the source tree (--src, default: the installed psdaq)
  mapping   mapping.json plus mapping.d/*.json:
              {"<row id>": {"web": "<CSS selector>", "test": "<pytest node id>"}
                         | {"na": "<one-line reason>"}}
  junit     one or more pytest --junitxml files from the web GUI's Playwright tests
  walk      raw observations of the offscreen PyQt walk (--walk, default the
            parity/qt_walk.json saved next to this file, so CI needs no Qt; or
            --run-walk to run psdaq.webgui.parity.qt_walk now)

A row counts as
  M  mapped: a "web"+"test" entry whose test is a headless-browser test
     (pytest-playwright id, e.g. [chromium]) that is in a junit file, passed
     (no failure, error or skipped child), AND whose junit testcase carries the
     row id in a `parity` property (the test calls record_property('parity', id));
  K  not applicable: an "na" entry whose one-line reason cites the row's guard
     line (enumerate_pyqt row['guard']: the `if __name__ == "__main__":` line,
     the setVisible test, the commented import, the dispatch) when it has one,
     on a row the enumerator flags (not reachable, hidden or inert), AND the
     walk agrees with the flag (qt_walk.reconcile verdict 'agree'), the walk
     being of the same control_gui source (sha256 digest).
     An na on a user-facing row is refused unless --allow-unproven-na.
The check passes (exit 0) only if N > 0 and M + K = N and there are no stale
entries (ids not in the enumeration) and no invalid entries.  Otherwise it
prints what is unmapped, failing, unconfirmed, stale or invalid and exits 1.

Usage:
    python -m psdaq.webgui.parity.check_parity [--src DIR] [--mapping FILE]
        [--junit FILE ...] [--walk FILE | --run-walk [--walk-python PY]]
        [--allow-unproven-na] [--json]
"""

import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from psdaq.webgui.parity.enumerate_pyqt import default_src, enumerate_rows
from psdaq.webgui.parity import qt_walk

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MAPPING = os.path.join(HERE, 'mapping.json')
BROWSER_PARAMS = ('[chromium', '[firefox', '[webkit')


def load_mapping(path):
    """mapping.json plus every fragment in mapping.d/ next to it (sorted by name).
    A row id may appear in only one of them, so separate owners never edit one file."""
    with open(path) as f:
        mapping = json.load(f)
    frag_dir = os.path.join(os.path.dirname(os.path.abspath(path)), 'mapping.d')
    if os.path.isdir(frag_dir):
        for name in sorted(os.listdir(frag_dir)):
            if not name.endswith('.json'):
                continue
            with open(os.path.join(frag_dir, name)) as f:
                frag = json.load(f)
            dup = sorted(set(frag) & set(mapping))
            if dup:
                raise SystemExit('check_parity: %s repeats ids already mapped: %s' % (name, ', '.join(dup)))
            mapping.update(frag)
    return mapping


def nodeid_key(nodeid):
    """(classname, name) as pytest's junitxml writes them for a node id."""
    parts = nodeid.split('::')
    path = parts[0]
    if path.endswith('.py'):
        path = path[:-3]
    names = [path.replace('/', '.').replace(os.sep, '.')] + parts[1:-1]
    return '.'.join(names), parts[-1]


def load_junit(paths):
    """{(classname, name): {'status': 'passed' | 'failed' | 'error' | 'skipped', 'parity': set of row ids}}"""
    out = {}
    for p in paths:
        root = ET.parse(p).getroot()
        for tc in root.iter('testcase'):
            key = (tc.get('classname', ''), tc.get('name', ''))
            status = 'passed'
            for child in tc:
                if child.tag in ('failure', 'error', 'skipped'):
                    status = {'failure': 'failed'}.get(child.tag, child.tag)
                    break
            props = {pr.get('value', '') for pr in tc.iter('property') if pr.get('name') == 'parity'}
            prev = out.get(key)
            if prev is None:
                out[key] = {'status': status, 'parity': props}
            else:
                # a test that ran several times passes only if every run passed and tags only what every run tagged
                out[key] = {'status': status if prev['status'] == 'passed' else prev['status'],
                            'parity': prev['parity'] & props}
    return out


def test_status(results, nodeid, rid=None):
    """'passed' (and, given rid, tagged with it) | 'failed' | 'error' | 'skipped' | 'missing' | 'untagged'"""
    cls, name = nodeid_key(nodeid)
    hits = [v for (c, n), v in results.items()
            if n == name and (c == cls or c.endswith('.' + cls) or cls.endswith('.' + c))]
    if not hits:
        return 'missing'
    bad = sorted(set(h['status'] for h in hits) - {'passed'})
    if bad:
        return bad[0]
    if rid is not None and not all(rid in h['parity'] for h in hits):
        return 'untagged'
    return 'passed'


def enum_flags(row):
    f = []
    if not row['reachable']:
        f.append('unreachable:%s' % row['reach'])
    if row['hidden']:
        f.append('hidden')
    if row['inert']:
        f.append('inert')
    return f


def na_group(row):
    if not row['reachable']:
        return row['reach']
    return 'hidden' if row['hidden'] else 'inert'


def check(rows, mapping, results, allow_unproven_na=False, walk=None, src_digest=None):
    """walk: raw qt_walk observations (dict) or None; src_digest: digest of the --src control_gui."""
    by = {r['id']: r for r in rows}
    rep = {'N': len(rows), 'mapped': [], 'na': [], 'unproven_na': [], 'unconfirmed_na': [], 'unmapped': [],
           'failing': [], 'stale': [], 'invalid': [], 'allow': allow_unproven_na, 'walk_note': ''}
    verdicts = {}
    if walk is None:
        rep['walk_note'] = 'no walk: no na row can be confirmed'
    elif src_digest is not None and walk.get('src_digest') != src_digest:
        rep['walk_note'] = 'walk is of other source (%s, --src has %s): no na row can be confirmed' % (
            walk.get('src_digest'), src_digest)
        walk = None
    else:
        verdicts = qt_walk.reconcile(rows, walk)
        rep['walk_note'] = 'walk source digest matches (%s)' % walk.get('src_digest')
    for rid in sorted(mapping):
        if rid not in by:
            rep['stale'].append(rid)
    for r in rows:
        rid = r['id']
        e = mapping.get(rid)
        if e is None:
            rep['unmapped'].append(r)
            continue
        if not isinstance(e, dict):
            rep['invalid'].append((rid, 'entry is not an object'))
            continue
        keys = set(e)
        if keys == {'na'}:
            reason = e['na']
            if not isinstance(reason, str) or not reason.strip() or '\n' in reason:
                rep['invalid'].append((rid, 'na reason must be a non-empty one-line string'))
                continue
            if r.get('guard') and r['guard'] not in reason:
                rep['invalid'].append((rid, 'na reason must cite the guard line %s' % r['guard']))
                continue
            if not enum_flags(r):
                rep['unproven_na'].append((r, reason))
                if allow_unproven_na:
                    rep['na'].append((r, reason, ('unchecked', 'user-facing row, --allow-unproven-na')))
                continue
            v = verdicts.get(rid, ('no walk', rep['walk_note']))
            if v[0] == 'agree':
                rep['na'].append((r, reason, v))
            else:
                rep['unconfirmed_na'].append((r, reason, v))
            continue
        if keys == {'web', 'test'}:
            if not all(isinstance(e[k], str) and e[k].strip() for k in ('web', 'test')):
                rep['invalid'].append((rid, 'web and test must be non-empty strings'))
                continue
            if not any(b in e['test'] for b in BROWSER_PARAMS):
                rep['invalid'].append((rid, 'test %s is not a headless-browser (pytest-playwright) test' % e['test']))
                continue
            st = test_status(results, e['test'], rid) if results is not None else 'no junit given'
            if st == 'passed':
                rep['mapped'].append((r, e))
            else:
                rep['failing'].append((r, e, st))
            continue
        rep['invalid'].append((rid, 'keys must be {"web","test"} or {"na"}, got %s' % sorted(keys)))
    rep['M'] = len(rep['mapped'])
    rep['K'] = len(rep['na'])
    blocking = [] if allow_unproven_na else rep['unproven_na']
    rep['ok'] = (rep['N'] > 0 and rep['M'] + rep['K'] == rep['N'] and not rep['stale']
                 and not rep['invalid'] and not blocking)
    return rep


def render(rep, header=''):
    L = []
    if header:
        L.append(header)
    L.append('%d controls found, %d mapped to a web element with a passing headless-browser test, '
             '%d marked not applicable' % (rep['N'], rep['M'], rep['K']))
    L.append('N = %d, M = %d, K = %d, M + K = %d' % (rep['N'], rep['M'], rep['K'], rep['M'] + rep['K']))
    L.append('walk: %s' % rep['walk_note'])
    L.append('')
    order = ['main-block', 'if-false', 'def-unreachable', 'module-unreachable', 'method-not-live', 'fallback-branch',
             'hidden', 'inert']
    groups = collections.OrderedDict()
    for item in sorted(rep['na'], key=lambda it: order.index(na_group(it[0])) if na_group(it[0]) in order else 99):
        groups.setdefault(na_group(item[0]), []).append(item)
    L.append('Not applicable (%d rows; %s): id | loc | enumerator flags | reason | walk' % (
        rep['K'], ', '.join('%s %d' % (g, len(v)) for g, v in groups.items()) or 'none'))
    for g, items in groups.items():
        L.append('  [%s: %d]' % (g, len(items)))
        for r, reason, v in items:
            L.append('  %s | %s | %s | %s | walk %s: %s' % (r['id'], r['loc'], ','.join(enum_flags(r)) or 'user-facing',
                                                          reason, v[0], v[1]))
    if rep['unconfirmed_na']:
        L.append('')
        L.append('na not confirmed by the walk (%d rows, not counted): id | loc | flags | walk verdict' % len(
            rep['unconfirmed_na']))
        for r, reason, v in rep['unconfirmed_na']:
            L.append('  %s | %s | %s | %s: %s' % (r['id'], r['loc'], ','.join(enum_flags(r)), v[0], v[1]))
    if rep['unproven_na']:
        L.append('')
        L.append('na on rows the enumerator says are user-facing (%d; %s): id | loc | reason' % (
            len(rep['unproven_na']), 'counted in K, --allow-unproven-na' if rep['allow']
            else 'not counted, fails the check'))
        for r, reason in rep['unproven_na']:
            L.append('  %s | %s | %s' % (r['id'], r['loc'], reason))
    L.append('')
    L.append('Unmapped (%d rows): id | loc | kind | label' % len(rep['unmapped']))
    for r in rep['unmapped']:
        L.append('  %s | %s | %s | %s' % (r['id'], r['loc'], r['kind'], r['label']))
    L.append('')
    L.append('Mapped but test not passing or not tagged with the row (%d rows): id | test | status' % len(rep['failing']))
    for r, e, st in rep['failing']:
        L.append('  %s | %s | %s' % (r['id'], e['test'], st))
    if rep['stale']:
        L.append('')
        L.append('Stale mapping entries, id not in the enumeration (%d):' % len(rep['stale']))
        for rid in rep['stale']:
            L.append('  %s' % rid)
    if rep['invalid']:
        L.append('')
        L.append('Invalid mapping entries (%d):' % len(rep['invalid']))
        for rid, why in rep['invalid']:
            L.append('  %s: %s' % (rid, why))
    L.append('')
    why = []
    if rep['N'] == 0:
        why.append('N = 0')
    if rep['M'] + rep['K'] != rep['N']:
        why.append('M + K = %d != N = %d (%d unmapped, %d not passing, %d na unconfirmed, %d unproven na, %d invalid)' % (
            rep['M'] + rep['K'], rep['N'], len(rep['unmapped']), len(rep['failing']), len(rep['unconfirmed_na']),
            0 if rep['allow'] else len(rep['unproven_na']), len(rep['invalid'])))
    if rep['stale']:
        why.append('%d stale entries' % len(rep['stale']))
    if rep['invalid']:
        why.append('%d invalid entries' % len(rep['invalid']))
    names = [r['id'] for r in rep['unmapped']] + [r['id'] for r, _, _ in rep['failing']] + \
        [r['id'] for r, _, _ in rep['unconfirmed_na']] + rep['stale'] + [rid for rid, _ in rep['invalid']]
    if not rep['ok'] and names:
        why.append('rows: %s' % ', '.join(names[:30]) + (' ...' if len(names) > 30 else ''))
    L.append('RESULT: %s' % ('PASS (M + K = N = %d)' % rep['N'] if rep['ok'] else 'FAIL: ' + '; '.join(why)))
    return '\n'.join(L)


def run_walk(python, src):
    """Run qt_walk in a fresh interpreter (it needs PyQt5) and return its walk dict."""
    d = tempfile.mkdtemp(prefix='qt_walk-')
    out = os.path.join(d, 'walk.json')
    env = dict(os.environ)
    env['PYTHONPATH'] = os.path.dirname(src) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    p = subprocess.run([python, '-m', 'psdaq.webgui.parity.qt_walk', '--out', out, '--workdir', d], env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
    sys.stderr.write(p.stdout[-2000:])
    if p.returncode != 0 or not os.path.isfile(out):
        raise SystemExit('check_parity: qt_walk failed (exit %s)' % p.returncode)
    return qt_walk.load_walk(out), out


def main(argv=None):
    ap = argparse.ArgumentParser(description='PyQt -> web GUI parity check')
    ap.add_argument('--src', default=default_src(), help='psdaq package dir holding control_gui/')
    ap.add_argument('--mapping', default=DEFAULT_MAPPING)
    ap.add_argument('--junit', action='append', default=[], help='pytest --junitxml file (repeatable)')
    ap.add_argument('--walk', default=qt_walk.DEFAULT_WALK,
                    help='saved qt_walk JSON (default: %(default)s)')
    ap.add_argument('--run-walk', action='store_true', help='run the offscreen PyQt walk now instead of --walk')
    ap.add_argument('--walk-python', default=sys.executable, help='interpreter with PyQt5 for --run-walk')
    ap.add_argument('--allow-unproven-na', action='store_true')
    ap.add_argument('--json', action='store_true', help='print the report as JSON')
    a = ap.parse_args(argv)
    rows, _ = enumerate_rows(a.src)
    mapping = load_mapping(a.mapping)
    results = load_junit(a.junit) if a.junit else None
    walk, walk_path = None, a.walk
    if a.run_walk:
        walk, walk_path = run_walk(a.walk_python, a.src)
    elif a.walk and os.path.isfile(a.walk):
        walk = qt_walk.load_walk(a.walk)
    rep = check(rows, mapping, results, a.allow_unproven_na, walk, qt_walk.source_digest(a.src))
    if a.json:
        out = {k: v for k, v in rep.items() if k in ('N', 'M', 'K', 'ok', 'stale', 'invalid', 'walk_note')}
        out['na'] = [{'id': r['id'], 'reason': reason, 'walk': v[1]} for r, reason, v in rep['na']]
        out['unmapped'] = [r['id'] for r in rep['unmapped']]
        out['failing'] = [{'id': r['id'], 'test': e['test'], 'status': st} for r, e, st in rep['failing']]
        out['unconfirmed_na'] = [{'id': r['id'], 'walk': list(v)} for r, _, v in rep['unconfirmed_na']]
        out['unproven_na'] = [r['id'] for r, _ in rep['unproven_na']]
        json.dump(out, sys.stdout, indent=1)
        print()
    else:
        print(render(rep, 'parity check: src=%s mapping=%s junit=%s walk=%s' % (
            a.src, a.mapping, ','.join(a.junit) or '(none)',
            '%s (elapsed %s s, %s)' % (walk_path, walk.get('elapsed'), walk.get('python')) if walk else '(none)')))
    return 0 if rep['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
