#!/usr/bin/env python3
"""Write redo/steps/pr42-tunnel.json: the web GUI through a two-hop tunnel, driven by headless Chromium from the VM."""
import json, sys
NAME = sys.argv[1] if len(sys.argv) > 1 else 'web1'
Q = '/sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/work/proof15'
steps = []
def s(send, expect=None, timeout=None, **kw):
    d = {'send': send}
    if expect: d['expect'] = expect
    if timeout: d['timeout'] = timeout
    d.update(kw); steps.append(d)
s('date -Is; hostname   # this machine: the exe.dev VM')
s("echo \"listening on 31053 on this VM: $(ss -ltn | grep -c ':31053 ')\"")
s(f"ssh sdfiana025 'cd {Q}/../../wt-final; git log -1 --format=\"%H %ad %s\" --date=iso | cut -c1-138; echo \"local changes: $(git status --short | wc -l)\"; date -u +%FT%TZ'")
s(f'ssh sdfiana025 {Q}/web15_up.sh {NAME}   # one Slurm step on sdfada011 (job 44016690), under its node lock: a fresh CPU DAQ and the web GUI',
  expect=r'SESSION_UP|SESSION_DONE|exists', timeout=1800, fail=r'SESSION_DONE|exists')
s("ssh sdfiana025 'mkdir -p -m 700 /tmp/cwang31-p42'")
s("# sdfiana025's ~/.ssh/known_hosts holds an older ECDSA key of sdfada011, and ssh turns port forwarding off for a changed key. The inner hop")
s("# checks the node's keys as the node itself reports them (read in a Slurm step on it), in a private file, StrictHostKeyChecking=yes")
s("ssh sdfiana025 'srun --jobid=44016690 --overlap -w sdfada011 -N 1 --ntasks=1 --cpus-per-task=1 --mem=1G cat /etc/ssh/ssh_host_ecdsa_key.pub /etc/ssh/ssh_host_ed25519_key.pub < /dev/null | sed \"s/^/sdfada011 /\" > /tmp/cwang31-p42/known_hosts; ssh-keygen -lf /tmp/cwang31-p42/known_hosts'", timeout=120)
s("ssh -f -S none -L 31053:/tmp/cwang31-p42/webgui.sock sdfiana025 'ssh -N -o StreamLocalBindUnlink=yes -o UserKnownHostsFile=/tmp/cwang31-p42/known_hosts -o StrictHostKeyChecking=yes -L /tmp/cwang31-p42/webgui.sock:127.0.0.1:31053 sdfada011'", timeout=60)
s('sleep 3; curl -s -o /dev/null -w "GET http://127.0.0.1:31053/ on this VM -> HTTP %{http_code}\\n" http://127.0.0.1:31053/')
s(f'./pwvenv/bin/python tunnel_drive.py http://127.0.0.1:31053/ rec/pr42-web --events 1100', expect=r'PAGE_EVENTS_FINAL=|Traceback', timeout=900, fail=r'Traceback|ALL_STATES_OK=False')
s(f'ssh sdfiana025 {Q}/web15_down.sh {NAME}   # on the node: simxpm\'s counters (daq_sim status), then daq_sim down; the up step ends', expect=r'SESSION_DONE|no session', timeout=600, always=True)
s("pkill -f '^ssh .*-L 31053:/tmp/cwang31-p42'; ssh sdfiana025 \"pkill -u \\$USER -f '^ssh -N .*cwang31-p42/webgui.sock'\"; pgrep -af '^ssh .*-L 31053:' || echo 'tunnel closed (both hops)'", always=True)
s('ls rec/pr42-web/; cat rec/pr42-web/result.json', always=True)
out = '/home/exedev/projects/lcls2/redo/steps/pr42-tunnel.json'
json.dump(steps, open(out, 'w'), indent=1); print(f'{len(steps)} steps -> {out}')
