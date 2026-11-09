#!/bin/bash
# procstat_hosts.sh REV OUT(new dir): the daq_webgui of commit REV (git archive of psdaq/psdaq), given a .cnf with
# one process with no host and one at 192.0.2.1, runs for 6 s with telnetlib stubbed (every Telnet.open is logged,
# nothing is connected) and an audit hook on socket.connect.  Prints its exit code, its refusal (stderr), and the
# (host, port) of every Telnet.open it made.
REV=$1; OUT=$2
[ -n "$OUT" ] && [ ! -e "$OUT" ] || { echo "usage: procstat_hosts.sh REV OUT(new dir)"; exit 2; }
mkdir -p $OUT/tree
git archive $REV psdaq/psdaq | tar -x -C $OUT/tree || exit 3
cat > $OUT/remote.cnf <<'CNF'
platform = '5'
procmgr_config = [
 { id:'here', flags:'s', cmd:'sleep 60' },
 { host:'192.0.2.1', id:'remote', flags:'s', cmd:'sleep 60' },
]
CNF
cat > $OUT/telnet_stub.py <<'PY'
import json, runpy, sys, telnetlib
log = open(sys.argv[1], 'a', buffering=1)
def hook(ev, args):
    if ev == 'socket.connect':
        log.write(json.dumps([ev, repr(args[1])]) + '\n')
sys.addaudithook(hook)
def _open(self, host, port=0, *a, **k):          # telnetlib stubbed: record the host, connect nothing
    log.write(json.dumps(['telnet.open', host, str(port)]) + '\n')
    raise ConnectionRefusedError('telnetlib stub: not contacted')
telnetlib.Telnet.open = _open
sys.argv = ['daq_webgui'] + sys.argv[2:]
runpy.run_module('psdaq.webgui.server', run_name='__main__')
PY
cd $OUT
echo "  $OUT/remote.cnf:"; sed 's/^/    /' remote.cnf
export PYTHONPATH=$OUT/tree/psdaq${PYTHONPATH:+:$PYTHONPATH}
python -c "import psdaq.webgui.procstat_api as m; print('  %s: procstat_api from %s; require_loopback_cnf: %s' % ('$REV', m.__file__.replace('$OUT/', ''), hasattr(m, 'require_loopback_cnf')))"
timeout -s TERM 6 python telnet_stub.py net.jsonl --emulate --port 0 --procstat-cnf remote.cnf > server.out 2> server.err
rc=$?
echo "  daq_webgui --procstat-cnf remote.cnf: exit $rc$( [ $rc = 124 ] && echo ' (still serving after 6 s: stopped by timeout)')"
grep -h -E 'listening|refusing' server.out server.err | sed 's/^/    /' | cut -c1-220
python3 - net.jsonl <<'PY'
import collections, json, os, sys
recs = [json.loads(l) for l in open(sys.argv[1])] if os.path.exists(sys.argv[1]) else []
opens = collections.Counter((r[1], r[2]) for r in recs if r[0] == 'telnet.open')
conn = [r[1] for r in recs if r[0] == 'socket.connect']
print('  Telnet.open calls: %d; (host, port): %s' % (sum(opens.values()), dict(sorted(opens.items())) or '{}'))
print('  socket.connect (audit hook): %d' % len(conn))
PY
