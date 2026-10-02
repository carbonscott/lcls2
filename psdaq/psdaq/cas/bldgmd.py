"""PVA server hosting address, port and payload-description PVs for the 'GMD' and 'XGMD' BLD sources."""
import sys
import logging
import struct
import socket

from p4p.nt import NTScalar
from p4p.server import Server, StaticProvider
from p4p.server.thread import SharedPV
from p4p import Value, Type

import argparse

prefix = ''
pvdb = {}     # start with empty dictionary


class DefaultPVHandler(object):
    """p4p put handler that posts the written value with a new timestamp."""
    type = None

    def __init__(self, parent):
        self.parent = parent

    def put(self, pv, op):
        """Post the written value with the current time as timestamp and complete the operation.

        The code calls `time.time()`, but `time` is not imported in this module, so a put raises NameError.
        """
        postedval = op.value()
        postedval['timeStamp.secondsPastEpoch'], postedval['timeStamp.nanoseconds'] = divmod(float(time.time()), 1.0)
        pv.post(postedval)
        op.done()

class PVAServer(object):
    """StaticProvider holding the BLD source PVs; the constructor adds 'GMD' (239.255.25.2:10148) and 'XGMD' (239.255.25.3:10148)."""
    def __init__(self, provider_name):
        self.provider = StaticProvider(provider_name)
        self.prefix = prefix
        self.pvs = {}

        self.addSource('GMD' , '239.255.25.2', 10148, [ ('milliJoulesPerPulse', 'f'), ('RMS_E1', 'f') ])
        self.addSource('XGMD', '239.255.25.3', 10148, [ ('milliJoulesPerPulse', 'f'), ('POSY', 'f'), ('RMS_E1', 'f'), ('RMS_E2', 'f') ])

    def addSource(self, name, addr, port, ntypes):
        """Add 'DAQ:SRCF:<name>:ADDR', ':PORT' and ':PAYLOAD' PVs for one source.

        ADDR holds `addr` converted to an int (``inet_aton``, struct 'I', ``ntohl``; also
        printed in hex), PORT holds `port`, and PAYLOAD is a structure with one field per
        (name, type) in `ntypes`, all initialized to 0.
        """
        ia = socket.inet_aton(addr)
        ha = struct.unpack('I',ia)[0]
        iaddr = socket.ntohl(ha)
        print('addr [{:x}]'.format(iaddr))

        addrpv = SharedPV(initial=NTScalar('I').wrap({'value' : iaddr}),
                      handler=DefaultPVHandler(self))
        self.provider.add(f'DAQ:SRCF:{name}:ADDR',addrpv)

        portpv = SharedPV(initial=NTScalar('I').wrap({'value' : port}),
                      handler=DefaultPVHandler(self))
        self.provider.add(f'DAQ:SRCF:{name}:PORT',portpv)

        nid = '1'
        nvalues = { n[0]:0 for n in ntypes }
        pv = SharedPV(initial=Value(Type(ntypes,id=nid),nvalues), 
                      handler=DefaultPVHandler(self))
        self.provider.add(f'DAQ:SRCF:{name}:PAYLOAD',pv)
        self.pvs[name] = (addrpv, portpv, pv)

    def forever(self):
        """Serve the provider with `p4p.server.Server.forever` (blocks)."""
        Server.forever(providers=[self.provider])


def main():
    """Parse -v, create a `PVAServer` and serve forever until KeyboardInterrupt."""
    parser = argparse.ArgumentParser(prog=sys.argv[0], description='host PVs for GMD BLD')

    parser.add_argument('-v', '--verbose', action='store_true', help='be verbose')

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    server = PVAServer(__name__)

    try:
        # process PVA transactions
        server.forever()
    except KeyboardInterrupt:
        print('\nInterrupted')

