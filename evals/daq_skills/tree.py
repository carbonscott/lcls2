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
'mfx' (or 'tmo') wherever it is not inside another word.  The sim's S3DF node names (sdfmilan082, sdfada013, ...)
become the hutch's real DAQ hosts, in file names and in the text, per process (HOSTS, from the hutch-resources map):
on MFX, control and teb0 run on drp-srcf-cmp014 (so the map's '<stamp>_drp-srcf-cmp014:control.log' works), the
timing, EPICS, BLD, PVA-camera and encoder DRPs there too, the GUIs and the sim's helper servers on mfx-daq, AMI and the
monitoring MEB on drp-srcf-mon006, and each detector DRP on one of MFX's drp-srcf-cmpNNN DRP nodes (jungfrau_N and
epix100_0 where MFX has them, any other by a fixed hash of its name).  In the text a node name takes the host of the
process it belongs to: the file's own process ('# HOST:'), the alias of the dict it sits in, the process of a log-file
name it is part of; a DAQ file report's 'hostname' takes the launch's first detector DRP.  As at MFX, the AMI chain and
the monitoring MEB carry the instance suffix '_first' (meb0_first, ami-node_0_first, ...; first_instance), in file
names and text.  No line is added, removed or reordered.  The keyed
launch of each case sits on the case's day; decoy launches from the other pools fill other days, chosen by a
fixed seed, never inside any case's widest window.  The partition configs are rebuilt from the '# HOST' and
'# CMDLINE' headers of one launch each, so they match processes that really ran in the sim, in the shape of MFX's
daq/scripts/mfx.py (double-quoted literals, control on collect_host, GUIs with no host, the AMI/MEB loop at the end).

Rotation.  Each case's tree shows the current MFX tree as the daily rotation had left it at the case's 'now'
(real_mfx.rotation_cutoff): a file modified 7 days or more before the last 14:00 run is .zst, a newer one plain .log
(a converted copy under OUT/rotation, modification time kept).  The old root and the second hutch keep the bundled
names (harvest compressed a pool's older launches).  The case table's keyed_files are the names in the case's tree.

The build fails (exit 1) unless, for every case, the MFX roots of its tree hold no launch but the keyed one
inside the widest reading of its vague time, and no S3DF node name is left in any file name or text of the tree.  Launches of the second hutch inside that window are counted
(manifest 'other_hutch_in_window'): they are a deliberate wrong-tree trap.

Standard library only, Python 3.6+; needs zstd for the compressed launches.
"""

import argparse
import datetime
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys

import real_mfx
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

# Real DAQ hosts per hutch (hutch-resources 974ee6d: mfx-resources.json code.daq_nodes.verified_active_assignments_2026_09_20,
# tmo-resources.json logs).  collect: control and the event builder; gui: the control host (GUIs, entries with no host key);
# monitor: AMI and the monitoring MEB; drps: the detector DRP nodes; fixed: where MFX runs that detector.
HOSTS = {
    'mfx': {'collect': 'drp-srcf-cmp014', 'gui': 'mfx-daq', 'monitor': 'drp-srcf-mon006',
            'drps': ['drp-srcf-cmp031', 'drp-srcf-cmp032', 'drp-srcf-cmp033', 'drp-srcf-cmp035', 'drp-srcf-cmp038',
                     'drp-srcf-cmp039', 'drp-srcf-cmp044'],
            'fixed': {'jungfrau_0': 'drp-srcf-cmp033', 'jungfrau_1': 'drp-srcf-cmp032', 'jungfrau_2': 'drp-srcf-cmp035',
                      'jungfrau_3': 'drp-srcf-cmp038', 'jungfrau_4': 'drp-srcf-cmp039', 'epix100_0': 'drp-srcf-cmp031'}},
    'tmo': {'collect': 'drp-srcf-mon001', 'gui': 'tmo-daq', 'monitor': 'drp-srcf-mon004',
            'drps': ['drp-srcf-cmp001', 'drp-srcf-cmp003', 'drp-srcf-cmp004', 'drp-srcf-cmp011', 'drp-srcf-cmp013',
                     'drp-srcf-cmp026', 'drp-srcf-cmp030', 'drp-srcf-cmp043'], 'fixed': {}},
}
# Process roles by name (first match wins); a name matching none is a detector DRP.
ROLES = [
    ('collect', re.compile(r'(?:control|teb\d*|ts_\d+|epics_\d+|bld_\d+|pvcam_\d+|encoder_\d+|simenc|enc_trig|tprtrig|pvrtmon_\d+)$')),
    ('gui', re.compile(r'(?:control_gui|daqstat|xpmpva|groupca|ami-client\w*|det_protec_mon|procstat|pvatable|hsdpva|dtica|pvant'
                       r'|partca|tprca|bldcas|hpsbldcas|hpsbldcpa|hpsbldsvc|lclsbldsvc|hpsdbuscas|deadca|wave8pvs)$')),
    ('monitor', re.compile(r'(?:ami-[\w-]+|meb\d*\w*|shmc\d*)$')),
]
# MFX runs its AMI chain and monitoring MEB as instance 'first' (the 'for instance ... {"first": ...}' loop at the end
# of daq/scripts/mfx.py): their ids carry '_first' everywhere (file names, '# ID:', control's rollcall, '-u meb0_first';
# hutch-resources mfx-resources.json monitoring_path), the programs keep their names (.../bin/ami-global).
INSTANCE = re.compile(r'(?<!bin/)(?<![\w-])(meb\d+|ami-(?:global|manager|client|export|node_\d+|worker_\d+|prefetch_\d+))(?![\w-])')
S3DF_NODE = re.compile(r'(?<![A-Za-z0-9])sdf[a-z]{3,}\d{3}(?:\.[a-z0-9.-]*stanford\.edu)?(?![A-Za-z0-9])')   # sdfmilan082, sdfada013
_ALIAS_BEFORE = re.compile(r"""['"]alias['"]:\s*['"]([^'"]+)['"][^{}]*$""")
_FILE_AFTER = re.compile(r'^:([\w.+-]+?)\.log')
_ALIAS_AFTER = re.compile(r"""^['"],\s*\d+\],\s*\[\w+,\s*['"]([^'"]+)['"]""")          # [False, 'drp/<pid>/<host>', 5], [False, '<alias>', ...]
_HOSTNAME_BEFORE = re.compile(r"""['"]hostname['"]:\s*['"]$""")


def first_instance(text):
    """MFX's names for the AMI and monitoring-MEB processes: 'meb0' -> 'meb0_first', 'ami-node_0' -> 'ami-node_0_first'."""
    return INSTANCE.sub(r'\1_first', text)


def role_of(proc):
    for role, rx in ROLES:
        if rx.match(proc):
            return role
    return 'drp'


def host_for(proc, hutch='mfx'):
    """The real host of a process of the sim on `hutch` (deterministic)."""
    h = HOSTS[hutch]
    role = role_of(proc)
    if role != 'drp':
        return h[role]
    return h['fixed'].get(proc) or h['drps'][int(hashlib.sha1(proc.encode()).hexdigest(), 16) % len(h['drps'])]


def proc_of(fname):
    """'09_21:12:48_sdfada013:control.log[.zst]' -> 'control'."""
    p = fname.rsplit(':', 1)[-1]
    return re.sub(r'\.log(?:\.zst)?$', '', p)


def rename(fname, old_prefix, new_prefix, hutch='mfx'):
    """A launch file's name under its new day and its process's real host."""
    rest = fname[len(old_prefix):]
    m = re.match(r'_([^:]+):(.+)$', rest)
    if not m:
        return new_prefix + rest
    proc = m.group(2) if hutch != 'mfx' else first_instance(m.group(2))
    return '%s_%s:%s' % (new_prefix, host_for(proc_of(fname), hutch), proc)


def rehost(text, proc, procs=(), hutch='mfx'):
    """Every S3DF node name in a file of `proc` replaced by the real host of the process it belongs to.
    procs: the launch's process names (a file report's 'hostname' takes the first detector DRP among them)."""
    drps = sorted(p for p in procs if role_of(p) == 'drp')
    report_host = host_for(drps[0] if drps else proc, hutch)

    def sub(m):
        line0 = text.rfind('\n', 0, m.start()) + 1
        before = text[max(line0, m.start() - 400):m.start()]
        after = text[m.end():m.end() + 160]
        if re.search(r'#\s*HOST:\s*$', before):
            return host_for(proc, hutch)
        f = _FILE_AFTER.match(after)
        if f:
            return host_for(f.group(1), hutch)
        a = _ALIAS_BEFORE.search(before)
        if a:
            return host_for(a.group(1), hutch)
        if _HOSTNAME_BEFORE.search(before):
            return report_host
        a = _ALIAS_AFTER.match(after)
        if a and re.search(r'/\d+/$', before):
            return host_for(a.group(1), hutch)
        return host_for(proc, hutch)
    return S3DF_NODE.sub(sub, text)


def node_names(text):
    """S3DF node names left in a text (should be none in a built tree)."""
    return S3DF_NODE.findall(text)


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
    """A procmgr partition config rebuilt from the '# HOST' and '# CMDLINE' headers of one launch, in the shape of MFX's
    daq/scripts/mfx.py: double-quoted literals ('{ host: "drp-srcf-cmp014", id: "teb0", ... }'), control on
    'host: collect_host', the GUIs with no host key (they run on the submitting host), and the AMI chain and the
    monitoring MEB made by a 'for instance ...' loop at the end, with ids '<name>_{instance}' (instance "first")."""
    rows, ami, workers = [], [], []
    for f in sorted(ln.files):
        head = read_log(os.path.join(ln.src, f)).split('\n', 40)[:40]
        h = dict((m.group(1), m.group(2).strip()) for m in (re.match(r'# (HOST|CMDLINE):\s*(.*)', l) for l in head) if m)
        if 'CMDLINE' not in h:
            continue
        pid = first_instance(proc_of(f))
        cmd = first_instance(h['CMDLINE']).replace('"', "'")
        w = re.match(r'(meb|ami-node_|ami-worker_|ami-prefetch_)(\d+)_first$', pid)
        if w:
            workers.append((w.group(1), cmd))
        elif pid.endswith('_first'):
            ami.append((pid[:-len('_first')], cmd))
        elif pid == 'control':
            rows.append(' { host: collect_host,%s id: "control", flags: "spu", cmd: "%s" },' % (' ' * 9, cmd))
        elif role_of(pid) == 'gui':
            rows.append(' {%s id: "%s", flags: "s", cmd: "%s" },' % (' ' * 29, pid, cmd))
        else:
            rows.append(' { host: "%s", id: "%s", flags: "spu", cmd: "%s" },' % (host_for(pid), pid, cmd))
    h = HOSTS['mfx']
    text = ('platform = "5"\n'
            'collect_host = "%s"\n'
            'hutch, station, user = ("mfx", 0, "mfxopr")\n'
            'ami_worker_nodes = ["%s"]\n'
            'ami_manager_node = "%s"\n'
            'host, cores, id, flags, env, cmd, rtprio = ("host", "cores", "id", "flags", "env", "cmd", "rtprio")\n\n'
            'procmgr_config = [\n%s\n]\n' % (h['collect'], h['monitor'], h['monitor'], '\n'.join(rows)))
    if ami or workers:
        text += '\nfor instance in ("first",):\n    procmgr_ami = [\n'
        for name, cmd in ami:
            where = '                        ' if role_of(name) == 'gui' else 'host:ami_manager_node, '
            text += '      { %sid:f"%s_{instance}", flags:"s", cmd:"%s" },\n' % (where, name, cmd)
        text += '    ]\n    for N, worker_node in enumerate(ami_worker_nodes):\n'
        for kind, cmd in workers:
            text += ('        procmgr_ami.append({ host:worker_node, id:f"%s{N}_{instance}", flags:"%s", cmd:"%s" })\n'
                     % (kind, 'spu' if kind == 'meb' else 's', cmd))
        text += '    procmgr_config.extend(procmgr_ami)\n'
    return text


def placements(work, cases, cat, calendar=None):
    """(pools, [(Launch, launch record)]): where every launch goes, without writing anything.  The record is
    {tree, dir, prefix, files, start, end, case, pool, source, days} as it will be on disk."""
    pools = load_pools(work, cat)
    out = []
    for ln, date, tree, cid in plan(cases, pools, cat, calendar):
        start, end, prefix, days = ln.moved(date)
        rel = os.path.join(where(start, tree), '%04d' % start.year, '%02d' % start.month)
        out.append((ln, {'tree': tree, 'dir': rel, 'prefix': prefix, 'files': sorted(rename(f, ln.prefix, prefix, tree) for f in ln.files),
                         'start': start.strftime('%Y-%m-%d %H:%M:%S'), 'end': end.strftime('%Y-%m-%d %H:%M:%S'), 'case': cid,
                         'pool': ln.pool, 'source': ln.prefix, 'days': days}))
    return pools, out


def build(work, cases, cat, out, quiet=False, calendar=None, configs=None):
    pools, placed = placements(work, cases, cat, calendar)
    configs = CONFIGS if configs is None else configs
    shared = os.path.join(out, 'shared')
    for d in ('shared', 'rotation', 'm1', 'm1-starved'):   # m0-starved is only redone where it differs (a run may have it mounted)
        if os.path.exists(os.path.join(out, d)):
            shutil.rmtree(os.path.join(out, d))
    launches, stale = [], 0                        # what is on disk
    for ln, rec in placed:
        procs = [proc_of(f) for f in ln.files]
        for f in ln.files:
            src = os.path.join(ln.src, f)
            mt = epoch(local_of_epoch(os.stat(src).st_mtime) + rec['days'] * DAY)
            text = shift_text(read_log(src), rec['days'], rec['tree'])
            if rec['tree'] == 'mfx':
                text = first_instance(text)
            text = rehost(text, proc_of(f), procs, rec['tree'])
            stale += len(stale_dates(text, ln, rec['days']))
            write_log(os.path.join(shared, rec['dir'], rename(f, ln.prefix, rec['prefix'], rec['tree'])), text, mt)
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
        cutoff = real_mfx.rotation_cutoff(now)
        names = {}                                  # (dir, shared name) -> name in this case's tree (the rotation at now)
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
                    src = os.path.join(shared, l['dir'], f)
                    name = rotated(l, f, local_of_epoch(os.stat(src).st_mtime), cutoff)
                    names[(l['dir'], f)] = name
                    if name != f:
                        src = real_mfx.converted(src, name, os.path.join(out, 'rotation', l['dir']))
                    link_or_copy(src, os.path.join(root, l['dir'], name))
            for s in statics:
                link_or_copy(os.path.join(shared, s), os.path.join(root, s))
            set_dir_mtimes(root)
        chk = check_root(os.path.join(out, 'm1', c['id']), mine, w0, w1)
        if not chk['pass']:
            failed.append(c['id'])
        m = derived(c, mine, dict((f, names.get((mine['dir'], f), f)) for f in mine['files']))
        moved = [(k, v) for k, v in names.items() if k[1] != v]
        m['rotation'] = {'cutoff': cutoff.strftime(FMT), 'made_plain': sum(1 for _k, v in moved if not v.endswith('.zst')),
                         'compressed': sum(1 for _k, v in moved if v.endswith('.zst'))}
        m.update(check=chk, now=c['m1']['now'], files=sum(len(fs) for _d, _s, fs in os.walk(os.path.join(out, 'm1', c['id']))),
                 bytes=du(os.path.join(out, 'm1', c['id'])), leftovers=leftovers(os.path.join(out, 'm1', c['id'])),
                 node_leftovers=node_leftovers(os.path.join(out, 'm1', c['id']), 'home'))
        if m['node_leftovers']:
            failed.append('%s: %d S3DF node names left' % (c['id'], m['node_leftovers']))
        if starve:
            gone = [f for f in m['starve_files'] if os.path.exists(os.path.join(out, 'm1-starved', c['id'], mine['dir'], f))]
            m['starved_absent'] = not gone and all(os.path.exists(os.path.join(out, 'm1', c['id'], mine['dir'], f)) for f in m['starve_files'])
        manifest['cases'][c['id']] = m
        # m0: the catalog pool without the root-cause files
        if c.get('starve_files'):
            pdir = os.path.join(work, 'pools', pool_id(c['pool']), 'logs')
            dst = os.path.join(out, 'm0-starved', c['id'], 'logs')
            want = dict((os.path.relpath(os.path.join(d, f), pdir), os.path.join(d, f)) for d, _s, fs in os.walk(pdir)
                        for f in fs if f not in c['starve_files'])
            have = dict((os.path.relpath(os.path.join(d, f), dst), os.path.join(d, f)) for d, _s, fs in os.walk(dst) for f in fs)
            if sorted(have) != sorted(want) or any(not os.path.samefile(have[k], want[k]) for k in want):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                for rel, src in sorted(want.items()):
                    link_or_copy(src, os.path.join(dst, rel))
            for d, _s, _f in os.walk(pdir):
                st = os.stat(d)
                if os.path.isdir(os.path.join(dst, os.path.relpath(d, pdir))):
                    os.utime(os.path.join(dst, os.path.relpath(d, pdir)), (st.st_atime, st.st_mtime))
    manifest['shared_bytes'] = du(shared)
    manifest['shared_node_leftovers'] = node_leftovers(shared, 'home')
    if manifest['shared_node_leftovers']:
        failed.append('%d S3DF node names left in the shared calendar' % manifest['shared_node_leftovers'])
    manifest['stale_local_dates'] = stale
    if stale:
        failed.append('%d local time stamps still carry a launch\'s old day' % stale)
    json.dump(manifest, open(os.path.join(out, 'manifest.json'), 'w'), indent=1, sort_keys=True)
    if not quiet:
        for cid, m in manifest['cases'].items():
            print('%-18s now %s  keyed %s/%s  in window: %s  other hutch in window: %d  %s files %.1f MB  leftover tst %d  node names %d  %s'
                  % (cid, m['now'], m['keyed_dir'], m['keyed_stamp'], m['check']['in_window'], m['check']['other_hutch_in_window'],
                     m['files'], m['bytes'] / 1e6, sum(m['leftovers'].values()), m['node_leftovers'], 'PASS' if m['check']['pass'] else 'FAIL'))
    return manifest, failed


def rotated(rec, f, mtime_local, cutoff):
    """The name of a launch file in a case's tree: a file of MFX's current tree is .zst iff it was modified before the
    rotation cutoff of the case's now (real_mfx.rotation_cutoff: the daily 14:00 run compresses files 7 days old), else
    plain .log; the old root and the second hutch keep the bundled names."""
    if rec['tree'] != 'mfx' or not rec['dir'].startswith(MFX_CUR + os.sep):
        return f
    return real_mfx.rotated_name(f, mtime_local < cutoff)


def names_at(ln, rec, now):
    """{name in the shared calendar: name in the tree of a case asked at `now`} for the files of a placed launch,
    from the bundled pool's modification times (no tree needs to be built)."""
    cutoff = real_mfx.rotation_cutoff(now)
    return dict((rename(f, ln.prefix, rec['prefix'], rec['tree']),
                 rotated(rec, rename(f, ln.prefix, rec['prefix'], rec['tree']),
                         local_of_epoch(os.stat(os.path.join(ln.src, f)).st_mtime) + rec['days'] * DAY, cutoff)) for f in ln.files)


def prefix_swap(f, case, mine):
    """A catalog file name of the keyed launch under its new day and real host."""
    return rename(f, mine['source'], mine['prefix'], mine['tree'])


def derived(case, mine, names=None):
    """The case-table fields that follow from the calendar: where the keyed launch sits in the m1 tree.  names: the
    keyed launch's shared file names -> their names in the case's tree (rotation); default unchanged."""
    names = names or {}
    start = datetime.datetime.strptime(mine['start'], '%Y-%m-%d %H:%M:%S')
    end = datetime.datetime.strptime(mine['end'], '%Y-%m-%d %H:%M:%S')
    d = '/sdf/' + mine['dir']
    hi = (end + datetime.timedelta(minutes=1)).replace(second=0)
    return {'keyed_stamp': mine['prefix'], 'keyed_dir': d, 'keyed_files': [names.get(f, f) for f in mine['files']],
            'starve_files': [names.get(f, f) for f in (prefix_swap(f, case, mine) for f in case.get('starve_files') or [])],
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


def node_leftovers(root, sub=os.path.join('home', 'm')):
    """S3DF node names (sdfmilan082, ...) left in the file names and texts under root/sub."""
    n = 0
    for d, _s, fs in os.walk(os.path.join(root, sub)):
        for f in fs:
            n += len(node_names(f)) + len(node_names(read_log(os.path.join(d, f))))
    return n


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
