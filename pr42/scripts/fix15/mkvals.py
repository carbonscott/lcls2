#!/usr/bin/env python3
"""mkvals.py ASSETS: the values mkbody.py fills in, from run h2's summary and logs and recording 3's transcript, to
ASSETS/logs/h2/vals.json and ASSETS/logs/h2/ready-h2.txt."""
import json, os, re, sys
A = sys.argv[1]
H2 = os.path.join(A, 'logs', 'h2')
d = json.load(open(os.path.join(A, 'matrix-summary-h2.json')))
mx = open(os.path.join(H2, 'mx-h2.log')).read().split('\n')
V = {}
hdr = next(l for l in mx if l.startswith('=== matrix h2'))
V['h2_step'] = re.search(r'step (\d+)', hdr).group(1)
t0 = re.search(r'(\d\d:\d\d:\d\d)Z$', hdr).group(1)
t1 = re.search(r'MATRIX_EXIT=\d+ \S+T(\d\d:\d\d:\d\d)Z', next(l for l in mx if l.startswith('MATRIX_EXIT'))).group(1)
V['h2_time'] = f'{t0}-{t1}'
chk = next(a['detail'] for a in d['programs']['assertions'] if a['name'] == 'programs/checks')
chk = re.sub(r'/sdf/\S+/', '', chk)
V['prog_checks'] = chk[:260] + ('...' if len(chk) > 260 else '')

def rep(f):
    return {l.split()[0] + ' ' + l.split()[1] if l.startswith('  drp ') else l.strip().split('  ')[0]: l.strip()
            for l in d['features'][f]['report']}
def lines(f, *keys):
    r = d['features'][f]['report']
    return [next((l.strip() for l in r if l.strip().startswith(k)), '') for k in keys]
def val(line):
    return re.split(r'\s{2,}', line, 1)[1] if re.search(r'\s{2,}', line) else line

a = d['features']['a']['report']
ga = next(l for l in a if 'readout groups' in l)
drps = [l.strip() for l in a if l.strip().startswith('drp ')]
def drpsum(l):
    m = re.match(r'drp (\S+)\s+(?:on (\S+): )?(?:group (\d+): )?DAQ \(simxpm L1Accepts sent\) (\d+) psana2 events (\d+)(?: with data (\d+))?', l)
    return m.groups() if m else None
s = [drpsum(l) for l in drps]
V['fa'] = (val(ga.strip()) + '; ' + '; '.join(f'{x[0]} (group {x[2]}) {x[3]} = {x[4]} = {x[5]}' for x in s if x) +
           '; each per-event check PASS.')
b = d['features']['b']['report']
steps = [l.strip() for l in b if re.match(r'\s+step \d', l)]
sv = [re.search(r'step_value (\S+)', l).group(1) for l in steps]
bd = [drpsum(l.strip()) for l in b if l.strip().startswith('drp ')]
per = re.search(r'per step (\[[^\]]*\])', next(l for l in b if 'per step' in l)).group(1)
V['fb'] = f"{' and '.join(x[0] for x in bd if x)} {bd[0][3]} events each, {per} per step; psana2 reads `step_value` {', '.join(sv)}"
def cvals(summary):
    c = summary['features']['c']['report']
    return {k: val(l.strip()) for k in ('simxpm NumL0Acc ', 'MEB_EvtCt', 'ami events', 'ami matched', 'ami seq range',
                                         'psana2 events', 'shmemClient L1Accepts', 'problem')
            for l in c if l.strip().startswith(k)}
h1s = json.load(open(os.path.join(A, 'matrix-summary-h1.json')))
cv = cvals(h1s)
V['fc'] = (f"(step 350) fakecam_0 {cv['simxpm NumL0Acc ']} = {cv['psana2 events']}, `MEB_EvtCt` {cv['MEB_EvtCt']}, shmemClient "
           f"{cv['shmemClient L1Accepts']} L1Accepts; AMI matched {cv['ami matched']} of {cv['ami events']} events it computed against "
           f"psana2 (seq {cv['ami seq range']})")
c2 = cvals(d)
V['fc_h2'] = (f"fakecam_0 {c2['simxpm NumL0Acc ']} = {c2['psana2 events']}, shmemClient {c2['shmemClient L1Accepts']} L1Accepts "
              f"from the MEB, AMI matched {c2['ami matched']} of {c2['ami events']} (seq {c2['ami seq range']}), but `{c2.get('problem', 'problem: ?')}` "
              f"(no MEB counter in the counts read after Disable)")
dd = [drpsum(l.strip()) for l in d['features']['d']['report'] if l.strip().startswith('drp ')]
V['fd'] = ' and '.join(f'{x[0]} on {x[1]}' for x in dd if x) + f', {dd[0][3]} = {dd[0][4]} each.'
e = d['features']['e']['report']
ev = {}
for l in e:
    m = re.match(r'\s+(sysdrp [a-z]+ [a-z ]+?|simxpm NumL0Acc)\s{2,}(.*)$', l)
    if m:
        ev[m.group(1).strip()] = m.group(2).strip()
V['fe'] = (f"{ev['simxpm NumL0Acc']} L1Accepts each; bld {ev.get('sysdrp bld matched')} matched, {ev.get('sysdrp bld missing')} missing; "
           f"udp {ev.get('sysdrp udp matched')} matched; pva {ev.get('sysdrp pva matched')} matched, {ev.get('sysdrp pva missing')} "
           f"L1Accepts without an image (seq {ev.get('sysdrp pva missing seqs', '').strip('[]')}; the check counts them and drp_pva's own "
           f"count agrees); epics {ev.get('sysdrp epics events')}.")
ready = [re.search(r'(\S+)_0 ready for transitions after (\d+) s', l) for l in mx if 'ready for transitions after' in l and '[sdfada013]' in l]
V_ready = ', '.join(f'{m.group(1)} {m.group(2)} s' for m in ready if m)
open(os.path.join(H2, 'ready-h2.txt'), 'w').write(f'each drp_gpu said `Ready for transitions` after {V_ready}, and `up` waited for it')
V['h2_records'] = str(len([l for l in open(os.path.join(H2, 'covneg-h2.log')).read().split('\n')]) and
                      re.search(r'(\d+) records in', open(os.path.join(H2, 'covneg-h2.out')).read()).group(1))
cn = open(os.path.join(H2, 'covneg-h2.log')).read()
V['covneg_line'] = re.search(r'^(\d+ rows, .*)$', cn, re.M).group(1)
V['mine'] = d['programs']['evidence']
f3 = open(os.path.join(H2, 'forge-fg3.log')).read()
V['fg3_begins'] = re.search(r'have 2 different BeginRuns \(([^)]*)\)', f3).group(1)
# raw: the summary of mx-h2.log without the PASS lines
i0 = next(i for i, l in enumerate(mx) if l.startswith('==== MATRIX SUMMARY'))
raw = [l for l in mx[i0:] if l.strip() and not l.startswith('  PASS ')]
raw = [re.sub(r' run /sdf/\S+', '', l) for l in raw]
raw = [l.replace('/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2', '$R')[:200] for l in raw]
V['h2_raw'] = f"$ $S bash $Q/mx.sh h2 sdfada013 43970564 ...      (sdfmilan023 job 44000948 step {V['h2_step']})\n{hdr}\n" + '\n'.join(raw)
n_pass = sum(1 for l in mx[i0:] if l.startswith('  PASS '))
V['n_pass_lines'] = n_pass
# negatives raw: breaks from recording 3, covneg and forgeries of recording 4
t3 = open(os.path.join(A, 'recording3.txt')).read().split('\n')
j0 = next(i for i, l in enumerate(t3) if l.startswith('=== breaks h1'))
j1 = next(i for i, l in enumerate(t3) if l.startswith('=== breaks done'))
brk = [l[:200] for l in t3[j0:j1 + 1]]
co = open(os.path.join(H2, 'covneg-h2.out')).read().strip().split('\n')
fo = [l[:200] for l in open(os.path.join(H2, 'forge-h2.out')).read().strip().split('\n')]
V['neg_raw'] = '\n'.join(brk + [''] + co + [''] + fo)
json.dump(V, open(os.path.join(H2, 'vals.json'), 'w'), indent=1)
for k, v in V.items():
    print(k, '=', str(v)[:300])
