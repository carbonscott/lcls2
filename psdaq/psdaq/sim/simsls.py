"""simsls: a stand-in for one Jungfrau module's slsDetector servers, so drp -D jungfrau runs with
no module.

Drp::Jungfrau (psdaq/drp/Jungfrau.cc) drives each module through sls::Detector, the
slsDetectorPackage 9.0.0 client in the DAQ env, at the module's control host:port (the drp's
-k slsHosts).  simsls serves that client's protocol for the calls Drp::Jungfrau makes, on
loopback only:

  control server  TCP <port>      sls::Detector's control socket
  stop server     TCP <port>+1    its stop socket (run status, stop)
  trigger input   UDP <port>      one datagram per trigger, the module's trigger input: the
                                  simulated PGP card (psdaq/drp/MemPoolSim.cc) sends one per
                                  L1Accept, as the card's timing receiver triggers the module
  data            UDP to the destination the client set (udp_dstip:udp_dstport, which
                  Drp::Jungfrau takes from the config DB's user.kcu_ip and user.port), from
                  127.0.0.1

Protocol (slsSupportLib ClientSocket, Module::sendToDetector): one call per TCP connection; the
client sends <int32 function id><arguments> and reads <int32 ret> (0 OK, 1 FAIL), then on FAIL a
1000-byte message, else the return value; all little-endian.  The function ids, argument and
return layouts are those of slsDetectorPackage 9.0.0 (sls_detector_funcs.h, Module.cpp); an id
simsls does not serve gets FAIL with 'Unrecognized Function enum', which the client reports as a
software version mismatch.  simsls reports the 9.0.0 Jungfrau server's version string, so the
client's version check passes, and answers F_IS_VIRTUAL with 1 (it is a virtual server: the
client then accepts a 127.0.0.1 data destination).

Settings read back what was last set, as the module's do, except under a fault (below).
Values the module refuses are refused with the 9.0.0 server's messages: a DAC above 4095 dac
units (2500 mV), a high voltage other than 0 or 60-200 V, a settings value Jungfrau has no
calibration for, a next frame number of 0.  A data destination that is not a 127.x address is
refused too: simsls sends on loopback only.

The data: start (F_START_ACQUISITION) arms the module.  In trigger mode (TRIGGER_EXPOSURE, what
Drp::Jungfrau configures) each trigger datagram makes one frame, until stop or #frames x
#triggers frames; in auto timing it sends #frames x #triggers frames, one per period.  A frame is
128 UDP packets of 48-byte sls_detector_header + 8192 bytes (psdaq/drp/JungfrauData.hh): header
frameNumber = the next frame number (set at BeginRun, +1 per frame), packetNumber p, modId = the
module id (F_GET_MODULE_ID), detType 3 (JUNGFRAU), version 2, timestamp in 10 MHz ticks since
start; packet p carries image rows 4p..4p+3, so pixel i of the 512 x 1024 image (psana2's
jungfrau raw, flattened) is psdaq.sim.pattern.pattern(seed, frameNumber, i, 16): 14 data bits
and the 2 gain bits.

Flow control: the module's 128 packets of a frame are 2 MiB of the receiver's buffer (a loopback
datagram of 8240 bytes costs 16640: its kernel buffer), and the receive buffer MemPoolSim's
UdpFront asks for (16 MiB) is capped at twice net.core.rmem_max: 425984 B where rmem_max is the
default 212992, room for 25 packets.  Sent back to back, a frame overflowed it whenever the DRP's
reading thread fell 25 packets behind, and the kernel dropped what did not fit ('MemPoolSim:
module ... sent 78 of 128 packets', DRP_Damage, in a drp_gpu jungfrau run of matrix h1 at
b14885af3).  So where the buffer cannot hold a frame, simsls sends a frame in bursts that fit:
before each burst it reads the receiving socket's queue (rx_queue in /proc/net/udp) and sends only
the packets that fit in three quarters of the buffer, waiting while none fit (at most 0.1 s per
burst, then it sends anyway; the DRP gives up a frame 0.2 s after its last packet).  Where a frame
fits (net.core.rmem_max of 1.5 MiB or more), it sends as before.  It logs the receiving socket's
drops (the drops column of /proc/net/udp: the packets the kernel dropped there) with its counts.

Fault (PSDAQ_SIM_SLS_FAULT='<setting>[=<value>]', or --fault): after the client sets <setting>,
reading it back returns <value> (default: what was set, plus 1), so Drp::Jungfrau's readback
check fails at Configure and names it.  <setting> is one of exptime, period, delay,
highvoltage, settings, gainmode, readoutspeed, or a DAC (vb_ds, vb_comp, vb_pixbuf, vref_ds,
vref_comp, vref_prech, vin_com, vdd_prot).

    python -m psdaq.sim.simsls --port 31054 --seed 0x1234 [--rcvbuf B]
"""

import argparse
import ipaddress
import logging
import os
import queue
import signal
import socket
import socketserver
import struct
import sys
import threading
import time

import numpy as np

from psdaq.sim.pattern import mix, SEQ_K

log = logging.getLogger('simsls')

ENV_FAULT = 'PSDAQ_SIM_SLS_FAULT'
VERSION = b'9.0.0 0x241121'         # APIJUNGFRAU of slsDetectorPackage 9.0.0 (versionAPI.h)
MAX_STR_LENGTH = 1000
OK, FAIL = 0, 1
GET_FLAG = -1
UNRECOGNIZED = 'Unrecognized Function enum'

JUNGFRAU = 3                        # slsDetectorDefs::detectorType
IDLE, ERROR, WAITING, RUN_FINISHED, TRANSMITTING, RUNNING, STOPPED = range(7)
AUTO_TIMING, TRIGGER_EXPOSURE = 0, 1
GAIN0, HIGHGAIN0 = 19, 7            # the settings Detector::getSettingsList() has for Jungfrau
HIGH_VOLTAGE = 81
DACS = {'vb_ds': 49, 'vb_comp': 44, 'vb_pixbuf': 48, 'vref_ds': 36, 'vref_comp': 42,
        'vref_prech': 47, 'vin_com': 46, 'vdd_prot': 45}
DAC_MAX_STEPS, DAC_MAX_MV = 4095, 2500

ROWS, COLS, PACKETS = 512, 1024, 128
PIXELS_PER_PACKET = ROWS * COLS // PACKETS
HEADER = struct.Struct('<QIIQQHHHHIHBB')        # sls_detector_header, 48 bytes
assert HEADER.size == 48
HEADER_VERSION = 2

RCVBUF_ASK = 16 << 20               # the receive buffer MemPoolSim's UdpFront asks for (SO_RCVBUF)
PACKET_COST = 16640                 # what one 8240-byte loopback datagram costs a receive buffer
ROOM_WAIT_S = 0.1                   # the longest wait for room before a burst
UDP_TABLE = '/proc/net/udp'


def receive_buffer(ask=RCVBUF_ASK):
    """The receive buffer a UDP socket on this host gets when it asks for 'ask' bytes, as
    MemPoolSim's does (the kernel doubles the request and caps it at twice net.core.rmem_max)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, ask)
        return s.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
    finally:
        s.close()


def udp_queue(ip, port, table=UDP_TABLE):
    """(bytes queued, packets dropped) at the UDP socket bound to ip:port on this host (rx_queue
    and drops of its /proc/net/udp line), or None when no socket is bound there."""
    want = {'%08X:%04X' % (struct.unpack('=I', socket.inet_aton(ip))[0], port),
            '00000000:%04X' % port}
    try:
        with open(table) as f:
            next(f, None)
            for line in f:
                col = line.split()
                if len(col) > 12 and col[1] in want:
                    return int(col[4].split(':')[1], 16), int(col[-1])
    except (OSError, ValueError, IndexError):
        pass
    return None

# Function ids of slsDetectorPackage 9.0.0 (sls_detector_funcs.h) that simsls serves:
# id: (name, argument layout, return layout)
F = {
    1: ('F_GET_DETECTOR_TYPE', '', 'i'),
    4: ('F_SET_TIMING_MODE', 'i', 'i'),
    5: ('F_GET_FIRMWARE_VERSION', '', 'q'),
    6: ('F_GET_SERVER_VERSION', '', '%ds' % MAX_STR_LENGTH),
    7: ('F_GET_SERIAL_NUMBER', '', 'q'),
    12: ('F_SET_DAC', 'iii', 'i'),
    17: ('F_SET_SETTINGS', 'i', 'i'),
    19: ('F_START_ACQUISITION', '', ''),
    20: ('F_STOP_ACQUISITION', '', ''),
    21: ('F_GET_RUN_STATUS', '', 'i'),
    23: ('F_GET_NUM_FRAMES', '', 'q'),
    24: ('F_SET_NUM_FRAMES', 'q', ''),
    25: ('F_GET_NUM_TRIGGERS', '', 'q'),
    26: ('F_SET_NUM_TRIGGERS', 'q', ''),
    33: ('F_GET_EXPTIME', 'i', 'q'),
    34: ('F_SET_EXPTIME', 'qq', ''),
    35: ('F_GET_PERIOD', '', 'q'),
    36: ('F_SET_PERIOD', 'q', ''),
    37: ('F_GET_DELAY_AFTER_TRIGGER', '', 'q'),
    38: ('F_SET_DELAY_AFTER_TRIGGER', 'q', ''),
    89: ('F_POWER_CHIP', 'i', 'i'),
    96: ('F_INITIAL_CHECKS', '', ''),
    107: ('F_SET_NEXT_FRAME_NUMBER', 'Q', ''),
    108: ('F_GET_NEXT_FRAME_NUMBER', '', 'Q'),
    115: ('F_SET_POSITION', 'ii', ''),
    116: ('F_SET_SOURCE_UDP_MAC', 'Q', ''),
    117: ('F_GET_SOURCE_UDP_MAC', '', 'Q'),
    120: ('F_SET_SOURCE_UDP_IP', 'I', ''),
    121: ('F_GET_SOURCE_UDP_IP', '', 'I'),
    124: ('F_SET_DEST_UDP_MAC', 'Q', ''),
    125: ('F_GET_DEST_UDP_MAC', '', 'Q'),
    128: ('F_SET_DEST_UDP_IP', 'I', ''),
    129: ('F_GET_DEST_UDP_IP', '', 'I'),
    132: ('F_SET_DEST_UDP_PORT', 'H', ''),
    133: ('F_GET_DEST_UDP_PORT', '', 'H'),
    137: ('F_GET_NUM_INTERFACES', '', 'i'),
    199: ('F_VALIDATE_UDP_CONFIG', '', ''),
    203: ('F_IS_VIRTUAL', '', 'i'),
    220: ('F_GET_GAIN_MODE', '', 'i'),
    221: ('F_SET_GAIN_MODE', 'i', ''),
    232: ('F_GET_MODULE_ID', '', 'i'),
    239: ('F_GET_READOUT_SPEED', '', 'i'),
    240: ('F_SET_READOUT_SPEED', 'i', ''),
    244: ('F_GET_UPDATE_MODE', '', 'i'),
    260: ('F_GET_SYNCHRONIZATION', '', 'i'),
}
SETTINGS = ('exptime', 'period', 'delay', 'highvoltage', 'settings', 'gainmode',
            'readoutspeed') + tuple(DACS)


class Refused(Exception):
    """The module refuses the call; the message goes back to the client as the server's."""


def parse_fault(text):
    if not text:
        return None
    name, _, value = text.partition('=')
    name = name.strip().lower()
    if name not in SETTINGS:
        raise ValueError('%s: unknown setting %r; one of %s' % (ENV_FAULT, name, ', '.join(SETTINGS)))
    return name, (int(value, 0) if value.strip() else None)


def loopback(ip):
    return ipaddress.ip_address(ip).is_loopback


def ip_str(value):
    """An sls IpAddr (uint32, in network byte order in memory) as dotted text."""
    return socket.inet_ntoa(struct.pack('<I', value))


class Module:
    """The state of one Jungfrau module and its data generator."""

    def __init__(self, seed=0x1234, module_id=0x2a0, serial=0x1e3, firmware=0x230920, fault=None,
                 rcvbuf=None):
        self.lock = threading.RLock()
        self.seed = seed
        self.module_id = module_id
        self.serial = serial
        self.firmware = firmware
        self.fault = fault
        self.fault_hits = 0
        self.timing = AUTO_TIMING
        self.frames = 1
        self.triggers = 1
        self.exptime = 10000                    # ns
        self.period = 2000000
        self.delay = 0
        self.dacs = {}
        self.high_voltage = 0
        self.settings = GAIN0
        self.gain_mode = 0                      # DYNAMIC
        self.speed = 1                          # HALF_SPEED
        self.power = 0
        self.next_frame = 1
        self.position = (0, 0)
        self.src_ip = self.dst_ip = 0
        self.src_mac = self.dst_mac = 0
        self.dst_port = 0
        self.status = IDLE
        self.run = None                         # the armed acquisition's stop event
        self.triggers_in = queue.Queue()
        self.counts = {'calls': 0, 'triggers': 0, 'triggers_ignored': 0, 'frames': 0, 'packets': 0,
                       'room_waits': 0, 'room_timeouts': 0, 'receiver_drops': None}
        self.rcvbuf = receive_buffer() if rcvbuf is None else rcvbuf    # the receiver's buffer
        self.base = (mix(np.arange(ROWS * COLS, dtype=np.uint64)) & np.uint32(0xffff)).astype(np.uint16)
        self.t0 = time.monotonic()
        self.data = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.data.bind(('127.0.0.1', 0))

    @property
    def limit(self):
        """What a burst may fill the receiver's buffer to (three quarters of it), or None when a
        whole frame fits under that, so a frame goes back to back."""
        lim = self.rcvbuf * 3 // 4
        return None if PACKETS * PACKET_COST <= lim else lim

    # ---- readbacks, with the fault --------------------------------------------------------
    def readback(self, name, value):
        if self.fault and self.fault[0] == name:
            self.fault_hits += 1
            wrong = value + 1 if self.fault[1] is None else self.fault[1]
            log.warning('FAULT %s reads back %d (set %d)', name, wrong, value)
            return wrong
        return value

    # ---- one frame -------------------------------------------------------------------------
    def image(self, frame):
        add = np.uint16((frame * SEQ_K + self.seed) & 0xffff)
        with np.errstate(over='ignore'):
            return self.base + add

    def send_frame(self):
        with self.lock:
            frame = self.next_frame
            self.next_frame += 1
            dest = (ip_str(self.dst_ip), self.dst_port)
            exp = self.exptime
        img = self.image(frame)
        ts = int((time.monotonic() - self.t0) * 1e7)
        raw = img.tobytes()
        step = PIXELS_PER_PACKET * 2
        p = 0
        while p < PACKETS:                  # in bursts that fit in the receiver's buffer
            n = PACKETS - p if self.limit is None else min(PACKETS - p, self.room(dest))
            for k in range(p, p + n):
                hdr = HEADER.pack(frame, exp // 100, k, 0, ts, self.module_id,
                                  self.position[0], self.position[1], 0, 0, 0, JUNGFRAU, HEADER_VERSION)
                self.data.sendto(hdr + raw[k * step:(k + 1) * step], dest)
            p += n
        with self.lock:
            self.counts['frames'] += 1
            self.counts['packets'] += PACKETS

    def room(self, dest):
        """How many packets fit in the receiver's buffer now (its queue below self.limit); waits
        while none fit, up to ROOM_WAIT_S, then answers all of them.  All of them too when the
        receiving socket is not in /proc/net/udp (not bound yet, or not on this host)."""
        end = None
        while True:
            q = self.receiver_queue(dest)
            if q is None:
                return PACKETS
            fit = (self.limit - q) // PACKET_COST
            if fit > 0:
                return fit
            now = time.monotonic()
            if end is None:
                end = now + ROOM_WAIT_S
                with self.lock:
                    self.counts['room_waits'] += 1
            elif now > end:
                with self.lock:
                    self.counts['room_timeouts'] += 1
                return PACKETS
            time.sleep(0.0002)

    def receiver_queue(self, dest):
        """Bytes queued at the receiving socket (None if it is not found); keeps its drops."""
        q = udp_queue(*dest)
        if q is None:
            return None
        with self.lock:
            self.counts['receiver_drops'] = q[1]
        return q[0]

    def acquire(self, stop):
        """The armed module: one frame per trigger, or per period in auto timing."""
        with self.lock:
            total = self.frames * self.triggers
            mode = self.timing
            period = self.period / 1e9
            wait = min((self.delay + self.exptime) / 1e9, 0.01)
        sent = 0
        try:
            while sent < total and not stop.is_set():
                if mode == TRIGGER_EXPOSURE:
                    try:
                        self.triggers_in.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    with self.lock:
                        self.status = RUNNING
                    if wait > 0:
                        time.sleep(wait)
                    for _ in range(self.frames):
                        self.send_frame()
                        sent += 1
                    with self.lock:
                        if not stop.is_set():
                            self.status = WAITING
                else:
                    t = time.monotonic()
                    self.send_frame()
                    sent += 1
                    stop.wait(max(0., period - (time.monotonic() - t)))
        finally:
            with self.lock:
                if self.run is stop:
                    self.status = IDLE
                    self.run = None

    def trigger(self):
        with self.lock:
            armed = self.run is not None and self.timing == TRIGGER_EXPOSURE
            self.counts['triggers' if armed else 'triggers_ignored'] += 1
        if armed:
            self.triggers_in.put(1)

    # ---- the calls -------------------------------------------------------------------------
    def call(self, fnum, args):
        name = F[fnum][0]
        with self.lock:
            self.counts['calls'] += 1
            return getattr(self, name[2:].lower())(*args)

    def get_detector_type(self):
        return JUNGFRAU

    def get_server_version(self):
        return VERSION

    def initial_checks(self):
        return None

    def get_num_interfaces(self):
        return 1

    def get_update_mode(self):
        return 0

    def get_synchronization(self):
        return 0

    def is_virtual(self):
        return 1

    def set_position(self, ny, index):
        self.position = (index % max(ny, 1), index // max(ny, 1))

    def get_module_id(self):
        return self.module_id

    def get_serial_number(self):
        return self.serial

    def get_firmware_version(self):
        return self.firmware

    def set_timing_mode(self, mode):
        if mode != GET_FLAG:
            if mode not in (AUTO_TIMING, TRIGGER_EXPOSURE):
                raise Refused('Timing mode (%d) not implemented for this detector\n' % mode)
            self.timing = mode
        return self.timing

    def get_num_frames(self):
        return self.frames

    def set_num_frames(self, n):
        if n < 1:
            raise Refused('Could not set number of frames %d. Must be at least 1\n' % n)
        self.frames = n

    def get_num_triggers(self):
        return self.triggers

    def set_num_triggers(self, n):
        if n < 1:
            raise Refused('Could not set number of triggers %d. Must be at least 1\n' % n)
        self.triggers = n

    def set_exptime(self, gate, ns):
        if ns < 0:
            raise Refused('Could not set exposure time. Cannot be negative\n')
        self.exptime = ns

    def get_exptime(self, gate):
        return self.readback('exptime', self.exptime)

    def set_period(self, ns):
        if ns < 0:
            raise Refused('Could not set period. Cannot be negative\n')
        self.period = ns

    def get_period(self):
        return self.readback('period', self.period)

    def set_delay_after_trigger(self, ns):
        if ns < 0:
            raise Refused('Could not set delay after trigger. Cannot be negative\n')
        self.delay = ns

    def get_delay_after_trigger(self):
        return self.readback('delay', self.delay)

    def set_dac(self, index, mv, value):
        if index == HIGH_VOLTAGE:
            if value != GET_FLAG:
                if value != 0 and not 60 <= value <= 200:
                    raise Refused('Setting high voltage failed. Bad value %d. The range is from 0 '
                                  'to 200 V, and below 60 V only 0.\n' % value)
                self.high_voltage = value
            return self.readback('highvoltage', self.high_voltage)
        name = {v: k for k, v in DACS.items()}.get(index)
        if name is None:
            raise Refused('Dac Index (%d) is not implemented for this detector\n' % index)
        if value != GET_FLAG:
            limit = DAC_MAX_MV if mv else DAC_MAX_STEPS
            if not 0 <= value <= limit:
                raise Refused('Could not set dac %d to value %d. Allowed limits (0 - %d %s).\n'
                              % (index, value, limit, 'mV' if mv else 'dac units'))
            self.dacs[name] = value * DAC_MAX_STEPS // DAC_MAX_MV if mv else value
        steps = self.dacs.get(name, 0)
        return self.readback(name, steps * DAC_MAX_MV // DAC_MAX_STEPS if mv else steps)

    def set_settings(self, value):
        if value != GET_FLAG:
            if value not in (GAIN0, HIGHGAIN0):
                raise Refused('Setting (%d) not allowed for this detector\n' % value)
            self.settings = value
        return self.readback('settings', self.settings)

    def set_gain_mode(self, mode):
        if not 0 <= mode <= 5:
            raise Refused('Gain mode (%d) not implemented for this detector\n' % mode)
        self.gain_mode = mode

    def get_gain_mode(self):
        return self.readback('gainmode', self.gain_mode)

    def power_chip(self, on):
        if on != GET_FLAG:
            self.power = 1 if on else 0
        return self.power

    def get_readout_speed(self):
        return self.readback('readoutspeed', self.speed)

    def set_readout_speed(self, speed):
        if speed not in (0, 1, 2):
            raise Refused('Unknown readout speed %d\n' % speed)
        self.speed = speed

    def set_next_frame_number(self, n):
        if n == 0:
            raise Refused('Could not set next frame number. Cannot be 0.\n')
        self.next_frame = n

    def get_next_frame_number(self):
        return self.next_frame

    def set_source_udp_mac(self, mac):
        self.src_mac = mac

    def get_source_udp_mac(self):
        return self.src_mac

    def set_source_udp_ip(self, ip):
        self.src_ip = ip

    def get_source_udp_ip(self):
        return self.src_ip

    def set_dest_udp_mac(self, mac):
        self.dst_mac = mac

    def get_dest_udp_mac(self):
        return self.dst_mac

    def set_dest_udp_ip(self, ip):
        if not loopback(ip_str(ip)):
            raise Refused('udp_dstip %s refused: simsls sends module data on loopback (127.x) '
                          'only\n' % ip_str(ip))
        self.dst_ip = ip

    def get_dest_udp_ip(self):
        return self.dst_ip

    def set_dest_udp_port(self, port):
        self.dst_port = port

    def get_dest_udp_port(self):
        return self.dst_port

    def validate_udp_config(self):
        missing = [n for n, v in (('udp_srcip', self.src_ip), ('udp_srcmac', self.src_mac),
                                  ('udp_dstip', self.dst_ip), ('udp_dstmac', self.dst_mac),
                                  ('udp_dstport', self.dst_port)) if not v]
        if missing:
            raise Refused('Configure MAC failed: %s not configured\n' % ', '.join(missing))

    def start_acquisition(self):
        if self.run is not None:
            raise Refused('Could not start acquisition. Already acquiring\n')
        self.validate_udp_config()
        if not self.power:
            raise Refused('Could not start acquisition. Chip is powered off\n')
        while not self.triggers_in.empty():
            self.triggers_in.get_nowait()
        self.run = threading.Event()
        self.status = WAITING if self.timing == TRIGGER_EXPOSURE else RUNNING
        threading.Thread(target=self.acquire, args=(self.run,), name='acquire', daemon=True).start()

    def stop_acquisition(self):
        if self.run is not None:
            self.run.set()
            self.run = None
        self.status = IDLE

    def get_run_status(self):
        return self.status


class Handler(socketserver.BaseRequestHandler):
    def recv(self, n):
        buf = b''
        while len(buf) < n:
            chunk = self.request.recv(n - len(buf))
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    def handle(self):
        module, which = self.server.module, self.server.which
        try:
            head = self.recv(4)
        except EOFError:
            return                      # Module::setHostname connects and closes to probe
        fnum, = struct.unpack('<i', head)
        if fnum not in F:
            log.warning('%s: function %d not served', which, fnum)
            self.fail('%s: %d' % (UNRECOGNIZED, fnum))
            return
        name, afmt, rfmt = F[fnum]
        try:
            args = struct.unpack('<' + afmt, self.recv(struct.calcsize('<' + afmt))) if afmt else ()
        except EOFError:
            return
        try:
            ret = module.call(fnum, args)
        except Refused as e:
            log.info('%s %s%s refused: %s', which, name, args, str(e).strip())
            self.fail(str(e))
            return
        out = struct.pack('<i', OK)
        if rfmt:
            out += struct.pack('<' + rfmt, ret)
        self.request.sendall(out)
        log.debug('%s %s%s -> %r', which, name, args, ret)

    def fail(self, message):
        msg = message.encode()[:MAX_STR_LENGTH - 1]
        self.request.sendall(struct.pack('<i', FAIL) + msg.ljust(MAX_STR_LENGTH, b'\0'))


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, module, which):
        super().__init__(addr, Handler)
        self.module, self.which = module, which


class SimSls:
    """The control and stop servers and the trigger input of one module, on 127.0.0.1."""

    def __init__(self, port, **kw):
        self.module = Module(**kw)
        self.control = Server(('127.0.0.1', port), self.module, 'control')
        self.stop_srv = Server(('127.0.0.1', port + 1), self.module, 'stop')
        self.trig = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.trig.bind(('127.0.0.1', port))
        self.trig.settimeout(0.2)
        self.port = port
        self.done = threading.Event()
        self.threads = [threading.Thread(target=s.serve_forever, kwargs={'poll_interval': 0.2},
                                         daemon=True) for s in (self.control, self.stop_srv)]
        self.threads.append(threading.Thread(target=self._triggers, daemon=True))

    def _triggers(self):
        while not self.done.is_set():
            try:
                self.trig.recvfrom(64)
            except socket.timeout:
                continue
            except OSError:
                return
            self.module.trigger()

    def start(self):
        for t in self.threads:
            t.start()
        return self

    def close(self):
        self.done.set()
        self.module.stop_acquisition()
        for s in (self.control, self.stop_srv):
            s.shutdown()
            s.server_close()
        self.trig.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Stand-in for a Jungfrau module\'s slsDetector '
                                     'servers (sls 9.0.0 protocol), on loopback')
    parser.add_argument('--port', type=int, required=True,
                        help='control server port; the stop server is port+1, the trigger input UDP port')
    parser.add_argument('--seed', type=lambda s: int(s, 0), default=0x1234,
                        help='mixed into the pixel values (psdaq.sim.pattern)')
    parser.add_argument('--module-id', type=lambda s: int(s, 0), default=0x2a0)
    parser.add_argument('--serial', type=lambda s: int(s, 0), default=0x1e3,
                        help='board id (F_GET_SERIAL_NUMBER)')
    parser.add_argument('--fault', default=os.environ.get(ENV_FAULT),
                        help='<setting>[=<value>]: that setting reads back wrong (default $%s)' % ENV_FAULT)
    parser.add_argument('--rcvbuf', type=int, default=None,
                        help='the receiver\'s buffer in bytes (default: what a %d B SO_RCVBUF request '
                        'gets on this host, as MemPoolSim asks); a frame is sent in bursts that fit' % RCVBUF_ASK)
    parser.add_argument('-v', action='store_true', help='log every call')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO,
                        format='%(asctime)s simsls %(levelname)s %(message)s')
    fault = parse_fault(args.fault)
    sim = SimSls(args.port, seed=args.seed, module_id=args.module_id, serial=args.serial,
                 fault=fault, rcvbuf=args.rcvbuf).start()
    m = sim.module
    log.info('Jungfrau module stand-in (sls %s): control 127.0.0.1:%d, stop :%d, trigger udp :%d, '
             'seed %#x, module id %#x%s; receiver buffer %d B: %s', VERSION.decode(), args.port,
             args.port + 1, args.port, args.seed, args.module_id, ', FAULT %s' % (fault,) if fault else '',
             m.rcvbuf, 'a frame fits, sent back to back' if m.limit is None else
             'a frame (%d B of it) is sent in bursts that keep the queue under %d B'
             % (PACKETS * PACKET_COST, m.limit))
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *a: stop.set())
    while not stop.wait(10):
        if m.dst_port:
            m.receiver_queue((ip_str(m.dst_ip), m.dst_port))     # its drops, for the log
        with sim.module.lock:
            log.info('status %d, next frame %d, %s', sim.module.status, sim.module.next_frame,
                     sim.module.counts)
    with sim.module.lock:
        log.info('exiting: status %d, next frame %d, %s, fault reads %d', sim.module.status,
                 sim.module.next_frame, sim.module.counts, sim.module.fault_hits)
    sim.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
