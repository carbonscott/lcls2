"""guard_lines.py WALKS: what the walk guard (qt_walk.guard_subprocess) refused in the datadev_monitor and daqstat walks
that check_gui_parity --run-walks just ran (WALKS/runs/<name>-<k>/walk.json)."""
import collections, glob, json, os, sys
for name in ('datadev_monitor', 'daqstat'):
    for p in sorted(glob.glob(os.path.join(sys.argv[1], 'runs', name + '-*', 'walk.json'))):
        d = json.load(open(p))
        calls = d.get('calls', [])
        ref = [c['args'][0] for c in calls if c.get('opener') == 'refused:subprocess']
        progs = collections.Counter(a.split()[0] for a in ref)
        print('%s: %d recorded calls, %d refused:subprocess %s, exit %s' % (
            os.path.basename(os.path.dirname(p)), len(calls), len(ref), dict(sorted(progs.items())), d.get('exit')))
        if progs.get('ssh'):
            hosts = sorted({a.split()[-3] for a in ref if a.startswith('ssh ')})
            print('    ssh to %d hosts, %s .. %s; e.g. %s' % (len(hosts), hosts[0], hosts[-1], ref[0][:120]))
        for prog in sorted(set(progs) - {'ssh'}):
            print('    e.g. %s' % next(a for a in ref if a.startswith(prog + ' '))[:110])
        other = collections.Counter(c.get('opener') for c in calls if c.get('opener') != 'refused:subprocess')
        if other:
            print('    other recorded calls (not subprocesses): %s' % dict(other))
