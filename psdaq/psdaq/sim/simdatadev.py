"""simdatadev: simulated DAQ nodes for datadev_monitor, so its checks run with no DAQ node and no ssh.

--root DIR makes one directory tree per node name under DIR (default: datadev_monitor's own drp-srcf-cmp001..080)
holding what datadev_monitor's CHECK_SCRIPT looks at: proc/datadev_<n> entries, usr/local/sbin/datadev.ko and
etc/systemd/system/datadev.service (with or without cfgRxCount, with an ExecStart line), different from node to node
by a fixed pattern; some nodes are 'unreachable'.  It writes DIR/simdatadev.json (the nodes and what each has, the
ground truth a test reads, and this process's pid), prints a 'ready' line and stays up until terminated.

--target DIR HOST runs a CHECK_SCRIPT read from stdin for node HOST as `ssh HOST bash -s` would on that node, with the
script's absolute paths (/proc/datadev_*, /usr/local/sbin/datadev.ko, /etc/systemd/system/datadev.service) read
under DIR/HOST instead; an unreachable node prints ssh's timeout message on stderr and exits 255; a name that is not
one of DIR's nodes is refused.  Nothing here opens a network connection.

    python -m psdaq.sim.simdatadev --root /tmp/datadev-sim
    echo "$CHECK_SCRIPT" | python -m psdaq.sim.simdatadev --target /tmp/datadev-sim drp-srcf-cmp007
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time

PATHS = (('/proc/datadev_', 'proc/datadev_'), ('/usr/local/sbin/datadev.ko', 'usr/local/sbin/datadev.ko'),
         ('/etc/systemd/system/datadev.service', 'etc/systemd/system/datadev.service'))
MARKER = 'simdatadev.json'


def default_nodes():
    from psdaq.cas import datadev_monitor as D            # the program's own node list
    return ['%s%03d' % (D.NODE_PREFIX, i) for i in D.NODE_RANGE]


def node_state(i):
    """What node number i (0-based) has: a fixed pattern over the nodes."""
    if i % 13 == 12:
        return {'reachable': False}
    st = {'reachable': True, 'proc': ['datadev_%d' % k for k in range(i % 3)], 'ko': i % 5 != 4,
          'svc': i % 7 != 6}
    st['cfg'] = st['svc'] and i % 2 == 0
    st['exec'] = ('ExecStart=/sbin/insmod /usr/local/sbin/datadev.ko cfgSize=0x%x%s' % (
        0x80000 + 0x1000 * i, ' cfgRxCount=%d' % (64 + i) if st['cfg'] else '')) if st['svc'] else None
    return st


def make_root(root, nodes):
    os.makedirs(root, exist_ok=True)
    truth = {}
    for i, h in enumerate(nodes):
        st = node_state(i)
        truth[h] = st
        d = os.path.join(root, h)
        for sub in ('proc', 'usr/local/sbin', 'etc/systemd/system'):
            os.makedirs(os.path.join(d, sub), exist_ok=True)
        if not st['reachable']:
            continue
        for p in st['proc']:
            open(os.path.join(d, 'proc', p), 'w').close()
        if st['ko']:
            with open(os.path.join(d, 'usr/local/sbin/datadev.ko'), 'w') as f:
                f.write('simdatadev: not a kernel module\n')
        if st['svc']:
            with open(os.path.join(d, 'etc/systemd/system/datadev.service'), 'w') as f:
                f.write('[Unit]\nDescription=datadev (simdatadev)\n[Service]\nType=oneshot\n%s\n' % st['exec'])
    with open(os.path.join(root, MARKER), 'w') as f:
        json.dump({'nodes': nodes, 'truth': truth, 'pid': os.getpid(), 'root': os.path.abspath(root)}, f, indent=1)
    return truth


def run_target(root, host, script):
    """(returncode, stdout, stderr) of the check script on simulated node `host` (as `ssh host bash -s`)."""
    with open(os.path.join(root, MARKER)) as f:
        m = json.load(f)
    if host not in m['nodes'] or not re.fullmatch(r'[A-Za-z0-9._-]+', host):
        return 255, '', 'simdatadev: %s is not a simulated node of %s\n' % (host, root)
    if not m['truth'][host]['reachable']:
        return 255, '', 'ssh: connect to host %s port 22: Connection timed out\n' % host
    d = os.path.join(m['root'], host)
    for absolute, rel in PATHS:
        script = script.replace(absolute, os.path.join(d, rel))
    p = subprocess.run(['bash', '-s'], input=script, capture_output=True, text=True, timeout=20,
                       env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    out = p.stdout.replace(d + '/proc/', '/proc/')           # ls prints the node's own paths
    return p.returncode, out, p.stderr


def main():
    ap = argparse.ArgumentParser(description='simulated DAQ nodes for datadev_monitor (no ssh, no network)')
    ap.add_argument('--root', help='make the simulated nodes under this dir and stay up')
    ap.add_argument('--nodes', nargs='*', help='node names (default: datadev_monitor\'s drp-srcf-cmp001..080)')
    ap.add_argument('--target', nargs=2, metavar=('ROOT', 'HOST'), help='run the check script on stdin for HOST')
    a = ap.parse_args()
    if a.target:
        rc, out, err = run_target(a.target[0], a.target[1], sys.stdin.read())
        sys.stdout.write(out)
        sys.stderr.write(err)
        return rc
    if not a.root:
        ap.error('give --root or --target')
    nodes = a.nodes or default_nodes()
    truth = make_root(a.root, nodes)
    print('simdatadev: ready, %d nodes (%d reachable) under %s, pid %d' % (
        len(nodes), sum(t['reachable'] for t in truth.values()), a.root, os.getpid()), flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        time.sleep(3600)


if __name__ == '__main__':
    sys.exit(main())
