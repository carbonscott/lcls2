#
# Copied from pyxpm.pvhander with archive removed
#
"""p4p PV helpers: create SharedPVs on a global provider, post updates, and simple put handlers.

A code comment says it was copied from pyxpm.pvhandler with archive support removed.
"""
from p4p.server.thread import SharedPV
from p4p.nt import NTScalar
from p4p.nt import NTTable

import time
import logging
from enum import Enum

provider = None

class AlarmSevr(Enum):
    """Enum of alarm severities: NONE, MINOR, MAJOR, INVALID (0-3)."""
    NONE = 0
    MINOR = 1
    MAJOR = 2
    INVALID = 3

class AlarmStatus(Enum):
    """Enum of alarm status codes NONE (0) through TIMEOUT (10)."""
    NONE = 0
    READ = 1
    WRITE = 2
    HIGH  = 3
    HIHI  = 4
    LOW   = 5
    LOLO  = 6
    STATE = 7
    CHANGE_OF_STATE = 8
    COMM  = 9
    TIMEOUT = 10

def setVerbose(v):
    """Do nothing; body is `pass`."""
    pass

def setProvider(v):
    """Set the module-global `provider` used by `addPV`, `addPVC` and `addPVT`."""
    global provider
    provider = v

def toTable(t):
    """Build an NTTable column spec from dict `t` of name -> (type string, values).

    Returns
    -------
    tuple
        (list of (name, type string without its first character), length of the values of
        the last entry).
    """
    table = []
    for v in t.items():
        table.append((v[0],v[1][0][1:]))
        n = len(v[1][1])
    return table,n

def toDict(t):
    """Return a dict mapping each key of `t` to ``t[key][1]``."""
    d = {}
    for v in t.items():
        d[v[0]] = v[1][1]
    return d

def toDictList(t,n):
    """Return `n` row dicts, row i mapping each key of `t` to ``t[key][1][i]``."""
    l = []
    for i in range(n):
        d = {}
        for v in t.items():
            d[v[0]] = v[1][1][i]
        l.append(d)
    return l

#  Translate from NTScalar type to XTC type
_ctype = {'?':'UINT8',
          's':'CHARSTR',
          'b':'INT8',
          'B':'UINT8',
          'h':'INT16',
          'H':'UINT16',
          'i':'INT32',
          'I':'UINT32',
          'l':'INT64',
          'L':'UINT64',
          'f':'FLOAT',
          'd':'DOUBLE'}

def addPV(name,ctype,init=0,valueAlarm=False):
    """Create an NTScalar SharedPV with a `DefaultPVHandler`, add it to `provider` under `name` and return it."""
    handler = DefaultPVHandler()
    pv = SharedPV(initial=NTScalar(ctype,valueAlarm=valueAlarm).wrap(init), handler=handler)
    provider.add(name, pv)
    return pv

def addPVC(name,ctype,init,cmd):
    """Create an NTScalar SharedPV whose puts also call ``cmd(pv, value)``, add it to `provider` and return it."""
    pv = SharedPV(initial=NTScalar(ctype).wrap(init), 
                  handler=PVHandler(cmd))
    provider.add(name,pv)
    return pv

def addPVT(name,t):
    """Create an NTTable SharedPV from table description `t`, add it to `provider` under `name` and return it."""
    table,n = toTable(t)
    init    = toDictList(t,n)
    pv = SharedPV(initial=NTTable(table).wrap(init),
                  handler=DefaultPVHandler())
    provider.add(name,pv)
    return pv

def pvUpdate(pv, val):
    """Post `val` as the PV's 'value' with the current time as timestamp."""
    value = pv.current()
    value['value'] = val
    value['timeStamp.secondsPastEpoch'], value['timeStamp.nanoseconds'] = divmod(float(time.time_ns()), 1.0e9)
    pv.post(value)

class DefaultPVHandler(object):

    """p4p put handler that posts the written value with a new timestamp."""
    def __init__(self, ctype='UINT32'):
        self._ctype   = ctype

    def put(self, pv, op):
        """Post the written value with the current timestamp and complete the operation."""
        postedval = op.value()
        logging.debug('DefaultPVHandler.put ',pv,postedval['value'])
        postedval['timeStamp.secondsPastEpoch'], postedval['timeStamp.nanoseconds'] = divmod(float(time.time_ns()), 1.0e9)
        pv.post(postedval)
        op.done()
            
class PVHandler(object):

    """p4p put handler that posts the written value and then calls the callback `cb`."""
    def __init__(self, cb, ctype='UINT32'):
        self._cb = cb

    def put(self, pv, op):
        """Post the written value with the current timestamp, call ``self._cb(pv, value)`` and complete the operation."""
        postedval = op.value()
        logging.debug('PVHandler.put ',postedval['value'],self._cb)
        postedval['timeStamp.secondsPastEpoch'], postedval['timeStamp.nanoseconds'] = divmod(float(time.time_ns()), 1.0e9)
        pv.post(postedval)
        self._cb(pv,postedval['value'])
        op.done()
