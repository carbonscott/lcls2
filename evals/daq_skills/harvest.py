"""Build eval log directories ("pools") from sim DAQ run folders (read-only on the source).

    python3 harvest.py --root SIM_RUNS_ROOT --out WORK_DIR [--pool NAME ...] [--catalog catalog.json]

A pool is one hutch log directory, logs/YYYY/MM/<DD_HH:MM:SS>_<host>:<component>.log[.zst],
the layout the DAQ writes in production.  A pool holds one DAQ launch (a "session") or many;
several cases can ask different questions about the same pool.  For every session the
catalog lists (its run folder under --root, YYYY/MM, launch prefix, host), harvest copies
only the process logs the DAQ itself wrote.  The sim's own records (state files, evidence)
are never copied: they would tell the agent what happened.

What is changed in the copies, and why:
  STRIP     lines only the sim writes that announce a planted fault are removed
            (rogue_dev's "FAULT <register>" warning).  The removed text is kept in
            pool.json as the machine record of what was planted.
  paths     the run folder's path, and any other path under --root, is replaced by a
            neutral one, because folder names such as ".../break-register/..." give the
            answer away.  The sim's config file name (daq_sim.cnf) becomes tst.cnf and the
            account name becomes tstopr.
  mtime     each copy gets its source's modification time; tools that pick sessions by
            time (the logs skill's helper) depend on it.
  .zst      sessions that start before the pool's "compress_before" are compressed with
            zstd, as log rotation does to older sessions in production.
Nothing else is edited: no line is added, reordered or re-timed.

Every copy is then scanned for hint words (HINTS, plus the distinctive parts of each run
folder's name).  A hit fails the pool (exit 1) unless the catalog's "leak_allow" lists it.

Writes WORK_DIR/pools/<pool id>/pool.json: per session its files, first and last
control.log timestamps, stripped lines and leak hits.  Standard library only, Python 3.6+;
needs the zstd program for pools that compress.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HINTS = ['fault', 'nopin', 'kill-drp', 'truncate-xtc2', 'break', 'brk', 'daq_sim', 'e2e', 'skeptic', 'skep',
         'inject', 'agentify', 'matrix', 'proof', 'hkill', 'pvaopen', 'mebwin']
# Folder-name parts that say nothing about what happened in the run
GENERIC = {'work', 'runs', 'daq', 'types', 'gpu', 'hosts', 'programs', 'features', 'meb', 'wd', 'run', 'final', 'base',
           'drp', 'drp_gpu', 'stack', 'fix', 'diag', 'dev', 'head', 'prog'}
# Text the DAQ itself writes that contains a hint word
OWN_WORDS = re.compile(r'Segmentation Fault', re.I)
STRIP = [re.compile(r'rogue_dev:? ?FAULT\b')]
LOGNAME = re.compile(r'^(\d\d_\d\d:\d\d:\d\d)_([^:]+):(.+)\.log$')
TS = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)')
SCRATCH = '/sdf/data/lcls/ds/tst/tstx00001/scratch/daq'
RELEASES = '/sdf/group/lcls/ds/daq/sw'


def h(text, n=8):
    return hashlib.sha1(text.encode()).hexdigest()[:n]


def pool_id(name):
    """Opaque folder name, so a path never hints at the case."""
    return 'p' + h(name)


def roots_of(root):
    """The spellings of the source root that logs may contain (symlinked filesystems)."""
    out = {root.rstrip('/'), os.path.realpath(root)}
    for r in list(out):
        out.add(r.replace('/sdf/data/', '/sdf/scratch/', 1))
        out.add(r.replace('/sdf/scratch/', '/sdf/data/', 1))
    return sorted(out, key=len, reverse=True)


def neutral(text, roots, run):
    """Replace paths under the source root.  The run folder first, then anything else."""
    sid = 's' + h(run, 6)
    for r in roots:
        text = text.replace(r + '/' + run, SCRATCH + '/' + sid)
    for r in roots:
        text = re.sub(re.escape(r) + r'/([^/\s\'",:)]+)(?:/work|/runs)?(/[^\s\'",:)]*)?',
                      lambda m: RELEASES + '/r' + h(m.group(1), 4) + neutral_tail(m.group(2)), text)
        text = text.replace(r, RELEASES)
    return text


def neutral_tail(tail):
    """Keep the last two parts of a path under the root (bin/drp, install/lib/...), hash the rest."""
    if not tail:
        return ''
    parts = tail.strip('/').split('/')
    keep = [p for p in parts if p in ('install', 'bin', 'lib', 'build', 'psdaq', 'psana', 'data', 'xtc', 'smalldata')
            or '.' in p or p.startswith('python') or p == 'site-packages' or p.startswith('tst')]
    drop = [p for p in parts if p not in keep]
    return ('/d' + h('/'.join(drop), 4) if drop else '') + ''.join('/' + p for p in keep)


def hint_words(run, components=()):
    """Distinctive parts of a run folder's name.  Detector and process names are not hints:
    the logs are full of them."""
    own = {re.sub(r'_?\d+$', '', c).lower() for c in components} | {c.lower() for c in components}
    words = []
    for part in re.split(r'[/]', run):
        for w in [part] + re.split(r'[-_.]', part):
            if len(w) >= 3 and w.lower() not in GENERIC and w.lower() not in own and not re.match(r'^[a-z]{1,2}\d*$', w):
                words.append(w)
    return words


def leak_scan(text, words, allow):
    hits = []
    low = [a.lower() for a in allow]
    for w in sorted(set(words)):
        if w.lower() in low:
            continue
        m = re.search(r'(?<![A-Za-z0-9_])' + re.escape(w) + r'(?![A-Za-z0-9_])', text, re.I)
        if m:
            hits.append({'word': w, 'line': text.count('\n', 0, m.start()) + 1,
                         'context': text[max(0, m.start() - 50):m.end() + 50].replace('\n', ' ')})
    return hits


def find_logdir(root, s):
    for d in (os.path.join(root, s['run'], 'pmlogs', s['ym']), os.path.join(root, s['run'], s['ym'])):
        if os.path.isdir(d):
            return d
    raise SystemExit('no log folder for %s %s under %s' % (s['run'], s['ym'], root))


def harvest_pool(name, pool, root, out, allow_extra=()):
    dst = os.path.join(out, 'pools', pool_id(name))
    if os.path.exists(dst):
        shutil.rmtree(dst)
    roots = roots_of(root)
    info = {'sessions': [], 'leaks': [], 'compress_before': pool.get('compress_before')}
    allow = list(pool.get('leak_allow', [])) + list(allow_extra)
    for s in pool['sessions']:
        src = find_logdir(root, s)
        d = os.path.join(dst, 'logs', s['ym'])
        os.makedirs(d, exist_ok=True)
        tag = '%s_%s:' % (s['prefix'], s['host'])
        names = sorted(n for n in os.listdir(src) if n.startswith(tag) and LOGNAME.match(n))
        if not names:
            raise SystemExit('%s: no logs %s* in %s' % (name, tag, src))
        start = '%s-%s-%s %s' % (s['ym'][:4], s['ym'][5:], s['prefix'][:2], s['prefix'][3:])
        zst = bool(pool.get('compress_before')) and start < pool['compress_before']
        rec = {'prefix': s['prefix'], 'host': s['host'], 'ym': s['ym'], 'start': start, 'files': [], 'planted': [],
               'first': None, 'last': None, 'zst': zst}
        words = HINTS + hint_words(s['run'], [LOGNAME.match(n).group(3) for n in names] + [s['host']])
        for n in names:
            p = os.path.join(src, n)
            lines = open(p, errors='replace').read().splitlines(True)
            keep = []
            for l in lines:
                if any(rx.search(l) for rx in STRIP):
                    rec['planted'].append(l.strip()[:300])
                else:
                    keep.append(l)
            text = neutral(''.join(keep), roots, s['run']).replace('cwang31', 'tstopr').replace('daq_sim.cnf', 'tst.cnf')
            for hit in leak_scan(OWN_WORDS.sub('', text), words, allow):
                hit.update(file=n)
                info['leaks'].append(hit)
            if n.endswith(':control.log'):
                stamps = [m.group(1) for m in (TS.match(l) for l in keep) if m]
                if stamps:
                    rec['first'], rec['last'] = stamps[0], stamps[-1]
            q = os.path.join(d, n)
            with open(q, 'w') as f:
                f.write(text)
            st = os.stat(p)
            if zst:
                subprocess.check_call(['zstd', '-q', '--rm', '-f', q])
                q += '.zst'
            os.utime(q, (st.st_mtime, st.st_mtime))
            rec['files'].append(os.path.basename(q))
        info['sessions'].append(rec)
    with open(os.path.join(dst, 'pool.json'), 'w') as f:
        json.dump(info, f, indent=1)
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--catalog', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'catalog.json'))
    ap.add_argument('--root', required=True, help='folder the catalog\'s run paths are relative to')
    ap.add_argument('--out', required=True)
    ap.add_argument('--pool', action='append', help='only these pools')
    a = ap.parse_args(argv)
    cat = json.load(open(a.catalog))
    bad = 0
    for name in sorted(cat['pools']):
        if a.pool and name not in a.pool:
            continue
        info = harvest_pool(name, cat['pools'][name], a.root, a.out)
        n = sum(len(s['files']) for s in info['sessions'])
        bad += bool(info['leaks'])
        print('%-26s %s %-4s %3d sessions %4d files, %d sim lines removed, %d compressed' % (
            name, pool_id(name), 'LEAK' if info['leaks'] else 'ok', len(info['sessions']), n,
            sum(len(s['planted']) for s in info['sessions']), sum(1 for s in info['sessions'] if s['zst'])))
        for x in info['leaks'][:8]:
            print('    %(file)s:%(line)d %(word)r: ...%(context)s...' % x)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
