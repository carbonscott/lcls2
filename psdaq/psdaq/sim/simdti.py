"""simdti: a software DTI (data trigger interface) PV server, so dtica runs with no DTI board.

It serves exactly the PVs psdaq/psdaq/cas/dticas.py (the soft DTI PV host) defines for the five slots 3-7 under a
prefix: dticas.main builds its PV table and hands it to epicstools.PVAServer.createPV, and simdti runs dticas.main with
a stand-in PVAServer that keeps that table, so the names, types and start values are dticas's.  Unlike dticas, simdti
also counts: once a second every statistics array (Us*, dUs*, Ds*, dDs*, UsLinkOb*, MonClk*) gets values that depend on
the slot, the PV and the element and advance with time, the link-up masks (BpLinkUp, UsLinkUp, DsLinkUp) and
QpllLock / TimLinkUp report a locked board, and the timing reference (TimRefClk 185.7 MHz, TimFrRate 928.6 kHz) and
MonClkRate are set.  UsLinkPartition<i> and UsLinkFwdMask<i> keep what a client puts (dtica's allocation checkboxes).
<prefix>:SIM:PID is this process's pid (simdti only: a client can tell the simulator from a DTI IOC).  The count n
the values advance with starts at a random second, so they differ from run to run, and every value it serves goes to
the served-value log when daq_sim names one (psdaq.sim.served_log: coverage checks the GUI witness's reads against it).

The PVA server binds the loopback interface unless told otherwise (--bind, --allow-remote), like simxpm.

    python -m psdaq.sim.simdti -P DAQ:SIM:DTI
"""

import argparse
import logging
import os
import random
import sys
import threading

from p4p.nt import NTScalar
from p4p.server import Server, StaticProvider
from p4p.server.thread import SharedPV

from psdaq.sim.served_log import ServedLog

STATIC = ('UsLinkPartition', 'UsLinkFwdMask', 'UsLinkTagEn', 'UsLinkL1En', 'UsLinkTrigDelay', 'UsLinkFwdMode',
          'UsLinkDataSrc', 'UsLinkDataType', 'UsLinkLabel', 'ModuleInit', 'CountClear', 'CountUpdate', 'BpTxInterval',
          'LinkId', 'UsLinkMsgDelay', 'PartMsgDelay')


def dticas_table(prefix):
    """(prefix + ':', {name: pcaspy-style definition}): the table dticas.main serves for `dticas -P prefix`."""
    from psdaq.cas import dticas
    got = {}

    class Keep:
        def __init__(self, name):
            pass

        def createPV(self, pfx, pvdb):
            got['prefix'], got['pvdb'] = pfx, dict(pvdb)

        def forever(self):
            pass
    argv, orig = sys.argv, dticas.PVAServer
    sys.argv, dticas.PVAServer = ['dticas', '-P', prefix], Keep
    try:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            dticas.main()
    finally:
        sys.argv, dticas.PVAServer = argv, orig
    return got['prefix'], got['pvdb']


class SimDti:
    def __init__(self, prefix):
        from psdaq.epicstools.PVAServer import PVAServer
        self.pfx, self.pvdb = dticas_table(prefix)
        self.server = PVAServer('simdti')
        self.server.createPV(self.pfx, self.pvdb)
        self.provider = self.server.provider
        self.pvs = dict(zip(self.pvdb, self.server.pvs))
        self.pid = SharedPV(initial=NTScalar('i').wrap(os.getpid()))
        self.provider.add(self.pfx + 'SIM:PID', self.pid)
        self.stop = threading.Event()
        self.served = ServedLog('simdti')
        for name, pv in self.pvs.items():
            try:
                self.served(self.pfx + name, pv.current())
            except Exception:
                pass                    # a PV opened without a value

    def _post(self, name, val):
        pv = self.pvs[name]
        v = pv.current()
        v['value'] = val
        pv.post(v)
        self.served(self.pfx + name, val)

    def tick(self, n):
        for k, name in enumerate(sorted(self.pvdb)):
            slot, _, base = name.partition(':')
            d = self.pvdb[name]
            if base in STATIC or base.startswith('UsLink') and base[-1].isdigit() and base.rstrip('0123456789') in STATIC:
                continue
            s = int(slot)
            cnt = d.get('count', 1)
            if base in ('BpLinkUp',):
                val = 1
            elif base in ('UsLinkUp', 'DsLinkUp'):
                val = (0x7f >> (s - 3)) & 0x7f                       # a slot-dependent set of links up
            elif base in ('QpllLock', 'TimLinkUp'):
                val = 1
            elif base == 'TimRefClk':
                val = 185.7e6 + s
            elif base == 'TimFrRate':
                val = 928571.4 + n
            elif base == 'MonClkRate':
                val = [156250000 + s * 1000 + j * 100 + n for j in range(cnt)]
            elif d['type'] == 'float':
                val = [(s * 100 + k + j) + 0.25 * (n % 4) for j in range(cnt)]
            else:
                val = [(s * 1000 + k * 10 + j + n) & 0xffffffff for j in range(cnt)]
            if cnt == 1 and isinstance(val, list):
                val = val[0]
            self._post(name, val)

    def run(self):
        n = random.randrange(100, 1000)        # a count of its own each run
        self.tick(n)
        while not self.stop.wait(1.0):
            n += 1
            self.tick(n)


def main():
    ap = argparse.ArgumentParser(description='software DTI PV server (the PVs of cas/dticas.py) for dtica')
    ap.add_argument('-P', required=True, metavar='PREFIX', help='PV prefix, as dticas -P (e.g. DAQ:SIM:DTI)')
    ap.add_argument('--bind', default='127.0.0.1', help='PVA server interface (default %(default)s)')
    ap.add_argument('--allow-remote', action='store_true', help='allow a non-loopback --bind')
    ap.add_argument('-v', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format='%(asctime)s simdti %(levelname)s %(message)s')
    if a.bind not in ('127.0.0.1', 'localhost') and not a.allow_remote:
        raise SystemExit('simdti: --bind %s is not loopback; use --allow-remote to mean it' % a.bind)
    conf = {'EPICS_PVAS_INTF_ADDR_LIST': a.bind, 'EPICS_PVAS_BEACON_ADDR_LIST': a.bind,
            'EPICS_PVAS_AUTO_BEACON_ADDR_LIST': 'NO'}
    for key in ('SERVER_PORT', 'BROADCAST_PORT'):
        v = os.environ.get('EPICS_PVAS_%s' % key, os.environ.get('EPICS_PVA_%s' % key))
        if v:
            conf['EPICS_PVAS_%s' % key] = v
    sim = SimDti(a.P)
    with Server(providers=[sim.provider], conf=conf, useenv=False) as server:
        logging.info('serving %d DTI PVs under %s; server conf %s', len(sim.pvdb), a.P, server.conf())
        print('simdti: ready, %d PVs under %s, pid %d' % (len(sim.pvdb), a.P, os.getpid()), flush=True)
        try:
            sim.run()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
