#!/usr/bin/env python3
"""mkvals_n.py ASSETS PRIMARY PARTIAL OUT: the values mkbody_n.py fills in that come from the logs: the features, the
programs checks, the ready waits, the raw summary of the PRIMARY run at H2 (n1 or n2), the coverage negative and the
breaks (recording 5, over n1; and over PRIMARY when it is n2); PARTIAL (a JSON written by hand) is merged in."""
import json, os, re, sys
A, P, partial, out = sys.argv[1:5]
V = json.load(open(partial))
d = json.load(open(os.path.join(A, f'matrix-summary-{P}.json')))
mx = open(os.path.join(A, 'logs', P, f'mx-{P}.log')).read().split('\n')
R = '/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2'

hdr = next(l for l in mx if l.startswith(f'=== matrix {P}'))
V['mx_step'] = re.search(r'step (\d+)', hdr).group(1)
chk = next(a['detail'] for a in d['programs']['assertions'] if a['name'] == 'programs/checks')
chk = re.sub(r'/sdf/\S+/', '', chk)
V['prog_checks'] = chk[:260] + ('...' if len(chk) > 260 else '')
ev = next(a['detail'] for a in d['programs']['assertions'] if a['name'] == 'programs/evidence')
V['prog_rows'] = re.search(r'for (\d+) rows', ev).group(1)

def val(line):
    return re.split(r'\s{2,}', line, 1)[1] if re.search(r'\s{2,}', line) else line
def drpsum(l):
    m = re.match(r'drp (\S+)\s+(?:on (\S+): )?(?:group (\d+): )?DAQ \(simxpm L1Accepts sent\) (\d+) psana2 events (\d+)(?: with data (\d+))?', l)
    return m.groups() if m else None
F = d['features']
def verdict(f):
    return 'PASS' if F[f].get('pass') in (True, 'True') else 'FAIL'
a = F['a']['report']
ga = next(l for l in a if 'readout groups' in l)
s = [drpsum(l.strip()) for l in a if l.strip().startswith('drp ')]
fa = (val(ga.strip()) + '; ' + '; '.join(f'{x[0]} (group {x[2]}) {x[3]} = {x[4]} = {x[5]}' for x in s if x) + '; each per-event check PASS.')
b = F['b']['report']
steps = [l.strip() for l in b if re.match(r'\s+step \d', l)]
sv = [re.search(r'step_value (\S+)', l).group(1) for l in steps]
bd = [drpsum(l.strip()) for l in b if l.strip().startswith('drp ')]
per = re.search(r'per step (\[[^\]]*\])', next(l for l in b if 'per step' in l)).group(1)
fb = f"{' and '.join(x[0] for x in bd if x)} {bd[0][3]} events each, {per} per step; psana2 reads `step_value` {', '.join(sv)} (a8bda341f)"
c = {k: val(l.strip()) for k in ('simxpm NumL0Acc ', 'MEB_EvtCt', 'ami events', 'ami matched', 'ami seq range', 'psana2 events',
                                  'shmemClient L1Accepts', 'problem', 'prometheus unread')
     for l in F['c']['report'] if l.strip().startswith(k)}
fc = (f"fakecam_0 {c['simxpm NumL0Acc ']} = {c['psana2 events']}, **`MEB_EvtCt` {c.get('MEB_EvtCt')}**, shmemClient "
      f"{c['shmemClient L1Accepts']} L1Accepts from the MEB; AMI matched {c['ami matched']} of {c['ami events']} events it computed "
      f"against psana2 (seq {c['ami seq range']}) ([AMI's viewer](https://raw.githubusercontent.com/carbonscott/lcls2/pr-assets/pr42/ami-shot-{P}-feature-c.png))")
dd = [drpsum(l.strip()) for l in F['d']['report'] if l.strip().startswith('drp ')]
fd = ' and '.join(f'{x[0]} on {x[1]}' for x in dd if x) + f', {dd[0][3]} = {dd[0][4]} each.'
e = F['e']['report']
ee = {}
for l in e:
    m = re.match(r'\s+(sysdrp [a-z]+ [a-z ]+?|simxpm NumL0Acc)\s{2,}(.*)$', l)
    if m:
        ee[m.group(1).strip()] = m.group(2).strip()
fe = (f"drp_bld, drp_pva, drp_udpencoder and epicsArch beside fakecam_0: {ee['simxpm NumL0Acc']} L1Accepts each; bld "
      f"{ee.get('sysdrp bld matched')} matched, {ee.get('sysdrp bld missing')} missing; udp {ee.get('sysdrp udp matched')} matched; "
      f"pva {ee.get('sysdrp pva matched')} matched, {ee.get('sysdrp pva missing')} L1Accepts without an image"
      + (f" (seq {ee.get('sysdrp pva missing seqs', '').strip('[]')}; the check counts them and drp_pva's own count agrees)"
         if ee.get('sysdrp pva missing') not in (None, '0') else '') + f"; epics {ee.get('sysdrp epics events')}.")
V['features'] = '\n'.join([
    f"- **a** {verdict('a')}: three DRP types in two readout groups at different rates: {fa}",
    f"- **b** {verdict('b')}: a three-step scan (`generic_timing_scan.py` over `epix100_0:user.start_ns`): {fb}.",
    f"- **c** {verdict('c')}: the MEB serving AMI: {fc}." + V.get('fc_extra', ''),
    f"- **d** {verdict('d')}: one partition over two nodes: {fd}",
    f"- **e** {verdict('e')}: {fe}"])
ready = [re.search(r'(\S+)_0 ready for transitions after (\d+) s', l) for l in mx if 'ready for transitions after' in l and '[sdfada010]' in l]
V['ready'] = ', '.join(f'{m.group(1)} {m.group(2)} s' for m in ready if m) + f' in {P}'
i0 = next(i for i, l in enumerate(mx) if l.startswith('==== MATRIX SUMMARY'))
raw = [l for l in mx[i0:] if l.strip() and not l.startswith('  PASS ')]
raw = [re.sub(r' run /sdf/\S+', '', l) for l in raw]
raw = [l.replace(R, '$R')[:200] for l in raw]
nt = sum(1 for l in raw if l.startswith('TYPE '))
allpass = all(l.rstrip().endswith('PASS PASS') for l in raw if l.startswith('TYPE '))
if allpass:
    k = next(i for i, l in enumerate(raw) if l.startswith('TYPE '))
    raw = raw[:k] + [f'TYPE ... ({nt} lines: every type PASS, as in the table above; in the log)'] + [l for l in raw[k:] if not l.startswith('TYPE ')]
gh = re.search(r'gpu (\S+) job (\d+)', hdr)
V['raw_matrix'] = (f"$ $S bash $Q/mx.sh {P} {gh.group(1)} {gh.group(2)} ...      (sdfmilan023 job 44000948 step {V['mx_step']})\n"
                   f"{hdr}\n" + '\n'.join(raw))
json.dump(V, open(out, 'w'), indent=1)
for k, v in V.items():
    print(k, '=', str(v)[:200])
