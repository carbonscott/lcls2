#!/usr/bin/env python

#
#  Launch this prior to Configure.  It will close after Unconfigure
#
"""PVA server thread (`PVCtrls`) that maps group PVs onto an XpmMini pyrogue device.

The header comment says: 'Launch this prior to Configure.  It will close after Unconfigure'
(no such shutdown logic is in this module).
"""
from p4p.server import Server, StaticProvider
from p4p.server.thread import SharedPV
from p4p.nt import NTScalar
import threading
import time
import datetime

class PVHandler(object):

    """SharedPV handler that posts a written value and then calls ``cb(pv, value)``.

    Parameters
    ----------
    cb : callable
        Called with the PV and the posted 'value' field.
    """
    def __init__(self,cb):
        self._cb = cb

    def put(self, pv, op):
        """Post the value of PUT operation `op` to `pv` with a ``time.time_ns()`` timestamp, call the callback with the new 'value', then call ``op.done()``."""
        postedval = op.value()
        #print('PVHandler cb[{:}] val[{:}]'.format(self._cb, postedval))
        postedval['timeStamp.secondsPastEpoch'], postedval['timeStamp.nanoseconds'] = divmod(float(time.time_ns()), 1.0e9)
        pv.post(postedval)
        self._cb(pv,postedval['value'])
        op.done()

#
#  Host the PVs used by DAQ control
#
class PVCtrls(threading.Thread):
    """Daemon thread hosting the PVs '<name>:GroupL0Reset', ':GroupL0Enable', ':GroupL0Disable', ':GroupMsgInsert', ':PART:0:Master' and ':PART:0:MsgHeader' for ``app.XpmMini``.

    The constructor writes ``app.TPGMiniCore.TStampWr`` (seconds since 1990-01-01, the 'epics epoch'
    per the code comment, shifted left 32 bits) and sets ``Pipeline_Depth_Clks`` to 95*200 and
    ``Pipeline_Depth_Fids`` to 95.

    Parameters
    ----------
    name : str
        PV name prefix.
    app : pyrogue Device
        Device with 'XpmMini' and 'TPGMiniCore' children.
    """
    def __init__(self, name, app):
        threading.Thread.__init__(self,daemon=True)
        self._name = name
        self._app  = app.XpmMini
        # initialize timestamp
        tnow = datetime.datetime.now()
        t0   = datetime.datetime(1990,1,1)  # epics epoch
        ts = int((tnow-t0).total_seconds())<<32
        app.TPGMiniCore.TStampWr.set(ts)
        app.XpmMini.Pipeline_Depth_Clks.set(95*200)
        app.XpmMini.Pipeline_Depth_Fids.set(95)

    def run(self):
        """Create the six 'I' PVs (initial value 0), each calling its handler method on PUT, and serve them; loops forever with 1 s sleeps."""
        self.provider = StaticProvider(__name__)

        self._pv = []
        self._msgHeader = 0

        def addPV(label,cmd):
            pv = SharedPV(initial=NTScalar('I').wrap(0), 
                          handler=PVHandler(cmd))
            name = self._name+':'+label
            print('Registering {:}'.format(name))
            self.provider.add(name,pv)
            self._pv.append(pv)

        addPV('GroupL0Reset'    , self.l0Reset)
        addPV('GroupL0Enable'   , self.l0Enable)
        addPV('GroupL0Disable'  , self.l0Disable)
        addPV('GroupMsgInsert'  , self.msgInsert)
        addPV('PART:0:Master'   , self.master)
        addPV('PART:0:MsgHeader', self.msgHeader)

        with Server(providers=[self.provider]):
            while True:
                time.sleep(1)

    def l0Reset(self, pv, val):
        """Pulse ``Config_L0Select_Reset``: write 1, sleep 10 ms, write 0. `pv` and `val` are ignored."""
        self._app.Config_L0Select_Reset.set(1)
        time.sleep(0.01)
        self._app.Config_L0Select_Reset.set(0)

    def l0Enable(self, pv, val):
        """Set ``Config_L0Select_Enabled`` to True. `pv` and `val` are ignored."""
        self._app.Config_L0Select_Enabled.set(True)

    def l0Disable(self, pv, val):
        """Set ``Config_L0Select_Enabled`` to False. `pv` and `val` are ignored."""
        self._app.Config_L0Select_Enabled.set(False)

    def msgInsert(self, pv, val):
        """If `val` > 0, call ``XpmMini.SendTransition`` with the header last stored by `msgHeader` (initially 0)."""
        if val>0:
            print('Sending Transition {:}'.format(self._msgHeader))
            self._app.SendTransition(self._msgHeader)

    def msgHeader(self, pv, val):
        """Store `val` as the header used by the next `msgInsert`."""
        self._msgHeader = val

    def master(self, pv, val):
        """Set ``XpmMini.HwEnable`` to True. `pv` and `val` are ignored."""
        self._app.HwEnable.set(True)

