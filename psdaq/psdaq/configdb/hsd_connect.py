"""Connect-phase helper for HSDs: reads the PADDR_U PV over PVA."""
from p4p.client.thread import Context

import json
import time
import pprint

def hsd_connect(epics_prefix):

    # Retrieve connection information from EPICS
    # May need to wait for other processes here {PVA Server, hsdioc}, so poll
    """Read '<epics_prefix>:PADDR_U' over PVA, retrying up to 50 times (0.1 s apart) while it is 0, and return it as JSON.

    Returns
    -------
    str
        ``json.dumps({'paddr': value})`` with the last value read, which may still be 0.
    """
    ctxt = Context('pva')
    for i in range(50):
        values = ctxt.get(epics_prefix+':PADDR_U')
        if values!=0:
            break
        print('{:} is zero, retry'.format(epics_prefix+':PADDR_U'))
        time.sleep(0.1)

    ctxt.close()

    d = {}
    d['paddr'] = values
    return json.dumps(d)
