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

control.py started with '-X <host>' sends the frame-producing writes (MsgHeader, GroupMsgInsert,
GroupL0Enable/Disable, GroupL0Reset, StepEnd, StepGroups) as JSON over a ZMQ PUSH socket instead
of PVA, to the PULL socket that pyxpm binds at xpm_pull_port(<pvbase>:XPM:<n>)
(psdaq/pyxpm/pvctrls.py zrcv, control.py DaqXPM).  simxpm binds the same PULL port on loopback and
treats those messages exactly like the PVA puts, so both control.py modes work.  Without -X,
control.py still connects its PUSH socket to 'tcp://None:<port>', so run it with -X 127.0.0.1.

Both the PVA server and the frame and PULL sockets bind to the loopback interface unless told
otherwise.
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
from p4p.nt import NTScalar
from p4p.server import Server, StaticProvider
from p4p.server.thread import SharedPV

POSIX_TIME_AT_EPICS_EPOCH = 631152000
NUM_GROUPS = 8
NUM_LINKS = 32                          # Length of DeadFLnk, as in pyxpm
NUM_PORTS = 14                          # Front-panel links with per-link PVs, as ts_connect.py uses
FW_BUILD = 'simxpm (psdaq/psdaq/sim/simxpm.py): software XPM, no firmware'
PID_MASK = (1 << 56) - 1


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
        if self._command:
            self._sim.command(self._command, self._arg, value['value'])
        op.done()


class SimXpm:
    def __init__(self, pvbase, xpm, endpoint, rate, pull=None):
        self.pvbase = pvbase
        self.xpm = xpm
        self.prefix = f'{pvbase}:XPM:{xpm}'
        self.endpoint = endpoint
        self.pull = pull                # control.py -X endpoint to bind, or None
        self.pull_count = 0
        self.rate = float(rate)
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
        self.pending = collections.deque()      # Transitions waiting for credit
        self.links = {}                 # identity -> Link
        self.link_numbers = {}          # alias -> link number, kept across restarts
        self.last_pid = 0
        self.frames_sent = 0

        self.provider = StaticProvider('simxpm')
        self.pvs = {}
        self._make_pvs()

    # --- PVs --------------------------------------------------------------------------

    def _add(self, name, ntype, initial, handler=None):
        nt = NTScalar(ntype)
        pv = SharedPV(initial=nt.wrap(initial, timestamp=time.time()), handler=handler or _Put(self))
        self.provider.add(name, pv)
        self.pvs[name] = (pv, nt)
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
            # GroupCtrls); simxpm keeps them, its L1Accepts stay at SIM:L1Rate
            for label in ('L0Select', 'L0Select_FixedRate', 'L0Select_ACRate', 'L0Select_ACTimeslot',
                          'L0Select_EventCode', 'L0Select_Sequence', 'L0Select_SeqBit'):
                self._add(f'{P}:{label}', 'I', 0)
            self._add(f'{P}:L0RawUpdate', 'I', 1)
            for i in range(4):
                self._add(f'{P}:InhInterval{i}', 'I', 10)
                self._add(f'{P}:InhLimit{i}', 'I', 4)
                self._add(f'{P}:InhEnable{i}', 'I', 0)
        # Per-link PVs that ts_connect.py reads and writes (pvctrls.py LinkCtrls, pvstats.py
        # LinkStatus): LinkRxReady<n> is 1 while a DRP holds link n (a locked receiver)
        for n in range(NUM_PORTS):
            for label in ('LinkGroupMask', 'TxLinkReset', 'RxLinkReset', 'LinkLoopback'):
                self._add(f'{X}:{label}{n}', 'I', 0)
            for label in ('LinkTxReady', 'LinkRxReady', 'LinkRxErr', 'LinkRxErrI', 'LinkRxIsXpm',
                          'RemoteLinkId'):
                self._add(f'{X}:{label}{n}', 'I', 0)
        self._add(f'{X}:FwBuild', 's', FW_BUILD)

    def _post(self, name, value):
        pv, nt = self.pvs[name]
        pv.post(nt.wrap(value, timestamp=time.time()))

    def command(self, command, arg, value):
        self.commands.put((command, arg, value))

    # --- Frame stream -----------------------------------------------------------------

    def _targets(self, rog):
        return [l for l in self.links.values() if l.group is not None and (rog >> l.group) & 1]

    def _emit(self, tid, rog, seq=0):
        """Queue one frame to every target link, if all have credit; return success."""
        targets = self._targets(rog)
        if any(l.credit == 0 for l in targets):
            return False
        self.last_pid, sec, ns = timing_now(self.last_pid)
        frame = pack_frame(tid, self.last_pid, sec, ns, rog, seq)
        for l in targets:
            l.credit -= 1
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

    def _l1(self):
        """One L1Accept tick."""
        rog = self.l0en & ~self.inhibit & 0xff
        if not rog:
            return
        for g in range(NUM_GROUPS):
            if rog & (1 << g):
                self.num_l0inp[g] += 1
        targets = self._targets(rog)
        blocked = [l for l in targets if l.credit == 0]
        if self.pending or blocked:
            for l in blocked:
                l.blocked += 1
            return
        low = (rog & -rog).bit_length() - 1
        for g in range(NUM_GROUPS):
            if rog & (1 << g):
                self.num_l0acc[g] += 1
        self._emit(TransitionId.L1Accept, rog, self.num_l0acc[low])
        for g in range(NUM_GROUPS):     # Step end: stop the step's groups, report done
            if (self.step_groups[g] and not self.step_done[g] and
                    self.num_l0acc[g] >= self.step_end[g]):
                self.inhibit |= self.step_groups[g]
                self.step_done[g] = True
                self._post(f'{self.prefix}:PART:{g}:StepDone', 1)
                self._post_counts()
                logging.info('step done for group %d at %d L1Accepts', g, self.num_l0acc[g])

    def _post_counts(self):
        for g in range(NUM_GROUPS):
            self._post(f'{self.prefix}:PART:{g}:NumL0Acc', float(self.num_l0acc[g]))
            self._post(f'{self.prefix}:PART:{g}:NumL0Inp', float(self.num_l0inp[g]))

    def _do(self, command, arg, value):
        if command == 'msghdr':
            self.msghdr[arg] = value
        elif command == 'insert':
            self._insert(value)
        elif command == 'l0enable':
            self.l0en |= value
            logging.info('L0 enable 0x%02x -> 0x%02x', value, self.l0en)
        elif command == 'l0disable':
            self.l0en &= ~value
            self._post_counts()
            logging.info('L0 disable 0x%02x -> 0x%02x; NumL0Acc %s', value, self.l0en, self.num_l0acc)
        elif command == 'l0reset':
            for g in range(NUM_GROUPS):
                if value & (1 << g):
                    self.num_l0acc[g] = self.num_l0inp[g] = 0
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
                logging.info('link %d: %s joins readout group %d', link.number, link.alias, link.group)
            elif kind == b'DISCONNECT':
                link.group = None
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
            self._post(f'{P}:DeadFLnk', dead)
            self._post(f'{P}:L0AccRate', (self.num_l0acc[g] - self._last_acc[g]) / dt)
            self._post(f'{P}:L0InpRate', ticks / dt)
        for l in self.links.values():
            l.blocked = 0
        self._last_acc = list(self.num_l0acc)
        self._last_inp = list(self.num_l0inp)
        self._post_counts()

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
        next_l1 = time.monotonic()
        next_stats = next_l1 + 1.
        while not self.stop.is_set():
            running = bool(self.l0en & ~self.inhibit) and self.rate > 0
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
            running = bool(self.l0en & ~self.inhibit) and self.rate > 0
            if not running:
                next_l1 = now
            else:
                if now - next_l1 > 0.1:     # Fell behind: a real XPM does not catch up
                    next_l1 = now
                while next_l1 <= now:
                    self._l1()
                    next_l1 += 1. / self.rate
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
    parser.add_argument('-v', action='store_true', help='be verbose')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO,
                        format='%(asctime)s simxpm %(levelname)s %(message)s')
    pull = pull_endpoint(args.pull, f'{args.P}:XPM:{args.x}')
    _local_only(args.frames, args.bind, args.allow_remote, pull)

    conf = {'EPICS_PVAS_INTF_ADDR_LIST': args.bind,
            'EPICS_PVAS_BEACON_ADDR_LIST': args.bind,
            'EPICS_PVAS_AUTO_BEACON_ADDR_LIST': 'NO'}
    for key in ('SERVER_PORT', 'BROADCAST_PORT'):
        value = os.environ.get(f'EPICS_PVAS_{key}', os.environ.get(f'EPICS_PVA_{key}'))
        if value:
            conf[f'EPICS_PVAS_{key}'] = value

    sim = SimXpm(args.P, args.x, args.frames, args.rate, pull)
    with Server(providers=[sim.provider], conf=conf, useenv=False) as server:
        logging.info('serving %d PVs under %s; server conf %s', len(sim.pvs), sim.prefix, server.conf())
        try:
            sim.run()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
