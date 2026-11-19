"""Calls to evidence: how many tool calls a run made before it first saw a file of the keyed launch.

    python3 evidence.py --results RESULTS_DIR --work WORK [--cases-v3 FILE] [--catalog FILE] [--write] [--json]

Definition (README.md, "v3: cold start (mode m1) and the controls", 'Calls to evidence'): the number of tool calls before
the first read of a file belonging to the keyed launch.  Every tool call counts, reads of skill or map files
included, and so do ask-operator calls.  A run that never reads one is censored at its total calls + 1.
Also written, for a descriptive sensitivity check only (verdict.py): calls_no_guidance, the same count with the
guidance calls left out (Skill tool calls, reads under the installed .claude/skills/ folder; see is_guidance).

A call reads a keyed-launch file when
  1. its output shows content of a keyed-launch file: the output holds a fingerprint of one anywhere in a
     line (after a line number or a file name, inside the skills helper's 'daq-logs.py list' row, inside a
     JSON string such as its '"line": "..."' or '"first_error": "..."', with JSON's \" and \\ undone).  A
     fingerprint is the first 40 characters of a line of a keyed-launch file (trimmed, 40 characters or
     longer) that starts no line of any other file in the root the run saw; or
  2. it is a Read of a keyed-launch file by its base name (.zst or not) that returned its text: a Read of a
     plain .log counts unless the tool reported an error (too large, not found); a Read of a .zst counts
     only through rule 1 (its output must show a fingerprint: compressed bytes do not).
So a Bash 'grep -h configure .../*control.log' or 'zstd -dc *.zst | head' over a glob counts when what it
printed includes a line of a keyed-launch file; a listing (ls, find, Glob, grep -l) that only shows the
file's name does not, nor does a grep of a keyed file that printed nothing.  A line that is the same in
two launches (a fixed banner, a header) is never a fingerprint, so it cannot count.

The keyed launch: family C runs (real MFX logs, case ids real-*), the files of cases_real.json's target launch;
other mode m1 runs (family B), the case table's m1 keyed_files (with the real MFX host names tree.py gives them);
mode m0 runs, the catalog pool's launch named by the key's sessions.  The root is the logs_src in the run's
meta.json (else the pool's logs).  Fingerprints are computed once per (root, keyed launch) and cached in
--cache (default RESULTS_DIR/.evidence-cache): a family-C root holds gigabytes of detector logs, so the other files
are only searched (zstd | grep -F) for the keyed line starts.
Standard library only, Python 3.6+.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

from harvest import pool_id

HERE = os.path.dirname(os.path.abspath(__file__))
WIDTH = 40
_cache = {}


def text_of(path):
    if path.endswith('.zst'):
        return subprocess.run(['zstd', '-q', '-dc', path], stdout=subprocess.PIPE).stdout.decode('utf-8', 'replace')
    return open(path, 'rb').read().decode('utf-8', 'replace')


def _lines_holding(paths, patterns, compressed):
    """Lines of the files (decompressed) that contain one of the fixed strings in the file `patterns`."""
    out = []
    for i in range(0, len(paths), 400):
        chunk = paths[i:i + 400]
        src = subprocess.Popen(['zstd', '-q', '-dc'] + chunk if compressed else ['cat'] + chunk, stdout=subprocess.PIPE)
        g = subprocess.run(['grep', '-a', '-F', '-f', patterns], stdin=src.stdout, stdout=subprocess.PIPE,
                           env=dict(os.environ, LC_ALL='C'))
        src.stdout.close()
        src.wait()
        out += g.stdout.decode('utf-8', 'replace').splitlines()
    return out


def fingerprints(root, keyed, cache=None):
    """The set of 40-character line starts unique to the keyed files (base names in `keyed`) under root:
    the keyed files' line starts, less every one that also starts a line of another file under root."""
    ck = (root, tuple(sorted(keyed)))
    if ck in _cache:
        return _cache[ck]
    names = set(keyed) | set(k[:-4] for k in keyed if k.endswith('.zst')) | set(k + '.zst' for k in keyed)
    mine_paths, other_paths, sig = [], [], hashlib.sha1()
    for d, subs, fs in os.walk(root):
        subs.sort()
        for f in sorted(fs):
            p = os.path.join(d, f)
            st = os.stat(p)
            sig.update(('%s|%d|%d\n' % (os.path.relpath(p, root), st.st_size, int(st.st_mtime))).encode('utf-8', 'replace'))
            (mine_paths if f in names else other_paths).append(p)
    path = None
    if cache:
        h = hashlib.sha1(('%s|%s|%s' % (os.path.abspath(root), '|'.join(sorted(keyed)), sig.hexdigest())).encode()).hexdigest()
        path = os.path.join(cache, 'fp-%s.json' % h)
        if os.path.exists(path):
            _cache[ck] = set(json.load(open(path)))
            return _cache[ck]
    mine = set()
    for p in mine_paths:
        mine.update(l.strip()[:WIDTH] for l in text_of(p).splitlines() if len(l.strip()) >= WIDTH)
    if mine and other_paths:
        with tempfile.NamedTemporaryFile('wb', suffix='.pat') as pat:
            pat.write('\n'.join(sorted(mine)).encode('utf-8') + b'\n')
            pat.flush()
            for compressed in (False, True):
                ps = [p for p in other_paths if p.endswith('.zst') == compressed]
                for line in _lines_holding(ps, pat.name, compressed) if ps else []:
                    mine.discard(line.strip()[:WIDTH])
    _cache[ck] = mine
    if path:
        os.makedirs(cache, exist_ok=True)
        tmp = '%s.tmp%d' % (path, os.getpid())
        json.dump(sorted(mine), open(tmp, 'w'))
        os.replace(tmp, path)
    return mine


def tool_calls(path, errors=None):
    """[(name, input, output text)] of a stream-json transcript, in the order the calls were made.  If `errors` is a
    set, the indexes of the calls whose result the tool marked as an error are added to it."""
    calls, results, failed = [], {}, set()
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
                if b.get('is_error'):
                    failed.add(b.get('tool_use_id'))
    if errors is not None:
        errors.update(k for k, (i, _n, _inp) in enumerate(calls) if i in failed)
    return [(name, inp, results.get(i, '')) for i, name, inp in calls]


def _unescaped(output):
    """The output with JSON string escapes undone, so a log line printed inside a JSON string reads as itself."""
    if '\\' not in output:
        return output
    return re.sub(r'\\(["\\/tnr])', lambda m: {'t': '\t', 'n': '\n', 'r': '\r'}.get(m.group(1), m.group(1)), output)


def shows(output, prints):
    """True if a fingerprint occurs anywhere in the output (any position of any line, JSON escapes undone)."""
    if not output or not prints:
        return False
    texts = set([output, _unescaped(output)])
    return any(p in t for t in texts for p in prints)


def calls_to_evidence(transcript, keyed, prints, skip=None):
    """{'calls': value, 'censored': bool, 'total': n, 'first': {index, name, why} or None}.
    skip(name, input) -> True leaves a call out of the count entirely (the guidance-free sensitivity count)."""
    names = set(keyed) | set(k[:-4] for k in keyed if k.endswith('.zst'))
    errors = set()
    calls = [(c, k in errors) for k, c in enumerate(tool_calls(transcript, errors))]
    if skip:                                                 # never drop a call whose output shows a keyed line
        calls = [(c, e) for c, e in calls if not skip(c[0], c[1]) or shows(c[2], prints)]
    for i, ((name, inp, out), err) in enumerate(calls):
        why = None
        base = os.path.basename(str(inp.get('file_path', ''))) if name == 'Read' else ''
        if shows(out, prints):
            why = ('Read of %s, output shows a keyed-launch line' % base) if base in names | set(n + '.zst' for n in names) \
                else 'output shows a keyed-launch line'
        elif base in names and not base.endswith('.zst') and not err:
            why = 'Read of ' + base
        if why:
            return {'calls': i, 'censored': False, 'total': len(calls), 'first': {'index': i + 1, 'name': name, 'why': why}}
    return {'calls': len(calls) + 1, 'censored': True, 'total': len(calls), 'first': None}


GUIDANCE = re.compile(r'(?:^|[\s/\'"=:])\.claude/skills(?:/|\b)')


def is_guidance(name, inp):
    """A call that reads guidance: a Skill tool call, a Read / Grep / Glob of a path under the installed skills folder
    (.claude/skills/ in the run's workspace), or a Bash command that names that folder and no log path (/sdf): running
    a skill's helper on the logs is not a guidance read."""
    if name == 'Skill':
        return True
    if not isinstance(inp, dict):
        return False
    if name == 'Bash':
        c = str(inp.get('command') or '')
        return bool(GUIDANCE.search(c)) and '/sdf' not in c
    return any(isinstance(inp.get(k), str) and GUIDANCE.search(inp[k]) for k in ('file_path', 'path', 'pattern'))


def is_real(meta, real_cases):
    return meta.get('family') == 'C' or meta['case'] in (real_cases or {})


def keyed_files(meta, cat_cases, table_cases, work, real_cases=None):
    if is_real(meta, real_cases):
        (l,) = [l for l in real_cases[meta['case']]['launches'] if l['id'] == real_cases[meta['case']]['target']]
        return [f['name'] for f in l['files']]
    case = cat_cases[meta['case']]
    if meta.get('mode') == 'm1':
        return table_cases[meta['case']]['m1']['keyed_files']
    pool = json.load(open(os.path.join(work, 'pools', pool_id(case['pool']), 'pool.json')))
    return [f for s in pool['sessions'] if s['prefix'] in case['key']['sessions'] for f in s['files']]


def evaluate(run_dir, cat_cases, table_cases, work, real_cases=None, cache=None):
    meta = json.load(open(os.path.join(run_dir, 'meta.json')))
    keyed = keyed_files(meta, cat_cases, table_cases, work, real_cases)
    root = meta.get('logs_src') or os.path.join(work, 'pools', pool_id(cat_cases[meta['case']]['pool']), 'logs')
    prints = fingerprints(root, keyed, cache)
    r = calls_to_evidence(os.path.join(run_dir, 'transcript.jsonl'), keyed, prints)
    ng = calls_to_evidence(os.path.join(run_dir, 'transcript.jsonl'), keyed, prints, skip=is_guidance)
    r.update(calls_no_guidance=ng['calls'], censored_no_guidance=ng['censored'], guidance_calls=r['total'] - ng['total'])
    r.update(case=meta['case'], arm=meta['arm'], repeat=meta['repeat'], mode=meta.get('mode', 'm0'), control=meta.get('control'),
             family='C' if is_real(meta, real_cases) else ('B' if meta.get('mode') == 'm1' else 'A'))
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--results', required=True)
    ap.add_argument('--work', required=True, help='where data/pools.tar.gz was unpacked')
    ap.add_argument('--catalog', default=os.path.join(HERE, 'catalog.json'))
    ap.add_argument('--cases-v3', default=os.path.join(HERE, 'cases_v3.json'))
    ap.add_argument('--cases-real', default=os.path.join(HERE, 'cases_real.json'))
    ap.add_argument('--cache', help='fingerprint cache (default RESULTS_DIR/.evidence-cache)')
    ap.add_argument('--write', action='store_true', help='also write evidence.json into each run folder')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    cat_cases = dict((c['id'], c) for c in json.load(open(a.catalog))['cases'])
    table_cases = dict((c['id'], c) for c in json.load(open(a.cases_v3))['cases']) if os.path.exists(a.cases_v3) else {}
    real_cases = dict((c['id'], c) for c in json.load(open(a.cases_real))['cases']) if os.path.exists(a.cases_real) else {}
    cache = a.cache or os.path.join(a.results, '.evidence-cache')
    rows = []
    for arm in sorted(x for x in os.listdir(a.results) if not x.startswith('.')):
        for name in sorted(os.listdir(os.path.join(a.results, arm))) if os.path.isdir(os.path.join(a.results, arm)) else []:
            d = os.path.join(a.results, arm, name)
            if not os.path.exists(os.path.join(d, 'transcript.jsonl')) or not os.path.exists(os.path.join(d, 'meta.json')):
                continue
            if json.load(open(os.path.join(d, 'meta.json'))).get('dry_run'):
                continue
            r = evaluate(d, cat_cases, table_cases, a.work, real_cases, cache)
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
