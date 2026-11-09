"""simtpr: a software TPR (timing pattern receiver) PV server, so tprca runs with no timing hardware.

It serves, under one prefix, the PVs psdaq/psdaq/cas/tprcas.py serves (the soft TPR IOC xcs.cnf starts beside
tprca): the input PVs ACCSEL, LINKSTATE, LINKLATCH, RXERRS, RXPOL, FRAMERATE, RXCLKRATE, IRQENA, EVTCNT and, for
channels CH0..CH13, MODE, DSTSEL, DESTNS, RSEL, FRATE, ARATE, ATS, SEQIDX, SEQBIT, XPART, BSTART, BWIDTH, RATE, plus
DELAY, WIDTH and POL for CH0..CH11 (tprcas serves none of these three for CH12 and CH13), with tprcas's types and
initial values; and the names tprioc (psdaq/psdaq/app/tprca.cc, the C++ TPR IOC xcs.cnf also starts) adds to those:
DELAY, WIDTH and POL for CH12 and CH13, RXERRSCL, VSNERR, FRAMEVSN and TXCLKRATE.  Writes are stored, as in tprcas.  Unlike tprcas, the link is up (LINKSTATE 1) and, once a second,
FRAMERATE / RXCLKRATE / TXCLKRATE / EVTCNT post a locked LCLS-II timing link (928571.4 Hz frames, 185.7 MHz, EVTCNT += frames)
and each enabled channel's RATE the frame rate of its fixed-rate selection (MODE != 0, RSEL 0: FRATE index into
psdaq.configdb.tsdef.fixedRates).  <prefix>:SIM:PID is this process's pid (simtpr only: a client can tell the
simulator from a TPR).

The PVA server binds the loopback interface unless told otherwise (--bind, --allow-remote), like simxpm.

    python -m psdaq.sim.simtpr -P DAQ:SIM:TPR [--bind 127.0.0.1]
"""

import argparse
import logging
import os
import threading
import time

from p4p.nt import NTScalar
from p4p.server import Server, StaticProvider
from p4p.server.thread import SharedPV

FRAME_RATE = 1300e6 / 1400.                 # LCLS-II timing frames [Hz] (929 kHz)
RXCLK_MHZ = 185.71
NCHAN = 14
NTRIG = 12                                  # channels with DELAY / WIDTH / POL in tprcas


def tprcas_pvdb():
    """{suffix: (type, initial)} as tprcas.main builds pvdb ('int' -> 'i', 'float' -> 'd' as epicstools.PVAServer)."""
    db = {':ACCSEL': ('i', 0), ':LINKSTATE': ('i', 0), ':LINKLATCH': ('i', 0), ':RXERRS': ('i', 0), ':RXPOL': ('i', 0),
          ':FRAMERATE': ('d', 0.), ':RXCLKRATE': ('d', 0.), ':IRQENA': ('i', 0), ':EVTCNT': ('i', 0)}
    for i in range(NCHAN):
        p = ':CH%u' % i
        if i < NTRIG:
            db.update({p + ':DELAY': ('d', 0.), p + ':WIDTH': ('d', 5.4e-9), p + ':POL': ('i', 0)})
        db.update({p + ':MODE': ('i', 0), p + ':DSTSEL': ('i', 0), p + ':DESTNS': ('i', 0), p + ':RSEL': ('i', 0),
                   p + ':FRATE': ('i', 0), p + ':ARATE': ('i', 0), p + ':ATS': ('i', 1), p + ':SEQIDX': ('i', 0),
                   p + ':SEQBIT': ('i', 0), p + ':XPART': ('i', 0), p + ':BSTART': ('i', 0), p + ':BWIDTH': ('i', 1),
                   p + ':RATE': ('d', 0.)})
    return db


def tprioc_extra():
    """{suffix: (type, initial)} of the PVs tprioc names that tprcas does not serve (tprca.cc: TprControl's
    RXERRSCL, VSNERR, FRAMEVSN, TXCLKRATE; ChannelControl's DELAY, WIDTH, POL for every channel)."""
    db = {':RXERRSCL': ('i', 0), ':VSNERR': ('i', 0), ':FRAMEVSN': ('i', 0), ':TXCLKRATE': ('d', 0.)}
    for i in range(NTRIG, NCHAN):
        p = ':CH%u' % i
        db.update({p + ':DELAY': ('d', 0.), p + ':WIDTH': ('d', 5.4e-9), p + ':POL': ('i', 0)})
    return db


class _Store:
    def __init__(self, sim, name):
        self.sim, self.name = sim, name

    def put(self, pv, op):
        v = op.value()
        v['timeStamp.secondsPastEpoch'], v['timeStamp.nanoseconds'] = divmod(time.time_ns(), 1000000000)
        pv.post(v)
        with self.sim.lock:
            self.sim.values[self.name] = v['value']
        op.done()


class SimTpr:
    def __init__(self, prefix):
        self.prefix = prefix
        self.provider = StaticProvider('simtpr')
        self.pvs, self.values = {}, {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        for suffix, (t, v) in dict(tprcas_pvdb(), **tprioc_extra()).items():
            self._add(prefix + suffix, t, v)
        self._add(prefix + ':SIM:PID', 'i', os.getpid())

    def _add(self, name, t, v):
        nt = NTScalar(t)
        pv = SharedPV(initial=nt.wrap(v, timestamp=time.time()), handler=_Store(self, name))
        self.provider.add(name, pv)
        self.pvs[name] = (pv, nt)
        self.values[name] = v

    def post(self, name, v):
        pv, nt = self.pvs[name]
        pv.post(nt.wrap(v, timestamp=time.time()))
        with self.lock:
            self.values[name] = v

    def run(self):
        from psdaq.configdb.tsdef import fixedRates
        hz = {i: _rate_hz(r) for i, r in enumerate(fixedRates)}
        P = self.prefix
        self.post(P + ':LINKSTATE', 1)
        evt = 0
        while not self.stop.wait(1.0):
            evt += int(FRAME_RATE)
            self.post(P + ':FRAMERATE', round(FRAME_RATE, 1))
            self.post(P + ':RXCLKRATE', RXCLK_MHZ)
            self.post(P + ':TXCLKRATE', RXCLK_MHZ)
            self.post(P + ':EVTCNT', evt & 0x7fffffff)
            for i in range(NCHAN):
                c = '%s:CH%u' % (P, i)
                with self.lock:
                    mode, rsel, frate = self.values[c + ':MODE'], self.values[c + ':RSEL'], self.values[c + ':FRATE']
                rate = float(hz.get(frate, 0.)) if mode and rsel == 0 else 0.
                if rate != self.values[c + ':RATE']:
                    self.post(c + ':RATE', rate)


def _rate_hz(label):
    """'929kHz' -> 929000.0, '1Hz' -> 1.0 (tsdef.fixedRates labels)."""
    s = label.strip()
    for unit, f in (('MHz', 1e6), ('kHz', 1e3), ('Hz', 1.)):
        if s.endswith(unit):
            try:
                return float(s[:-len(unit)]) * f
            except ValueError:
                return 0.
    return 0.


def main():
    ap = argparse.ArgumentParser(description='software TPR PV server (the PVs of cas/tprcas.py) for tprca')
    ap.add_argument('-P', required=True, metavar='PREFIX', help='PV prefix, as tprcas -P (e.g. DAQ:SIM:TPR)')
    ap.add_argument('--bind', default='127.0.0.1', help='PVA server interface (default %(default)s)')
    ap.add_argument('--allow-remote', action='store_true', help='allow a non-loopback --bind')
    ap.add_argument('-v', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format='%(asctime)s simtpr %(levelname)s %(message)s')
    if a.bind not in ('127.0.0.1', 'localhost') and not a.allow_remote:
        raise SystemExit('simtpr: --bind %s is not loopback; use --allow-remote to mean it' % a.bind)
    conf = {'EPICS_PVAS_INTF_ADDR_LIST': a.bind, 'EPICS_PVAS_BEACON_ADDR_LIST': a.bind,
            'EPICS_PVAS_AUTO_BEACON_ADDR_LIST': 'NO'}
    for key in ('SERVER_PORT', 'BROADCAST_PORT'):
        v = os.environ.get('EPICS_PVAS_%s' % key, os.environ.get('EPICS_PVA_%s' % key))
        if v:
            conf['EPICS_PVAS_%s' % key] = v
    sim = SimTpr(a.P)
    with Server(providers=[sim.provider], conf=conf, useenv=False) as server:
        logging.info('serving %d PVs under %s; server conf %s', len(sim.pvs), a.P, server.conf())
        print('simtpr: ready, %d PVs under %s, pid %d' % (len(sim.pvs), a.P, os.getpid()), flush=True)
        try:
            sim.run()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
