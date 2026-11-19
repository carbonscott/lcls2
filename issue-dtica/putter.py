"""Post new values to the DTI PVs that dtica displays, once a second, the way the hardware DTI server does
(psdaq/psdaq/dti/dtiPVs.cc:75,125 -> PVStats::update, PVStats.cc:147-180).  Generic p4p client: puts go to
upstream dticas (psdaq.epicstools.PVAServer accepts puts and re-posts them).

usage: python putter.py PREFIX        (PREFIX as given to dticas -P)
"""
import itertools, sys, time
from p4p.client.thread import Context

pfx = sys.argv[1]
INT7 = ['UsWrFifoD', 'UsRdFifoD', 'dUsIbEvt', 'UsObSent', 'UsObRecv', 'dUsRxInh', 'dUsRxErrs', 'dDsRxErrs',
        'UsRxErrs', 'UsRxFull', 'UsRxInh', 'dUsWrFifoD', 'dUsRdFifoD', 'UsIbEvt', 'DsRxErrs', 'DsRxFull', 'DsObSent']
FLT7 = ['dUsRxFull', 'dDsRxFull', 'dDsObSent']
ctx = Context('pva')
for n in itertools.count():
    names, vals = [], []
    for s in range(3, 8):
        p = f'{pfx}:{s}:'
        names += [p + a for a in INT7]; vals += [[n * (i + 1) + s for i in range(7)] for _ in INT7]
        names += [p + a for a in FLT7]; vals += [[0.5 * n + i + s for i in range(7)] for _ in FLT7]
        names += [p + 'MonClkRate']; vals += [[156250000 + n % 7, 185714000, 0, 0]]
        names += [p + a for a in ('BpLinkUp', 'UsLinkUp', 'DsLinkUp', 'QpllLock', 'TimLinkUp')]
        vals += [1, (n % 2) and 0x7f or 0x3f, 0x7f, 3, 1]
        names += [p + 'TimRefClk', p + 'TimFrRate']; vals += [185714285.0 + n % 3, 928571.0 + n % 5]
    t0 = time.time()
    try:
        ctx.put(names, vals, timeout=5.0)
    except Exception as e:
        print(time.strftime('%H:%M:%S'), 'put failed:', repr(e)[:200], flush=True)
    if n % 60 == 0:
        print(time.strftime('%H:%M:%S'), f'round {n}: {len(names)} PVs posted in {time.time() - t0:.2f}s', flush=True)
    time.sleep(max(0.0, 1.0 - (time.time() - t0)))
