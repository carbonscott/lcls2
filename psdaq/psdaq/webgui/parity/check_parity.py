"""
Parity check: PyQt control GUI affordances (enumerated live from the PyQt
source by enumerate_pyqt) against the web GUI mapping and the web GUI's
headless-browser test results.

Inputs
  rows      computed from the source tree (--src, default: the installed psdaq)
  mapping   mapping.json: {"<row id>": {"web": "<CSS selector>", "test": "<pytest node id>"}
                                     | {"na": "<one-line reason>"}}
  junit     one or more pytest --junitxml files from the web GUI's Playwright tests

A row counts as
  M  mapped: a "web"+"test" entry whose test is in a junit file and passed
     (a testcase with no failure, error or skipped child);
  K  not applicable: an "na" entry with a non-empty one-line reason.  By default
     an na is accepted only on a row the enumerator itself flags (reachable
     False, hidden or inert): an na on a user-facing row is reported as
     unproven and fails the check unless --allow-unproven-na is given.
The check passes (exit 0) only if N > 0 and M + K = N and there are no stale
entries (ids not in the enumeration) and no invalid entries.  Otherwise it
prints what is unmapped, failing, stale or invalid and exits 1.

Usage:
    python -m psdaq.webgui.parity.check_parity [--src DIR] [--mapping FILE]
        [--junit FILE ...] [--allow-unproven-na] [--json]
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

from psdaq.webgui.parity.enumerate_pyqt import default_src, enumerate_rows

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MAPPING = os.path.join(HERE, 'mapping.json')


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
    """{(classname, name): 'passed' | 'failed' | 'error' | 'skipped'}"""
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
            prev = out.get(key)
            # a test that ran several times passes only if every run passed
            out[key] = status if prev in (None, 'passed') else prev
    return out


def test_status(results, nodeid):
    cls, name = nodeid_key(nodeid)
    hits = [st for (c, n), st in results.items()
            if n == name and (c == cls or c.endswith('.' + cls) or cls.endswith('.' + c))]
    if not hits:
        return 'missing'
    return 'passed' if all(h == 'passed' for h in hits) else sorted(set(hits) - {'passed'})[0]


def enum_flags(row):
    f = []
    if not row['reachable']:
        f.append('unreachable:%s' % row['reach'])
    if row['hidden']:
        f.append('hidden')
    if row['inert']:
        f.append('inert')
    return f


def check(rows, mapping, results, allow_unproven_na=False):
    by = {r['id']: r for r in rows}
    rep = {'N': len(rows), 'mapped': [], 'na': [], 'unproven_na': [], 'unmapped': [],
           'failing': [], 'stale': [], 'invalid': [], 'allow': allow_unproven_na}
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
            if enum_flags(r):
                rep['na'].append((r, reason))
            elif allow_unproven_na:
                rep['na'].append((r, reason))
                rep['unproven_na'].append((r, reason))
            else:
                rep['unproven_na'].append((r, reason))
            continue
        if keys == {'web', 'test'}:
            if not all(isinstance(e[k], str) and e[k].strip() for k in ('web', 'test')):
                rep['invalid'].append((rid, 'web and test must be non-empty strings'))
                continue
            st = test_status(results, e['test']) if results is not None else 'no junit given'
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
    L.append('')
    L.append('Not applicable (%d rows): id | loc | enumerator flags | reason' % rep['K'])
    for r, reason in rep['na']:
        L.append('  %s | %s | %s | %s' % (r['id'], r['loc'], ','.join(enum_flags(r)) or 'user-facing',
                                          reason))
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
    L.append('Mapped but test not passing (%d rows): id | test | status' % len(rep['failing']))
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
        why.append('M + K = %d != N = %d (%d unmapped, %d not passing, %d unproven na)' % (
            rep['M'] + rep['K'], rep['N'], len(rep['unmapped']), len(rep['failing']),
            0 if rep['allow'] else len(rep['unproven_na'])))
    if rep['stale']:
        why.append('%d stale entries' % len(rep['stale']))
    if rep['invalid']:
        why.append('%d invalid entries' % len(rep['invalid']))
    L.append('RESULT: %s' % ('PASS (M + K = N = %d)' % rep['N'] if rep['ok'] else 'FAIL: ' + '; '.join(why)))
    return '\n'.join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description='PyQt -> web GUI parity check')
    ap.add_argument('--src', default=default_src(), help='psdaq package dir holding control_gui/')
    ap.add_argument('--mapping', default=DEFAULT_MAPPING)
    ap.add_argument('--junit', action='append', default=[], help='pytest --junitxml file (repeatable)')
    ap.add_argument('--allow-unproven-na', action='store_true')
    ap.add_argument('--json', action='store_true', help='print the report as JSON')
    a = ap.parse_args(argv)
    rows, _ = enumerate_rows(a.src)
    mapping = load_mapping(a.mapping)
    results = load_junit(a.junit) if a.junit else None
    rep = check(rows, mapping, results, a.allow_unproven_na)
    if a.json:
        out = {k: v for k, v in rep.items() if k in ('N', 'M', 'K', 'ok', 'stale', 'invalid')}
        out['na'] = [{'id': r['id'], 'reason': reason} for r, reason in rep['na']]
        out['unmapped'] = [r['id'] for r in rep['unmapped']]
        out['failing'] = [{'id': r['id'], 'test': e['test'], 'status': st} for r, e, st in rep['failing']]
        out['unproven_na'] = [r['id'] for r, _ in rep['unproven_na']]
        json.dump(out, sys.stdout, indent=1)
        print()
    else:
        print(render(rep, 'parity check: src=%s mapping=%s junit=%s' % (
            a.src, a.mapping, ','.join(a.junit) or '(none)')))
    return 0 if rep['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
