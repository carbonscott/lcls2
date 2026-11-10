"""tprframes: the timing frames of a simulated TPR card (tpr::Client with PSDAQ_SIM_TPR).

    python -m psdaq.sim.tprframes CARD [CARD ...] [--max-rate HZ] [--duration S]

With PSDAQ_SIM_TPR=<dir>, tpr::Client (psdaq/psdaq/tpr/Client.cc) maps the file <dir>/tpr<x> as the card's
register map (TprReg) and <dir>/tpr<x><channel> as that channel's message queues (Queues,
psdaq/psdaq/tpr/Queues.hh), where the driver puts the timing frames the card receives.  This process does what
the card and its driver do with those frames.  For every channel of a CARD (its register map file) that a program
enabled (TprBase channel control bit 0) on a fixed rate (evtSel mode 0, TprBase::setupChannel with a FixedRate),
and whose queue file the program mapped, it writes every pulse of that rate's marker into the queue file as the
driver does: the frame (Frame.hh) in allq[gwp], its index at allrp[channel].idx[allwp[channel]], then
allwp[channel] and gwp advanced, so tpr::Client::advance() returns it.

The markers run on the system clock: LCLS-II's pulses (1300/1.4 MHz, simxpm.TIMING_BASE_HZ) counted from the EPICS
epoch, pulse n at time ceil(n * 14000 / 13) ns, and fixed rate r's marker fires on the pulses n divisible by
simxpm.FIXED_RATE_DIV[r] (929 kHz / 1, 13, 91, 910, 9100, 91000, 910000), as pyxpm's markers do, so fixed rate 4
fires at 102 Hz; a frame's 'rates' has bit r set for every marker its pulse fires.  Its timeStamp is that pulse's
time (sec << 32 | ns) and its pulseId the one simxpm gives that instant (psdaq.sim.simxpm.timing_now, the pulse IDs
of the DAQ's L1Accepts), so a frame matches the DAQ's timing.  A channel on another selection (AC rate, event code,
partition), or on a rate faster than --max-rate, gets no frame, and the log says so.  The registers are re-read
every REREAD seconds, so a channel a program stops (control 0) gets no more frames.
"""

import argparse
import mmap
import os
import signal
import struct
import sys
import time

from psdaq.sim.simxpm import FIXED_RATE_DIV, TIMING_BASE_HZ, POSIX_TIME_AT_EPICS_EPOCH, PID_MASK

# TprReg (psdaq/psdaq/tpr/Module.hh): TprBase's channels from 0x80000, 0x1000 bytes apart: control, evtSel
CHANNELS, STRIDE, NCHANNELS = 0x80000, 0x1000, 14
# Queues (psdaq/psdaq/tpr/Queues.hh): TprEntry allq[MAX_TPR_ALLQ], TprEntry bsaq[MAX_TPR_BSAQ],
# TprQIndex allrp[MOD_SHARED] (long long idx[MAX_TPR_ALLQ]), long long allwp[MOD_SHARED], bsawp, gwp, int fifofull
MAX_TPR_ALLQ, MAX_TPR_BSAQ, MSG_SIZE, MOD_SHARED = 32 * 1024, 1024, 32, 14
ENTRY = 4 * MSG_SIZE + 8                # TprEntry: uint32_t word[MSG_SIZE], uint64_t fifo_tsc
ALLQ = 0
ALLRP = ALLQ + (MAX_TPR_ALLQ + MAX_TPR_BSAQ) * ENTRY
ALLWP = ALLRP + MOD_SHARED * MAX_TPR_ALLQ * 8
GWP = ALLWP + MOD_SHARED * 8 + 8        # after allwp[] and bsawp
QUEUES_SIZE = GWP + 8 + 8               # gwp, then int fifofull padded to the struct's 8-byte alignment
# Frame (psdaq/psdaq/tpr/Frame.hh): channels, msg_type, msg_size (words), pulseId, timeStamp (sec << 32 | ns,
# EPICS epoch), rates, acTimeSlot, beamRequest, beamEnergy[4], photonWavelen[2], reserved, mpsLimit, mpsClass[4],
# control[18]
FRAME = struct.Struct('<HHIQQHHI4H2HHH4H18H')
Q = struct.Struct('<q')
REREAD = 0.2                            # s: how often the channel registers are read
MAX_HZ = 2000.                          # --max-rate default: the fastest marker delivered (as simxpm's --max-rate)
MAX_BACKLOG = 4096                      # pulses: a channel further behind than this skips ahead (the log says so)


def pulse_now():
    """The LCLS-II pulse (1300/1.4 MHz since the EPICS epoch) of now."""
    return (time.time_ns() - POSIX_TIME_AT_EPICS_EPOCH * 10**9) * 13 // 14000


def pulse_time(n):
    """(EPICS-epoch seconds, ns) of pulse n: ceil(n * 14000 / 13) ns (so pulse_of gives n back)."""
    return divmod(-(-n * 14000 // 13), 10**9)


def pulse_of(sec, ns):
    """The pulse of EPICS-epoch time (sec, ns)."""
    return (sec * 10**9 + ns) * 13 // 14000


def stamp_pid(sec, ns):
    """The pulse ID simxpm gives EPICS-epoch time (sec, ns) (psdaq.sim.simxpm.timing_now)."""
    return ((sec * 14000000) // 13 + (ns * 14) // 13000) & PID_MASK


def rates_mask(n):
    """Frame.rates: bit r set for each fixed-rate marker r that fires on pulse n."""
    return sum(1 << r for r, d in enumerate(FIXED_RATE_DIV) if n % d == 0)


def selection(control, evt_sel):
    """What a channel's registers select: ('fixed', rate index), (mode name, value), or None if disabled."""
    if not control & 1:
        return None
    mode = (evt_sel >> 11) & 3
    if mode == 0:
        return ('fixed', evt_sel & 0xf)
    return (('ac rate', 'event code', 'partition')[mode - 1], evt_sel & 0x3ff)


class Channel:
    def __init__(self, card, ch):
        self.card, self.ch = card, ch
        self.path = f'{card.path}{ch:x}'        # as tpr::Client: sprintf("%s%x", devname, channel)
        self.sel = self.mm = self.div = self.next = None
        self.frames = 0
        self.last = None
        self.said = None

    def say(self, what):
        if what != self.said:
            self.said = what
            log(f'{self.card.path} channel {self.ch}: {what}')

    def update(self, sel, max_hz):
        """Follow the channel's registers: map its queue file once a program has, and find its divisor."""
        if sel != self.sel:
            self.sel, self.div, self.next = sel, None, None
        if sel is None:
            self.say('disabled (control bit 0 clear): no frames')
            return
        if sel[0] != 'fixed':
            self.say(f'{sel[0]} {sel[1]} selected: this stand-in delivers fixed-rate markers only, no frames')
            return
        r = sel[1]
        if r >= len(FIXED_RATE_DIV):
            self.say(f'fixed rate {r}: no such marker, no frames')
            return
        hz = TIMING_BASE_HZ / FIXED_RATE_DIV[r]
        if hz > max_hz:
            self.say(f'fixed rate {r} ({hz:.1f} Hz) is faster than --max-rate {max_hz:g} Hz: no frames')
            return
        if self.mm is None:
            try:
                if os.path.getsize(self.path) != QUEUES_SIZE:
                    raise OSError(f'{os.path.getsize(self.path)} B, not sizeof(Queues) {QUEUES_SIZE} B')
                fd = os.open(self.path, os.O_RDWR)
                try:
                    self.mm = mmap.mmap(fd, QUEUES_SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
                finally:
                    os.close(fd)
            except OSError as ex:
                self.say(f'fixed rate {r} ({hz:.1f} Hz) selected, waiting for its queue file {self.path}: {ex}')
                return
        if self.div is None:
            self.div = FIXED_RATE_DIV[r]
            self.say(f'fixed rate {r} ({hz:.1f} Hz): frames to {self.path}')

    def due(self, now):
        """The pulses of this channel's marker up to pulse `now` not yet delivered."""
        if self.div is None:
            return []
        d = self.div
        if self.next is None:
            self.next = (now // d + 1) * d
        if (now - self.next) // d > MAX_BACKLOG:
            skip = (now // d) * d
            log(f'{self.card.path} channel {self.ch}: {(skip - self.next) // d} pulses behind, skipped to {skip:#x}')
            self.next = skip
        out = list(range(self.next, now + 1, d))
        if out:
            self.next = out[-1] + d
        return out


class Card:
    def __init__(self, path):
        self.path = path
        self.regs = None
        self.channels = [Channel(self, i) for i in range(NCHANNELS)]
        self.said = None

    def read(self, max_hz):
        if self.regs is None:
            try:
                need = CHANNELS + NCHANNELS * STRIDE
                if os.path.getsize(self.path) < need:
                    raise OSError(f'{os.path.getsize(self.path)} B, shorter than the channel registers')
                fd = os.open(self.path, os.O_RDONLY)
                try:
                    self.regs = mmap.mmap(fd, need, mmap.MAP_SHARED, mmap.PROT_READ)
                finally:
                    os.close(fd)
                log(f'{self.path}: register map mapped (a program opened the card)')
            except OSError as ex:
                if self.said != str(ex):
                    self.said = str(ex)
                    log(f'{self.path}: waiting for the register map: {ex}')
                return
        for i, c in enumerate(self.channels):
            control, evt_sel = struct.unpack_from('<II', self.regs, CHANNELS + i * STRIDE)
            c.update(selection(control, evt_sel), max_hz)

    def deliver(self, now):
        """Write every due frame, in pulse ID order, into the queue file of each channel that takes it (the card's
        channels map one file each, <card><channel>): the frame in allq[gwp], its index in allrp[channel], then
        allwp[channel] (which the reader follows) and gwp advanced."""
        due = {}
        for c in self.channels:
            for n in c.due(now):
                due.setdefault(n, []).append(c)
        for n in sorted(due):
            chans = due[n]
            sec, ns = pulse_time(n)
            pid = stamp_pid(sec, ns)
            frame = FRAME.pack(sum(1 << c.ch for c in chans), 0, FRAME.size // 4, pid, (sec << 32) | ns,
                               rates_mask(n), *([0] * 32))   # then acTimeSlot .. control[18]: 0
            for c in chans:
                mm = c.mm
                gwp = Q.unpack_from(mm, GWP)[0]
                off = ALLQ + (gwp & (MAX_TPR_ALLQ - 1)) * ENTRY
                mm[off:off + FRAME.size] = frame
                Q.pack_into(mm, off + 4 * MSG_SIZE, time.monotonic_ns())        # fifo_tsc
                wp = Q.unpack_from(mm, ALLWP + 8 * c.ch)[0]
                Q.pack_into(mm, ALLRP + (c.ch * MAX_TPR_ALLQ + (wp & (MAX_TPR_ALLQ - 1))) * 8, gwp)
                Q.pack_into(mm, ALLWP + 8 * c.ch, wp + 1)     # last but gwp: the reader takes the frame from here
                Q.pack_into(mm, GWP, gwp + 1)
                c.frames += 1
                c.last = (pid, sec, ns)

    def next_due(self):
        return min((c.next for c in self.channels if c.div is not None and c.next is not None), default=None)


def log(text):
    print(f'{time.strftime("%Y-%m-%dT%H:%M:%S")} tprframes: {text}', flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('cards', nargs='+', metavar='CARD', help='a simulated card\'s register map file (<dir>/tpr<x>)')
    p.add_argument('--max-rate', type=float, default=MAX_HZ, help='the fastest fixed-rate marker delivered (Hz)')
    p.add_argument('--duration', type=float, default=None, help='stop after this many seconds (default: never)')
    args = p.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    cards = [Card(c) for c in args.cards]
    log(f'ready: {len(cards)} card(s): {" ".join(args.cards)}; markers up to {args.max_rate:g} Hz')
    end = time.monotonic() + args.duration if args.duration else None
    reread, report = 0., time.monotonic() + 10
    try:
        while end is None or time.monotonic() < end:
            if time.monotonic() >= reread:
                for c in cards:
                    c.read(args.max_rate)
                reread = time.monotonic() + REREAD
            now = pulse_now()
            for c in cards:
                c.deliver(now)
            if time.monotonic() >= report:
                report = time.monotonic() + 10
                for card in cards:
                    for c in card.channels:
                        if c.last:
                            log(f'{card.path} channel {c.ch}: {c.frames} frames, the last pulseId {c.last[0]:#x} '
                                f'time {c.last[1]}.{c.last[2]:09d}')
            nxt = [n for n in (c.next_due() for c in cards) if n is not None]
            wait = (min(nxt) - pulse_now()) / TIMING_BASE_HZ if nxt else REREAD
            time.sleep(min(max(wait, 0.0002), REREAD))
    finally:
        for card in cards:
            for c in card.channels:
                if c.frames:
                    log(f'{card.path} channel {c.ch}: {c.frames} frames in all')
    return 0


if __name__ == '__main__':
    sys.exit(main())
