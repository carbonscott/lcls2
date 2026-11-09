#!/bin/bash
# hostmacro.sh TREE: the web procstat (daq_webgui --emulate --procstat-cnf) of TREE's psdaq, on a .cnf whose
# procmgr_macro['HOST'] names another machine (daq-remote-host.invalid).  telnetlib is stubbed (an open is recorded,
# nothing is contacted) and an audit hook refuses (and records) any socket connect or name lookup of a host that is not
# loopback, so no packet leaves the node.  The server runs at most 12 s.  Prints its exit status, what it said about the
# .cnf, and every recorded open / lookup.
TREE=$(cd $1 && pwd); O=$(mktemp -d /tmp/hostmacro-XXXX)
cat > $O/p.cnf <<'CNF'
platform = '5'
procmgr_macro['HOST'] = 'daq-remote-host.invalid'
procmgr_config = [
 { id:'nohost', flags:'s', cmd:'sleep 60' },
 { host:'localhost', id:'named_localhost', flags:'s', cmd:'sleep 60' },
]
CNF
cat > $O/stub.py <<'PY'
import json, runpy, sys, telnetlib
log = open(sys.argv[1], 'a', buffering=1)
LOCAL = ('127.0.0.1', 'localhost', '::1', '', None)
def hook(ev, args):
    if ev == 'socket.connect':
        a = args[1]
        host = a[0] if isinstance(a, tuple) else a
        if host not in LOCAL:
            log.write(json.dumps([ev, repr(a), 'refused']) + '\n')
            raise ConnectionRefusedError('hostmacro.sh: no connect to %r' % (a,))
    elif ev in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex'):
        host = args[0]
        if isinstance(host, bytes):
            host = host.decode()
        if host not in LOCAL and not str(host).startswith('127.'):
            log.write(json.dumps([ev, host, 'refused']) + '\n')
            raise OSError('hostmacro.sh: no lookup of %r' % (host,))
sys.addaudithook(hook)
def _open(self, host, port=0, *a, **k):          # telnetlib stubbed: record the host, connect nothing
    log.write(json.dumps(['telnet.open', host, str(port)]) + '\n')
    raise ConnectionRefusedError('telnetlib stub: not contacted')
telnetlib.Telnet.open = _open
sys.argv = ['daq_webgui'] + sys.argv[2:]
runpy.run_module('psdaq.webgui.server', run_name='__main__')
PY
echo "tree $TREE at $(git -C $TREE rev-parse --short HEAD 2>/dev/null || cat $TREE/COMMIT 2>/dev/null)"
echo "  .cnf: $(grep HOST $O/p.cnf)"
cd $O && PYTHONPATH=$TREE/psdaq${PYTHONPATH:+:$PYTHONPATH} timeout -k 2 12 python $O/stub.py $O/net.jsonl --emulate --port 0 --procstat-cnf $O/p.cnf --procstat-interval 0.5 > $O/out.log 2> $O/err.log
rc=$?
echo "  daq_webgui exit $rc$([ $rc = 124 ] && echo ' (still serving after 12 s: stopped by timeout)')"
grep -h -E "HOST|refus|listening on" $O/out.log $O/err.log | grep -v Warning | sed 's/^/  says: /' | cut -c1-150 | head -4
echo "  telnet opens / lookups / connects recorded: $(wc -l < $O/net.jsonl 2>/dev/null || echo 0)"
[ -s $O/net.jsonl ] && sort $O/net.jsonl | uniq -c | sed 's/^/   /' | cut -c1-150 | head -6
