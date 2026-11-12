#!/bin/bash
# sentinel.sh: about once a second, one line to $D/<node>.log (D defaults to $ROOT/work/sentinel):
#   <UTC time, ms>Z group_stat=<s> tmp_stat=<s> root_stat=<s> sleep_over=<s> prev_write=<s>
#   group_stat: os.stat() of a conda file under /sdf/group; tmp_stat: of a file under /tmp;
#   root_stat: of this script, a file under $ROOT (/sdf/data); sleep_over: how far sleep(1) overran;
#   prev_write: writing and flushing the previous line (the log is under $ROOT too).
# A stat that raises prints ERR:<name> in place of its time.
# Stops when $D/STOP or $D/STOP.<node> exists (checked every line), or when the step ends.
D=${SENT_DIR:-$ROOT/work/sentinel}
exec /usr/bin/python3 -u - "$D" "$(hostname -s)" "$(readlink -f "$0")" <<'PY'
import os, sys, time, datetime
D, node, F = sys.argv[1:4]
G = '/sdf/group/lcls/ds/ana/sw/conda2/inst/envs/daq_20250402_r9/bin/python3.9'
T = '/tmp/sentinel-%s.touch' % node
open(T, 'a').close()
log = open(os.path.join(D, node + '.log'), 'a', buffering=1)
stops = [os.path.join(D, 'STOP'), os.path.join(D, 'STOP.' + node)]
def tstat(p):
    t0 = time.monotonic()
    try:
        os.stat(p)
    except OSError as e:
        return 'ERR:' + e.__class__.__name__
    return '%.4f' % (time.monotonic() - t0)
def utc():
    return datetime.datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'
log.write('# sentinel start node=%s pid=%d group_file=%s tmp_file=%s root_file=%s\n' % (node, os.getpid(), G, T, F))
pw = 0.0
while True:
    if any(os.path.exists(s) for s in stops):
        log.write('# sentinel stop file seen %s\n' % utc()); break
    now = utc(); g, t, r = tstat(G), tstat(T), tstat(F)
    s0 = time.monotonic(); time.sleep(1); so = time.monotonic() - s0 - 1.0
    w0 = time.monotonic()
    log.write('%s group_stat=%s tmp_stat=%s root_stat=%s sleep_over=%.4f prev_write=%.4f\n' % (now, g, t, r, so, pw))
    pw = time.monotonic() - w0
PY
