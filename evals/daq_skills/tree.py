"""Build the prepared roots of the cold-start mode (m1, family B) and the starved copies.

    python3 tree.py --work WORK [--cases cases_v3.json] [--out WORK/roots] [--write-cases]

WORK is where data/pools.tar.gz was unpacked (tar keeps the modification times).  Output:

  OUT/shared/                 one calendar of launches at the real MFX paths, every launch of every case
  OUT/m1/<case>/              what run.py --mode m1 mounts read-only at /sdf: the shared calendar up to the
                              case's 'now' (later launches do not exist yet), hard links into shared/
  OUT/m1-starved/<case>/      the same without the case's root-cause files (fault cases only)
  OUT/m0-starved/<case>/logs  the case's catalog pool without its root-cause files (mounted as in mode m0)
  OUT/manifest.json           per case: keyed launch, root-cause files, the window check, sizes, leftovers

The calendar (one history for all cases, so each case's tree also holds the other cases' launches):

  /sdf/home/m/mfxopr/daq/logs/<YYYY>/<MM>/   launches from 2026-09-17 09:29:03 on (the current MFX root)
  /sdf/home/m/mfxopr/<YYYY>/<MM>/            launches before that (the root MFX used until then)
  /sdf/home/m/mfxopr/daq/scripts/            seven partition configs side by side, plus editor backups
  /sdf/home/t/tmoopr/daq/logs/<YYYY>/<MM>/   a second hutch's tree

Each launch is a pool's launch moved to another day: the file names' day, the directory, every date in the
text (local dates, UTC ISO stamps, HTTP dates, ctime dates) and the modification times move by whole days with
the time of day kept; UTC stamps follow US Pacific daylight time on the new day.  The hutch name 'tst' becomes
'mfx' (or 'tmo') wherever it is not inside another word.  No line is added, removed or reordered.  The keyed
launch of each case sits on the case's day; decoy launches from the other pools fill other days, chosen by a
fixed seed, never inside any case's widest window.  The partition configs are rebuilt from the '# HOST' and
'# CMDLINE' headers of one launch each, so they match processes that really ran in the sim.

The build fails (exit 1) unless, for every case, the MFX roots of its tree hold no launch but the keyed one
inside the widest reading of its vague time.  Launches of the second hutch inside that window are counted
(manifest 'other_hutch_in_window'): they are a deliberate wrong-tree trap.

Standard library only, Python 3.6+; needs zstd for the compressed launches.
"""

import argparse
import datetime
import json
import os
import random
import re
import shutil
import subprocess
import sys

from harvest import pool_id

HERE = os.path.dirname(os.path.abspath(__file__))
MFX_CUR, MFX_OLD, TMO_CUR = 'home/m/mfxopr/daq/logs', 'home/m/mfxopr', 'home/t/tmoopr/daq/logs'
SCRIPTS = 'home/m/mfxopr/daq/scripts'
CUTOVER = datetime.datetime(2026, 9, 17, 9, 29, 3)      # hutch-resources mfx-resources.json, navigation_pitfalls
SEED = 20261119
FMT = '%Y-%m-%d %H:%M'
DAY = datetime.timedelta(days=1)

# Decoy days: (date, launches, earliest start, latest start, tree).  Each slot takes the next launches of the
# shuffled decoy list that fit: start inside [earliest, latest], no overlap with another launch of that day,
# and (MFX only) no overlap with any case's widest window.
CALENDAR = [
    ('2025-12-02', 2, '08:00', '20:00', 'mfx'), ('2025-12-09', 1, '08:00', '20:00', 'mfx'),
    ('2026-07-14', 2, '08:00', '22:00', 'mfx'), ('2026-07-28', 2, '08:00', '22:00', 'mfx'),
    ('2026-08-11', 3, '00:00', '23:00', 'mfx'), ('2026-08-27', 3, '08:00', '23:00', 'mfx'),
    ('2026-09-02', 3, '00:00', '23:00', 'mfx'), ('2026-09-09', 3, '00:00', '23:00', 'mfx'),
    ('2026-09-15', 3, '00:00', '23:00', 'mfx'), ('2026-09-16', 3, '00:00', '15:00', 'mfx'),
    ('2026-09-17', 1, '02:30', '09:20', 'mfx'), ('2026-09-17', 2, '09:35', '13:30', 'mfx'),
    ('2026-09-17', 2, '14:30', '23:00', 'mfx'), ('2026-09-18', 3, '00:00', '23:00', 'mfx'),
    ('2026-09-23', 3, '00:00', '23:00', 'mfx'), ('2026-09-30', 3, '00:00', '23:00', 'mfx'),
    ('2026-10-01', 2, '00:00', '23:00', 'mfx'), ('2026-10-04', 3, '00:00', '23:00', 'mfx'),
    ('2026-10-07', 3, '00:00', '23:00', 'mfx'), ('2026-10-14', 3, '00:00', '23:00', 'mfx'),
    ('2026-10-21', 3, '00:00', '23:00', 'mfx'), ('2026-10-22', 4, '00:00', '23:00', 'mfx'),
    ('2026-10-23', 2, '02:30', '23:00', 'mfx'), ('2026-10-28', 3, '00:00', '23:00', 'mfx'),
    ('2026-10-31', 3, '00:00', '16:30', 'mfx'), ('2026-11-01', 1, '07:05', '10:45', 'mfx'),
    ('2026-11-01', 1, '11:30', '23:00', 'mfx'), ('2026-11-04', 4, '00:00', '23:00', 'mfx'),
    ('2026-11-09', 4, '00:00', '23:00', 'mfx'), ('2026-11-10', 4, '00:00', '23:00', 'mfx'),
    ('2026-11-12', 4, '00:00', '23:00', 'mfx'), ('2026-11-13', 4, '00:00', '23:00', 'mfx'),
    ('2026-11-16', 4, '00:00', '23:00', 'mfx'), ('2026-11-17', 4, '00:00', '23:00', 'mfx'),
    ('2026-11-18', 4, '07:10', '23:00', 'mfx'), ('2026-11-19', 3, '00:00', '14:30', 'mfx'),
    # the second hutch: a few days of its own, and launches inside some MFX cases' windows (the wrong-tree trap)
    ('2026-10-22', 1, '16:30', '23:00', 'tmo'), ('2026-11-09', 2, '11:30', '18:30', 'tmo'),
    ('2026-11-13', 1, '11:30', '18:30', 'tmo'), ('2026-11-17', 1, '17:30', '23:30', 'tmo'),
    ('2026-11-05', 3, '00:00', '23:00', 'tmo'), ('2026-11-11', 3, '00:00', '23:00', 'tmo'),
]
# Partition configs: (file name, catalog pool whose first launch's headers give the processes)
CONFIGS = [('mfx.py', 'big-healthy-36'), ('mfx_testfabric.py', 'healthy-ami'), ('mfx_epixuhr.py', 'reg-cfg-epixUHR'),
           ('mfx_epixuhr3x2.py', 'reg-cfg-epixuhr3x2'), ('mfx_jf_test.py', 'jf-readback'), ('mfx_tt_test.py', 'healthy-tt'),
           ('mfx_wave8_cpo.py', 'reg-cfg-hrencoder')]
CONFIG_TIME = datetime.datetime(2026, 9, 17, 9, 52)     # daq/scripts was created then (mfx-resources.json)

HUTCH = re.compile(r'(?<![a-z])tst')
MON = 'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec'
WDAY = 'Mon|Tue|Wed|Thu|Fri|Sat|Sun'
STAMPS = re.compile(r'(?P<utc>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:\+00:00|Z))'
                    r'|(?P<http>(?:%s), \d\d (?:%s) \d{4} \d\d:\d\d:\d\d GMT)'
                    r'|(?P<ctime>(?:%s) (?:%s) [ \d]\d \d\d:\d\d:\d\d \d{4})'
                    r'|(?P<date>\d{4}-\d\d-\d\d)'
                    r'|(?P<path>\d{4}/\d\d/\d\d(?=_\d\d:\d\d:\d\d))' % (WDAY, MON, WDAY, MON))
BENIGN_TST = re.compile(r'getstate|setstate|getstatus|bootstrap|TSTRB|tStream|tStartup|tStore|TStamp|Tstate')   # not the hutch name


# ---------------------------------------------------------------------------- US Pacific time, by hand

def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(days=7 * (n - 1))


def is_dst(local):
    """US rule since 2007: from the second Sunday of March 02:00 to the first Sunday of November 02:00."""
    a = datetime.datetime.combine(_nth_sunday(local.year, 3, 2), datetime.time(2))
    b = datetime.datetime.combine(_nth_sunday(local.year, 11, 1), datetime.time(2))
    return a <= local < b


def to_utc(local):
    return local + datetime.timedelta(hours=7 if is_dst(local) else 8)


def to_local(utc):
    guess = utc - datetime.timedelta(hours=7)
    return guess if is_dst(guess) else utc - datetime.timedelta(hours=8)


def epoch(local):
    return (to_utc(local) - datetime.datetime(1970, 1, 1)).total_seconds()


def local_of_epoch(t):
    return to_local(datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=t))


def parse(s):
    return datetime.datetime.strptime(s, FMT)


# ---------------------------------------------------------------------------- rewriting one file

def shift_text(text, days, hutch):
    """The hutch name and every date moved by `days` whole days, the local time of day kept."""
    text = HUTCH.sub(hutch, text)
    if not days:
        return text
    dd = datetime.timedelta(days=days)

    def utc(u):
        return to_utc(to_local(u) + dd)

    def sub(m):
        s = m.group(0)
        if m.group('utc'):
            frac = re.search(r'(\.\d+)?(\+00:00|Z)$', s)
            u = utc(datetime.datetime.strptime(s[:19], '%Y-%m-%dT%H:%M:%S'))
            return u.strftime('%Y-%m-%dT%H:%M:%S') + (frac.group(1) or '') + frac.group(2)
        if m.group('http'):
            return utc(datetime.datetime.strptime(s, '%a, %d %b %Y %H:%M:%S GMT')).strftime('%a, %d %b %Y %H:%M:%S GMT')
        if m.group('ctime'):
            t = datetime.datetime.strptime(re.sub(' +', ' ', s), '%a %b %d %H:%M:%S %Y') + dd
            return t.strftime('%a %b ') + ('%2d' % t.day) + t.strftime(' %H:%M:%S %Y')
        fmt = '%Y/%m/%d' if m.group('path') else '%Y-%m-%d'
        try:
            return (datetime.datetime.strptime(s, fmt) + dd).strftime(fmt)
        except ValueError:
            return s
    return STAMPS.sub(sub, text)


def stale_dates(text, ln, days):
    """Local stamps of the launch's old days left in a moved file (UTC stamps may legitimately carry them)."""
    if not days:
        return []
    out = []
    for d in sorted(set([ln.start.date(), ln.end.date()])):
        ct = d.strftime('%a %b ') + ('%2d' % d.day)
        out += re.findall(r'%s \d\d:\d\d:\d\d|%s_\d\d:\d\d:\d\d|%s \d\d:\d\d:\d\d %d' % (d.strftime('%Y-%m-%d'), d.strftime('%Y/%m/%d'), ct, d.year), text)
    return out


def read_log(path):
    if path.endswith('.zst'):
        return subprocess.run(['zstd', '-q', '-dc', path], stdout=subprocess.PIPE, check=True).stdout.decode('latin-1')
    return open(path, 'rb').read().decode('latin-1')


def write_log(path, text, mtime):
    data = text.encode('latin-1')
    if path.endswith('.zst'):
        data = subprocess.run(['zstd', '-q', '-c', '-3'], input=data, stdout=subprocess.PIPE, check=True).stdout
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').write(data)
    os.chmod(path, 0o644)
    os.utime(path, (mtime, mtime))


# ---------------------------------------------------------------------------- launches and the calendar

class Launch(object):
    def __init__(self, pool, s, src):
        self.pool, self.host, self.prefix, self.ym, self.files = pool, s['host'], s['prefix'], s['ym'], list(s['files'])
        self.src = src                                               # .../pools/<id>/logs/<YYYY>/<MM>
        self.start = datetime.datetime.strptime(s['start'], '%Y-%m-%d %H:%M:%S')
        self.end = max(local_of_epoch(os.stat(os.path.join(src, f)).st_mtime) for f in self.files)
        self.end = max(self.end, datetime.datetime.strptime(s['last'], '%Y-%m-%d %H:%M:%S') if s.get('last') else self.start)

    def key(self):
        return (self.host, self.ym, self.prefix)

    def moved(self, date):
        """(new start, new end, new prefix) when the launch is moved to `date`."""
        days = (date - self.start.date()).days
        return self.start + days * DAY, self.end + days * DAY, '%02d_%s' % (date.day, self.prefix[3:]), days


def load_pools(work, cat):
    out = {}
    for name in sorted(cat['pools']):
        pdir = os.path.join(work, 'pools', pool_id(name))
        if not os.path.exists(os.path.join(pdir, 'pool.json')):
            raise SystemExit('%s: no pool %s under %s; unpack data/pools.tar.gz there first' % (name, pool_id(name), work))
        info = json.load(open(os.path.join(pdir, 'pool.json')))
        out[name] = [Launch(name, s, os.path.join(pdir, 'logs', s['ym'])) for s in info['sessions']]
    return out


def keyed_launch(case, pools, cat):
    want = set(dict((c['id'], c) for c in cat['cases'])[case['id']]['key']['sessions'])
    (ln,) = [l for l in pools[case['pool']] if l.prefix in want]
    return ln


def window(case):
    return parse(case['m1']['widest'][0]), parse(case['m1']['widest'][1])


def overlaps(a0, a1, b0, b1, margin=datetime.timedelta(0)):
    return a0 < b1 + margin and b0 < a1 + margin


def plan(cases, pools, cat, calendar=None):
    """[(launch, date, tree, case id or None)]: the keyed launches on their days, then the decoys."""
    placed = []
    keyed = set()
    for c in cases:
        ln = keyed_launch(c, pools, cat)
        placed.append((ln, datetime.datetime.strptime(c['m1']['date'], '%Y-%m-%d').date(), 'mfx', c['id']))
        keyed.add(ln.key())
    seen, decoys = set(keyed), []
    for name in sorted(pools):
        for ln in pools[name]:
            if ln.key() not in seen:
                seen.add(ln.key())
                decoys.append(ln)
    random.Random(SEED).shuffle(decoys)
    wins = [window(c) for c in cases]
    latest = max(parse(c['m1']['now']) for c in cases)
    for date_s, n, lo, hi, tree in CALENDAR if calendar is None else calendar:
        date = datetime.datetime.strptime(date_s, '%Y-%m-%d').date()
        lo_t, hi_t = (datetime.datetime.strptime(x, '%H:%M').time() for x in (lo, hi))
        for _ in range(n):
            for i, ln in enumerate(decoys):
                s, e, _p, _d = ln.moved(date)
                if not lo_t <= s.time() <= hi_t or e >= latest:
                    continue
                if any(t == tree and overlaps(s, e, *p.moved(d)[:2], margin=datetime.timedelta(minutes=2))
                       for p, d, t, _c in placed if d == date):
                    continue
                if tree == 'mfx' and any(overlaps(s, e, w0, w1) for w0, w1 in wins):
                    continue
                placed.append((ln, date, tree, None))
                del decoys[i]
                break
            else:
                raise SystemExit('calendar: no decoy fits %s %s-%s (%s)' % (date_s, lo, hi, tree))
    return placed


def where(start, tree):
    if tree == 'tmo':
        return TMO_CUR
    return MFX_OLD if start < CUTOVER else MFX_CUR


# ---------------------------------------------------------------------------- building

def link_or_copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def set_dir_mtimes(root):
    """Each directory takes the newest modification time below it, as if written by the launches."""
    newest = {}
    for d, subs, files in os.walk(root, topdown=False):
        ts = [os.lstat(os.path.join(d, f)).st_mtime for f in files] + [newest[os.path.join(d, s)] for s in subs if os.path.join(d, s) in newest]
        if ts:
            newest[d] = max(ts)
            os.utime(d, (newest[d], newest[d]))


def config_text(ln):
    """A procmgr partition config rebuilt from the '# HOST' and '# CMDLINE' headers of one launch."""
    rows = []
    for f in sorted(ln.files):
        head = read_log(os.path.join(ln.src, f)).split('\n', 40)[:40]
        h = dict((m.group(1), m.group(2).strip()) for m in (re.match(r'# (HOST|CMDLINE):\s*(.*)', l) for l in head) if m)
        if 'CMDLINE' in h:
            pid = f.rsplit(':', 1)[-1].replace('.log.zst', '').replace('.log', '')
            rows.append(" { host: '%s', id: '%s', flags: 'spu', cmd: '%s' }," % (h.get('HOST', 'localhost'), pid, h['CMDLINE'].replace("'", '"')))
    return ("platform = '5'\nhost, cores, id, flags, env, cmd, rtprio = ('host', 'cores', 'id', 'flags', 'env', 'cmd', 'rtprio')\n\n"
            "procmgr_config = [\n%s\n]\n" % '\n'.join(rows))


def placements(work, cases, cat, calendar=None):
    """(pools, [(Launch, launch record)]): where every launch goes, without writing anything.  The record is
    {tree, dir, prefix, files, start, end, case, pool, source, days} as it will be on disk."""
    pools = load_pools(work, cat)
    out = []
    for ln, date, tree, cid in plan(cases, pools, cat, calendar):
        start, end, prefix, days = ln.moved(date)
        rel = os.path.join(where(start, tree), '%04d' % start.year, '%02d' % start.month)
        out.append((ln, {'tree': tree, 'dir': rel, 'prefix': prefix, 'files': sorted(prefix + f[len(ln.prefix):] for f in ln.files),
                         'start': start.strftime('%Y-%m-%d %H:%M:%S'), 'end': end.strftime('%Y-%m-%d %H:%M:%S'), 'case': cid,
                         'pool': ln.pool, 'source': ln.prefix, 'days': days}))
    return pools, out


def build(work, cases, cat, out, quiet=False, calendar=None, configs=None):
    pools, placed = placements(work, cases, cat, calendar)
    configs = CONFIGS if configs is None else configs
    shared = os.path.join(out, 'shared')
    for d in ('shared', 'm1', 'm1-starved', 'm0-starved'):
        if os.path.exists(os.path.join(out, d)):
            shutil.rmtree(os.path.join(out, d))
    launches, stale = [], 0                        # what is on disk
    for ln, rec in placed:
        for f in ln.files:
            src = os.path.join(ln.src, f)
            mt = epoch(local_of_epoch(os.stat(src).st_mtime) + rec['days'] * DAY)
            text = shift_text(read_log(src), rec['days'], rec['tree'])
            stale += len(stale_dates(text, ln, rec['days']))
            write_log(os.path.join(shared, rec['dir'], rec['prefix'] + f[len(ln.prefix):]), text, mt)
        launches.append(rec)
    first = dict((name, ls[0]) for name, ls in pools.items())
    for name, pool in configs:
        text = HUTCH.sub('mfx', config_text(first[pool]))
        for i, fn in enumerate((name, name + '~')):
            p = os.path.join(shared, SCRIPTS, fn)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'w').write(text)
            t = epoch(CONFIG_TIME - datetime.timedelta(days=configs.index((name, pool)) * 9 + (0 if i == 0 else 3)))
            os.utime(p, (t, t))
    statics = [os.path.relpath(os.path.join(d, f), shared) for d, _s, fs in os.walk(os.path.join(shared, SCRIPTS)) for f in fs]
    manifest = {'seed': SEED, 'launches': launches, 'cases': {}}
    failed = []
    for c in cases:
        now, (w0, w1) = parse(c['m1']['now']), window(c)
        (mine,) = [l for l in launches if l['case'] == c['id']]
        starve = set(prefix_swap(f, c, mine) for f in c.get('starve_files') or [])
        for variant in ('m1', 'm1-starved'):
            if variant == 'm1-starved' and not starve:
                continue
            root = os.path.join(out, variant, c['id'])
            for l in launches:
                if datetime.datetime.strptime(l['end'], '%Y-%m-%d %H:%M:%S') >= now:
                    continue
                for f in l['files']:
                    if variant == 'm1-starved' and l is mine and f in starve:
                        continue
                    link_or_copy(os.path.join(shared, l['dir'], f), os.path.join(root, l['dir'], f))
            for s in statics:
                link_or_copy(os.path.join(shared, s), os.path.join(root, s))
            set_dir_mtimes(root)
        chk = check_root(os.path.join(out, 'm1', c['id']), mine, w0, w1)
        if not chk['pass']:
            failed.append(c['id'])
        m = derived(c, mine)
        m.update(check=chk, now=c['m1']['now'], files=sum(len(fs) for _d, _s, fs in os.walk(os.path.join(out, 'm1', c['id']))),
                 bytes=du(os.path.join(out, 'm1', c['id'])), leftovers=leftovers(os.path.join(out, 'm1', c['id'])))
        if starve:
            gone = [f for f in m['starve_files'] if os.path.exists(os.path.join(out, 'm1-starved', c['id'], mine['dir'], f))]
            m['starved_absent'] = not gone and all(os.path.exists(os.path.join(out, 'm1', c['id'], mine['dir'], f)) for f in m['starve_files'])
        manifest['cases'][c['id']] = m
        # m0: the catalog pool without the root-cause files
        if c.get('starve_files'):
            pdir = os.path.join(work, 'pools', pool_id(c['pool']), 'logs')
            dst = os.path.join(out, 'm0-starved', c['id'], 'logs')
            for d, _s, fs in os.walk(pdir):
                for f in fs:
                    if f not in c['starve_files']:
                        link_or_copy(os.path.join(d, f), os.path.join(dst, os.path.relpath(d, pdir), f))
            for d, _s, _f in os.walk(pdir):
                st = os.stat(d)
                if os.path.isdir(os.path.join(dst, os.path.relpath(d, pdir))):
                    os.utime(os.path.join(dst, os.path.relpath(d, pdir)), (st.st_atime, st.st_mtime))
    manifest['shared_bytes'] = du(shared)
    manifest['stale_local_dates'] = stale
    if stale:
        failed.append('%d local time stamps still carry a launch\'s old day' % stale)
    json.dump(manifest, open(os.path.join(out, 'manifest.json'), 'w'), indent=1, sort_keys=True)
    if not quiet:
        for cid, m in manifest['cases'].items():
            print('%-18s now %s  keyed %s/%s  in window: %s  other hutch in window: %d  %s files %.1f MB  leftover tst %d  %s'
                  % (cid, m['now'], m['keyed_dir'], m['keyed_stamp'], m['check']['in_window'], m['check']['other_hutch_in_window'],
                     m['files'], m['bytes'] / 1e6, sum(m['leftovers'].values()), 'PASS' if m['check']['pass'] else 'FAIL'))
    return manifest, failed


def prefix_swap(f, case, mine):
    """A catalog file name of the keyed launch under its new day."""
    return mine['prefix'] + f[len(mine['source']):]


def derived(case, mine):
    """The case-table fields that follow from the calendar: where the keyed launch sits in the m1 tree."""
    start = datetime.datetime.strptime(mine['start'], '%Y-%m-%d %H:%M:%S')
    end = datetime.datetime.strptime(mine['end'], '%Y-%m-%d %H:%M:%S')
    d = '/sdf/' + mine['dir']
    hi = (end + datetime.timedelta(minutes=1)).replace(second=0)
    return {'keyed_stamp': mine['prefix'], 'keyed_dir': d, 'keyed_files': mine['files'],
            'starve_files': [prefix_swap(f, case, mine) for f in case.get('starve_files') or []],
            'pointer': 'The DAQ logs are in %s, and the launch in question ran on %s between %s and %s.'
                       % (d, start.strftime('%Y-%m-%d'), start.strftime('%H:%M'), hi.strftime('%H:%M'))}


def launches_on_disk(root):
    """{(tree, dir, prefix): [start, end]} from the files themselves: the stamp in the name, the newest mtime."""
    out = {}
    for d, _s, fs in os.walk(root):
        rel = os.path.relpath(d, root)
        m = re.match(r'home/(m/mfxopr|t/tmoopr)/(?:daq/logs/)?(\d{4})/(\d\d)$', rel)
        if not m:
            continue
        for f in fs:
            mm = re.match(r'(\d\d)_(\d\d:\d\d:\d\d)_', f)
            if not mm:
                continue
            k = ('mfx' if m.group(1).startswith('m') else 'tmo', rel, f[:11])
            t0 = datetime.datetime.strptime('%s-%s-%s %s' % (m.group(2), m.group(3), mm.group(1), mm.group(2)), '%Y-%m-%d %H:%M:%S')
            t1 = local_of_epoch(os.stat(os.path.join(d, f)).st_mtime)
            lo, hi = out.get(k, [t0, t0])
            out[k] = [min(lo, t0), max(hi, t1)]
    return out


def check_root(root, mine, w0, w1):
    """Inside the widest window, the MFX roots must hold the keyed launch and nothing else."""
    found = launches_on_disk(root)
    inside = sorted('%s/%s' % (d, p) for (t, d, p), (a, b) in found.items() if t == 'mfx' and overlaps(a, b, w0, w1))
    other = sum(1 for (t, d, p), (a, b) in found.items() if t == 'tmo' and overlaps(a, b, w0, w1))
    want = '%s/%s' % (mine['dir'], mine['prefix'])
    return {'window': [w0.strftime(FMT), w1.strftime(FMT)], 'in_window': inside, 'other_hutch_in_window': other,
            'pass': inside == [want], 'launches_mfx': sum(1 for k in found if k[0] == 'mfx'), 'launches_other': sum(1 for k in found if k[0] == 'tmo')}


def du(root):
    seen, n = set(), 0
    for d, _s, fs in os.walk(root):
        for f in fs:
            st = os.lstat(os.path.join(d, f))
            if st.st_ino not in seen:
                seen.add(st.st_ino)
                n += st.st_size
    return n


def leftovers(root):
    """Words that still contain 'tst' in the MFX tree, other than ordinary words (getstate, bootstrap, ...)."""
    out = {}
    for d, _s, fs in os.walk(os.path.join(root, 'home', 'm')):
        for f in fs:
            for w in re.findall(r'[A-Za-z0-9_]*tst[A-Za-z0-9_]*', read_log(os.path.join(d, f)), re.I):
                if not BENIGN_TST.search(w):
                    out[w] = out.get(w, 0) + 1
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--work', required=True, help='where data/pools.tar.gz was unpacked')
    ap.add_argument('--catalog', default=os.path.join(HERE, 'catalog.json'))
    ap.add_argument('--cases', default=os.path.join(HERE, 'cases_v3.json'))
    ap.add_argument('--out', help='default WORK/roots')
    ap.add_argument('--write-cases', action='store_true', help='write the derived m1 fields (keyed files, pointer) into --cases')
    a = ap.parse_args(argv)
    cat, table = json.load(open(a.catalog)), json.load(open(a.cases))
    manifest, failed = build(a.work, table['cases'], cat, a.out or os.path.join(a.work, 'roots'))
    if a.write_cases:
        for c in table['cases']:
            m = manifest['cases'][c['id']]
            c['m1'].update((k, m[k]) for k in ('keyed_stamp', 'keyed_dir', 'keyed_files', 'starve_files', 'pointer'))
        open(a.cases, 'w').write(json.dumps(table, indent=1) + '\n')
    if failed:
        print('FAILED window check: %s' % ', '.join(failed))
        return 1
    print('%d cases, window check passed for all' % len(table['cases']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
