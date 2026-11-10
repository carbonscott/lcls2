"""Build eval case folders from sim DAQ run folders (read-only on the source).

    python3 harvest.py --catalog catalog.json --out CASES_DIR [--case ID ...]

For each catalog case with a 'source' run folder, copies the process logs the DAQ
itself wrote (<run>/pmlogs/YYYY/MM/<DD_HH:MM:SS>_<host>:<component>.log, the
production layout) to CASES_DIR/<case_dir>/logs/YYYY/MM/, and nothing else: the sim's own
records (cycle.jsonl, daq_sim.state.json, evidence) would tell the agent what happened.

Paths can leak the answer (a run folder named 'f2fault'), so every occurrence of the
source folder's path is replaced by the case folder's path, and the case folder has an
opaque name (case_dir()), not the catalog id.  Lines only the sim writes and that name
the planted fault (rogue_dev's 'FAULT <register>' warning) are removed (STRIP).  Then every copied file is
scanned for hint words (the source folder's name, 'fault', 'nopin', 'kill-drp', ...);
a hit fails the case unless the catalog lists that word in the case's 'leak_allow'
(for words the DAQ writes itself, e.g. 'Segmentation fault').

Writes CASES_DIR/<case_dir>/case.json (no case id): the session prefix, host, first and last control.log
timestamps, and the file list with sizes.  The source is never written to.
"""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sys

HINTS = ['fault', 'nopin', 'kill-drp', 'truncate-xtc2', 'break', 'daq_sim', 'e2e', 'skeptic', 'inject']
# Lines the sim (never production) writes that announce the planted fault
STRIP = [re.compile(r'rogue_dev:? ?FAULT\b')]
LOGNAME = re.compile(r'^(\d\d_\d\d:\d\d:\d\d)_([^:]+):(.+)\.log$')
TS = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)')


def session_logs(run):
    """[(path, yyyy, mm, name)] of the DAQ process logs under run/pmlogs."""
    out = []
    for p in sorted(glob.glob(os.path.join(run, 'pmlogs', '[0-9]' * 4, '[0-9]' * 2, '*.log'))):
        name = os.path.basename(p)
        if LOGNAME.match(name):
            mm = os.path.basename(os.path.dirname(p))
            yyyy = os.path.basename(os.path.dirname(os.path.dirname(p)))
            out.append((p, yyyy, mm, name))
    return out


def case_dir(cid):
    """Opaque folder name for a case, so neither the path nor a sibling's name hints at it."""
    return 'c' + hashlib.sha1(cid.encode()).hexdigest()[:8]


def leak_scan(paths, words, allow):
    hits = []
    for p in paths:
        text = open(p, errors='replace').read()
        for w in words:
            if w.lower() in [a.lower() for a in allow]:
                continue
            for m in re.finditer(r'(?<![A-Za-z0-9_])' + re.escape(w) + r'(?![A-Za-z0-9_])', text, re.I):
                line = text.count('\n', 0, m.start()) + 1
                ctx = text[max(0, m.start() - 40):m.end() + 40].replace('\n', ' ')
                hits.append({'file': os.path.basename(p), 'line': line, 'word': w, 'context': ctx})
                break
    return hits


def harvest(case, out_root):
    src = os.path.realpath(case['source'])
    dst = os.path.join(out_root, case_dir(case['id']))
    logs = session_logs(src)
    if not logs:
        raise SystemExit('%s: no process logs under %s/pmlogs' % (case['id'], src))
    if os.path.exists(dst):
        shutil.rmtree(dst)
    copied, stripped = [], 0
    for p, yyyy, mm, name in logs:
        d = os.path.join(dst, 'logs', yyyy, mm)
        os.makedirs(d, exist_ok=True)
        lines = open(p, errors='replace').read().splitlines(True)
        keep = [l for l in lines if not any(rx.search(l) for rx in STRIP)]
        stripped += len(lines) - len(keep)
        text = ''.join(keep)
        # Longest first, so a parent path does not leave the run folder's name behind
        for old in sorted({src, case['source'].rstrip('/')}, key=len, reverse=True):
            text = text.replace(old, os.path.abspath(dst))
        q = os.path.join(d, name)
        with open(q, 'w') as f:
            f.write(text)
        copied.append(q)
    words = HINTS + [os.path.basename(src)] + case.get('leak_words', [])
    hits = leak_scan(copied, words, case.get('leak_allow', []))
    ctl = [q for q in copied if q.endswith(':control.log')]
    stamps = []
    if ctl:
        for line in open(ctl[0], errors='replace'):
            m = TS.match(line)
            if m:
                stamps.append(m.group(1))
    m = LOGNAME.match(os.path.basename(copied[0]))
    # No case id here: the logs' rewritten paths point at this folder
    info = {'prefix': m.group(1), 'host': m.group(2),
            'year_month': os.path.relpath(os.path.dirname(copied[0]), os.path.join(dst, 'logs')),
            'first': stamps[0] if stamps else None, 'last': stamps[-1] if stamps else None,
            'files': [{'name': os.path.relpath(q, dst), 'bytes': os.path.getsize(q)} for q in copied],
            'stripped_lines': stripped, 'leaks': hits}
    with open(os.path.join(dst, 'case.json'), 'w') as f:
        json.dump(info, f, indent=1)
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--catalog', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'catalog.json'))
    ap.add_argument('--out', required=True)
    ap.add_argument('--case', action='append', help='only these case ids')
    a = ap.parse_args(argv)
    cases = json.load(open(a.catalog))['cases']
    bad = 0
    for c in cases:
        if not c.get('source') or (a.case and c['id'] not in a.case):
            continue
        info = harvest(c, a.out)
        status = 'LEAK' if info['leaks'] else 'ok'
        bad += bool(info['leaks'])
        print('%-24s %s %-4s %s %s..%s %d files, %d sim lines removed' % (
            c['id'], case_dir(c['id']), status, info['prefix'], info['first'], (info['last'] or '')[11:],
            len(info['files']), info['stripped_lines']))
        for h in info['leaks']:
            print('    %(file)s:%(line)d %(word)r: ...%(context)s...' % h)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
