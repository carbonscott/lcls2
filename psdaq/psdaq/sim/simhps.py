"""simhps: a stand-in for the HPS crate that hpsBldServer reads (lab3-bld.cnf: hpsBldServer -a 10.0.3.105).

    python -m psdaq.sim.simhps --reg-port P --diag-port Q [--max-hz HZ]

hpsBldServer (psdaq/psdaq/app/hpsBldServer.cc) talks to its crate on two UDP ports of the crate's address (-a):

  registers   psdaq.pyhpsbld.pyhpsbld.hps_init builds HpsRoot, whose Top (pyhpsbld/hpsbld/_Top.py) opens the crate's
              register space with pyrogue.protocols.UdpRssiPack (RSSI, packetizer v1) and SrpV3 on port 8193 (-r):
              it programs the BLD, BSSS and BSAS engines, and PVCtrls.update (the HPS:FIELDMASK PV) sets
              BldControl.channelMask and Enable.
  diagn. bus  it sends 4 bytes to port 8198 (-d) and reads the packets the crate sends back on that socket
              (psdaq/psdaq/bld/HpsEventIterator.cc): the first event [timeStamp lo, hi, pulseId lo, hi, channel
              mask, beam word, one word per channel of the mask, severity lo, hi], then each next event
              [pulseId delta << 20 | timeStamp delta (ns), beam word, channel words, severity lo, hi].  A beam word
              with bits 31..24 0 is a BSSS packet, with bit 31 a BSAS packet, else BLD, which it publishes.

This process is that crate, on ports of its own (daq_sim.ports 'hps'):

  registers   pyrogue's own RSSI server (UdpRssiPack(server=True): rogue.protocols.udp.Server on every interface of
              the node, ruling R9; the program addresses it by 127.0.0.1) with an SRPv3 responder on tDest 0 over a
              register store of psdaq.sim.rogue_dev (SimStreamDma, Store): registers read back what was last
              written, a seed file (psdaq/sim/seeds/hps.json, PSDAQ_SIM_ROGUE_SEEDS) presets status registers by
              their path in HpsRoot's tree, and every write is logged with the register paths it covers
              (PSDAQ_SIM_ROGUE_LOG, JSON lines).  The tree is HpsRoot itself, built here on the same store (its
              UdpRssiPack replaced by the responder) only to name registers: nothing in it is simulated.
  diagn. bus  a UDP socket on 127.0.0.1:Q.  Once the program has sent its 4 bytes, and while BldControl.Enable is 1
              and BldControl.channelMask is not 0 (what the program wrote), it sends one BLD packet per pulse of
              fixed rate 4 (simxpm.FIXED_RATE_DIV: 102 Hz), each with EVENTS events EVENT_STEP pulses apart (fixed
              rate 2), each event timed at its pulse with the pulse ID simxpm gives that instant
              (psdaq.sim.tprframes.stamp_pid), so they match the DAQ's L1Accepts, and channel k of the mask holding
              channel_value(pulseId, k).  It counts what it sent in BldControl.packets and pulseIdL.

Nothing here opens a device or reaches another host: the register port listens on the node only for the program on
it, the diagnostic bus answers only the sender of its 4 bytes on 127.0.0.1.
"""

import argparse
import json
import os
import signal
import socket
import struct
import sys
import threading
import time

from psdaq.sim.tprframes import pulse_now, pulse_time, stamp_pid
from psdaq.sim.simxpm import FIXED_RATE_DIV, TIMING_BASE_HZ

DEV = 'sim://hps'
RATE = 4                                # fixed rate of the packets (102 Hz)
EVENTS = 4                              # events per packet
EVENT_STEP = FIXED_RATE_DIV[2]          # pulses between the events of a packet (fixed rate 2, 91 pulses)
BEAM = 0x01000000                       # the beam word: bits 31..24 = 1, a BLD packet (hpsBldServer.cc handle_data)
BLD = 'Top.AmcCarrierBsa.BldControl'


def log(msg):
    print(time.strftime('%Y-%m-%dT%H:%M:%S ') + 'simhps: ' + msg, flush=True)


def channel_value(pid, k):
    """The word channel k of the diagnostic bus carries for the event of pulse ID pid."""
    return (pid & 0xffffff) | (k << 24)


def diag_packet(n0, mask, events=EVENTS, step=EVENT_STEP, beam=BEAM):
    """The diagnostic-bus packet of `events` events at pulses n0, n0 + step, ... with the channels of `mask`:
    (bytes, [(pulseId, timeStamp)] of its events)."""
    chans = [k for k in range(31) if (mask >> k) & 1]
    words, evs = [], []
    sec0, ns0 = pulse_time(n0)
    pid0, ts0 = stamp_pid(sec0, ns0), (sec0 << 32) | ns0
    words += [ts0 & 0xffffffff, ts0 >> 32, pid0 & 0xffffffff, pid0 >> 32, mask, beam]
    words += [channel_value(pid0, k) for k in chans] + [0, 0]
    evs.append((pid0, ts0))
    for i in range(1, events):
        sec, ns = pulse_time(n0 + i * step)
        pid = stamp_pid(sec, ns)
        dns = (sec - sec0) * 10**9 + ns - ns0
        words += [((pid - pid0) & 0xfff) << 20 | (dns & 0xfffff), beam]
        words += [channel_value(pid, k) for k in chans] + [0, 0]
        evs.append((pid, (sec << 32) | ns))
    return struct.pack(f'<{len(words)}I', *words), evs


class Crate:
    """The register side: the RSSI server, the SRPv3 responder and HpsRoot's tree on one store."""

    def __init__(self, reg_port):
        import pyrogue
        import pyrogue.protocols
        from psdaq.sim import rogue_dev
        self.sim = rogue_dev.install(DEV, det_type='hps')
        local = self.sim.stream_dma(DEV, 0)             # the tree's SRPv3 peer; its store is the crate's registers
        self.store = local.store
        self.net = rogue_dev.SimStreamDma(DEV, 0)       # the network side's SRPv3 peer, on the same registers
        self.net.store = self.store
        orig = pyrogue.protocols.UdpRssiPack

        class Link:                                     # HpsRoot's register link, here: the responder itself
            def __init__(self, **kwargs):
                pass

            def application(self, dest):
                return local
        pyrogue.protocols.UdpRssiPack = Link
        try:
            from psdaq.pyhpsbld.hpsbld._HpsRoot import HpsRoot
            self.root = HpsRoot(ipAddr='127.0.0.1', pollEn=False, initRead=False)
        finally:
            pyrogue.protocols.UdpRssiPack = orig
        self.root.start()               # rogue_dev applies the seeds and indexes the register paths
        pending = self.sim.pending()
        if pending:
            raise SystemExit(f'simhps: seeds not applied: {pending}')
        self.rudp = orig(name='rudpReg', port=reg_port, packVer=1, jumbo=False, server=True)
        pyrogue.streamConnectBiDir(self.net, self.rudp.application(dest=0))
        bld = self.root.getNode(f'{self.root.name}.{BLD}')
        self.vars = {n: bld.node(n) for n in ('Enable', 'channelMask', 'packets', 'pulseIdL')}
        log(f'registers: RSSI server on UDP port {reg_port} (every interface of this node), SRPv3 on tDest 0, '
            f'tree {self.root.name}, seeds {sorted(self.sim.applied)}')

    def _addr(self, var):
        return var.parent.address + var.offset

    def reg(self, name):
        from psdaq.sim.rogue_dev import _get_bits
        v = self.vars[name]
        a = self._addr(v)
        n = (max(o + s for o, s in zip(v.bitOffset, v.bitSize)) + 7) // 8
        return _get_bits(self.store.raw_read(a, n), a, a, v.bitOffset, v.bitSize)

    def poke(self, name, value):
        v = self.vars[name]
        self.store.poke(self._addr(v), v.bitOffset, v.bitSize, value & ((1 << sum(v.bitSize)) - 1))

    def stop(self):
        try:
            self.root.stop()
        except Exception:
            pass


def serve_diag(crate, port, stop, max_hz):
    """The diagnostic bus: wait for the program's 4 bytes on 127.0.0.1:port, then send it BLD packets while it has
    the BLD enabled with a channel mask."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('127.0.0.1', port))
    s.settimeout(0.2)
    log(f'diagnostic bus on 127.0.0.1:{port}')
    peer = None
    while not stop.is_set() and peer is None:
        try:
            data, peer = s.recvfrom(64)
        except socket.timeout:
            continue
        log(f'diagnostic bus: {peer[0]}:{peer[1]} asked for the stream ({len(data)} B)')
    div = FIXED_RATE_DIV[RATE]
    if TIMING_BASE_HZ / div > max_hz:
        raise SystemExit(f'simhps: fixed rate {RATE} is faster than --max-hz {max_hz}')
    n = (pulse_now() // div + 1) * div
    sent, said, last = 0, None, time.time()
    while not stop.is_set():
        due = n + (EVENTS - 1) * EVENT_STEP
        wait = (due - pulse_now()) * 14000 / 13 / 1e9
        if wait > 0:
            time.sleep(min(wait, 0.2))
            continue
        if pulse_now() - n > 2 * TIMING_BASE_HZ:     # more than 2 s behind (a stall): skip ahead
            n = (pulse_now() // div + 1) * div
            continue
        enable, mask = crate.reg('Enable'), crate.reg('channelMask') & 0x7fffffff
        state = (enable, mask)
        if state != said:
            said = state
            log(f'BldControl.Enable={enable} channelMask=0x{mask:x}: '
                + ('sending BLD packets' if enable and mask else 'no packets'))
        if enable and mask:
            b, evs = diag_packet(n, mask)
            s.sendto(b, peer)
            sent += 1
            crate.poke('packets', sent)
            crate.poke('pulseIdL', evs[-1][0])
            if sent == 1 or time.time() - last >= 10:
                last = time.time()
                log(f'sent {sent} packets; last pulse IDs 0x{evs[0][0]:x}..0x{evs[-1][0]:x}')
        n += div
    log(f'stopped after {sent} packets')
    s.close()



def main(argv=None):
    p = argparse.ArgumentParser(prog='simhps', description=__doc__.split('\n')[0])
    p.add_argument('--reg-port', type=int, required=True, help='UDP port of the register link (RSSI)')
    p.add_argument('--diag-port', type=int, required=True, help='UDP port of the diagnostic bus (127.0.0.1)')
    p.add_argument('--max-hz', type=float, default=200., help='refuse a packet rate above this')
    args = p.parse_args(argv)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    crate = Crate(args.reg_port)
    log(f'pid {os.getpid()} ready')
    try:
        serve_diag(crate, args.diag_port, stop, args.max_hz)
    finally:
        crate.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
