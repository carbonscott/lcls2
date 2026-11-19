"""Calls to evidence: how many tool calls a run made before it first saw a file of the keyed launch.

    python3 evidence.py --results RESULTS_DIR --work WORK [--cases-v3 FILE] [--catalog FILE] [--write] [--json]

Definition (.goal/daq-skill-eval-v3.predictions.json, 'Calls to evidence'): the number of tool calls before
the first read of a file belonging to the keyed launch.  Every tool call counts, reads of skill or map files
included, and so do ask-operator calls.  A run that never reads one is censored at its total calls + 1.

A call reads a keyed-launch file when
  1. it is a Read of a file whose base name is one of the keyed launch's files (.zst or not), or
  2. its output shows content of a keyed-launch file: an output line holds a fingerprint of one.  A
     fingerprint is the first 40 characters of a line of a keyed-launch file (trimmed, 40 characters or
     longer) that starts no line of any other file in the root the run saw.  Output lines are compared after
     removing a line-number prefix (Read's '  12->' or '  12<TAB>', grep -n's '12:') and a file-name
     prefix ('<path>.log:', '<path>.log-', '<path>.log:12:').
So a Bash 'grep -h configure .../*control.log' or 'zstd -dc *.zst | head' over a glob counts when what it
printed includes a line of a keyed-launch file; a listing (ls, find, Glob, grep -l) that only shows the
file's name does not, nor does a grep of a keyed file that printed nothing.  A line that is the same in
two launches (a fixed banner, a header) is never a fingerprint, so it cannot count.

The keyed launch: mode m1 runs, the case table's m1 keyed_files; mode m0 runs, the catalog pool's launch
named by the key's sessions.  The root is the logs_src in the run's meta.json (else the pool's logs).
Standard library only, Python 3.6+.
"""

import argparse
import json
import os
import re
import subprocess
import sys

from harvest import pool_id

HERE = os.path.dirname(os.path.abspath(__file__))
WIDTH = 40
PREFIX = re.compile(r'^\s*\d+(?:\t|→|:|-)'                          # cat -n / Read / grep -n
                    r'|^\S*?\.log(?:\.zst)?(?::\d+:|-\d+-|:|-)')       # grep with file names
_cache = {}


def text_of(path):
    if path.endswith('.zst'):
        return subprocess.run(['zstd', '-q', '-dc', path], stdout=subprocess.PIPE).stdout.decode('utf-8', 'replace')
    return open(path, 'rb').read().decode('utf-8', 'replace')


def fingerprints(root, keyed):
    """The set of 40-character line starts unique to the keyed files (base names in `keyed`) under root."""
    ck = (root, tuple(sorted(keyed)))
    if ck in _cache:
        return _cache[ck]
    mine, other = set(), set()
    names = set(keyed) | set(k[:-4] for k in keyed if k.endswith('.zst')) | set(k + '.zst' for k in keyed)
    for d, _s, fs in os.walk(root):
        for f in fs:
            starts = set(l.strip()[:WIDTH] for l in text_of(os.path.join(d, f)).splitlines() if len(l.strip()) >= WIDTH)
            (mine if f in names else other).update(starts)
    _cache[ck] = mine - other
    return _cache[ck]


def tool_calls(path):
    """[(name, input, output text)] of a stream-json transcript, in the order the calls were made."""
    calls, results = [], {}
    for line in open(path, errors='replace'):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        msg = ev.get('message') if isinstance(ev, dict) else None
        if not isinstance(msg, dict) or not isinstance(msg.get('content'), list):
            continue
        for b in msg['content']:
            if not isinstance(b, dict):
                continue
            if ev.get('type') == 'assistant' and b.get('type') == 'tool_use':
                calls.append((b.get('id'), b.get('name'), b.get('input') or {}))
            elif b.get('type') == 'tool_result':
                c = b.get('content')
                if isinstance(c, list):
                    c = '\n'.join(x.get('text', '') for x in c if isinstance(x, dict))
                results[b.get('tool_use_id')] = c if isinstance(c, str) else ''
    return [(name, inp, results.get(i, '')) for i, name, inp in calls]


def shows(output, prints):
    for line in output.splitlines():
        s = line.strip()
        for _ in range(3):                                   # e.g. 'file.log:12:' then the line
            if s[:WIDTH] in prints:
                return True
            m = PREFIX.match(s)
            if not m or not m.group(0):
                break
            s = s[m.end():].strip()
    return False


def calls_to_evidence(transcript, keyed, prints):
    """{'calls': value, 'censored': bool, 'total': n, 'first': {index, name, why} or None}."""
    names = set(keyed) | set(k[:-4] for k in keyed if k.endswith('.zst'))
    calls = tool_calls(transcript)
    for i, (name, inp, out) in enumerate(calls):
        why = None
        if name == 'Read' and os.path.basename(str(inp.get('file_path', ''))) in names | set(n + '.zst' for n in names):
            why = 'Read of ' + os.path.basename(inp['file_path'])
        elif shows(out, prints):
            why = 'output shows a keyed-launch line'
        if why:
            return {'calls': i, 'censored': False, 'total': len(calls), 'first': {'index': i + 1, 'name': name, 'why': why}}
    return {'calls': len(calls) + 1, 'censored': True, 'total': len(calls), 'first': None}


def keyed_files(meta, cat_cases, table_cases, work):
    case = cat_cases[meta['case']]
    if meta.get('mode') == 'm1':
        return table_cases[meta['case']]['m1']['keyed_files']
    pool = json.load(open(os.path.join(work, 'pools', pool_id(case['pool']), 'pool.json')))
    return [f for s in pool['sessions'] if s['prefix'] in case['key']['sessions'] for f in s['files']]


def evaluate(run_dir, cat_cases, table_cases, work):
    meta = json.load(open(os.path.join(run_dir, 'meta.json')))
    keyed = keyed_files(meta, cat_cases, table_cases, work)
    root = meta.get('logs_src') or os.path.join(work, 'pools', pool_id(cat_cases[meta['case']]['pool']), 'logs')
    r = calls_to_evidence(os.path.join(run_dir, 'transcript.jsonl'), keyed, fingerprints(root, keyed))
    r.update(case=meta['case'], arm=meta['arm'], repeat=meta['repeat'], mode=meta.get('mode', 'm0'), control=meta.get('control'))
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--results', required=True)
    ap.add_argument('--work', required=True, help='where data/pools.tar.gz was unpacked')
    ap.add_argument('--catalog', default=os.path.join(HERE, 'catalog.json'))
    ap.add_argument('--cases-v3', default=os.path.join(HERE, 'cases_v3.json'))
    ap.add_argument('--write', action='store_true', help='also write evidence.json into each run folder')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    cat_cases = dict((c['id'], c) for c in json.load(open(a.catalog))['cases'])
    table_cases = dict((c['id'], c) for c in json.load(open(a.cases_v3))['cases']) if os.path.exists(a.cases_v3) else {}
    rows = []
    for arm in sorted(os.listdir(a.results)):
        for name in sorted(os.listdir(os.path.join(a.results, arm))) if os.path.isdir(os.path.join(a.results, arm)) else []:
            d = os.path.join(a.results, arm, name)
            if not os.path.exists(os.path.join(d, 'transcript.jsonl')) or not os.path.exists(os.path.join(d, 'meta.json')):
                continue
            r = evaluate(d, cat_cases, table_cases, a.work)
            r['run'] = '%s/%s' % (arm, name)
            rows.append(r)
            if a.write:
                json.dump(r, open(os.path.join(d, 'evidence.json'), 'w'), indent=1)
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        for r in rows:
            print('%-28s %-18s %-4s %-8s calls=%s%s of %d  %s' % (r['run'], r['case'], r['mode'], r['control'] or '-', r['calls'],
                                                              ' (censored)' if r['censored'] else '', r['total'],
                                                              (r['first'] or {}).get('why', '')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
