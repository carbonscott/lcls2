#!/usr/bin/env python3
"""covbind: forged copies of a real evidence dir, one forgery per dir (the skeptic's cases, each
as it edited the record and, where it matters, with the record's hashes recomputed as a forger
who knows the format would; plus the new rules' cases).
usage: mutreal.py <evidence dir> <out dir> -> one 'CASE <name> <rows that must drop> <dir>' line each"""
import glob, hashlib, json, os, shutil, struct, sys

ev, out = sys.argv[1], sys.argv[2]
recs = {}
for f in sorted(glob.glob(os.path.join(ev, '*.json'))):
    r = json.load(open(f))
    dets = [x for x in r['rows'] if x.startswith('det:')]
    nxtc = sum(x.endswith('.xtc2') for x in r['files'])
    if nxtc == 1:                       # the fakecam --segments 2 record has 2; it is not a target
        recs[dets[0]] = (os.path.basename(f), r)
W8, W8HE, E100 = 'det:drp:wave8', 'det:drp:wave8he', 'det:drp:epix100'


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 23), b''):
            h.update(block)
    return h.hexdigest()


def rehash(r):
    r['content'] = {f: {'bytes': os.path.getsize(f), 'sha256': sha(f)} for f in r['files'] if os.path.isfile(f)}


def xtc(r):
    return [f for f in r['files'] if f.endswith('.xtc2')][0]


def log_of(r, name):
    return [f for f in r['files'] if f.endswith(name)][0]


def case(name, drops, mutate, targets=None, rehashed=False):
    d = os.path.join(out, name)
    fdir = d + '-files'
    for p in (d, fdir):
        shutil.rmtree(p, ignore_errors=True)
        os.makedirs(p)
    for f in sorted(glob.glob(os.path.join(ev, '*.json'))):
        r = json.load(open(f))
        det = [x for x in r['rows'] if x.startswith('det:')][0]
        if targets == 'all' or (det in drops and os.path.basename(f) == recs[det][0]):
            mutate(r, fdir)
            if rehashed:
                rehash(r)
        with open(os.path.join(d, os.path.basename(f)), 'w') as g:
            json.dump(r, g, indent=1)
    print(f'CASE {name} {",".join(drops) or "-"} {d}', flush=True)


def swap_xtc(data):
    def m(r, fdir):
        p = os.path.join(fdir, os.path.basename(xtc(r)))
        with open(p, 'wb') as f:
            f.write(data(xtc(r)) if callable(data) else data)
        r['files'] = [p if f.endswith('.xtc2') else f for f in r['files']]
    return m


def flip_copy(r, fdir):                 # a copy with one byte changed, under the original's hash
    src = xtc(r)
    p = os.path.join(fdir, os.path.basename(src))
    shutil.copyfile(src, p)
    with open(p, 'r+b') as f:
        f.seek(os.path.getsize(p) // 2)
        b = f.read(1)
        f.seek(-1, 1)
        f.write(bytes([b[0] ^ 0xff]))
    r['content'][p] = r['content'][src]
    r['files'] = [p if f == src else f for f in r['files']]


def head(n):
    return lambda path: open(path, 'rb').read(n)


TINY = struct.pack('<QIIHHI', 0, 2 << 24, 0, 0, 0, 12)
OTHER_SHA = 'f' * 40
case('valid', [], lambda r, d: None)
# the skeptic's cases, as it edited the records
case('dirty-true', [W8], lambda r, d: r.__setitem__('dirty', True))
case('dirty-absent', [W8HE], lambda r, d: r.pop('dirty'))
case('runid-null', [E100], lambda r, d: r.__setitem__('run_id', None))
case('runid-blank', [W8], lambda r, d: r.__setitem__('run_id', '  '))
case('other-sha', [E100], lambda r, d: r.__setitem__('sha', OTHER_SHA))
case('xtc2-empty', [W8], swap_xtc(b''))
case('xtc2-random', [W8HE], swap_xtc(lambda p: os.urandom(4096)))
case('xtc2-truncated', [W8], swap_xtc(head(1000000)))
case('log-missing', [W8HE], lambda r, d: r['files'].__setitem__(-1, r['files'][-1] + '.gone'))
case('probe-xtc2-tiny-configure', [E100], swap_xtc(TINY))
case('probe-xtc2-of-other-det', [W8HE], lambda r, d: r.__setitem__(
    'files', [xtc(recs[W8][1]) if f.endswith('.xtc2') else f for f in r['files']]))
case('probe-no-xtc2-listed', [W8], lambda r, d: r.__setitem__(
    'files', [f for f in r['files'] if not f.endswith('.xtc2')]))
# the same file forgeries with the record's hashes recomputed
case('rehashed-xtc2-random', [W8HE], swap_xtc(lambda p: os.urandom(4096)), rehashed=True)
case('rehashed-xtc2-truncated', [W8], swap_xtc(head(1000000)), rehashed=True)
case('rehashed-probe-xtc2-tiny-configure', [E100], swap_xtc(TINY), rehashed=True)
case('rehashed-probe-xtc2-of-other-det', [W8HE], lambda r, d: r.__setitem__(
    'files', [xtc(recs[W8][1]) if f.endswith('.xtc2') else f for f in r['files']]), rehashed=True)
# the new rules
case('runid-other-run', [E100], lambda r, d: r.__setitem__('run_id', 'tstx00001/r0002'))
case('xtc2-byte-changed', [W8], flip_copy)
case('det-log-of-other-type', [W8HE], lambda r, d: r.__setitem__('files', [
    log_of(recs[W8][1], ':wave8_0.log') if f.endswith(':wave8he_0.log') else f for f in r['files']]),
    rehashed=True)
case('no-content-hashes', [W8], lambda r, d: r.pop('content'))
# program rows: every record forged, so no record is left to prove the row
tebs = sorted(log_of(json.load(open(f)), ':teb0.log') for f in glob.glob(os.path.join(ev, '*.json')))


def other_teb(r, d):                    # the teb log of the next record's run
    mine = log_of(r, ':teb0.log')
    r['files'] = [tebs[(tebs.index(mine) + 1) % len(tebs)] if f == mine else f for f in r['files']]


case('teb-log-of-another-run', ['prog:teb'], other_teb, targets='all', rehashed=True)
case('no-simxpm-log', ['prog:pyxpm'], lambda r, d: r.__setitem__(
    'files', [f for f in r['files'] if not f.endswith('/simxpm.log')]), targets='all', rehashed=True)
