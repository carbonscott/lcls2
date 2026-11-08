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
rogue's SrpV3 protocol, the config script -- is the real code.  Registers
read back what was last written (0 if never written), except:

  seeds   a JSON file {"<register path>": value, ...} (psdaq/sim/seeds/
          <type>.json by default) presets status registers the config
          script polls (FW version, lock bits, clock counters...).  Each
          path is applied when the root that owns it starts; a path that
          is not a RemoteVariable in the tree raises (no auto-vivifying).
  fault   PSDAQ_SIM_ROGUE_FAULT='<register path>[=<value>]': that register
          reads back <value> (default all ones) whatever is written, so
          rogue's write-verify, or the config script's own check, fails
          and names it.

Every register write is recorded (WRITES, and one JSON line per write to
$PSDAQ_SIM_ROGUE_LOG if set) with the register paths it covers.

Nothing here runs unless the device string starts with 'sim://'.
"""

import json
import logging
import os
import queue
import struct
import threading

import rogue
import rogue.hardware.axi
import rogue.interfaces.memory as rim
import rogue.interfaces.stream as ris
import pyrogue as pr

SIM_PREFIX = 'sim://'
ENV_SEEDS = 'PSDAQ_SIM_ROGUE_SEEDS'
ENV_FAULT = 'PSDAQ_SIM_ROGUE_FAULT'
ENV_LOG = 'PSDAQ_SIM_ROGUE_LOG'
SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'seeds')

log = logging.getLogger('psdaq.sim.rogue_dev')


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
        self._vars = {}         # word address -> [(path, var_addr, offsets, sizes)]

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

    def poke(self, var_addr, offsets, sizes, value):
        nbytes = (max(o + s for o, s in zip(offsets, sizes)) + 7) // 8
        with self._lock:
            buf = self.raw_read(var_addr, nbytes)
            _put_bits(buf, var_addr, var_addr, offsets, sizes, value)
            self.raw_write(var_addr, buf)

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

    def __init__(self, path, dest, ssi=True):
        ris.Master.__init__(self)
        ris.Slave.__init__(self)
        self.dest = dest
        self.store = Store('AxiStreamDma(%s,0x%x)' % (path, dest))
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
                resp = self._srpv3(ba)
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

    def _stop(self):
        self._q.put(None)


class _Sim(object):
    def __init__(self):
        self.dev = None
        self.stores = []
        self.seeds = {}         # path -> value, not yet applied
        self.applied = {}       # path -> (store, addr, value)
        self.fault = None       # (path, value)
        self.fault_applied = None
        self.roots = []
        self.writes = []
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
        s = SimStreamDma(path, dest, ssi)
        self.stores.append(s.store)
        log.info('AxiStreamDma(%s, 0x%x) -> SimStreamDma (SRPv3 responder)', path, dest)
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

    # ---- seeds / fault ----------------------------------------------------
    def _var_addr(self, var):
        return var.parent.address + var.offset

    def _locate(self, var):
        """Which store serves var: read it once and see which store answered."""
        before = [s.ntrans for s in self.stores]
        var.get(read=True)
        hit = [s for s, n in zip(self.stores, before) if s.ntrans != n]
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
                store = self._locate(rvars[0])
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
        self._index_paths(root)
        pfx = root.path + '.'
        for path in [p for p in self.seeds if p.startswith(pfx)]:
            var = self._resolve(root, path, 'seed')
            value = self.seeds.pop(path)
            store = self._locate(var)
            addr = self._var_addr(var)
            store.poke(addr, var.bitOffset, var.bitSize, value)
            got = var.get(read=True)
            self.applied[path] = (store.name, addr, value)
            log.info('seed %s @%s+0x%x = 0x%x (reads %r)', path, store.name, addr, value, got)
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

    def pending(self):
        out = sorted(self.seeds)
        if self.fault and not self.fault_applied:
            out.append(self.fault[0])
        return out


_SIM = _Sim()


def load_seeds(det_type=None, path=None):
    path = path or os.environ.get(ENV_SEEDS) or (
        os.path.join(SEED_DIR, '%s.json' % det_type) if det_type else None)
    if not path:
        return {}, None
    with open(path) as f:
        d = json.load(f)
    return {k: _int(v) for k, v in d.items() if not k.startswith('_')}, path


def parse_fault(s):
    if not s:
        return None
    path, _, value = s.partition('=')
    return path.strip(), (_int(value.strip()) if value.strip() else None)


def install(dev, det_type=None, seeds=None, fault=None):
    """Replace rogue's hardware transports with simulated ones for device dev.

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
        seeds, spath = load_seeds(det_type)
        log.info('rogue_dev: %d seeds from %s', len(seeds), spath)
    _SIM.seeds = dict(seeds)
    _SIM.fault = parse_fault(fault if fault is not None else os.environ.get(ENV_FAULT))
    if os.environ.get(ENV_LOG):
        _SIM._logf = open(os.environ[ENV_LOG], 'a')

    axi = rogue.hardware.axi
    _SIM._orig = (axi.AxiMemMap, axi.AxiStreamDma, pr.Device._start,
                  pr.interfaces.ZmqServer.__init__)
    axi.AxiMemMap = _SIM.mem_map
    axi.AxiStreamDma = _SIM.stream_dma

    # Seeds go in once a root has built its blocks, before its devices'
    # _start() hooks and its initial read (pyrogue Root.start calls
    # pr.Device._start(root) in between).
    dev_start = pr.Device._start

    def _start(self, *args, **kwargs):
        if isinstance(self, pr.Root):
            _SIM.attach(self)
        return dev_start(self, *args, **kwargs)
    pr.Device._start = _start

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
    if _SIM._logf:
        _SIM._logf.close()
    _SIM = _Sim()
