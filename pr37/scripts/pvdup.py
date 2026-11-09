"""Every PV simxpm serves, counted at run time: SimXpm built (no socket opened), each _add/_add_table name recorded."""
import collections, sys
from psdaq.sim import simxpm
names = []
for meth in ('_add', '_add_table'):
    orig = getattr(simxpm.SimXpm, meth)
    def wrap(self, name, *a, _orig=orig, **k):
        names.append(name)
        return _orig(self, name, *a, **k)
    setattr(simxpm.SimXpm, meth, wrap)
x = simxpm.SimXpm('DAQ:SIM', 0, 'tcp://127.0.0.1:0', 1000.)
dup = sorted(n for n, c in collections.Counter(names).items() if c > 1)
print(f'simxpm PVs: {len(names)} added, {len(set(names))} distinct names, {len(x.pvs)} served; duplicates: {dup or "none"}')
for k in ('LinkLabel0', 'PATT:GROUPS', 'PATT:COINC', 'PART:5:MsgConfig', 'PART:5:ResetL0', 'LinkRxReady0', 'LinkTxReady13',
          'TxLinkReset0', 'LinkLoopback13', 'LinkRxIsXpm0', 'FwBuild', 'LinkGroupMask31', 'RemoteLinkId31'):
    print(f'  DAQ:SIM:XPM:0:{k:<16} served: {("DAQ:SIM:XPM:0:" + k) in x.pvs}')
sys.exit(1 if dup or len(set(names)) != len(x.pvs) else 0)
