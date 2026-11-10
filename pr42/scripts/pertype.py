#!/usr/bin/env python3
"""pertype.py SUMMARY.json > table.md: the per-type table of a daq_sim matrix summary."""
import json, re, sys
d = json.load(open(sys.argv[1]))
# per-type check: what xtc2_check compared, from the RUNBOOK sections of each type (short)
CHECK = {
 'fakecam': 'payload words vs seed pattern', 'cspad': 'payload words vs seed pattern', 'hsd': 'every sample of waveforms() and every peak of peaks()',
 'epixquad': 'every pixel of raw (4,352,384)', 'epixquad1kfps': 'every pixel of raw', 'epixhr2x2': 'every pixel of raw',
 'epixhremu': 'every pixel of raw', 'epixm320': 'every pixel of raw', 'epixUHR': 'every pixel of raw', 'epix100': 'every pixel of raw',
 'jungfrau': 'every pixel of raw (1 module)', 'jungfrauemu': 'payload words', 'opal': 'every pixel of raw (1024,1024)', 'tt': 'every pixel of the ROI',
 'tb': 'every recorded timing field', 'ts': 'every recorded timing field', 'wave8': 'every sample of raw_0..', 'wave8he': 'every sample of raw_0..',
 'hrencoder': 'encoder value', 'piranha4': 'every pixel of raw (2048,)', 'epixuhr3x2': 'every pixel of raw',
}
print('| type | DRP | node | DAQ (simxpm L1Accepts) | TEB_WrtCt | psana2 events | with data | per-event check (`xtc2_check --det <type>`) | evidence record |')
print('|---|---|---|---|---|---|---|---|---|')
for k, t in d['types'].items():
    drp, typ = (k.split(':') + [None])[:2] if ':' in k else ('drp', k)
    if typ is None: typ = k
    teb = None
    for a in t.get('assertions', []):
        if a['name'].endswith('/counts'):
            m = re.search(r'TEB_WrtCt (\w+)', a['detail']); teb = m.group(1) if m else None
    ok = t.get('pass')
    pe = t.get('per_event')
    print(f"| {typ} | {drp} | {t['node']} | {t.get('daq')} | {teb} | {t.get('psana2')} | {t.get('with_data')} | {pe} | {t.get('evidence') or '-'} |")
p = d['programs']
teb = None
for a in p.get('assertions', []):
    if a['name'].endswith('/counts'):
        m = re.search(r'TEB_WrtCt (\w+)', a['detail']); teb = m.group(1) if m else None
print(f"| programs run: fakecam_0 with the MEB, AMI, system DRPs, GUIs, PV servers | drp | {p['node']} | {p.get('daq')} | {teb} | {p.get('psana2')} | {p.get('with_data')} | {p.get('per_event')} | {p.get('evidence') or '-'} |")
