"""simxpm: a software XPM, so the DAQ runs with no timing hardware.

It serves the XPM PVs that control.py and the DRPs use (names and types as in
psdaq/pyxpm/pvctrls.py and pvstats.py), and turns writes to them into a stream of timing
frames that each DRP started with '-d sim://<host>:<port>' receives (psdaq/drp/MemPoolSim.hh):

  PART:<g>:MsgHeader + GroupMsgInsert  ->  one transition frame (ClearReadout, Configure, ...)
  GroupL0Enable / GroupL0Disable       ->  start / stop a train of L1Accepts at SIM:L1Rate

Frames go out in one total order from one thread.  A frame is sent to every DRP connected to
one of its readout groups, and only when all of them have credit, so none is dropped and all
DRPs of a group see the same pulses.  A DRP that stops returning credit causes deadtime, as
it would with a real XPM.

Deadtime per link.  A real XPM holds back a readout group's L0s while one of its links asserts full
(the DRP's TriggerEventBuffer is past its PauseThreshold) and reports, for each link, the share of
the last second it did so (pyxpm pvstats.py GroupStats: DeadFLnk, from the firmware's inhibit-time
counters), which deadca shows.  simxpm's link is full while its DRP has no credit, so a healthy run
shows 0.  SIM:LinkFull (one share per link, 0 by default; a sim-only PV) makes link n also assert
full for that share of every FULL_PERIOD seconds from the put, as a DRP whose readout stalls
periodically would: its group's L0s are held back meanwhile (counted in NumL0Inp, not NumL0Acc, so
DeadFrac rises and fewer L1Accepts are recorded) and DeadFLnk[n] is the share of the second's L0s
it held.  FULL_PERIOD is not a whole second, so each second's share differs.  Transitions are not
held back, as on a real XPM.

control.py started with '-X <host>' sends the frame-producing writes (MsgHeader, GroupMsgInsert,
GroupL0Enable/Disable, GroupL0Reset, StepEnd, StepGroups) as JSON over a ZMQ PUSH socket instead
of PVA, to the PULL socket that pyxpm binds at xpm_pull_port(<pvbase>:XPM:<n>)
(psdaq/pyxpm/pvctrls.py zrcv, control.py DaqXPM).  simxpm binds the same PULL port on loopback and
treats those messages exactly like the PVA puts, so both control.py modes work.  Without -X,
control.py still connects its PUSH socket to 'tcp://None:<port>', so run it with -X 127.0.0.1.

Both the PVA server and the frame and PULL sockets bind to the loopback interface unless told
otherwise.

With --camera-pv NAME it also serves a camera PV for drp_pva (opened 0.25 s after a client connects, as
CameraPV says), as an areaDetector IOC whose
frames a timing receiver stamps: an NTNDArray (uint16, CAMERA_SHAPE) updated once for every
L1Accept, its timeStamp the L1Accept's time (drp_pva matches PV updates to L1Accepts by exact
time), its pixels camera_image(seed, seq): pixels 0 and 1 the L1Accept's seq (low, high 16 bits),
pixel i >= 2 psdaq.sim.pattern.pattern(seed, seq, i, 16).  A reader checks each recorded image
against the seq it carries.

Readout groups at different rates.  By default every enabled readout group gets an L1Accept on
every tick of SIM:L1Rate.  With --fixed-rates, a group whose L0Select is 0 (FixedRate) instead
fires on pyxpm's fixed-rate marker L0Select_FixedRate selects (0..6: 929 kHz / 1, 13, 91, 910,
9100, 91000, 910000, i.e. 929 kHz, 71.4 kHz, 10.2 kHz, 1.02 kHz, 102 Hz, 10.2 Hz, 1.02 Hz), as
an operator sets it in the XPM GUI or ts_config.py at Configure; a marker faster than --max-rate
keeps SIM:L1Rate (a software XPM cannot tick at 929 kHz).  The groups' markers are nested as the
real ones are: simxpm ticks at the fastest enabled group's rate and a slower group fires on every
k-th tick (k the rates' ratio), so each of its L1Accepts is also one of the faster group's.  An
L1Accept frame carries, for each DRP, the L1Accept count of that DRP's own readout group (its
seq), and SIM:LinkL1Acc (a JSON string) holds each link's alias, group and the L1Accepts sent to
it since its group's last GroupL0Reset: the count each DRP was triggered for.

With --bld PREFIX it is also a beam line data (BLD) source, as an accelerator's BLD server: on
every L1Accept tick it sends one LCLS-II style BLD packet (BldDetector.hh: u64 time, u64
pulseId, u32 id, then the payload: u64 severity and the fields of BLD_PAYLOAD) by UDP multicast
to --bld-dest (an administratively scoped group, 239.0.0.0/8 outside LCLS's 239.255.0.0/16;
TTL 1, sent and looped back on the 127.0.0.1 interface only), and serves the payload's
description <PREFIX>:BLD_PAYLOAD over PVA, as drp_bld reads it (BldPVA; the group and port it
reads from the CA PVs <PREFIX>:BLD1_MULT_ADDR and BLD1_MULT_PORT, which a CA server such as
daq_sim's stand-in IOC serves).  The fields are bld_values(seed, seq): seq, value =
pattern(seed, seq, 0, 31) and energy = pattern(seed, seq, 1, 20) / 1024; severity =
pattern(seed, seq, 2, 6), 2 bits per field.
"""

import argparse
import collections
import json
import logging
import os
import queue
import re
import struct
import threading
import time

import zmq
from p4p.nt import NTNDArray, NTScalar, NTTable
from p4p.server import Server, StaticProvider
from p4p.server.thread import SharedPV

from psdaq.sim.served_log import ServedLog

POSIX_TIME_AT_EPICS_EPOCH = 631152000
NUM_GROUPS = 8
NUM_LINKS = 32                          # Length of DeadFLnk, as in pyxpm
FULL_PERIOD = 1.3                       # s: the period of a SIM:LinkFull share (module doc)
NUM_COINC = NUM_GROUPS * (NUM_GROUPS + 1) // 2      # PATT:COINC entries (pyxpm pvstats NCOINC)
PATT_STATS = ('Sum', 'First', 'Last', 'MinIntv', 'MaxIntv')     # PATT:GROUPS columns (pyxpm pvstats pattStats)
NUM_PORTS = 14                          # Front-panel links with per-link PVs, as ts_connect.py uses
FW_BUILD = 'simxpm (psdaq/psdaq/sim/simxpm.py): software XPM, no firmware'
PID_MASK = (1 << 56) - 1
CAMERA_SHAPE = (8, 16)                  # --camera-pv image: rows, columns
# pyxpm's fixed-rate markers (L0Select 0 = FixedRate, L0Select_FixedRate = index): divisors of
# LCLS-II's 1300/1.4 MHz pulse rate
TIMING_BASE_HZ = 1300e6 / 1400
FIXED_RATE_DIV = (1, 13, 91, 910, 9100, 91000, 910000)
MAX_TICK_HZ = 2000.                     # --max-rate default: the fastest a fixed-rate group ticks
# --bld: the payload after the u64 severity (each field naturally aligned), and the description
# drp_bld reads (BldDescriptor: the first field of the PV's structure, scalar fields only)
BLD_FIELDS = (('energy', 'd'), ('value', 'i'), ('seq', 'I'))
BLD_HEADER = struct.Struct('<QQI')      # time (sec << 32 | ns), pulseId, id
BLD_PAYLOAD = struct.Struct('<QdiI')     # severity, energy, value, seq
BLD_ID = 0x5153                         # the header's id word


def fixed_rate_hz(index):
    """The rate of pyxpm's fixed-rate marker `index` (L0Select_FixedRate), or None."""
    return TIMING_BASE_HZ / FIXED_RATE_DIV[index] if 0 <= index < len(FIXED_RATE_DIV) else None


def bld_values(seed, seq):
    """(severity, {field: value}) of the --bld packet of the L1Accept with this seq."""
    from psdaq.sim import pattern
    p = lambda i, bits: int(pattern.pattern(seed, seq, i, bits))
    return p(2, 6), {'energy': p(1, 20) / 1024., 'value': p(0, 31), 'seq': seq & 0xffffffff}


def bld_packet(seed, seq, sec, ns, pid):
    """The --bld packet of one L1Accept (time sec, ns past the EPICS epoch)."""
    sevr, v = bld_values(seed, seq)
    return (BLD_HEADER.pack((sec << 32) | ns, pid, BLD_ID) +
            BLD_PAYLOAD.pack(sevr, v['energy'], v['value'], v['seq']))


def check_bld_dest(dest):
    """(group, port) of --bld-dest 'ADDR:PORT': a multicast group in 239.0.0.0/8 outside LCLS's
    239.255.0.0/16, so a sent packet can reach no production BLD receiver."""
    import ipaddress
    addr, port = dest.rsplit(':', 1)
    a = ipaddress.ip_address(addr)
    if not (a in ipaddress.ip_network('239.0.0.0/8') and a not in ipaddress.ip_network('239.255.0.0/16')):
        raise ValueError(f'--bld-dest {dest}: use a group in 239.0.0.0/8 outside 239.255.0.0/16 '
                         '(where LCLS BLD lives)')
    return addr, int(port)


class BldSource:
    """--bld: BLD_PAYLOAD over PVA and one multicast packet per L1Accept tick (module doc)."""

    def __init__(self, prefix, provider, dest, seed, iface='127.0.0.1'):
        import socket
        from p4p import Type, Value
        self.prefix, self.seed = prefix, seed
        self.group, self.port = check_bld_dest(dest)
        t = Type([('value', ('S', 'BldPayload', list(BLD_FIELDS))),
                  ('timeStamp', ('S', 'time_t', [('secondsPastEpoch', 'l'), ('nanoseconds', 'i'),
                                                 ('userTag', 'i')]))])
        self.pv = SharedPV(initial=Value(t, {'value': {n: 0 for n, _ in BLD_FIELDS}}))
        provider.add(f'{prefix}:BLD_PAYLOAD', self.pv)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
        self.sent = 0

    def send(self, sec, ns, pid, seq):
        self.sock.sendto(bld_packet(self.seed, seq, sec, ns, pid), (self.group, self.port))
        self.sent += 1


def camera_image(seed, seq, shape=CAMERA_SHAPE):
    """The --camera-pv image of the L1Accept with this seq (module doc)."""
    import numpy as np
    from psdaq.sim import pattern
    img = np.asarray(pattern.pattern(seed, seq, np.arange(shape[0] * shape[1]), 16), dtype=np.uint16)
    img[0], img[1] = seq & 0xffff, (seq >> 16) & 0xffff
    return img.reshape(shape)


class CameraPV:
    """--camera-pv: an NTNDArray PV posted once per L1Accept with that L1Accept's time.

    The PV opens OPEN_S after a client's first channel, with the last image, and closes after its last
    channel.  drp_pva's PvMonitor (MonTracker, psdaq/psdaq/epicstools) starts its monitor inside its
    constructor and drops an update that arrives before the constructor has returned (shared_from_this()
    throws bad_weak_ptr in MonTracker::monitorEvent); pvAccessCPP signals a monitor's data only when its
    queue goes from empty to not empty, so no later update reaches it either, and drp_pva waited out its
    3 s at Configure ("PV ... hasn't connected").  Served open, as a camera IOC's PV is, the first update
    came within 1 ms of drp_pva's search when its TCP link to simxpm was already up, before that
    constructor had returned; opened OPEN_S later, it comes after.  An L1Accept with no client is not
    posted (nobody would see it) but is the image the PV opens with."""
    OPEN_S = 0.25

    def __init__(self, name, provider, seed):
        self.name, self.seed, self.nt = name, seed, NTNDArray()
        self.lock = threading.Lock()
        self.last = (0, None, None)                 # seq, sec, ns of the last L1Accept
        self.clients = 0                            # first channels seen, so a stale open does nothing
        self.pv = SharedPV(handler=self)            # closed until a client connects (posts Values, as _add)
        provider.add(name, self.pv)
        self.posted = 0
        self.opened = 0

    def _value(self, seq, sec, ns):
        value = self.nt.wrap(camera_image(self.seed, seq))
        if sec is not None:
            value['uniqueId'] = seq
            value['timeStamp.secondsPastEpoch'] = sec + POSIX_TIME_AT_EPICS_EPOCH
            value['timeStamp.nanoseconds'] = ns
        return value

    def post(self, sec, ns, seq):
        value = self._value(seq, sec, ns)
        with self.lock:
            self.last = (seq, sec, ns)
            if self.pv.isOpen():
                self.pv.post(value)
            self.posted += 1

    def onFirstConnect(self, pv):               # p4p SharedPV handler: a client's first channel
        with self.lock:
            self.clients += 1
            timer = threading.Timer(self.OPEN_S, self._open, (self.clients,))
        timer.daemon = True
        timer.start()

    def _open(self, n):
        with self.lock:
            if n == self.clients and not self.pv.isOpen():
                self.pv.open(self._value(*self.last))
                self.opened += 1

    def onLastDisconnect(self, pv):             # its last channel: the next client waits OPEN_S again
        with self.lock:
            self.clients += 1
            if self.pv.isOpen():
                self.pv.close()


class TransitionId:
    ClearReadout = 0
    Reset = 1
    Configure = 2
    Unconfigure = 3
    BeginRun = 4
    EndRun = 5
    BeginStep = 6
    EndStep = 7
    Enable = 8
    Disable = 9
    SlowUpdate = 10
    L1Accept = 12
    names = {0: 'ClearReadout', 1: 'Reset', 2: 'Configure', 3: 'Unconfigure', 4: 'BeginRun',
             5: 'EndRun', 6: 'BeginStep', 7: 'EndStep', 8: 'Enable', 9: 'Disable',
             10: 'SlowUpdate', 12: 'L1Accept'}


# One frame, as MemPoolSim::Frame: pulseId|control<<56, ns, s (EPICS epoch), env, seq
FRAME = struct.Struct('<QIIII')

MSGHDR_DROP_IF_DEADTIME = 0x80          # e.g. SlowUpdate (control.py condition_slowupdate)
MSGHDR_RETRY = 0x100                    # with 0x80: queue and retry (Disable, control.py:2498)


def droppable(hdr):
    return bool(hdr & MSGHDR_DROP_IF_DEADTIME) and not hdr & MSGHDR_RETRY


def timing_now(last_pid=0):
    """Return (pulseId, seconds, nanoseconds) for now, the pulseId strictly increasing."""
    sec, ns = divmod(time.time_ns(), 1000000000)
    sec -= POSIX_TIME_AT_EPICS_EPOCH
    pid = (sec * 14000000) // 13 + (ns * 14) // 13000   # 929 kHz, as drpGpu/SimDetector.cc
    if pid <= last_pid:
        pid = last_pid + 1
    return pid & PID_MASK, sec, ns


def pack_frame(tid, pid, sec, ns, env, seq=0):
    return FRAME.pack(((tid & 0xf) << 56) | (pid & PID_MASK), ns, sec, env, seq)


def unpack_frame(data, offset=0):
    word, ns, sec, env, seq = FRAME.unpack_from(data, offset)
    return {'tid': (word >> 56) & 0xf, 'pulseId': word & PID_MASK,
            'seconds': sec, 'nanoseconds': ns, 'env': env, 'seq': seq}


# control.py -X: pyxpm register name -> simxpm command (see DaqXPM in control.py)
_PULL_REGS = {'groupL0Reset': 'l0reset', 'groupL0Enable': 'l0enable',
              'groupL0Disable': 'l0disable', 'groupMsgInsert': 'insert'}
_PULL_GROUP_REGS = re.compile(r'(stepEnd|stepGroup)([0-7])$')


def pull_commands(msg):
    """Translate one control.py -X message (pyxpm zrcv format) to simxpm commands.

    Returns (commands, pvs): commands is a list of (command, arg, value) for SimXpm._do, and
    pvs the PV names whose value pyxpm posts (the message's optional 'pv' entry).
    Raises ValueError for a message simxpm does not understand."""
    kind, reg, value = msg.get('type'), msg.get('reg'), msg.get('value')
    if not isinstance(value, int):
        raise ValueError(f'no integer value in {msg}')
    if kind == 'set_reg':
        if reg in _PULL_REGS:
            commands = [(_PULL_REGS[reg], None, value)]
        else:
            m = _PULL_GROUP_REGS.match(reg or '')
            if not m:
                raise ValueError(f'unknown register {reg!r} in {msg}')
            commands = [('stepend' if m.group(1) == 'stepEnd' else 'stepgroups', int(m.group(2)), value)]
    elif kind == 'set_idx_reg' and reg == 'msgHdr':
        groups = msg.get('groups', 0)
        commands = [('msghdr', g, value) for g in range(NUM_GROUPS) if groups & (1 << g)]
    else:
        raise ValueError(f'unknown message {msg}')
    pvs = msg.get('pv', [])
    return commands, [pvs] if isinstance(pvs, str) else list(pvs)


class Link:
    def __init__(self, identity, alias, number):
        self.identity = identity
        self.alias = alias
        self.number = number
        self.credit = 0
        self.group = None               # Readout group once CONNECTed
        self.outbox = []
        self.blocked = 0                # L1 ticks lost to this link since the last stats
        self.l1acc = 0                  # L1Accepts sent since its group's GroupL0Reset


class _Put:
    """Post the new value, hand it to the generator thread, then complete the put.

    control.py waits for each put to complete, so commands reach the generator in its order.
    """
    def __init__(self, sim, command=None, arg=None):
        self._sim = sim
        self._command = command
        self._arg = arg

    def put(self, pv, op):
        value = op.value()
        value['timeStamp.secondsPastEpoch'], value['timeStamp.nanoseconds'] = divmod(time.time_ns(), 1000000000)
        pv.post(value)
        self._sim.served(getattr(self, 'name', '?'), value)
        if self._command:
            self._sim.command(self._command, self._arg, value['value'])
        op.done()


class SimXpm:
    def __init__(self, pvbase, xpm, endpoint, rate, pull=None, camera=None, camera_seed=0,
                 fixed_rates=False, max_rate=MAX_TICK_HZ, bld=None, bld_dest=None, bld_seed=0, fwbuild=FW_BUILD):
        self.pvbase = pvbase
        self.xpm = xpm
        self.fwbuild = fwbuild          # FwBuild: xpmpva builds AMC / QSFP and Cu / Us tabs by what it says
        self.prefix = f'{pvbase}:XPM:{xpm}'
        self.endpoint = endpoint
        self.pull = pull                # control.py -X endpoint to bind, or None
        self.pull_count = 0
        self.rate = float(rate)
        self.fixed_rates = fixed_rates  # --fixed-rates: FixedRate groups follow their marker
        self.max_rate = float(max_rate)
        self.l0select = [0] * NUM_GROUPS
        self.fixed_rate = [0] * NUM_GROUPS
        self.tick = 0                   # ticks since the last GroupL0Enable (--fixed-rates)
        self.commands = queue.Queue()
        self.stop = threading.Event()

        self.msghdr = [0] * NUM_GROUPS
        self.l0en = 0
        self.inhibit = 0                # Groups stopped at their step end
        self.step_groups = [0] * NUM_GROUPS
        self.step_end = [0] * NUM_GROUPS
        self.step_done = [False] * NUM_GROUPS
        self.num_l0acc = [0] * NUM_GROUPS
        self.num_l0inp = [0] * NUM_GROUPS
        self.run_time = [0.] * NUM_GROUPS     # seconds with L0 enabled (RunTime)
        self.pending = collections.deque()      # Transitions waiting for credit
        self.links = {}                 # identity -> Link
        self.link_numbers = {}          # alias -> link number, kept across restarts
        self.last_pid = 0
        self.frames_sent = 0
        self.coinc = {}                 # readout-group mask of an L0Accept tick -> ticks since the last stats
        self.patt = {}                  # group -> [first, last, min, max interval] pulse IDs since the last stats
        self.link_full = [0.] * NUM_LINKS   # SIM:LinkFull: share of every FULL_PERIOD link n asserts full
        self.full_t0 = time.monotonic()     # when SIM:LinkFull was last put

        self.provider = StaticProvider('simxpm')
        self.pvs = {}
        self.served = ServedLog('simxpm')       # every value served, when daq_sim names a log (psdaq.sim.served_log)
        self._make_pvs()
        self.camera = CameraPV(camera, self.provider, camera_seed) if camera else None
        self.bld = BldSource(bld, self.provider, bld_dest, bld_seed) if bld else None

    # --- PVs --------------------------------------------------------------------------

    def _add_table(self, name, columns, rows):
        """An NTTable PV as pyxpm pvhandler.addPVT makes it: columns [(label, 'i')], rows [{label: value}]."""
        nt = NTTable(columns)
        handler = _Put(self)
        handler.name = name
        pv = SharedPV(initial=nt.wrap(rows), handler=handler)
        self.provider.add(name, pv)
        self.pvs[name] = (pv, nt)
        self.served(name, rows)
        return pv

    def _add(self, name, ntype, initial, handler=None):
        nt = NTScalar(ntype)
        handler = handler or _Put(self)
        handler.name = name
        pv = SharedPV(initial=nt.wrap(initial, timestamp=time.time()), handler=handler)
        self.provider.add(name, pv)
        self.pvs[name] = (pv, nt)
        self.served(name, initial)
        return pv

    def _make_pvs(self):
        X = self.prefix
        self._add(f'{X}:GroupL0Enable', 'I', 0, _Put(self, 'l0enable'))
        self._add(f'{X}:GroupL0Disable', 'I', 0, _Put(self, 'l0disable'))
        self._add(f'{X}:GroupMsgInsert', 'I', 0, _Put(self, 'insert'))
        self._add(f'{X}:GroupL0Reset', 'I', 0, _Put(self, 'l0reset'))
        self._add(f'{X}:CommonL0Delay', 'I', 0)
        self._add(f'{X}:SIM:L1Rate', 'd', self.rate, _Put(self, 'rate'))
        self._add(f'{X}:SIM:NumLinks', 'I', 0)
        self._add(f'{X}:SIM:LinkL1Acc', 's', '{}')
        self._add(f'{X}:SIM:LinkFull', 'ad', [0.] * NUM_LINKS, _Put(self, 'linkfull'))
        # Stand-ins for the pyxpm PVs the XPM GUIs read (groupca: xpmTree, XpmDeadTime): stored values only.
        # RemoteLinkId stays 0 (no remote id, so groupca never resolves a host name); LinkGroupMask<n> is
        # 1 << group while the DRP of link n is in a readout group (pyxpm pvctrls LinkGroupMask).
        self._add(f'{X}:FwBuild', 's', self.fwbuild)
        # xpmpva reads PAddr, Us:RxAlign, Cu:RxAlign and SFPSTATUS at start (a .get() that fails ends it):
        # _make_xpmpva_pvs serves them
        for n in range(NUM_LINKS):
            self._add(f'{X}:RemoteLinkId{n}', 'I', 0)
            self._add(f'{X}:LinkGroupMask{n}', 'I', 0)
            # LinkLabel<n>: the link's name, as the older XPM IOC served it (deadca, partca-sum read it): the
            # alias of the DRP on that link, '' while none is
            self._add(f'{X}:LinkLabel{n}', 's', '')
        # Pattern statistics (pyxpm pvstats PatternStats, NTTables): per group, Sum = L0Accepts in the last
        # second, First/Last the low 20 bits of its first and last L0Accept's pulse ID, MinIntv/MaxIntv the least and
        # most pulse IDs between two (_post_patt); COINC = for each pair of groups i <= j, the L0Accept ticks of
        # the last second that both took (xpmpatt, xpmpva Pattern tab)
        self._add_table(f'{X}:PATT:GROUPS', [(c, 'i') for c in PATT_STATS],
                        [{c: 0 for c in PATT_STATS} for _ in range(NUM_GROUPS)])
        self._add_table(f'{X}:PATT:COINC', [('Coinc', 'i')], [{'Coinc': 0} for _ in range(NUM_COINC)])
        for g in range(NUM_GROUPS):
            P = f'{X}:PART:{g}'
            self._add(f'{P}:MsgHeader', 'I', 0, _Put(self, 'msghdr', g))
            self._add(f'{P}:StepGroups', 'I', 0, _Put(self, 'stepgroups', g))
            self._add(f'{P}:StepEnd', 'I', 0, _Put(self, 'stepend', g))
            self._add(f'{P}:StepDone', 'I', 0)
            self._add(f'{P}:L0Delay', 'I', 90)
            for label in ('Master', 'L0Groups', 'SeqMask', 'MsgPayload', 'DstSelect',
                          'DstSelect_Mask', 'Run'):
                self._add(f'{P}:{label}', 'I', 0)
            self._add(f'{P}:Recording', 'b', 0)
            self._add(f'{P}:DeadFLnk', 'af', [0.] * NUM_LINKS)
            for label in ('NumL0Acc', 'NumL0Inp', 'L0AccRate', 'L0InpRate'):
                self._add(f'{P}:{label}', 'f', 0.)
            # Trigger and inhibit settings that ts_config.py writes (pvctrls.py PVCtrls and
            # GroupCtrls); simxpm keeps them, its L1Accepts stay at SIM:L1Rate.
            # Stand-ins (pyxpm pvctrls/pvstats names and types) for groupca and partca: stored values,
            # RunTime/DeadFrac/DeadTime/NumL1/L1Rate computed from the counters in _stats.
            # L0Select and L0Select_FixedRate also set the group's rate with --fixed-rates.
            self._add(f'{P}:L0Select', 'I', 0, _Put(self, 'l0select', g))
            self._add(f'{P}:L0Select_FixedRate', 'I', 0, _Put(self, 'fixedrate', g))
            for label in ('L0Select_ACRate', 'L0Select_ACTimeslot',
                          'L0Select_EventCode', 'L0Select_Sequence', 'L0Select_SeqBit'):
                self._add(f'{P}:{label}', 'I', 0)
            self._add(f'{P}:L0RawUpdate', 'I', 1)
            for i in range(4):
                self._add(f'{P}:InhInterval{i}', 'I', 10)
                self._add(f'{P}:InhLimit{i}', 'I', 4)
                self._add(f'{P}:InhEnable{i}', 'I', 0)
            for label in ('RunTime', 'DeadFrac', 'DeadTime', 'NumL1', 'L1Rate', 'NumL0Inh'):
                self._add(f'{P}:{label}', 'f', 0.)
            # The group PVs the older partition IOC served that partca's buttons and fields write (pyxpm keeps
            # only MsgConfigKey): stored values, no frames (groupca's MsgHeader + GroupMsgInsert make those)
            for label in ('MsgConfig', 'MsgConfigKey', 'MsgEnable', 'MsgDisable', 'MsgClear', 'MsgInsert',
                          'ResetL0'):
                self._add(f'{P}:{label}', 'I', 0)
        # Per-link PVs that ts_connect.py reads and writes (pvctrls.py LinkCtrls, pvstats.py
        # LinkStatus): LinkRxReady<n> is 1 while a DRP holds link n (a locked receiver).
        # LinkGroupMask<n>, RemoteLinkId<n> and FwBuild are added above for the XPM GUIs.
        for n in range(NUM_PORTS):
            for label in ('TxLinkReset', 'RxLinkReset', 'LinkLoopback'):
                self._add(f'{X}:{label}{n}', 'I', 0)
            for label in ('LinkTxReady', 'LinkRxReady', 'LinkRxErr', 'LinkRxErrI', 'LinkRxIsXpm'):
                self._add(f'{X}:{label}{n}', 'I', 0)

        self._make_xpmpva_pvs()

    def _make_xpmpva_pvs(self):
        """Stand-ins for the other pyxpm PVs cas/xpmpva.py reads and writes (names and types as pyxpm pvstats,
        pvctrls and pvxtpg serve them), stored values only, except that a counter of the timing receivers and the
        clocks hold fixed plausible values.  Not served, as pyxpm does not serve them either: ModuleInit,
        Inhibit, TagStream, XTPG:CuDelay_ns and LinkIsXpm<n> (xpmpva's widgets on those never connect)."""
        X = self.prefix
        self._add(f'{X}:PAddr', 'I', 0xffffffff)            # the top of the timing tree (no parent XPM): 'XTPG'
        self._add(f'{X}:UsRxEnable', 'I', 1)
        self._add(f'{X}:CuRxEnable', 'I', 0)
        for label, v in (('RecClk', 185.71), ('FbClk', 185.71), ('BpClk', 185.71), ('PhyClk', 185.71)):
            self._add(f'{X}:{label}', 'f', v)
        for tim in ('Us', 'Cu'):                            # pvstats TimingStatus: counters as floats
            for label in ('RxClks', 'TxClks', 'RxRsts', 'CrcErrs', 'RxDecErrs', 'RxDspErrs', 'BypassRsts',
                          'BypassDones', 'RxLinkUp', 'FIDs', 'SOFs', 'EOFs'):
                self._add(f'{X}:{tim}:{label}', 'f', {'RxClks': 185.71, 'RxLinkUp': 1., 'FIDs': 929000.}.get(label, 0.))
            self._add(f'{X}:{tim}:RxAlign', 'aI', [20] + [(k * 7) % 31 for k in range(64)])
            for label in ('RxReset', 'RxCountReset'):
                self._add(f'{X}:{tim}:{label}', 'I', 0)
        T = f'{X}:XTPG'                                      # pvctrls CuGenCtrls, pvstats / pvxtpg
        for label in ('CuInput', 'CuBeamCode', 'CuDelay', 'FiducialIntv', 'FiducialErr', 'ClearErr'):
            self._add(f'{T}:{label}', 'I', {'CuBeamCode': 140, 'CuDelay': 200, 'FiducialIntv': 1300}.get(label, 0))
        self._add(f'{T}:PulseId', 'L', 0)
        self._add(f'{T}:TimeStamp', 'L', 0)
        for i in range(4):                                  # pvxtpg PVMmcm: [locked | busy | steps | edge] + steps
            self._add(f'{T}:MMCM{i}', 'aI', [(1 << 31) | (64 << 16) | (20 + 8 * i)] + [(k * 5 + i) % 64 for k in range(64)])
            self._add(f'{T}:ResetMmcm{i}', 'I', 0)
        for n in range(NUM_PORTS):                          # pvctrls LinkCtrls, pvstats LinkStatus
            for label in ('RxLinkDump', 'LinkTxResetDone', 'LinkRxResetDone', 'LinkRxRcv'):
                self._add(f'{X}:{label}{n}', 'I', 0)
        for c in range(2):                                  # pvstats PLL status of each AMC
            for label in ('PLL_LOS', 'PLL_LOSCNT', 'PLL_LOL', 'PLL_LOLCNT'):
                self._add(f'{X}:{label}{c}', 'I', 0)
        ncodes = 32                                         # pvctrls seqCodes (the last 32 event codes)
        self._add_table(f'{X}:SEQCODES', [('EventCode', 'i'), ('Description', 's'), ('Rate', 'i'), ('Enabled', '?')],
                        [{'EventCode': 288 - ncodes + k, 'Description': '', 'Rate': 0, 'Enabled': False}
                         for k in range(ncodes)])
        for i in range(ncodes // 4):                        # pvseq PVSeq engines
            for label in ('ENABLE', 'DUMP'):
                self._add(f'{X}:SEQENG:{i}:{label}', 'I', 0)
        self._add_table(f'{X}:SFPSTATUS', [('LossOfSignal', 'i'), ('ModuleAbsent', 'i'), ('TxPower', 'f'),
                                          ('RxPower', 'f')],
                        [{'LossOfSignal': 0, 'ModuleAbsent': 0, 'TxPower': 0.5, 'RxPower': 0.25} for _ in range(14)])
        self._add_table(f'{X}:QSFPSTATUS', [('TxPower', 'f'), ('RxPower', 'f')],
                        [{'TxPower': 0.5, 'RxPower': 0.25} for _ in range(8)])
        for g in range(NUM_GROUPS):                         # pvstats PathTimer
            self._add(f'{X}:PART:{g}:PATH_TIME:Latched', 'I', 0)
            self._add(f'{X}:PART:{g}:PATH_TIME:Array', 'ai', [0] * NUM_PORTS)
            self._add(f'{X}:PART:{g}:PATH_TIME:Update', 'I', 0)
        for label in ('L0Select', 'L0Select_FixedRate', 'L0Select_ACRate', 'L0Select_ACTimeslot',
                      'L0Select_EventCode', 'L0Select_Sequence', 'L0Select_SeqBit'):
            self._add(f'{X}:PATT:{label}', 'I', 0)          # pvctrls RateSetup(name+':PATT')

    def _post(self, name, value):
        pv, nt = self.pvs[name]
        self.served(name, value)
        if isinstance(nt, NTTable):
            pv.post(nt.wrap(value))
            return
        pv.post(nt.wrap(value, timestamp=time.time()))

    def command(self, command, arg, value):
        self.commands.put((command, arg, value))

    # --- Frame stream -----------------------------------------------------------------

    def _targets(self, rog):
        return [l for l in self.links.values() if l.group is not None and (rog >> l.group) & 1]

    def _emit(self, tid, rog, seq=0):
        """Queue one frame to every target link, if all have credit; return success.  An
        L1Accept frame carries each link's own group's L1Accept count as its seq."""
        targets = self._targets(rog)
        if any(l.credit == 0 for l in targets):
            return False
        self.last_pid, sec, ns = timing_now(self.last_pid)
        self.last_sec, self.last_ns = sec, ns
        frame = pack_frame(tid, self.last_pid, sec, ns, rog, seq)
        for l in targets:
            l.credit -= 1
            if tid == TransitionId.L1Accept:
                l.l1acc += 1
                l.outbox.append(pack_frame(tid, self.last_pid, sec, ns, rog, self.num_l0acc[l.group]))
            else:
                l.outbox.append(frame)
        self.frames_sent += 1
        if tid != TransitionId.L1Accept:
            log = logging.debug if tid in (TransitionId.SlowUpdate,) else logging.info
            log('%s rog 0x%02x pulseId 0x%014x time %d.%09d to %d link(s)',
                TransitionId.names.get(tid, tid), rog, self.last_pid, sec, ns, len(targets))
        return True

    def _flush(self):
        for l in self.links.values():
            if l.outbox:
                self.sock.send_multipart([l.identity, b'FRAMES', b''.join(l.outbox)])
                l.outbox = []

    def _insert(self, groups):
        # One frame per distinct header among the groups (normally they are all equal)
        byhdr = collections.OrderedDict()
        for g in range(NUM_GROUPS):
            if groups & (1 << g):
                byhdr.setdefault(self.msghdr[g], 0)
                byhdr[self.msghdr[g]] |= 1 << g
        for hdr, rog in byhdr.items():
            tid = hdr & 0xf
            if not droppable(hdr):
                self.pending.append((tid, rog))
            elif self.pending or not self._emit(tid, rog):
                logging.debug('dropped %s (deadtime)', TransitionId.names.get(tid, tid))

    def _send_pending(self):
        while self.pending:
            tid, rog = self.pending[0]
            if not self._emit(tid, rog):
                return
            self.pending.popleft()

    def group_rate(self, g):
        """Group g's L1Accept rate: its fixed-rate marker with --fixed-rates (L0Select 0 and a
        marker no faster than --max-rate), else SIM:L1Rate."""
        if self.fixed_rates and self.l0select[g] == 0:
            hz = fixed_rate_hz(self.fixed_rate[g])
            if hz is not None and hz <= self.max_rate:
                return hz
        return self.rate

    def tick_rate(self):
        """The rate simxpm ticks at: the fastest enabled group's."""
        active = self.l0en & ~self.inhibit & 0xff
        rates = [self.group_rate(g) for g in range(NUM_GROUPS) if active & (1 << g)]
        return max(rates) if rates else self.rate

    def _tick_groups(self):
        """The groups that fire on this tick: every enabled one, or with --fixed-rates those
        whose marker falls on it (a group k times slower than the fastest fires every k-th)."""
        active = self.l0en & ~self.inhibit & 0xff
        if not self.fixed_rates or not active:
            return active
        rates = {g: self.group_rate(g) for g in range(NUM_GROUPS) if active & (1 << g)}
        fastest = max(rates.values())
        rog = 0
        for g, hz in rates.items():
            if self.tick % max(1, int(round(fastest / hz))) == 0:
                rog |= 1 << g
        self.tick += 1
        return rog

    def _l1(self):
        """One L1Accept tick."""
        rog = self._tick_groups()
        if not rog:
            return
        for g in range(NUM_GROUPS):
            if rog & (1 << g):
                self.num_l0inp[g] += 1
        targets = self._targets(rog)
        blocked = [l for l in targets if l.credit == 0 or self._full(l)]
        if self.pending or blocked:
            for l in blocked:
                l.blocked += 1
            return
        low = (rog & -rog).bit_length() - 1
        for g in range(NUM_GROUPS):
            if rog & (1 << g):
                self.num_l0acc[g] += 1
        self.coinc[rog] = self.coinc.get(rog, 0) + 1
        self._emit(TransitionId.L1Accept, rog, self.num_l0acc[low])
        for g in range(NUM_GROUPS):     # PATT:GROUPS First/Last/MinIntv/MaxIntv of the second
            if rog & (1 << g):
                p = self.patt.get(g)
                if p is None:
                    self.patt[g] = [self.last_pid, self.last_pid, None, 0]
                else:
                    d = self.last_pid - p[1]
                    p[1], p[2], p[3] = self.last_pid, d if p[2] is None else min(p[2], d), max(p[3], d)
        if self.camera is not None:
            self.camera.post(self.last_sec, self.last_ns, self.num_l0acc[low])
        if self.bld is not None:
            self.bld.send(self.last_sec, self.last_ns, self.last_pid, self.num_l0acc[low])
        for g in range(NUM_GROUPS):     # Step end: stop the step's groups, report done
            if (self.step_groups[g] and not self.step_done[g] and
                    self.num_l0acc[g] >= self.step_end[g]):
                self.inhibit |= self.step_groups[g]
                self.step_done[g] = True
                self._post(f'{self.prefix}:PART:{g}:StepDone', 1)
                self._post_counts()
                logging.info('step done for group %d at %d L1Accepts', g, self.num_l0acc[g])

    def _full(self, link):
        """True while SIM:LinkFull has link assert full (module doc)."""
        share = self.link_full[link.number] if link.number < NUM_LINKS else 0.
        return share > 0. and (time.monotonic() - self.full_t0) % FULL_PERIOD < share * FULL_PERIOD

    def link_counts(self):
        """{alias: {link, group, l1acc}}: the L1Accepts each DRP was sent (SIM:LinkL1Acc)."""
        return {l.alias: {'link': l.number, 'group': l.group, 'l1acc': l.l1acc}
                for l in self.links.values()}

    def _post_counts(self):
        for g in range(NUM_GROUPS):
            self._post(f'{self.prefix}:PART:{g}:NumL0Acc', float(self.num_l0acc[g]))
            self._post(f'{self.prefix}:PART:{g}:NumL0Inp', float(self.num_l0inp[g]))
        self._post(f'{self.prefix}:SIM:LinkL1Acc', json.dumps(self.link_counts(), sort_keys=True))

    def _do(self, command, arg, value):
        if command == 'msghdr':
            self.msghdr[arg] = value
        elif command == 'insert':
            self._insert(value)
        elif command == 'l0enable':
            self.l0en |= value
            self.tick = 0
            logging.info('L0 enable 0x%02x -> 0x%02x%s', value, self.l0en, ''.join(
                f'; group {g} at {self.group_rate(g):g} Hz' for g in range(NUM_GROUPS)
                if self.fixed_rates and value & (1 << g)))
        elif command == 'l0disable':
            self.l0en &= ~value
            self._post_counts()
            logging.info('L0 disable 0x%02x -> 0x%02x; NumL0Acc %s; per link %s', value, self.l0en,
                         self.num_l0acc, json.dumps(self.link_counts(), sort_keys=True))
        elif command == 'l0reset':
            for g in range(NUM_GROUPS):
                if value & (1 << g):
                    self.num_l0acc[g] = self.num_l0inp[g] = 0
                    self.run_time[g] = 0.
            for l in self.links.values():
                if l.group is not None and value & (1 << l.group):
                    l.l1acc = 0
            self._post_counts()
        elif command == 'stepgroups':
            self.inhibit &= ~self.step_groups[arg]
            self.step_groups[arg] = value
        elif command == 'stepend':
            self.step_end[arg] = value
            self.step_done[arg] = False
            self.inhibit &= ~self.step_groups[arg]
            self._post(f'{self.prefix}:PART:{arg}:StepDone', 0)
        elif command == 'rate':
            self.rate = float(value)
        elif command == 'linkfull':
            full = [min(1., max(0., float(v))) for v in list(value)[:NUM_LINKS]]
            self.link_full = full + [0.] * (NUM_LINKS - len(full))
            self.full_t0 = time.monotonic()
            logging.info('SIM:LinkFull: %s', {n: d for n, d in enumerate(self.link_full) if d} or 'none')
        elif command in ('l0select', 'fixedrate'):
            (self.l0select if command == 'l0select' else self.fixed_rate)[arg] = int(value)
            if self.fixed_rates:
                hz = fixed_rate_hz(self.fixed_rate[arg])
                logging.info('group %d: L0Select %d FixedRate %d -> %g Hz%s', arg, self.l0select[arg],
                             self.fixed_rate[arg], self.group_rate(arg),
                             f' (marker {hz:g} Hz is above --max-rate {self.max_rate:g})'
                             if self.l0select[arg] == 0 and hz and hz > self.max_rate else '')

    # --- DRP links --------------------------------------------------------------------

    def _link_ready(self, number, ready):
        if number < NUM_PORTS:
            for label in ('LinkTxReady', 'LinkRxReady'):
                self._post(f'{self.prefix}:{label}{number}', ready)

    def _receive(self):
        while True:
            try:
                parts = self.sock.recv_multipart(zmq.NOBLOCK)
            except zmq.Again:
                return
            if len(parts) < 2:
                continue
            identity, kind, body = parts[0], parts[1], parts[2] if len(parts) > 2 else b''
            link = self.links.get(identity)
            if kind == b'HELLO':
                info = json.loads(body or b'{}')
                alias = info.get('alias', identity.hex())
                for old in [i for i, l in self.links.items() if l.alias == alias]:
                    del self.links[old]
                number = self.link_numbers.get(alias)
                if number is None:
                    used = set(self.link_numbers.values())
                    number = next(n for n in range(NUM_LINKS) if n not in used)
                    self.link_numbers[alias] = number
                self.links[identity] = Link(identity, alias, number)
                self._post(f'{self.prefix}:LinkLabel{number}', alias)
                self.sock.send_multipart([identity, b'WELCOME', json.dumps(
                    {'xpm': self.xpm, 'link': number, 'pvbase': self.pvbase}).encode()])
                self._post(f'{self.prefix}:SIM:NumLinks', len(self.links))
                self._link_ready(number, 1)
                logging.info('link %d: %s (%s pid %s)', number, alias, info.get('host'), info.get('pid'))
            elif link is None:
                logging.warning('%s from an unregistered DRP; restart that DRP', kind.decode())
            elif kind == b'CREDIT':
                link.credit += struct.unpack('<I', body[:4])[0]
            elif kind == b'CONNECT':
                link.group = int(json.loads(body)['group'])
                link.l1acc = 0
                self._post(f'{self.prefix}:LinkGroupMask{link.number}', 1 << link.group)
                logging.info('link %d: %s joins readout group %d', link.number, link.alias, link.group)
            elif kind == b'DISCONNECT':
                link.group = None
                self._post(f'{self.prefix}:LinkGroupMask{link.number}', 0)
                link.outbox = []
                logging.info('link %d: %s leaves its readout group', link.number, link.alias)
            elif kind == b'BYE':
                del self.links[identity]
                self._post(f'{self.prefix}:SIM:NumLinks', len(self.links))
                self._link_ready(link.number, 0)
                logging.info('link %d: %s is gone', link.number, link.alias)

    def _receive_pull(self):
        """Apply control.py -X messages, in order, as the PVA puts would be."""
        while True:
            try:
                msg = self.pull_sock.recv_json(zmq.NOBLOCK)
            except zmq.Again:
                return
            except ValueError as e:     # Not JSON
                logging.warning('pull: bad message: %s', e)
                continue
            try:
                commands, pvs = pull_commands(msg)
            except (ValueError, AttributeError, TypeError) as e:
                logging.warning('pull: ignored: %s', e)
                continue
            self.pull_count += 1
            logging.debug('pull: %s', msg)
            for command in commands:
                self._do(*command)
            for name in pvs:
                if name in self.pvs:
                    self._post(name, msg['value'])
                else:
                    logging.warning('pull: no PV %s to post', name)

    def _stats(self, dt):
        for g in range(NUM_GROUPS):
            P = f'{self.prefix}:PART:{g}'
            dead = [0.] * NUM_LINKS
            ticks = self.num_l0inp[g] - self._last_inp[g]
            for l in self.links.values():
                if l.group == g and ticks:
                    dead[l.number] = min(1., l.blocked / ticks)
            if dead != self._last_dead[g]:      # posted when it changes (a value put to it stays until then)
                self._post(f'{P}:DeadFLnk', dead)
                self._last_dead[g] = dead
            acc = self.num_l0acc[g] - self._last_acc[g]
            self._post(f'{P}:L0AccRate', acc / dt)
            self._post(f'{P}:L0InpRate', ticks / dt)
            self._post(f'{P}:L1Rate', acc / dt)
            if (self.l0en & ~self.inhibit) & (1 << g):
                self.run_time[g] += dt
            self._post(f'{P}:RunTime', self.run_time[g])
            self._post(f'{P}:NumL1', float(self.num_l0acc[g]))
            self._post(f'{P}:DeadFrac', (ticks - acc) / ticks if ticks else 0.)
            self._post(f'{P}:DeadTime', ((self.num_l0inp[g] - self.num_l0acc[g]) / self.num_l0inp[g])
                       if self.num_l0inp[g] else 0.)
        for l in self.links.values():
            l.blocked = 0
        self._post_patt()
        self._post_sfp()
        self._last_acc = list(self.num_l0acc)
        self._last_inp = list(self.num_l0inp)
        self._post_counts()

    def _post_sfp(self):
        """pyxpm SFPStatus / QSFPStatus post their table each time their update has visited every link (xpmpva shows
        a table once a post comes after its window is built): the same fixed values, once a second."""
        self._post(f'{self.prefix}:SFPSTATUS', [{'LossOfSignal': 0, 'ModuleAbsent': 0, 'TxPower': 0.5, 'RxPower': 0.25}
                                                for _ in range(14)])
        self._post(f'{self.prefix}:QSFPSTATUS', [{'TxPower': 0.5, 'RxPower': 0.25} for _ in range(8)])

    def _post_patt(self):
        """PATT:GROUPS: per group, Sum = its L0Accepts of the last second, First and Last the low 20 bits of the
        pulse IDs of the first and last of them, MinIntv and MaxIntv the fewest and most pulse IDs between two of
        them (20 bits all ones for none, the empty value xpmpva's Pattern tab shows as '-'); PATT:COINC as below."""
        rows = [{c: 0 for c in PATT_STATS} for _ in range(NUM_GROUPS)]
        none = (1 << 20) - 1
        for g in range(NUM_GROUPS):
            rows[g]['Sum'] = self.num_l0acc[g] - self._last_acc[g]
            first, last, lo, hi = self.patt.get(g) or (None, None, None, 0)
            rows[g].update(First=none if first is None else first & none, Last=none if last is None else last & none,
                           MinIntv=none if lo is None else min(lo, none), MaxIntv=min(hi, none))
        self.patt = {}
        coinc = []
        for i in range(NUM_GROUPS):         # pyxpm order: (0,0) (0,1) .. (0,7) (1,1) .. (7,7)
            for j in range(i, NUM_GROUPS):
                coinc.append(sum(n for m, n in self.coinc.items() if m & (1 << i) and m & (1 << j)))
        self.coinc = {}
        self._post(f'{self.prefix}:PATT:GROUPS', rows)
        self._post(f'{self.prefix}:PATT:COINC', [{'Coinc': c} for c in coinc])

    def run(self):
        ctx = zmq.Context.instance()
        self.sock = ctx.socket(zmq.ROUTER)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.bind(self.endpoint)
        logging.info('frames on %s', self.endpoint)
        poller = zmq.Poller()
        poller.register(self.sock, zmq.POLLIN)
        self.pull_sock = None
        if self.pull:
            self.pull_sock = ctx.socket(zmq.PULL)
            self.pull_sock.setsockopt(zmq.LINGER, 0)
            self.pull_sock.bind(self.pull)
            poller.register(self.pull_sock, zmq.POLLIN)
            logging.info('control.py -X messages on %s', self.pull)
        self._last_acc = [0] * NUM_GROUPS
        self._last_inp = [0] * NUM_GROUPS
        self._last_dead = [None] * NUM_GROUPS
        next_l1 = time.monotonic()
        next_stats = next_l1 + 1.
        while not self.stop.is_set():
            rate = self.tick_rate()
            running = bool(self.l0en & ~self.inhibit) and rate > 0
            wait = max(0., next_l1 - time.monotonic()) if running else 0.1
            poller.poll(min(wait, 0.1) * 1000)
            self._receive()
            if self.pull_sock is not None:
                self._receive_pull()    # Before the PVA commands: sent first, applied first
            while True:
                try:
                    self._do(*self.commands.get_nowait())
                except queue.Empty:
                    break
            self._send_pending()
            now = time.monotonic()
            rate = self.tick_rate()
            running = bool(self.l0en & ~self.inhibit) and rate > 0
            if not running:
                next_l1 = now
            else:
                if now - next_l1 > 0.1:     # Fell behind: a real XPM does not catch up
                    next_l1 = now
                while next_l1 <= now:
                    self._l1()
                    next_l1 += 1. / rate
            self._flush()
            if now >= next_stats:
                self._stats(1. + now - next_stats)
                next_stats = now + 1.
        self.sock.close()
        if self.pull_sock is not None:
            self.pull_sock.close()


def _tcp_host(endpoint):
    return endpoint.split('://', 1)[1].rsplit(':', 1)[0] if endpoint and endpoint.startswith('tcp://') else None


def pull_endpoint(pull, prefix):
    """--pull value -> endpoint to bind: 'auto' is loopback at control.py's xpm_pull_port."""
    if pull == 'none':
        return None
    if pull == 'auto':
        from psdaq.control.ControlDef import xpm_pull_port
        return f'tcp://127.0.0.1:{xpm_pull_port(prefix)}'
    return pull


def _local_only(endpoint, bind, allow_remote, pull=None):
    for what, h in (('--frames', _tcp_host(endpoint)), ('--bind', bind), ('--pull', _tcp_host(pull))):
        if h is not None and h not in ('127.0.0.1', 'localhost') and not allow_remote:
            raise SystemExit(f'simxpm: {what} host {h} is not loopback; use --allow-remote to mean it')


def main():
    parser = argparse.ArgumentParser(description='Software XPM: XPM PVs plus a timing frame '
                                     'stream for DRPs started with -d sim://<host>:<port>')
    parser.add_argument('-P', metavar='PVBASE', required=True, help='PV base, as control.py -B (e.g. DAQ:SIM)')
    parser.add_argument('-x', metavar='XPM', type=int, default=0, help='XPM number, as control.py -x (default 0)')
    parser.add_argument('--frames', default='tcp://127.0.0.1:31000', help='frame endpoint to bind (default %(default)s)')
    parser.add_argument('--rate', type=float, default=1000., help='L1Accept rate in Hz (default %(default)s)')
    parser.add_argument('--pull', default='auto',
                        help="endpoint for control.py -X messages: 'auto' (default) binds "
                        "tcp://127.0.0.1:<xpm_pull_port>, as pyxpm does on all interfaces; 'none' disables")
    parser.add_argument('--bind', default='127.0.0.1', help='PVA server interface (default %(default)s)')
    parser.add_argument('--allow-remote', action='store_true', help='allow non-loopback --frames/--bind/--pull')
    parser.add_argument('--fwbuild', default=FW_BUILD,
                        help="FwBuild string (xpmpva: 'Kcu1500' or 'C1100' in it -> QSFP tabs, 'xtpg' -> CuTiming)")
    parser.add_argument('--camera-pv', metavar='NAME', default=None,
                        help='also serve NAME, an NTNDArray camera PV updated with the time of every '
                             'L1Accept (for drp_pva)')
    parser.add_argument('--camera-seed', type=lambda s: int(s, 0), default=0,
                        help='seed of the --camera-pv images (default %(default)s)')
    parser.add_argument('--fixed-rates', action='store_true',
                        help='a readout group whose L0Select is 0 (FixedRate) fires on the marker its '
                             'L0Select_FixedRate selects, if no faster than --max-rate (default: every '
                             'group at --rate)')
    parser.add_argument('--max-rate', type=float, default=MAX_TICK_HZ,
                        help='fastest fixed-rate marker followed (default %(default)g Hz)')
    parser.add_argument('--bld', metavar='PREFIX', default=None,
                        help='also be a BLD source: serve PREFIX:BLD_PAYLOAD and send one packet per '
                             'L1Accept tick to --bld-dest (multicast, TTL 1, 127.0.0.1 only)')
    parser.add_argument('--bld-dest', metavar='ADDR:PORT', default='239.254.31.5:31205',
                        help='--bld multicast group and port, in 239.0.0.0/8 outside 239.255.0.0/16 '
                             '(default %(default)s)')
    parser.add_argument('--bld-seed', type=lambda s: int(s, 0), default=0,
                        help='seed of the --bld values (default %(default)s)')
    parser.add_argument('-v', action='store_true', help='be verbose')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO,
                        format='%(asctime)s simxpm %(levelname)s %(message)s')
    pull = pull_endpoint(args.pull, f'{args.P}:XPM:{args.x}')
    _local_only(args.frames, args.bind, args.allow_remote, pull)
    if args.bld:
        try:
            check_bld_dest(args.bld_dest)
        except ValueError as e:
            raise SystemExit(f'simxpm: {e}')

    conf = {'EPICS_PVAS_INTF_ADDR_LIST': args.bind,
            'EPICS_PVAS_BEACON_ADDR_LIST': args.bind,
            'EPICS_PVAS_AUTO_BEACON_ADDR_LIST': 'NO'}
    for key in ('SERVER_PORT', 'BROADCAST_PORT'):
        value = os.environ.get(f'EPICS_PVAS_{key}', os.environ.get(f'EPICS_PVA_{key}'))
        if value:
            conf[f'EPICS_PVAS_{key}'] = value

    sim = SimXpm(args.P, args.x, args.frames, args.rate, pull, args.camera_pv, args.camera_seed,
                 args.fixed_rates, args.max_rate, args.bld, args.bld_dest, args.bld_seed, fwbuild=args.fwbuild)
    with Server(providers=[sim.provider], conf=conf, useenv=False) as server:
        logging.info('serving %d PVs under %s; server conf %s', len(sim.pvs), sim.prefix, server.conf())
        print('simxpm: ready, %d PVs under %s, pid %d' % (len(sim.pvs), sim.prefix, os.getpid()), flush=True)
        try:
            sim.run()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
