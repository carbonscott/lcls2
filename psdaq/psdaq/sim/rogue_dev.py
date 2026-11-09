"""
psdaq.sim.rogue_dev -- run a BEB detector's own psdaq/configdb/<type>_config.py,
unmodified, against an in-process simulated device.

A BEB detector's config script builds real firmware roots (pyrogue + the
firmware packages under $SUBMODULEDIR) on top of two rogue hardware
transports: rogue.hardware.axi.AxiMemMap (the PCIe BAR) and
rogue.hardware.axi.AxiStreamDma (DMA lanes; the register lane carries SRPv3
to the front-end board).  install('sim://...') replaces those two
constructors, before the config module builds its roots, with:

  SimMemMap     a memory slave over a sparse in-process register store
  SimStreamDma  a stream endpoint that answers SRPv3 requests from its own
                register store (and drops anything else, like a null stream)

Everything above the transports -- pyrogue, the firmware device trees,
rogue's SrpV3 protocol, the config script -- is the real code, with three
more hooks: pr.Device._start of a root applies the seeds below, pyrogue's
ZmqServer binds 127.0.0.1 on a free port, and rogue's Xvc (a JTAG-over-TCP
server some roots start) is a null stream endpoint.  Registers read back
what was last written (0 if never written), except:

  seeds   a JSON file {"<register path>": value, ...} (psdaq/sim/seeds/
          <type>.json by default) presets status registers the config
          script polls (FW version, lock bits, clock counters...).  Each
          path is applied when the root that owns it starts; a path that
          is not a RemoteVariable in the tree raises (no auto-vivifying).
          A value {"count_hz": f} makes the register a free-running counter
          that advances f per second from the moment its root starts (a
          clock-cycle counter the script turns into a frequency, such as
          TimingFrameRx.TxClkCount for TDetTiming.refClockRate()); a value
          {"string": text} is a string register's text (AxiVersion.ImageName); a
          value {"response": v, "bits": n} makes the register's low n bits read v
          whatever is written, the rest what was last written: a command register
          whose low bits carry the device's answer (a SPI PROM's status byte, which
          surf's CypressS25Fl.waitForFlashReady polls for its ready bit).
  fault   PSDAQ_SIM_ROGUE_FAULT='<register path>[=<value>]': that register
          reads back <value> (default all ones) whatever is written, so
          rogue's write-verify, or the config script's own check, fails
          and names it.

Two more parts of the device that some config scripts reach without rogue:

  /proc   the driver's /proc/<device> text (PgpMonitor.detect_version reads
          its 'Build String' for the board type and PGP version): the seed
          file's "_proc" lines are what open('/proc/<sim device name>') reads.
  PVs     a type configured through its front-end's rogue IOC over Channel
          Access (wave8, wave8he: psdaq/configdb/wave8_common.py, pyepics
          epics.PV) gets epics.PV replaced by SimPV, in process, on a table of
          the IOC's PVs: seed keys "pv:<name>", where {prefix} in <name> is the
          drp's -k epics_prefix.  A PV in the table reads back what was last
          put; one not in it reads None and its put does nothing, as pyepics
          does for a PV no IOC serves, and is listed in missing_pvs.  No CA
          traffic leaves the process.  A fault 'pv:<name>[=<value>]' makes that
          PV read back <value> (default 0).

  UART    a camera behind a camera link FEB (cameralink_gateway: Opal, Piranha4) answers
          its serial commands, one character per 32-bit word on the lane's VC2 stream (surf
          ClinkSerialTx/ClinkSerialRx): the seed file's "_uart" {"dests": [stream dests],
          "replies": {command: reply}, "default": reply} is the camera's answer to each command
          (a reply ends with CR where the camera's does; "default", ACK by default, answers the
          rest).  The commands are recorded with the register writes.

Every register write is recorded (WRITES, and one JSON line per write to
$PSDAQ_SIM_ROGUE_LOG if set) with the register paths it covers.

Nothing here runs unless the device string starts with 'sim://'.
"""

import builtins
import io
import json
import logging
import os
import queue
import struct
import sys
import threading
import time

import rogue
import rogue.hardware.axi
import rogue.protocols.xilinx
import rogue.interfaces.memory as rim
import rogue.interfaces.stream as ris
import pyrogue as pr

SIM_PREFIX = 'sim://'
ENV_SEEDS = 'PSDAQ_SIM_ROGUE_SEEDS'
ENV_FAULT = 'PSDAQ_SIM_ROGUE_FAULT'
ENV_LOG = 'PSDAQ_SIM_ROGUE_LOG'
SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'seeds')

log = logging.getLogger('psdaq.sim.rogue_dev')


def _say(msg):
    """Report what a config script must not miss (a fault, a PV the IOC lacks) whatever
    logging level the script sets (wave8_init sets the root logger to ERROR)."""
    print('rogue_dev: ' + msg, file=sys.stderr, flush=True)


def is_sim(dev):
    return isinstance(dev, str) and dev.startswith(SIM_PREFIX)


class SimDeviceError(RuntimeError):
    pass


def _int(v):
    return int(v, 0) if isinstance(v, str) else int(v)


def _put_bits(buf, base, var_addr, offsets, sizes, value):
    """Insert value into buf (holding bytes base..base+len) at a variable's bits."""
    shift = 0
    for off, size in zip(offsets, sizes):
        chunk = (value >> shift) & ((1 << size) - 1)
        shift += size
        first = (var_addr - base) * 8 + off
        for b in range(size):
            bit = first + b
            if 0 <= bit < len(buf) * 8:
                if (chunk >> b) & 1:
                    buf[bit >> 3] |= 1 << (bit & 7)
                else:
                    buf[bit >> 3] &= ~(1 << (bit & 7)) & 0xff


def _get_bits(buf, base, var_addr, offsets, sizes):
    """Inverse of _put_bits; None if the variable is not wholly inside buf."""
    value, shift = 0, 0
    for off, size in zip(offsets, sizes):
        first = (var_addr - base) * 8 + off
        if first < 0 or first + size > len(buf) * 8:
            return None
        for b in range(size):
            bit = first + b
            value |= ((buf[bit >> 3] >> (bit & 7)) & 1) << (shift + b)
        shift += size
    return value


class Store(object):
    """Sparse little-endian register space; unwritten bytes read as 0."""
    PAGE = 4096

    def __init__(self, name):
        self.name = name
        self.ntrans = 0
        self.last = None
        self._pages = {}
        self._lock = threading.Lock()
        self._faults = []       # (var_addr, offsets, sizes, value, path)
        self._responses = []    # (var_addr, offsets, sizes, value): bits a device answers in
        self._counters = []     # (var_addr, offsets, sizes, hz, t0): free-running counters
        self._vars = {}         # word address -> [(path, var_addr, offsets, sizes)]
        self._hooks = {}        # word address -> fn(store): what a write there makes the device do
        self.proxy_of = None    # the store whose AXI-Lite master proxy this one is behind

    def _span(self, addr, size):
        while size > 0:
            page, off = divmod(addr, self.PAGE)
            n = min(size, self.PAGE - off)
            yield page, off, n
            addr += n
            size -= n

    def raw_read(self, addr, size):
        out = bytearray()
        for page, off, n in self._span(addr, size):
            p = self._pages.get(page)
            out += p[off:off + n] if p is not None else bytes(n)
        return out

    def raw_write(self, addr, data):
        pos = 0
        for page, off, n in self._span(addr, len(data)):
            p = self._pages.setdefault(page, bytearray(self.PAGE))
            p[off:off + n] = data[pos:pos + n]
            pos += n

    def read(self, addr, size):
        with self._lock:
            self.ntrans += 1
            self.last = ('R', addr, size)
            buf = self.raw_read(addr, size)
            if self._counters:
                now = time.monotonic()
                for (vaddr, offs, sizes, hz, t0) in self._counters:
                    count = int((now - t0) * hz) & ((1 << sum(sizes)) - 1)
                    _put_bits(buf, addr, vaddr, offs, sizes, count)
            for (vaddr, offs, sizes, value) in self._responses:
                _put_bits(buf, addr, vaddr, offs, sizes, value)
            for (vaddr, offs, sizes, value, path) in self._faults:
                _put_bits(buf, addr, vaddr, offs, sizes, value)
            return buf

    def write(self, addr, data):
        with self._lock:
            self.ntrans += 1
            self.last = ('W', addr, len(data))
            old = self.raw_read(addr, len(data))
            self.raw_write(addr, data)
        _SIM.record(self, addr, old, data)
        for a in range(addr - (addr % 4), addr + len(data), 4):
            if a in self._hooks:
                self._hooks[a](self)

    def poke(self, var_addr, offsets, sizes, value):
        nbytes = (max(o + s for o, s in zip(offsets, sizes)) + 7) // 8
        with self._lock:
            buf = self.raw_read(var_addr, nbytes)
            _put_bits(buf, var_addr, var_addr, offsets, sizes, value)
            self.raw_write(var_addr, buf)

    def add_counter(self, var_addr, offsets, sizes, hz):
        with self._lock:
            self._counters.append((var_addr, list(offsets), list(sizes), float(hz),
                                   time.monotonic()))

    def add_response(self, var_addr, offset, size, value):
        with self._lock:
            self._responses.append((var_addr, [offset], [size], value))

    def add_fault(self, var_addr, offsets, sizes, value, path):
        with self._lock:
            self._faults.append((var_addr, offsets, sizes, value, path))

    def changes(self, addr, old, new):
        """['path=value', ...] for the registers a write changed (all it covers
        when it changed none), and how many registers it covers."""
        changed, covered = [], []
        for a in range(addr - (addr % 4), addr + len(new), 4):
            for (path, vaddr, offs, sizes) in self._vars.get(a, []):
                v1 = _get_bits(new, addr, vaddr, offs, sizes)
                if v1 is None:
                    continue
                item = '%s=0x%x' % (path, v1)
                covered.append(item)
                if _get_bits(old, addr, vaddr, offs, sizes) != v1:
                    changed.append(item)
        return (changed or covered), len(covered)


class SimMemMap(rim.Slave):
    """Stands in for rogue.hardware.axi.AxiMemMap(path)."""

    def __init__(self, path):
        rim.Slave.__init__(self, 4, 4)
        self.store = Store('AxiMemMap(%s)' % path)
        self._name = self.store.name

    def setName(self, name):
        self._name = name

    def _checkRange(self, address, size):
        return 0

    def _doMinAccess(self):
        return 4

    def _doMaxAccess(self):
        return 0x100000

    def _doTransaction(self, tran):
        addr, size, typ = tran.address(), tran.size(), tran.type()
        try:
            if typ == rim.Write or typ == rim.Post:
                ba = bytearray(size)
                tran.getData(ba, 0)
                self.store.write(addr, ba)
            else:
                tran.setData(self.store.read(addr, size), 0)
            tran.done()
        except Exception as e:      # never leave a transaction hanging
            tran.error('%s: %r' % (self._name, e))


class SimStreamDma(ris.Master, ris.Slave):
    """Stands in for rogue.hardware.axi.AxiStreamDma(path, dest, ssi).

    SRPv3 requests are answered from this lane's register store on a worker
    thread (rogue's SrpV3 holds the transaction lock while it sends, so a
    synchronous reply could deadlock).  Other frames are dropped and counted.
    """

    def __init__(self, path, dest, ssi=True, uart=None):
        ris.Master.__init__(self)
        ris.Slave.__init__(self)
        self.dest = dest
        self.store = Store('AxiStreamDma(%s,0x%x)' % (path, dest))
        self.uart = uart                # a SimUart answers this stream instead of SRPv3
        self.dropped = 0
        self._q = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='sim-srp-0x%x' % dest)
        self._thread.start()

    def _acceptFrame(self, frame):
        with frame.lock():
            ba = bytearray(frame.getPayload())
            frame.read(ba, 0)
        self._q.put(ba)

    def _run(self):
        while True:
            ba = self._q.get()
            if ba is None:
                return
            try:
                resp = self.uart.reply(ba, self.dest) if self.uart else self._srpv3(ba)
            except Exception:
                log.exception('%s: bad request', self.store.name)
                continue
            if resp is not None:
                frame = self._reqFrame(len(resp), True)
                frame.write(resp, 0)
                self._sendFrame(frame)

    def _srpv3(self, ba):
        # Request: 5 words {ver|opcode<<8|..|timeout<<24, tid, addrLo, addrHi, size-1}
        # then write data.  Reply: the same header, the data (read or echoed
        # write), and a status word (0 = ok).  Posted writes get no reply.
        if len(ba) < 20 or (ba[0] != 0x03):
            self.dropped += 1
            return None
        hdr = struct.unpack_from('<5I', ba, 0)
        opcode = (hdr[0] >> 8) & 0x3
        addr = hdr[2] | (hdr[3] << 32)
        size = hdr[4] + 1
        status = 0
        if opcode == 0:                         # non-posted read
            data = self.store.read(addr, size)
        elif opcode in (1, 2):                  # non-posted / posted write
            data = ba[20:20 + size]
            if len(data) != size:
                status = 0x400                  # frame error
            else:
                self.store.write(addr, data)
            if opcode == 2:
                return None
        else:                                   # null
            data = bytearray(size)
        return bytes(ba[:20]) + bytes(data) + struct.pack('<I', status)

    def setDriverDebug(self, level):
        pass

    # rogue's 'dma == peer' (connect both ways), as on AxiStreamDma: the C++ operator cannot
    # use a Python class as both ends, so it is pyrogue's streamConnectBiDir here
    def __eq__(self, other):
        pr.streamConnectBiDir(self, other)
        return other

    __hash__ = object.__hash__

    def _stop(self):
        self._q.put(None)


class SimUart(object):
    """A camera's serial port as its camera link FEB carries it (surf.protocols.clink
    ClinkSerialTx/ClinkSerialRx): each character in the low byte of a 32-bit word, a command
    ending with CR.  Each command is answered from the seed file's "_uart" table."""

    def __init__(self, table):
        self.replies = dict(table.get('replies', {}))
        self.default = table.get('default', '\x06')        # ACK
        self.commands = []

    @staticmethod
    def words(text):
        out = bytearray(4 * len(text))
        out[0::4] = text.encode('latin-1')
        return out

    def reply(self, ba, dest=0):
        chars = bytes(ba[0::4])
        if b'\r' not in chars:                 # an escape or a partial line: no answer
            return None
        cmd = chars.split(b'\r')[0].decode('latin-1')
        self.commands.append(cmd)
        _SIM.record_uart(dest, cmd)
        r = self.replies.get(cmd, self.default)
        return self.words(r) if r else None


class SimXvc(object):
    """Stands in for rogue.protocols.xilinx.Xvc(port): no TCP server.  A stream peer as rogue's
    '==' takes it (_getStreamSlave/_getStreamMaster): what it is sent is counted and dropped,
    and it sends nothing."""

    def __init__(self, port=2542, *args, **kwargs):
        self.port = port
        self._slave = ris.Slave()
        self._master = ris.Master()
        log.info('Xvc(%s) -> SimXvc (no socket)', port)

    def _getStreamSlave(self):
        return self._slave

    def _getStreamMaster(self):
        return self._master

    def _start(self):
        pass

    def _stop(self):
        pass


PV_PREFIX = 'pv:'


class SimPV(object):
    """Stands in for epics.PV(pvname) of the simulated device's IOC."""

    def __init__(self, pvname, *args, **kwargs):
        self.pvname = pvname

    @property
    def connected(self):
        return self.pvname in _SIM.pvs

    def wait_for_connection(self, timeout=None):
        return self.connected

    def get(self, *args, **kwargs):
        return _SIM.pv_get(self.pvname)

    @property
    def value(self):
        return self.get()

    def put(self, value, *args, **kwargs):
        return _SIM.pv_put(self.pvname, value)


class _Sim(object):
    def __init__(self):
        self.dev = None
        self.pvs = {}           # PV name -> value (the simulated IOC)
        self.pv_fault = None    # (name, value)
        self.missing_pvs = []   # names asked for that the IOC does not serve, in order
        self.proc = None        # the driver's /proc/<device> text
        self.stores = []
        self.seeds = {}         # path -> value, not yet applied
        self.applied = {}       # path -> (store, addr, value)
        self.fault = None       # (path, value)
        self.fault_applied = None
        self.roots = []
        self.writes = []
        self.uart = None        # {"dests": [...], "replies": {...}, "default": ...} or None
        self.uarts = []
        self._logf = None
        self._orig = None

    # ---- transports -------------------------------------------------------
    def _check_path(self, path):
        if path != self.dev:
            raise SimDeviceError('rogue_dev: %r is not the simulated device %r; '
                                 'refusing to open hardware' % (path, self.dev))

    def mem_map(self, path, *args, **kwargs):
        self._check_path(path)
        m = SimMemMap(path)
        self.stores.append(m.store)
        log.info('AxiMemMap(%s) -> SimMemMap', path)
        return m

    def stream_dma(self, path, dest, ssi=True, *args, **kwargs):
        self._check_path(path)
        uart = None
        if self.uart and dest in [_int(d) for d in self.uart.get('dests', [])]:
            uart = SimUart(self.uart)
            self.uarts.append(uart)
        s = SimStreamDma(path, dest, ssi, uart)
        self.stores.append(s.store)
        log.info('AxiStreamDma(%s, 0x%x) -> SimStreamDma (%s)', path, dest,
                 'camera UART' if uart else 'SRPv3 responder')
        return s

    # ---- write log --------------------------------------------------------
    def record(self, store, addr, old, data):
        regs, ncovered = store.changes(addr, old, data)
        rec = {'store': store.name, 'addr': '0x%x' % addr, 'size': len(data),
               'regs': regs[:8], 'nregs': ncovered}
        self.writes.append(rec)
        if self._logf:
            self._logf.write(json.dumps(rec) + '\n')
            self._logf.flush()

    def record_uart(self, dest, cmd):
        rec = {'store': 'uart', 'dest': '0x%x' % dest, 'cmd': cmd}
        self.writes.append(rec)
        if self._logf:
            self._logf.write(json.dumps(rec) + '\n')
            self._logf.flush()

    # ---- seeds / fault ----------------------------------------------------
    def _var_addr(self, var):
        return var.parent.address + var.offset

    def _locate(self, var, wait=2.0):
        """Which store serves var: read it once and see which store answered.  A device whose
        enableDeps a seed just set (a front-end board behind its PGP link-ready bit) is enabled
        by pyrogue's update thread, so a read that reaches no store is retried for up to 'wait' s."""
        end = time.monotonic() + wait
        while True:
            before = [s.ntrans for s in self.stores]
            var.get(read=True)
            hit = [s for s, n in zip(self.stores, before) if s.ntrans != n]
            if hit or time.monotonic() >= end:
                break
            time.sleep(0.05)
        behind = [s for s in hit if s.proxy_of in hit]     # through an AXI-Lite master proxy
        if behind:
            hit = behind
        if len(hit) != 1:
            raise SimDeviceError('rogue_dev: cannot tell which simulated transport serves %s '
                                 '(%d answered)' % (var.path, len(hit)))
        return hit[0]

    def _resolve(self, root, path, what):
        node = root.getNode(path)
        if node is None:
            raise SimDeviceError('rogue_dev: %s path %r is not in the %s tree' %
                                 (what, path, root.name))
        if not isinstance(node, pr.RemoteVariable):
            deps = [d.path for d in getattr(node, 'dependencies', []) or []]
            raise SimDeviceError('rogue_dev: %s path %r is a %s, not a register%s' %
                                 (what, path, type(node).__name__,
                                  ('; set its dependencies %s' % deps) if deps else ''))
        return node

    def _index_paths(self, root):
        """addr -> register paths, for the write log (one probe per top-level device)."""
        for dev in root.deviceList:
            if dev.parent is not root:
                continue
            rvars = [v for v in dev.variableList
                     if isinstance(v, pr.RemoteVariable) and v.mode != 'WO']
            if not rvars:
                continue
            try:
                store = self._locate(rvars[0], wait=0)
            except Exception as e:
                log.warning('%s', e)
                continue
            for v in dev.variableList:
                if isinstance(v, pr.RemoteVariable):
                    a = self._var_addr(v)
                    store._vars.setdefault(a - (a % 4), []).append(
                        (v.path, a, list(v.bitOffset), list(v.bitSize)))

    def _on_sim(self, root):
        """True if some register of root is served by a simulated transport."""
        for v in root.variableList:
            if isinstance(v, pr.RemoteVariable) and v.mode != 'WO':
                before = [s.ntrans for s in self.stores]
                v.get(read=True)
                return any(s.ntrans != n for s, n in zip(self.stores, before))
        return False

    def attach(self, root):
        if not self._on_sim(root):
            log.info('rogue_dev: root %s is not on a simulated transport; left alone', root.path)
            return
        self.roots.append(root)
        for dev in root.deviceList:
            if type(dev).__module__.endswith('_AxiLiteMasterProxy') and type(dev).__name__ == '_Regs':
                self._axil_proxy(dev)
        pfx = root.path + '.'
        for path in [p for p in self.seeds if p.startswith(pfx)]:
            var = self._resolve(root, path, 'seed')
            value = self.seeds.pop(path)
            store = self._locate(var)
            addr = self._var_addr(var)
            if isinstance(value, dict) and 'response' in value:     # the device's answer bits
                store.add_response(addr, var.bitOffset[0], value['bits'], value['response'])
                self.applied[path] = (store.name, addr, value)
                log.info('seed %s @%s+0x%x: low %d bits read 0x%x', path, store.name, addr,
                         value['bits'], value['response'])
                continue
            if isinstance(value, dict):         # {"count_hz": f}: a free-running counter
                store.add_counter(addr, var.bitOffset, var.bitSize, value['count_hz'])
                self.applied[path] = (store.name, addr, value)
                log.info('seed %s @%s+0x%x counts at %s Hz', path, store.name, addr,
                         value['count_hz'])
                continue
            store.poke(addr, var.bitOffset, var.bitSize, value)
            got = var.get(read=True)
            self.applied[path] = (store.name, addr, value)
            log.info('seed %s @%s+0x%x = 0x%x (reads %r)', path, store.name, addr, value, got)
        self._index_paths(root)         # after the seeds, which may enable a device (_locate)
        if self.fault and self.fault[0].startswith(pfx):
            path, value = self.fault
            var = self._resolve(root, path, 'fault')
            store = self._locate(var)
            addr = self._var_addr(var)
            if value is None:
                value = (1 << sum(var.bitSize)) - 1
            store.add_fault(addr, var.bitOffset, var.bitSize, value, path)
            self.fault_applied = (path, store.name, addr, value)
            log.warning('FAULT %s @%s+0x%x reads back 0x%x', path, store.name, addr, value)
            _say('FAULT %s @%s+0x%x reads back 0x%x' % (path, store.name, addr, value))

    def _axil_proxy(self, regs):
        """Emulate a firmware AXI-Lite master proxy (surf AxiLiteMasterProxy): the host writes Addr
        (and Data), then Rnw, and polls Done; the firmware does the access on its AXI-Lite bus and
        sets Done (Resp 0), a read's data in Data.  The proxied bus is a register store of its own."""
        rnw, done, addr, data = (regs.nodes[n] for n in ('Rnw', 'Done', 'Addr', 'Data'))
        store = self._locate(addr, wait=0)
        bus = Store('AxiLiteMasterProxy(%s)' % regs.path)
        bus.proxy_of = store
        self.stores.append(bus)
        a_rnw, a_done = self._var_addr(rnw), self._var_addr(done)
        a_addr, a_data = self._var_addr(addr), self._var_addr(data)

        def kick(st):
            word = lambda a: int.from_bytes(st.raw_read(a, 4), 'little')
            target = word(a_addr)
            if (word(a_rnw) >> rnw.bitOffset[0]) & 1:                  # Read
                st.raw_write(a_data, bus.read(target, 4))
            else:
                bus.write(target, st.raw_read(a_data, 4))
            st.poke(a_done, done.bitOffset, [3], 1)                    # Done 1, Resp 0 (OK)
        store._hooks[a_rnw - (a_rnw % 4)] = kick
        log.info('rogue_dev: %s is an AXI-Lite master proxy onto %s', regs.path, bus.name)

    def pending(self):
        out = sorted(self.seeds)
        if self.fault and not self.fault_applied:
            out.append(self.fault[0])
        return out

    # ---- the IOC's PVs ----------------------------------------------------
    def pv_get(self, name):
        if self.pv_fault and name == self.pv_fault[0]:
            return self.pv_fault[1]
        if name not in self.pvs:
            if name not in self.missing_pvs:
                self.missing_pvs.append(name)
                _say('the simulated IOC serves no PV %s (reads None)' % name)
            return None
        return self.pvs[name]

    def pv_put(self, name, value):
        if name not in self.pvs:
            if name not in self.missing_pvs:
                self.missing_pvs.append(name)
                _say('the simulated IOC serves no PV %s (put ignored)' % name)
            return None
        old, self.pvs[name] = self.pvs[name], value
        rec = {'store': 'pv', 'pv': name, 'value': value, 'old': old}
        self.writes.append(rec)
        if self._logf:
            self._logf.write(json.dumps(rec, default=str) + '\n')
            self._logf.flush()
        return 1


_SIM = _Sim()


def _seed_value(k, v):
    if k.startswith(PV_PREFIX) and not isinstance(v, str):
        return v                    # PV values keep their JSON type (float, list...)
    if isinstance(v, dict) and set(v) == {'string'}:     # a string register (pr.String)
        return int.from_bytes(str(v['string']).encode('ascii'), 'little')
    if isinstance(v, dict) and set(v) == {'response', 'bits'}:   # a device's answer bits
        if not 0 < int(v['bits']) <= 32:
            raise SimDeviceError('rogue_dev: seed %r: "bits" is 1..32, not %r' % (k, v['bits']))
        return {'response': _int(v['response']), 'bits': int(v['bits'])}
    if isinstance(v, dict):
        if set(v) != {'count_hz'} or float(v['count_hz']) <= 0:
            raise SimDeviceError('rogue_dev: seed %r: a dict seed is {"count_hz": <positive '
                                 'rate>}, {"string": <text>} or {"response": <value>, "bits": '
                                 '<n>}, not %r' % (k, v))
        return {'count_hz': float(v['count_hz'])}
    return _int(v)


def _comment_key(k):
    """A seed-file key that is not a register: '_' and no '.' (a register path of a root whose
    class name starts with '_', such as tb_config's _DevRoot, has dots)."""
    return k.startswith('_') and '.' not in k


def load_seeds(det_type=None, path=None, extra=False):
    """{path: value} from the type's seed file (keys starting with '_' with no '.' are comments);
    with extra=True also its "_proc" text (or None)."""
    path = path or os.environ.get(ENV_SEEDS) or (
        os.path.join(SEED_DIR, '%s.json' % det_type) if det_type else None)
    if not path:
        return ({}, None, None) if extra else ({}, None)
    with open(path) as f:
        d = json.load(f)
    seeds = {k: _seed_value(k, v) for k, v in d.items() if not _comment_key(k)}
    proc = d.get('_proc')
    proc = '\n'.join(proc) + '\n' if isinstance(proc, list) else proc
    return (seeds, path, proc) if extra else (seeds, path)


def load_uart(det_type=None, path=None):
    """The seed file's "_uart" table (a camera's serial answers), or None."""
    path = path or os.environ.get(ENV_SEEDS) or (
        os.path.join(SEED_DIR, '%s.json' % det_type) if det_type else None)
    if not path:
        return None
    with open(path) as f:
        return json.load(f).get('_uart')


def parse_fault(s):
    if not s:
        return None
    path, _, value = s.partition('=')
    value = value.strip()
    if path.strip().startswith(PV_PREFIX) and value:
        try:
            return path.strip(), _int(value)
        except ValueError:
            return path.strip(), float(value)
    return path.strip(), (_int(value) if value else None)


def proc_path(dev):
    """The /proc file a datadev driver has for device dev (PgpMonitor.detect_version)."""
    return '/proc/' + dev.split('/')[-1]


def install(dev, det_type=None, seeds=None, fault=None, epics_prefix=None, proc=None):
    """Replace rogue's hardware transports with simulated ones for device dev, and, when the
    seeds name PVs or /proc text, the device's IOC (epics.PV) and its /proc file.

    Must run before the config module builds its firmware roots.  Returns the
    simulation state.  Raises if dev is not a 'sim://' device.
    """
    if not is_sim(dev):
        raise SimDeviceError('rogue_dev.install: %r is not a sim:// device' % dev)
    if _SIM.dev is not None:
        if _SIM.dev != dev:
            raise SimDeviceError('rogue_dev: already installed for %r' % _SIM.dev)
        return _SIM
    _SIM.dev = dev
    if seeds is None:
        seeds, spath, sproc = load_seeds(det_type, extra=True)
        proc = proc if proc is not None else sproc
        log.info('rogue_dev: %d seeds from %s', len(seeds), spath)
        _SIM.uart = load_uart(det_type)
    pvs = {k[len(PV_PREFIX):]: v for k, v in seeds.items() if k.startswith(PV_PREFIX)}
    _SIM.seeds = {k: v for k, v in seeds.items() if not k.startswith(PV_PREFIX)}
    _SIM.fault = parse_fault(fault if fault is not None else os.environ.get(ENV_FAULT))
    if os.environ.get(ENV_LOG):
        _SIM._logf = open(os.environ[ENV_LOG], 'a')

    axi = rogue.hardware.axi
    _SIM._orig = (axi.AxiMemMap, axi.AxiStreamDma, pr.Device._start,
                  pr.interfaces.ZmqServer.__init__)
    axi.AxiMemMap = _SIM.mem_map
    axi.AxiStreamDma = _SIM.stream_dma

    if pvs or (_SIM.fault and _SIM.fault[0].startswith(PV_PREFIX)):
        if any('{prefix}' in n for n in pvs) and not epics_prefix:
            raise SimDeviceError('rogue_dev: the %s PVs need the drp\'s -k epics_prefix' % det_type)
        _SIM.pvs = {n.replace('{prefix}', epics_prefix or ''): v for n, v in pvs.items()}
        if _SIM.fault and _SIM.fault[0].startswith(PV_PREFIX):
            name = _SIM.fault[0][len(PV_PREFIX):].replace('{prefix}', epics_prefix or '')
            if name not in _SIM.pvs:
                raise SimDeviceError('rogue_dev: fault PV %r is not served by the simulated '
                                     'IOC' % name)
            _SIM.pv_fault = (name, 0 if _SIM.fault[1] is None else _SIM.fault[1])
            _SIM.fault_applied = (_SIM.fault[0], 'pv', name, _SIM.pv_fault[1])
            _say('FAULT PV %s reads back %r' % (name, _SIM.pv_fault[1]))
        import epics
        _SIM._orig_pv = epics.PV
        epics.PV = SimPV
        log.info('rogue_dev: epics.PV -> SimPV, %d PVs (prefix %s)', len(_SIM.pvs), epics_prefix)

    if proc is not None:
        _SIM.proc = proc
        real_open, ppath = builtins.open, proc_path(dev)
        _SIM._orig_open = real_open

        def _open(file, mode='r', *args, **kwargs):
            if file == ppath and 'r' in mode and 'b' not in mode:
                return io.StringIO(_SIM.proc)
            return real_open(file, mode, *args, **kwargs)
        builtins.open = _open
        log.info('rogue_dev: %s reads the simulated driver text', ppath)

    # Seeds go in once a root has built its blocks, before its devices'
    # _start() hooks and its initial read (pyrogue Root.start calls
    # pr.Device._start(root) in between).
    dev_start = pr.Device._start

    def _start(self, *args, **kwargs):
        if isinstance(self, pr.Root):
            _SIM.attach(self)
        return dev_start(self, *args, **kwargs)
    pr.Device._start = _start

    # Some firmware roots (high_rate_encoder_dev) serve Xilinx's XVC debug protocol on a TCP port
    # of all interfaces, for a JTAG cable behind the card; the simulated device has none, so its
    # Xvc is a stream endpoint that drops what it gets and opens no socket.
    _SIM._orig_xvc = rogue.protocols.xilinx.Xvc
    rogue.protocols.xilinx.Xvc = SimXvc

    # Firmware roots open a ZMQ server on a fixed port on all interfaces; a
    # simulated one stays on loopback and takes a free port.
    zmq_init = pr.interfaces.ZmqServer.__init__

    def zmq(self, *, root, addr, port, **kwargs):
        zmq_init(self, root=root, addr='127.0.0.1', port=0, **kwargs)
    pr.interfaces.ZmqServer.__init__ = zmq

    log.info('rogue_dev: installed for %s (fault=%s)', dev, _SIM.fault)
    return _SIM


def state():
    return _SIM


def uninstall():
    """Undo install(): rogue's own transports and hooks come back and the state starts fresh.
    For tests; a DRP installs once per process and never uninstalls."""
    global _SIM
    if _SIM._orig:
        axi = rogue.hardware.axi
        (axi.AxiMemMap, axi.AxiStreamDma, pr.Device._start,
         pr.interfaces.ZmqServer.__init__) = _SIM._orig
    if getattr(_SIM, '_orig_pv', None):
        import epics
        epics.PV = _SIM._orig_pv
    if getattr(_SIM, '_orig_xvc', None):
        rogue.protocols.xilinx.Xvc = _SIM._orig_xvc
    if getattr(_SIM, '_orig_open', None):
        builtins.open = _SIM._orig_open
    if _SIM._logf:
        _SIM._logf.close()
    _SIM = _Sim()
