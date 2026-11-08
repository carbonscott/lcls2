"""
Write `na` entries into mapping.json for the rows the enumerator itself flags
(reachable False, hidden or inert), each with a one-line reason built from the
enumerator's file:line evidence.  Entries already in the file are kept as they
are (web mappings and hand-written reasons are never overwritten); entries
whose id is no longer enumerated are reported, not deleted.  Rows the
enumerator says are user-facing are left unmapped for the web GUI to fill.

Usage:
    python -m psdaq.webgui.parity.draft_mapping [--src DIR] [--mapping FILE] [--write]
"""

import argparse
import collections
import json
import os
import sys

from psdaq.webgui.parity.enumerate_pyqt import default_src, enumerate_rows

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MAPPING = os.path.join(HERE, 'mapping.json')


def _short(e, n=150):
    return e if len(e) <= n else e[:n - 3] + '...'


# na reasons written by hand where the generated one would say less than the source does
KEEP = {
    'CGWMainTabs.gui_win':
        'fallback window: QTextEdit("Default window for tab ...") at control_gui/CGWMainTabs.py:156 is the else of '
        'tab_name == "Expert" / "User" (CGWMainTabs.py:142, :147), and gui_selector only gets names of the tabs added from '
        'tab_names (CGWMainTabs.py:50, :115-116, :180); the module is also not imported '
        '(control_gui/CGWMain.py:43 import commented out)',
}


def _guard_ev(row):
    return next((e[6:] for e in row['evidence'] if e.startswith('guard ')), '')


def reason(row):
    """One-line na reason from the enumerator's evidence; it cites row['guard'] (the
    `if __name__` line, the setVisible test, the commented import, the dispatch) when
    the row has one, because check_parity refuses an na reason that does not."""
    ev = row['evidence']
    reach = row['reach']
    guard = row.get('guard', '')
    if not row['reachable']:
        if reach == 'main-block':
            inst = next((e for e in ev if 'is instantiated only at' in e), None)
            if inst:
                return 'test harness: %s, under %s; never runs when control_gui imports the module' % (
                    inst, _guard_ev(row) or 'if __name__ == "__main__"')
            return 'test harness: under %s (row at %s); never runs when control_gui imports the module' % (
                _guard_ev(row) or 'if __name__ == "__main__"', row['loc'])
        if reach == 'if-false':
            return 'dead code: under %s (row at %s)' % (_guard_ev(row) or '`if False:`', row['loc'])
        if reach == 'module-unreachable':
            g = _guard_ev(row)
            return 'module %s is not imported from app/control_gui.py%s' % (
                row['file'], (': ' + g) if g else '')
        if reach == 'def-unreachable':
            return '%s is never named by code reachable from app/control_gui.py' % row['class']
        if reach == 'method-not-live':
            head = next((e for e in ev if 'is not live' in e), 'method not live')
            rest = [e for e in ev if 'is not live' not in e and ('dropped' in e or 'named in' in e
                                                                   or 'called from' in e or 'no call' in e)]
            return _short('%s (never called from __init__, Qt events, live slots or other classes): %s' % (
                head, '; '.join(rest[:2]) or 'no references'), 300)
        if reach == 'fallback-branch':
            return _short('unreachable fallback: %s' % (ev[0] if ev else reach), 400)
        return 'not reachable: %s' % reach
    if row['hidden']:
        vis = next((e for e in ev if 'setVisible' in e), 'hidden')
        site = [e for e in ev if 'passes' in e or 'omits' in e]
        what = 'hidden'
        if row['kind'] == 'mnemonic':
            what = 'hidden button, so its %s never fires' % row['widget']
        return _short('%s: %s%s' % (what, vis, ('; ' + '; '.join(site)) if site else ''), 260)
    if row['inert']:
        k = row['kind']
        if k == 'text':
            ro = next((e for e in ev if 'setReadOnly' in e and '(True)' in e), ev[-1] if ev else '')
            return 'read-only display: %s' % ro
        if k == 'column':
            cells = [e for e in ev if 'checkable' in e or 'editable' in e]
            return _short('inert column: cells %s; no click action for this column' % '; '.join(cells), 220)
        if k == 'cell':
            return _short('inert cells: %s' % '; '.join(e for e in ev if '{' in e), 220)
        if k == 'click':
            dis = next((e for e in ev if 'disconnected' in e or 'only logs' in e), '')
            return _short('inert view signal: %s' % dis, 200)
        return _short('inert: %s' % '; '.join(ev[:2]), 200)
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description='write provable na entries into mapping.json')
    ap.add_argument('--src', default=default_src())
    ap.add_argument('--mapping', default=DEFAULT_MAPPING)
    ap.add_argument('--write', action='store_true', help='write the file (default: print a summary)')
    ap.add_argument('--refresh', action='store_true',
                    help='rewrite existing generated na reasons (entries in KEEP and web mappings are kept)')
    a = ap.parse_args(argv)
    rows, _ = enumerate_rows(a.src)
    try:
        with open(a.mapping) as f:
            mapping = json.load(f)
    except FileNotFoundError:
        mapping = {}
    ids = {r['id'] for r in rows}
    added = collections.Counter()
    for r in rows:
        if r['id'] in mapping and not (a.refresh and set(mapping[r['id']]) == {'na'}):
            continue
        why = KEEP.get(r['id']) or reason(r)
        if why:
            mapping[r['id']] = {'na': why.replace('\n', ' ')}
            added[r['reach'] or ('hidden' if r['hidden'] else 'inert')] += 1
    stale = sorted(k for k in mapping if k not in ids)
    print('rows %d; na entries added %d %s; entries kept %d; stale (not deleted) %d %s' % (
        len(rows), sum(added.values()), dict(sorted(added.items())),
        len(mapping) - sum(added.values()), len(stale), stale))
    if a.write:
        with open(a.mapping, 'w') as f:
            json.dump(dict(sorted(mapping.items())), f, indent=1)
            f.write('\n')
        print('wrote', a.mapping)
    return 0


if __name__ == '__main__':
    sys.exit(main())
