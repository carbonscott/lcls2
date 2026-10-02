#!/usr/bin/env python

"""Serve KCU QSFP0 monitoring values (and TDetSemi counters unless --hsd) as a PVA NTTable PV.

Run as a script; see `main` for the arguments.
"""
import sys
import pyrogue as pr
import argparse
import socket
import time
import logging

from p4p.nt import NTTable
from p4p.server.thread import SharedPV
from p4p.server import Server, StaticProvider

from .Top import *

provider = None

class DefaultPVHandler(object):

    """SharedPV handler whose `put` posts the written value with the current time."""
    def __init__(self):
        pass

    def put(self, pv, op):
        """Post the value of PUT operation `op` to `pv` with a timestamp from ``time.time_ns()`` and call ``op.done()``.

        Parameters
        ----------
        pv : p4p.server.thread.SharedPV
            PV being written.
        op : p4p server operation
            PUT operation whose value is posted.
        """
        postedval = op.value()
        postedval['timeStamp.secondsPastEpoch'], postedval['timeStamp.nanoseconds'] = divmod(float(time.time_ns()), 1.0e9)
        pv.post(postedval)
        op.done()

def toTable(t):
    """Build the NTTable column list from a definition dict ``{name: (type, values)}``.

    Returns
    -------
    tuple
        ``(columns, n)``: `columns` is a list of ``(name, type[1:])`` (e.g. 'af' becomes 'f') and
        `n` is the length of the values list of the last entry. An empty `t` raises
        UnboundLocalError because `n` is never set.
    """
    table = []
    for v in t.items():
        table.append((v[0],v[1][0][1:]))
        n = len(v[1][1])
    return table,n

def toDict(t):
    """Return ``{name: values}`` from a definition dict ``{name: (type, values)}`` (the value lists are shared, not copied)."""
    d = {}
    for v in t.items():
        d[v[0]] = v[1][1]
    return d

def toDictList(t,n):
    """Return a list of `n` row dicts, row ``i`` being ``{name: values[i]}`` for each entry of the definition dict `t`."""
    l = []
    for i in range(n):
        d = {}
        for v in t.items():
            d[v[0]] = v[1][1][i]
        l.append(d)
    return l

def addPVT(name,t):
    """Create an NTTable SharedPV from definition dict `t`, add it to the module-level `provider` under `name`, and return it.

    `provider` must already be set (``main`` sets it); the PV uses `DefaultPVHandler`.
    """
    table,n = toTable(t)
    init    = toDictList(t,n)
    pv = SharedPV(initial=NTTable(table).wrap(init),
                  handler=DefaultPVHandler())
    provider.add(name,pv)
    return pv

pvdef = {'RxPwr'  : ('af',[0]*4),
         'TxBiasI': ('af',[0]*4),
         'FullTT' : ('ai',[0]*4),
         'nFullTT': ('ai',[0]*4)}


class PVStats(object):

    """Publish the 'RxPwr', 'TxBiasI', 'FullTT' and 'nFullTT' columns (four rows each) of a `Top` device in the NTTable PV '<name>:MON'.

    Parameters
    ----------
    name : str
        PV name prefix; ':MON' is appended.
    kcu : Top
        Device tree read by `update`.
    hsd : bool, optional
        If True, `update` does not read 'FullTT'/'nFullTT'. Default False.
    """
    def __init__(self, name, kcu, hsd=False):
        self.kcu   = kcu
        self.pv    = addPVT(name+':MON',pvdef)
        self.value = toDict(pvdef)
        self.hsd   = hsd

    def init(self):
        """Does nothing (stub)."""
        pass

    def update(self):
        """Read QSFP0 values from the device and post them to the PV with the current time.

        Selects 'QSFP0' on the I2C bus, stores ``getRxPwr()`` and ``getTxBiasI()`` in 'RxPwr' and 'TxBiasI',
        and, unless `hsd` is set, stores the pairs from ``TDetSemi.getRTT()`` in 'FullTT' and 'nFullTT'.
        """
        self.kcu.I2cBus.selectDevice('QSFP0')
        v = self.kcu.I2cBus.QSFP0.getRxPwr()
        for i in range(len(v)):
            self.value['RxPwr'][i] = v[i]
        v = self.kcu.I2cBus.QSFP0.getTxBiasI()
        for i in range(len(v)):
            self.value['TxBiasI'][i] = v[i]
        if self.hsd:
            pass
        else:
            v = self.kcu.TDetSemi.getRTT()
            for i in range(len(v)):
                self.value['FullTT' ][i] = v[i][0]
                self.value['nFullTT'][i] = v[i][1]

        value = self.pv.current()
        value['value'] = self.value
        value['timeStamp.secondsPastEpoch'], value['timeStamp.nanoseconds'] = divmod(float(time.time_ns()), 1.0e9)
        self.pv.post(value)

def main():
    """Start the KCU monitor: open the device, print diagnostics, then post PV updates forever.

    Arguments: -P PREFIX (required), -i/--interval seconds (default 10), -H/--hsd and -d/--dev
    (default '/dev/datadev_0'). The PV name is '<PREFIX>:<HOSTNAME>:MON', with the host name upper-cased
    and '-' replaced by '_'; `PVStats.update` is called every interval until KeyboardInterrupt.
    """
    global pvdb
    pvdb = {}     # start with empty dictionary
    global prefix
    prefix = ''
    global provider

    parser = argparse.ArgumentParser(prog=sys.argv[0], description='host PVs for KCU')
    parser.add_argument('-P', required=True, help='e.g. DAQ:LAB2', metavar='PREFIX')
    parser.add_argument('-i','--interval',type=int ,help='PV update interval',default=10)
    parser.add_argument('-H','--hsd'     ,action='store_true',help='HSD node',default=False)
    parser.add_argument('-d','--dev'     ,type=str, default='/dev/datadev_0')
    args = parser.parse_args()

    # Set base
    base = pr.Root(name='KCUr',description='')

    coreMap = rogue.hardware.axi.AxiMemMap(args.dev)

    base.add(Top(memBase = coreMap))

    # Start the system
    base.start(
#        pollEn   = False,
#        initRead = False,
#        zmqPort  = None,
    )

    kcu = base.KCU

    if args.hsd:
        kcu.I2cBus.selectDevice('QSFP0')
        print(kcu.I2cBus.QSFP0.getRxPwr())
        print('I2cMux: {:x}'.format(kcu.I2cBus.select.get()))
        print('RxPwrBlk: {:x}'.format(kcu.I2cBus.QSFP0.RxPwrBlock.get()))
        print('page: {:x}'.format(kcu.I2cBus.QSFP0.page.get()))
        print('BaseId: {:x}'.format(kcu.I2cBus.QSFP0.BaseIdBlock.get()))
        print('DiagnType: {:x}'.format(kcu.I2cBus.QSFP0.DiagnType.get()))
        print('DateBlock: {:x}'.format(kcu.I2cBus.QSFP0.DateBlock.get()))
        print(kcu.I2cBus.QSFP0.getDate())
    else:
        print('ClkRates: ', kcu.TDetTiming.getClkRates())
        print('RTT: ', kcu.TDetSemi.getRTT())

    provider = StaticProvider(__name__)

    pvstats = PVStats(args.P+':'+socket.gethostname().replace('-','_').upper(),kcu,args.hsd)

    # process PVA transactions
    updatePeriod = args.interval
    with Server(providers=[provider]):
        try:
            pvstats.init()
            while True:
                prev = time.perf_counter()
                pvstats.update()
                curr  = time.perf_counter()
                delta = prev+updatePeriod-curr
#                print('Delta {:.2f}  Update {:.2f}  curr {:.2f}  prev {:.2f}'.format(delta,curr-prev,curr,prev))
                if delta>0:
                    time.sleep(delta)
        except KeyboardInterrupt:
            pass

if __name__ == '__main__':
    main()
