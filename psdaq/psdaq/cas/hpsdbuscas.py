#!/usr/bin/env python
"""
This implements a PVAccess server that defines the PVs for a HPS server diagnostic bus for conversion to BLD
Any change to the diagnostic bus description (field names, mask) results in an updated payload structure
"""
import sys
import logging
import time

from p4p.nt import NTScalar
from p4p.server import Server, StaticProvider
from p4p.server.thread import SharedPV
from p4p import Value, Type

logger = logging.getLogger(__name__)

class DefaultPVHandler(object):
    """p4p put handler that timestamps and posts the written value, then calls ``parent.update()``."""
    type = None

    def __init__(self, parent):
        self.parent = parent

    def put(self, pv, op):
        """Post the written value with the current timestamp, complete the operation and call ``self.parent.update()``."""
        postedval = op.value()
        postedval['timeStamp.secondsPastEpoch'], postedval['timeStamp.nanoseconds'] = divmod(float(time.time()), 1.0)
        pv.post(postedval)
        op.done()
        self.parent.update()

class PVAServer(object):
    """StaticProvider with '<prefix>HPS:FIELDNAMES', 'HPS:FIELDTYPES', 'HPS:FIELDMASK' and a 'PAYLOAD' structure PV rebuilt from them.

    Defaults: 31 names 'pid00'..'pid1e', all types 'i', mask 0x8000.
    """
    def __init__(self, provider_name, prefix):
        self.provider = StaticProvider(provider_name)
        self.prefix = prefix
        self.pvs = []

        self.fieldNames = SharedPV(initial=NTScalar('as').wrap
                                   ({'value' : ['pid%02x'%i for i in range(31)]}),
                                   handler=DefaultPVHandler(self))

        # 'i' (integer) or 'f' (float)
        self.fieldTypes = SharedPV(initial=NTScalar('aB').wrap({'value' : [ord('i')]*31}),
                                   handler=DefaultPVHandler(self))

        self.fieldMask  = SharedPV(initial=NTScalar('I').wrap({'value' : 0x8000}),
                                   handler=DefaultPVHandler(self))

        self.payload    = SharedPV(initial=Value(Type([]),{}), 
                                   handler=DefaultPVHandler(self))

        self.provider.add(prefix+'HPS:FIELDNAMES',self.fieldNames)
        self.provider.add(prefix+'HPS:FIELDTYPES',self.fieldTypes)
        self.provider.add(prefix+'HPS:FIELDMASK' ,self.fieldMask)
        self.provider.add(prefix+'PAYLOAD'   ,self.payload)
        self.update()

    def update(self):
        """Replace the 'PAYLOAD' PV with a structure holding 'valid' plus one field per set bit of the mask.

        Field names and type characters come from FIELDNAMES/FIELDTYPES; the structure ID is
        the mask as a string (with 'a' appended if equal to the old ID). The new ID is printed.
        """
        mask  = self.fieldMask .current().get('value')
        names = self.fieldNames.current().get('value')
        types = self.fieldTypes.current().get('value')
        oid   = self.payload   .current().getID()
        nid   = str(mask)

        if nid==oid:
            nid += 'a'
        ntypes  = []
        nvalues = {}
        ntypes.append( ('valid', 'i') )
        nvalues[ 'valid' ] = 0
        for i in range(31):
            if mask&1:
                ntypes.append( (names[i], chr(types[i])) )
                nvalues[ names[i] ] = 0
            mask >>= 1

        pvname = self.prefix+'PAYLOAD'
        self.provider.remove(pvname)
        self.payload = SharedPV(initial=Value(Type(ntypes,id=nid),nvalues), handler=DefaultPVHandler(self))
        print('Payload struct ID %s'%self.payload.current().getID())
        self.provider.add(pvname,self.payload)

    def forever(self):
        """Serve the provider with `p4p.server.Server.forever` (blocks)."""
        Server.forever(providers=[self.provider])


import argparse

def main():
    """Parse -P (prefix, required) and -v, create a `PVAServer` for '<prefix>:' and serve until KeyboardInterrupt."""
    global prefix
    prefix = ''

    parser = argparse.ArgumentParser(prog=sys.argv[0], description='host PVs for HPS diagnostic bus')

    parser.add_argument('-P', required=True, help='DAQ:SIM', metavar='PREFIX')
    parser.add_argument('-v', '--verbose', action='store_true', help='be verbose')

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    stationstr = ''
    prefix = args.P+':'

    server = PVAServer(__name__, args.P+':')

    try:
        # process PVA transactions
        server.forever()
    except KeyboardInterrupt:
        print('\nInterrupted')



if __name__ == '__main__':
    main()
