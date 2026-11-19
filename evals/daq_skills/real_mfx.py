"""Family C of the DAQ-skill eval: cold-start cases on REAL MFX DAQ logs.

The logs are never committed.  cases_real.json holds only window specs (today's date, a
vague phrase, the keyed launch's stamp, its file names and their sha256) and the keys this
script computes from the logs.  A clone gets the logs with `fetch`, from S3DF, with the
user's own login; the MFX trees are world-readable there.

    python3 real_mfx.py fetch --dest ROOT [--host sdfiana025] [--rsh "ssh -F CFG"] [--max-bytes 2e9]
    python3 real_mfx.py keys  --root ROOT [--update]      # recompute the keys; exit 1 on drift
    python3 real_mfx.py check --root ROOT                 # is each vague window unambiguous?
    python3 real_mfx.py inventory --root ROOT --since 2026-09-01 --until 2026-11-19 --out INV.json
    python3 real_mfx.py candidates --inventory INV.json   # (launch, today, phrase) alone in its window

ROOT is a prepared root laid out as the real paths (ROOT/home/m/mfxopr/...); the cold-start
harness mounts it read-only at /sdf.  On S3DF itself ROOT is /sdf.

The two trees are one log stream (see the hutch-resources map, logs.the_three_trees):
  current   /sdf/home/m/mfxopr/daq/logs/<YYYY>/<MM>/   from 2026-09-17 09:29
  previous  /sdf/home/m/mfxopr/<YYYY>/<MM>/            before that (and a few later launches)
File names are <DD>_<HH:MM:SS>_<host>:<process>.log[.zst]; the stamp is the launch time in
local Pacific time (the log lines inside use the same clock).  A daily rotation job on S3DF
compresses files of the current tree to .zst after about a week, so a file is matched by its
.log name whatever its suffix, and its sha256 is taken over the DECOMPRESSED bytes.

A launch is a stamp that has a control.log.  Files of a stamp without a control.log (a single
process restarted by hand) are attached to the launch before them, as 'restarts'.

Python 3.6 compatible (S3DF's python3), standard library only; needs zstd for .zst files.
"""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, 'cases_real.json')
OPR = 'home/m/mfxopr'
TREES = (('current', OPR + '/daq/logs'), ('previous', OPR))
EXTRA = (OPR + '/daq/scripts', OPR + '/.psdaq')          # small config folders copied by fetch
NAME = re.compile(r'^(\d\d)_(\d\d:\d\d:\d\d)_([^:/]+):(.+?)\.log(\.zst)?$')
ISO = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ (\S+?)\[\d+\]: <(\w)> (.*)$')

# Error-line classes, counted per component (= the file's process name).  First match wins.
CLASSES = (
    ('pv_connect', re.compile(r"PVs? that didn't connect|PV \S+ didn't connect|Failed to get parameters for PV"
                              r"|PV \S+ (?:failed to connect|not connected|disconnected)")),
    ('no_response', re.compile(r'\bdid not respond to (?!rollcall)[a-z]+')),
    ('state_failed', re.compile(r'\b[a-z]+ failed to change state\b')),
    ('crash', re.compile(r'core dumped|Segmentation fault|SIG(?:SEGV|BUS|ABRT|FPE)\b|received signal|cleaning up on signal'
                         r'|terminate called|Exited with exit code [1-9]|\bKilled\b|\*\*\*\* python error')),
    ('traceback', re.compile(r'Traceback \(most recent call last\)')),
)
SEVERE = re.compile(r'<([EC])> ')
BENIGN_C = re.compile(r'Inadequate RTPRIO limit')
PREFILTER = ("<E> |<C> |<F> |didn't connect|Failed to get parameters for PV|did not respond to|failed to change state"
             "|core dumped|Segmentation fault|SIGSEGV|SIGBUS|SIGABRT|SIGFPE|received signal|cleaning up on signal"
             "|terminate called|Exited with exit code|Killed|python error|Traceback|not connected|disconnected|failed to connect"
             "|ClientSocket: Cannot connect|Failed to allocate lane|failed to execute|connect failed|linksConnect"
             "|checkTransaction|Aborted")

# Failure lines in control.log (the <E> message text).
F_NAMED = (('no_response', re.compile(r'^(?P<comp>[A-Za-z]\w*) did not respond to (?P<tr>[a-z]+)')),
           ('phase_error', re.compile(r'^(?P<comp>[A-Za-z]\w*): Phase \d error in [\w:]*?::(?P<tr>[a-z]+)\(')))
F_EB_HEAD = re.compile(r"^(?P<eb>(?:teb|meb)\w*): (?:TEB|MEB) didn't hear from:")
F_EB_ITEM = re.compile(r'^(?P<eb>(?:teb|meb)\w*): (?P<comp>[A-Za-z]\w*)$')
F_EB_QUIET = re.compile(r'^(?P<eb>(?:teb|meb)\w*): Too many events missing a contribution')
F_STATE = re.compile(r'^(?P<tr>[a-z]+) failed to change state')
F_PHASE = re.compile(r'^(?:condition_\w+\(\): )?(?P<tr>[a-z]+) phase\d failed')
F_UNNAMED = re.compile(r'^\d+ clients? did not respond to (?P<tr>[a-z]+)')
GENERIC = {'control'}
GROUP_SECONDS = 60

# Mechanism labels from the keyed component's own log (first match in file order wins).
MECHANISMS = (
    ('detector-socket-connect', re.compile(r'ClientSocket: Cannot connect to Detector')),
    ('pv-get-parameters', re.compile(r'Failed to get parameters for PV')),
    ('pv-not-connected', re.compile(r"PV \S+ didn't connect")),
    ('lane-alloc', re.compile(r'Failed to allocate lane/vc')),
    ('exec-not-found', re.compile(r'failed to execute \S+: No such file')),
    ('eb-link-connect', re.compile(r'(?:Teb|Meb)Contributor connect failed|linksConnect')),
    ('rogue-transaction', re.compile(r'Block::checkTransaction: General Error')),
    ('python-error', re.compile(r'\*\*\*\* python error|Traceback \(most recent call last\)')),
    ('abort', re.compile(r'Aborted|core dumped|received signal|cleaning up on signal')),
)

# Widest readings of the parts of a day, in hours from that day's midnight.
PARTS = {'morning': (0, 13), 'afternoon': (11, 19), 'evening': (16, 24), 'night': (18, 32), 'day': (0, 24)}
WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


# ----------------------------------------------------------------------------- reading

def open_text(path):
    """Iterate decoded lines of a .log or .log.zst file."""
    if path.endswith('.zst'):
        p = subprocess.Popen(['zstd', '-dcq', path], stdout=subprocess.PIPE)
        try:
            for raw in p.stdout:
                yield raw.decode('utf-8', 'replace')
        finally:
            p.stdout.close()
            p.wait()
    else:
        with open(path, 'rb') as f:
            for raw in f:
                yield raw.decode('utf-8', 'replace')


def sha256_of(path):
    """sha256 of the decompressed content, so a file hashes the same before and after rotation."""
    h = hashlib.sha256()
    if path.endswith('.zst'):
        p = subprocess.Popen(['zstd', '-dcq', path], stdout=subprocess.PIPE)
        for chunk in iter(lambda: p.stdout.read(1 << 20), b''):
            h.update(chunk)
        p.stdout.close()
        if p.wait():
            raise RuntimeError('zstd failed on %s' % path)
    else:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
    return h.hexdigest()


def prefiltered(path, pattern=PREFILTER):
    """Lines that could matter to the classes, via grep (fast on multi-GB files)."""
    src = ['zstd', '-dcq', path] if path.endswith('.zst') else ['cat', path]
    a = subprocess.Popen(src, stdout=subprocess.PIPE)
    g = subprocess.Popen(['grep', '-a', '-E', pattern], stdin=a.stdout, stdout=subprocess.PIPE,
                         env=dict(os.environ, LC_ALL='C'))
    a.stdout.close()
    for raw in g.stdout:
        yield raw.decode('utf-8', 'replace')
    g.stdout.close()
    g.wait()
    a.wait()


def classify(line):
    for name, rx in CLASSES:
        if rx.search(line):
            return name
    return None


# ----------------------------------------------------------------------------- tree listing

def month_dirs(root, start, end):
    """(tree, 'YYYY/MM', abs dir) for every existing month dir of both trees overlapping [start, end]."""
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        for tree, base in TREES:
            d = os.path.join(root, base, '%04d' % y, '%02d' % m)
            if os.path.isdir(d):
                out.append((tree, '%04d/%02d' % (y, m), d))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse_name(name):
    m = NAME.match(name)
    if not m:
        return None
    dd, hms, host, proc, z = m.groups()
    return {'day': int(dd), 'hms': hms, 'host': host, 'comp': proc, 'base': name[:-4] if z else name}


def stamp_time(month, day, hms):
    y, mo = month.split('/')
    return dt.datetime.strptime('%s-%s-%02d %s' % (y, mo, day, hms), '%Y-%m-%d %H:%M:%S')


def list_launches(root, start, end):
    """Launches with stamps in [start - 1 month, end], both trees, in time order (restarts attached)."""
    lo = (start.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    stamps = {}
    for tree, month, d in month_dirs(root, lo, end):
        for name in sorted(os.listdir(d)):
            p = parse_name(name)
            if not p:
                continue
            key = (tree, month, p['day'], p['hms'])
            s = stamps.setdefault(key, {'tree': tree, 'month': month, 'dir': d,
                                        'start': stamp_time(month, p['day'], p['hms']), 'files': []})
            s['files'].append(name)
    launches, last = [], {}
    for key in sorted(stamps, key=lambda k: (stamps[k]['start'], k[0])):
        s, tree = stamps[key], key[0]
        if any(parse_name(f)['comp'] == 'control' for f in s['files']):
            _, month, day, hms = key
            last[tree] = {'id': '%s/%s/%02d_%s' % (tree, month, day, hms), 'tree': tree, 'month': month,
                          'dir': s['dir'], 'start': s['start'], 'files': s['files'], 'restarts': []}
            launches.append(last[tree])
        elif tree in last:          # a hand restart of one process: part of the launch before it
            l = last[tree]
            l['restarts'].extend(os.path.join(os.path.relpath(s['dir'], l['dir']), f) if s['dir'] != l['dir']
                                 else f for f in s['files'])
    return [l for l in launches if l['start'] <= end]


# ----------------------------------------------------------------------------- analysis

def parse_control(path):
    out = {'first_ts': None, 'last_ts': None, 'states': [], 'errors': []}
    for line in open_text(path):
        m = ISO.match(line.rstrip('\n'))
        if not m:
            continue
        ts, who, lvl, msg = m.groups()
        out['first_ts'] = out['first_ts'] or ts
        out['last_ts'] = ts
        sm = re.match(r'Finished processing state (\w+) enter callbacks', msg)
        if sm:
            out['states'].append(sm.group(1))
        if lvl == 'E' and who.endswith('-control'):
            out['errors'].append((ts, msg.strip()))
    return out


def failure_of(errors):
    """First failure in control.log and the components it names.  errors: [(ts, msg)] in order."""
    events = []
    for ts, msg in errors:
        t = dt.datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
        for kind, rx in F_NAMED:
            m = rx.match(msg)
            if m:
                events.append((t, kind, m.group('tr'), m.group('comp')))
                break
        else:
            m = F_EB_ITEM.match(msg)
            if m:
                events.append((t, 'eb_missing', 'running', m.group('comp')))
                continue
            for kind, rx in (('eb_missing', F_EB_HEAD), ('eb_missing', F_EB_QUIET), ('state_failed', F_STATE),
                             ('phase_failed', F_PHASE), ('no_response', F_UNNAMED)):
                m = rx.match(msg)
                if m:
                    events.append((t, kind, m.groupdict().get('tr', 'running'), None))
                    break
    if not events:
        return None
    t0, kind0, tr0 = events[0][:3]
    group = [e for e in events if (e[0] - t0).total_seconds() <= GROUP_SECONDS
             and (e[2] == tr0 or e[1] == 'eb_missing' and kind0 == 'eb_missing')]
    comps = sorted({e[3] for e in group if e[3] and e[3] not in GENERIC})
    later = sorted({e[2] for e in events if e[2] != tr0})
    return {'first_time': t0.isoformat(), 'stage': tr0, 'kind': kind0, 'components': comps,
            'n_failure_lines': len(events), 'later_stages': later}


def scan_file(path):
    """Class counts, severe-line counts and the first mechanism label of one file."""
    classes, sev, mech = {}, {'E': 0, 'C': 0}, None
    for line in prefiltered(path):
        c = classify(line)
        if c:
            classes[c] = classes.get(c, 0) + 1
        m = SEVERE.search(line)
        if m and not BENIGN_C.search(line):
            sev[m.group(1)] += 1
        if mech is None:
            for label, rx in MECHANISMS:
                if rx.search(line):
                    mech = label
                    break
    return {'classes': classes, 'severe': sev, 'mechanism': mech}


def analyse(launch, jobs=1, pool=None):
    """Inventory of one launch (the launch dict from list_launches)."""
    names = list(launch['files']) + list(launch['restarts'])
    paths = [os.path.normpath(os.path.join(launch['dir'], n)) for n in names]
    if pool is not None:
        scans = list(pool.map(scan_file, paths))
    else:
        scans = [scan_file(p) for p in paths]
    ctl = [p for p in paths if parse_name(os.path.basename(p))['comp'] == 'control'
           and os.path.dirname(p) == os.path.normpath(launch['dir'])]
    c = parse_control(ctl[0]) if ctl else {'first_ts': None, 'last_ts': None, 'states': [], 'errors': []}
    classes, severe, mech = {}, {}, {}
    for p, s in zip(paths, scans):
        comp = parse_name(os.path.basename(p))['comp']
        for k, n in s['classes'].items():
            classes.setdefault(k, {})
            classes[k][comp] = classes[k].get(comp, 0) + n
        if s['severe']['E'] or s['severe']['C']:
            severe[comp] = [severe.get(comp, [0, 0])[0] + s['severe']['E'], severe.get(comp, [0, 0])[1] + s['severe']['C']]
        if s['mechanism'] and comp not in mech:
            mech[comp] = s['mechanism']
    fail = failure_of(c['errors'])
    end = c['last_ts'].replace(' ', 'T') if c['last_ts'] else launch['start'].isoformat()
    inv = {'id': launch['id'], 'start': launch['start'].isoformat(), 'end': end,
           'files': sorted(launch['files']), 'restarts': sorted(launch['restarts']),
           'n_files': len(launch['files']), 'states': sorted(set(c['states'])),
           'n_running': c['states'].count('running'), 'classes': classes, 'severe': severe,
           'failure': fail}
    inv['key'] = launch_key(inv, mech)
    return inv


def launch_key(inv, mech):
    """The scripted keys of a launch: inventory key always, component key where one exists."""
    classes = {k: sorted(v) for k, v in sorted(inv['classes'].items())}
    key = {'inventory': {'reached_running': inv['n_running'] > 0, 'n_running': inv['n_running'],
                         'failed': inv['failure'] is not None, 'classes': classes}}
    f = inv['failure']
    if f is None:
        key['component'] = 'healthy' if inv['n_running'] > 0 else 'not keyed'
        return key
    if len(f['components']) == 1:
        comp = f['components'][0]
        own = sum(inv['classes'].get(k, {}).get(comp, 0) for k in ('pv_connect', 'crash', 'traceback'))
        own += sum(inv['severe'].get(comp, [0, 0]))
        if own:
            key['component'] = {'component': comp, 'stage': f['stage'], 'kind': f['kind'],
                                'mechanism': mech.get(comp), 'first_time': f['first_time']}
            return key
    key['component'] = 'not keyed'
    key['named'] = f['components']
    key['why_not'] = ('control names %d components in its first failure' % len(f['components'])
                      if len(f['components']) != 1 else "the named component's own log has no error line")
    return key


def inventory(root, since, until, jobs=1):
    launches = [l for l in list_launches(root, since, until) if since <= l['start'] <= until]
    ex = concurrent.futures.ProcessPoolExecutor(jobs) if jobs > 1 else None
    try:
        return [analyse(l, pool=ex) for l in launches]
    finally:
        if ex:
            ex.shutdown()


# ----------------------------------------------------------------------------- windows

def widest_window(today, phrase):
    """[start, end) of the widest reading of a vague phrase said on date `today` (YYYY-MM-DD)."""
    t = dt.datetime.strptime(today, '%Y-%m-%d')
    words = [w for w in phrase.lower().replace(',', ' ').split() if w not in ('early', 'late', 'on', 'the', 'in')]
    if words in (['over', 'weekend'], ['weekend'], ['last', 'weekend']):
        sat = t - dt.timedelta(days=(t.weekday() - 5) % 7 or 7)
        return sat - dt.timedelta(hours=6), sat + dt.timedelta(days=2, hours=8)
    if words == ['last', 'night']:
        day, part = t - dt.timedelta(days=1), 'night'
    elif words[0] in ('this', 'today', 'tonight'):
        day, part = t, (words[1] if len(words) > 1 else ('night' if words[0] == 'tonight' else 'day'))
    elif words[0] == 'yesterday':
        day, part = t - dt.timedelta(days=1), (words[1] if len(words) > 1 else 'day')
    elif words[0] in WEEKDAYS:
        back = (t.weekday() - WEEKDAYS.index(words[0])) % 7 or 7
        day, part = t - dt.timedelta(days=back), (words[1] if len(words) > 1 else 'day')
    else:
        raise ValueError('phrase not understood: %r' % phrase)
    if part not in PARTS:
        raise ValueError('part of day not understood: %r' % phrase)
    a, b = PARTS[part]
    return day + dt.timedelta(hours=a), day + dt.timedelta(hours=b)


def in_window(launches, start, end):
    """Launches whose span [start stamp, last control line] overlaps [start, end)."""
    out = []
    for inv in launches:
        a = dt.datetime.strptime(inv['start'], '%Y-%m-%dT%H:%M:%S')
        b = dt.datetime.strptime(inv['end'][:19], '%Y-%m-%dT%H:%M:%S')
        if a < end and b >= start:
            out.append(inv['id'])
    return out


# ----------------------------------------------------------------------------- cases

def load_cases(path=CASES):
    with open(path) as f:
        return json.load(f)


def find_file(root, launch_id, base):
    """Path of a case file under root, as .log or .log.zst."""
    tree, rest = launch_id.split('/', 1)
    d = os.path.join(root, dict(TREES)[tree], rest.rsplit('/', 1)[0])
    for name in (base, base + '.zst'):
        p = os.path.normpath(os.path.join(d, name))
        if os.path.exists(p):
            return p
    return None


def launch_by_id(root, launch_id):
    tree, y, m, st = launch_id.split('/')
    start = stamp_time('%s/%s' % (y, m), int(st[:2]), st[3:])
    for l in list_launches(root, start, start + dt.timedelta(days=40)):
        if l['id'] == launch_id:
            return l
    return None


def case_keys(root, case, jobs=1):
    """Recompute files, sha256 and keys of each keyed launch of a case."""
    out = []
    for lid in case['keyed_launches']:
        l = launch_by_id(root, lid)
        if l is None:
            out.append({'id': lid, 'error': 'launch not found under %s' % root})
            continue
        ex = concurrent.futures.ProcessPoolExecutor(jobs) if jobs > 1 else None
        try:
            inv = analyse(l, pool=ex)
        finally:
            if ex:
                ex.shutdown()
        files = []
        for name in inv['files'] + inv['restarts']:
            p = os.path.normpath(os.path.join(l['dir'], name))
            base = name[:-4] if name.endswith('.zst') else name
            files.append({'name': base, 'sha256': sha256_of(p)})
        out.append({'id': lid, 'start': inv['start'], 'end': inv['end'], 'files': files, 'key': inv['key']})
    return out


def cmd_keys(args):
    spec = load_cases(args.cases)
    bad = 0
    for case in spec['cases']:
        got = case_keys(args.root, case, args.jobs)
        if args.update:
            case['launches'] = got
            print('%-14s updated %s' % (case['id'], ', '.join(g['id'] for g in got)))
            continue
        want = case.get('launches', [])
        for g, w in zip(got, want):
            diffs = []
            if 'error' in g:
                diffs.append(g['error'])
            else:
                gf = {f['name']: f['sha256'] for f in g['files']}
                for f in w['files']:
                    if f['name'] not in gf:
                        diffs.append('missing file %s' % f['name'])
                    elif gf[f['name']] != f['sha256']:
                        diffs.append('sha256 differs: %s' % f['name'])
                if json.dumps(g['key'], sort_keys=True) != json.dumps(w['key'], sort_keys=True):
                    diffs.append('key differs: got %s' % json.dumps(g['key'], sort_keys=True))
            if len(got) != len(want):
                diffs.append('keyed launch count differs')
            bad += bool(diffs)
            comp = g.get('key', {}).get('component')
            label = comp if isinstance(comp, str) else '%s @ %s (%s)' % (comp['component'], comp['stage'], comp['mechanism'])
            print('%-14s %-34s %s %s' % (case['id'], g['id'], 'OK ' if not diffs else 'BAD', label))
            for d in diffs:
                print('    ' + d)
    if args.update:
        with open(args.cases, 'w') as f:
            json.dump(spec, f, indent=1, sort_keys=True)
            f.write('\n')
        return 0
    return 1 if bad else 0


def cmd_check(args):
    spec = load_cases(args.cases)
    bad = 0
    for case in spec['cases']:
        start, end = widest_window(case['today'], case['phrase'])
        invs = inventory(args.root, start - dt.timedelta(days=3), end, args.jobs)
        there = in_window(invs, start, end)
        extra = [i for i in there if i not in case['keyed_launches']]
        missing = [i for i in case['keyed_launches'] if i not in there]
        ok = not extra and not missing
        bad += not ok
        print('%-14s %-26s %s .. %s  launches in window: %d  %s' % (
            case['id'], '"%s"' % case['phrase'], start.strftime('%m-%d %H:%M'), end.strftime('%m-%d %H:%M'),
            len(there), 'UNIQUE' if ok else 'AMBIGUOUS'))
        for i in extra:
            print('    not keyed but in window: ' + i)
        for i in missing:
            print('    keyed but outside window: ' + i)
    return 1 if bad else 0


def cmd_inventory(args):
    since = dt.datetime.strptime(args.since, '%Y-%m-%d')
    until = dt.datetime.strptime(args.until, '%Y-%m-%d')
    invs = inventory(args.root, since, until, args.jobs)
    with open(args.out, 'w') as f:
        json.dump(invs, f, indent=1, sort_keys=True)
    print('%d launches -> %s' % (len(invs), args.out))
    return 0


def phrases_for(today):
    """The vague phrases tried for a case said on `today`."""
    t = dt.datetime.strptime(today, '%Y-%m-%d')
    out = ['this morning', 'yesterday morning', 'yesterday afternoon', 'yesterday evening', 'last night']
    for back in range(2, 7):
        wd = WEEKDAYS[(t - dt.timedelta(days=back)).weekday()].capitalize()
        out += ['%s %s' % (wd, part) for part in ('morning', 'afternoon', 'evening', 'night')]
    if t.weekday() in (0, 1):
        out.append('over the weekend')
    return out


def candidates(invs, lag_days=(1, 2, 3)):
    """(launch id, today, phrase, n launches in window) for every keyed or healthy launch whose widest
    window holds that launch alone.  `today` is 1-3 days after the launch's start."""
    out = []
    for inv in invs:
        comp = inv['key']['component']
        if comp == 'not keyed':
            continue
        a = dt.datetime.strptime(inv['start'], '%Y-%m-%dT%H:%M:%S')
        for lag in lag_days:
            today = (a + dt.timedelta(days=lag)).strftime('%Y-%m-%d')
            for phrase in phrases_for(today):
                w0, w1 = widest_window(today, phrase)
                if not (w0 <= a < w1):
                    continue
                there = in_window(invs, w0, w1)
                if there == [inv['id']]:
                    out.append((inv['id'], today, phrase))
    return out


def cmd_candidates(args):
    with open(args.inventory) as f:
        invs = json.load(f)
    for lid, today, phrase in candidates(invs):
        inv = [i for i in invs if i['id'] == lid][0]
        comp = inv['key']['component']
        label = comp if isinstance(comp, str) else '%s@%s/%s' % (comp['component'], comp['stage'], comp['mechanism'])
        print('%-30s %s  %-22s %s' % (lid, today, phrase, label))
    return 0


# ----------------------------------------------------------------------------- name scan

NAME_PATTERNS = (
    ('home-path', re.compile(r'/(?:sdf/|cds/|reg/neh/|reg/d/)?home\d?/(?:[a-z]/)?([a-z][\w-]{1,15})\b')),
    ('user-assign', re.compile(r'\b(?:user|USER|username|LOGNAME|owner)\s*[=:]\s*[\'"]?([A-Za-z][\w.-]{1,30})')),
    ('cli-user', re.compile(r'--user[= ]+([A-Za-z][\w.-]{1,30})')),
    ('getpass', re.compile(r'\b(getpass|getuser)\b')),
    ('email-or-principal', re.compile(r'\b([A-Za-z][\w.-]*@(?:SLAC\.STANFORD\.EDU|(?:\w+\.)*stanford\.edu))\b', re.I)),
    ('owned-by', re.compile(r"owned by(?: user)? '?([A-Za-z][\w.-]{1,30})")),
)
SHARED_ACCOUNTS = {'mfxopr', 'root', 'psdatmgr', 'psrel', 'm', 'mfx'}


def scan_names(root):
    """Per pattern: files, lines and distinct values that look like a person's account (shared
    operator accounts excluded).  Values are counted, never returned."""
    pre = r'home|user|USER|LOGNAME|owner|getpass|getuser|@|owned by'
    stats = {name: {'files': 0, 'lines': 0, 'values': set()} for name, _ in NAME_PATTERNS}
    for d, _, names in os.walk(root):
        for n in sorted(names):
            path = os.path.join(d, n)
            seen = set()
            for line in prefiltered(path, pre):
                for name, rx in NAME_PATTERNS:
                    vals = [m.group(1) for m in rx.finditer(line)]
                    vals = [v for v in vals if v.split('@')[0].lower() not in SHARED_ACCOUNTS]
                    if vals:
                        stats[name]['lines'] += 1
                        stats[name]['values'].update(vals)
                        seen.add(name)
            for name in seen:
                stats[name]['files'] += 1
    return {k: {'files': v['files'], 'lines': v['lines'], 'distinct': len(v['values'])} for k, v in stats.items()}


def cmd_names(args):
    for name, st in sorted(scan_names(args.root).items()):
        print('%-20s files %6d  lines %8d  distinct values %4d' % (name, st['files'], st['lines'], st['distinct']))
    print('patterns: ' + '; '.join('%s = %s' % (n, rx.pattern) for n, rx in NAME_PATTERNS))
    return 0


# ----------------------------------------------------------------------------- fetch

def months_of_cases(spec):
    months = set()
    for case in spec['cases']:
        a, b = widest_window(case['today'], case['phrase'])
        for t in (a, b - dt.timedelta(seconds=1)):
            months.add('%04d/%02d' % (t.year, t.month))
        for lid in case['keyed_launches']:
            months.add('/'.join(lid.split('/')[1:3]))
    return sorted(months)


def remote(args, cmd):
    if not args.host:
        return subprocess.check_output(['bash', '-c', cmd]).decode()
    rsh = args.rsh.split() if args.rsh else ['ssh']
    return subprocess.check_output(rsh + [args.host, cmd]).decode()


def plan_fetch(listing, keep, max_bytes):
    """listing: [(size, relpath)].  Drop the largest files not in `keep` until the total fits."""
    total = sum(s for s, _ in listing)
    dropped = []
    for s, p in sorted(listing, key=lambda x: (-x[0], x[1])):
        if total <= max_bytes:
            break
        base = os.path.basename(p)
        if (base[:-4] if base.endswith('.zst') else base) in keep:
            continue
        dropped.append((s, p))
        total -= s
    gone = {p for _, p in dropped}
    return [p for _, p in listing if p not in gone], dropped, total


def cmd_fetch(args):
    spec = load_cases(args.cases)
    src = args.source_root.rstrip('/')
    months = args.month or months_of_cases(spec)
    dirs = [os.path.join(base, m) for m in months for _, base in TREES] + list(EXTRA)
    cmd = 'cd %s && for d in %s; do [ -d "$d" ] && find "$d" -maxdepth 1 -type f -printf "%%s %%p\\n"; done; true' % (
        src, ' '.join(dirs))
    listing = []
    for line in remote(args, cmd).splitlines():
        size, path = line.split(' ', 1)
        if '/__pycache__/' in path or path.endswith('~'):
            continue
        listing.append((int(size), path))
    keep = {f['name'] for c in spec['cases'] for l in c.get('launches', []) for f in l['files']}
    files, dropped, total = plan_fetch(listing, keep, int(float(args.max_bytes)))
    print('months %s: %d files, %.1f MB to copy, %d dropped (%.1f MB)' % (
        ' '.join(months), len(files), total / 1e6, len(dropped), sum(s for s, _ in dropped) / 1e6))
    if args.dry_run:
        for s, p in dropped:
            print('  drop %s (%d bytes)' % (p, s))
        return 0
    os.makedirs(args.dest, exist_ok=True)
    lst = args.dest.rstrip('/') + '.files.txt'
    with open(lst, 'w') as f:
        f.write('\n'.join(files) + '\n')
    rsync = ['rsync', '-a', '--files-from=' + lst]
    if args.host:
        rsync += ['-e', args.rsh or 'ssh', '%s:%s/' % (args.host, src), args.dest.rstrip('/') + '/']
    else:
        rsync += [src + '/', args.dest.rstrip('/') + '/']
    subprocess.check_call(rsync)
    manifest = {'source': '%s:%s' % (args.host or 'local', src), 'months': months, 'n_files': len(files),
                'bytes': total, 'max_bytes': int(float(args.max_bytes)),
                'dropped': [{'path': p, 'bytes': s} for s, p in dropped],
                'fetched_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    with open(args.dest.rstrip('/') + '.manifest.json', 'w') as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    bad = 0
    for case in spec['cases']:
        for l in case.get('launches', []):
            for fl in l['files']:
                p = find_file(args.dest, l['id'], fl['name'])
                if p is None or sha256_of(p) != fl['sha256']:
                    bad += 1
                    print('  sha256 %s: %s' % ('missing' if p is None else 'MISMATCH', fl['name']))
    print('case files verified: %s' % ('all sha256 match' if not bad else '%d problems' % bad))
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd')
    f = sub.add_parser('fetch', help='copy the months the cases need from S3DF into a prepared root')
    f.add_argument('--dest', required=True, help='prepared root to build (ROOT/home/m/mfxopr/...)')
    f.add_argument('--host', default='sdfiana025', help="S3DF host for ssh/rsync; '' = local copy")
    f.add_argument('--rsh', default='', help='ssh command for rsync -e, e.g. "ssh -F ~/.ssh/my_config"')
    f.add_argument('--source-root', default='/sdf', help='where home/m/mfxopr lives on the source')
    f.add_argument('--month', action='append', help='YYYY/MM to copy (default: the months the cases touch)')
    f.add_argument('--max-bytes', default='2e9', help='drop the largest non-case files beyond this')
    f.add_argument('--dry-run', action='store_true')
    for name, hlp in (('keys', 'recompute the keys from a local copy; exit 1 on drift'),
                      ('check', 'is each vague window unambiguous?'),
                      ('inventory', 'per-launch inventory of a date range')):
        p = sub.add_parser(name, help=hlp)
        p.add_argument('--root', required=True, help='prepared root; /sdf on S3DF itself')
        p.add_argument('--jobs', type=int, default=1)
        if name == 'keys':
            p.add_argument('--update', action='store_true', help='write the computed launches into the cases file')
        if name == 'inventory':
            p.add_argument('--since', required=True)
            p.add_argument('--until', required=True)
            p.add_argument('--out', required=True)
    p = sub.add_parser('names', help='count lines that look like personal accounts (prints no values)')
    p.add_argument('--root', required=True)
    p = sub.add_parser('candidates', help='launches that are alone in the widest window of some phrase')
    p.add_argument('--inventory', required=True, help='output of the inventory subcommand')
    for p in sub.choices.values():
        p.add_argument('--cases', default=CASES)
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        return 2
    return {'fetch': cmd_fetch, 'keys': cmd_keys, 'check': cmd_check, 'inventory': cmd_inventory,
            'candidates': cmd_candidates, 'names': cmd_names}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
