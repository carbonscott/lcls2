"""Tests for psdaq.sim.simsls, the stand-in for a Jungfrau module's slsDetector servers.

A small client here speaks the slsDetectorPackage 9.0.0 protocol as sls::Detector does (one call
per TCP connection: <int32 fnum><args>, reply <int32 ret>[1000-byte message on FAIL]<retval>);
with the env's own client tools (sls_detector_put/get) on PATH, one test also drives simsls
through them.  Every socket is on 127.0.0.1."""

import json
import os
import shutil
import socket
import struct
import subprocess
import time

import numpy as np
import pytest

from psdaq.sim import pattern, simsls

SEED = 0x1234


def free_port():
    """A loopback port p whose TCP p, p+1 and UDP p are all free (simsls binds those)."""
    for _ in range(50):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        p = s.getsockname()[1]
        s.close()
        try:
            socks = []
            for port, typ in ((p, socket.SOCK_STREAM), (p + 1, socket.SOCK_STREAM), (p, socket.SOCK_DGRAM)):
                t = socket.socket(socket.AF_INET, typ)
                socks.append(t)
                t.bind(('127.0.0.1', port))
            return p
        except OSError:
            continue
        finally:
            for t in socks:
                t.close()
    raise RuntimeError('no free port')


def call(port, fnum, args=b'', rlen=0):
    """(ret, payload): one sls call; payload is the error message on FAIL."""
    with socket.create_connection(('127.0.0.1', port), timeout=5) as c:
        c.sendall(struct.pack('<i', fnum) + args)
        ret = struct.unpack('<i', recv(c, 4))[0]
        if ret == simsls.FAIL:
            return ret, recv(c, simsls.MAX_STR_LENGTH).rstrip(b'\0').decode()
        return ret, recv(c, rlen)


def recv(c, n):
    b = b''
    while len(b) < n:
        chunk = c.recv(n - len(b))
        assert chunk, 'connection closed'
        b += chunk
    return b


def ok(port, fnum, fmt_args='', args=(), fmt_ret=''):
    ret, out = call(port, fnum, struct.pack('<' + fmt_args, *args) if fmt_args else b'',
                    struct.calcsize('<' + fmt_ret) if fmt_ret else 0)
    assert ret == simsls.OK, out
    return struct.unpack('<' + fmt_ret, out)[0] if fmt_ret else None


def ip(text):
    return struct.unpack('<I', socket.inet_aton(text))[0]


@pytest.fixture
def sim():
    port = free_port()
    s = simsls.SimSls(port, seed=SEED).start()
    yield s
    s.close()


@pytest.fixture
def faulty():
    port = free_port()
    s = simsls.SimSls(port, seed=SEED, fault=simsls.parse_fault('exptime')).start()
    yield s
    s.close()


def configure(port, dport):
    ok(port, 4, 'i', (simsls.TRIGGER_EXPOSURE,), 'i')          # F_SET_TIMING_MODE
    ok(port, 26, 'q', (2 ** 63 - 1,))                          # F_SET_NUM_TRIGGERS, as Drp::Jungfrau
    ok(port, 24, 'q', (1,))                                    # F_SET_NUM_FRAMES
    ok(port, 132, 'H', (dport,))                               # F_SET_DEST_UDP_PORT
    ok(port, 128, 'I', (ip('127.0.0.1'),))                     # F_SET_DEST_UDP_IP
    ok(port, 124, 'Q', (0x080056000000,))                      # F_SET_DEST_UDP_MAC
    ok(port, 120, 'I', (ip('127.0.0.1'),))                     # F_SET_SOURCE_UDP_IP
    ok(port, 116, 'Q', (0xaabbccddeeff,))                      # F_SET_SOURCE_UDP_MAC
    ok(port, 199)                                              # F_VALIDATE_UDP_CONFIG
    ok(port, 89, 'i', (1,), 'i')                               # F_POWER_CHIP on


def test_identity_and_version(sim):
    p = sim.port
    assert ok(p, 1, fmt_ret='i') == simsls.JUNGFRAU
    for port in (p, p + 1):                                    # control and stop servers
        assert ok(port, 6, fmt_ret='%ds' % simsls.MAX_STR_LENGTH).rstrip(b'\0') == b'9.0.0 0x241121'
        ok(port, 96)                                           # F_INITIAL_CHECKS
    assert ok(p, 203, fmt_ret='i') == 1                        # F_IS_VIRTUAL
    assert ok(p, 232, fmt_ret='i') == 0x2a0                    # F_GET_MODULE_ID
    assert ok(p + 1, 21, fmt_ret='i') == simsls.IDLE           # F_GET_RUN_STATUS (stop server)


def test_settings_read_back_and_values_are_validated(sim):
    p = sim.port
    ok(p, 34, 'qq', (-1, 10000))                               # F_SET_EXPTIME
    assert ok(p, 33, 'i', (-1,), 'q') == 10000
    ok(p, 12, 'iii', (simsls.DACS['vb_ds'], 0, 1000), 'i')     # F_SET_DAC
    assert ok(p, 12, 'iii', (simsls.DACS['vb_ds'], 0, -1), 'i') == 1000
    assert ok(p, 12, 'iii', (simsls.HIGH_VOLTAGE, 0, 200), 'i') == 200
    ret, msg = call(p, 12, struct.pack('<iii', simsls.HIGH_VOLTAGE, 0, 250), 4)
    assert ret == simsls.FAIL and 'Bad value 250' in msg
    ret, msg = call(p, 12, struct.pack('<iii', simsls.DACS['vb_ds'], 0, 5000), 4)
    assert ret == simsls.FAIL and 'Allowed limits' in msg
    ret, msg = call(p, 17, struct.pack('<i', 0), 4)            # F_SET_SETTINGS STANDARD
    assert ret == simsls.FAIL
    ret, msg = call(p, 107, struct.pack('<Q', 0))              # next frame number 0
    assert ret == simsls.FAIL and 'Cannot be 0' in msg


def test_data_destination_must_be_loopback(sim):
    ret, msg = call(sim.port, 128, struct.pack('<I', ip('10.0.0.10')))
    assert ret == simsls.FAIL and '10.0.0.10' in msg and 'loopback' in msg


def test_unserved_function_is_a_version_mismatch(sim):
    ret, msg = call(sim.port, 999)
    assert ret == simsls.FAIL and simsls.UNRECOGNIZED in msg


def test_start_needs_the_udp_config(sim):
    ret, msg = call(sim.port, 19)
    assert ret == simsls.FAIL and 'udp_dstip' in msg


def test_fault_reads_back_wrong(faulty):
    ok(faulty.port, 34, 'qq', (-1, 10000))
    assert ok(faulty.port, 33, 'i', (-1,), 'q') == 10001
    assert faulty.module.fault_hits == 1


def test_unknown_fault_setting_is_refused():
    with pytest.raises(ValueError):
        simsls.parse_fault('nosuchsetting')


@pytest.mark.parametrize('slow', [False, True])
def test_one_frame_per_trigger(sim, slow):
    """Every frame arrives whole through a 256 KiB receive buffer (a frame costs a buffer 2 MiB),
    also when the reader takes 1 ms per packet: simsls sends a frame in bursts that fit (sent back
    to back, a frame overflowed the 416 KiB buffer the DRP gets where net.core.rmem_max is the
    default: 'sent 78 of 128 packets' in matrix run h1 at b14885af3)."""
    p = sim.port
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 128 << 10)
    rx.bind(('127.0.0.1', 0))
    rx.settimeout(5)
    sim.module.rcvbuf = rx.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
    assert sim.module.rcvbuf <= 256 << 10 and sim.module.limit is not None     # a frame does not fit
    configure(p, rx.getsockname()[1])
    ok(p, 107, 'Q', (1,))                                      # BeginRun: next frame number 1
    trig = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    trig.sendto(b'TRIG', ('127.0.0.1', p))                     # not armed yet: ignored
    time.sleep(0.3)
    assert sim.module.counts['triggers_ignored'] == 1
    ok(p, 19)                                                  # F_START_ACQUISITION
    assert ok(p + 1, 21, fmt_ret='i') == simsls.WAITING
    idx = np.arange(512 * 1024, dtype=np.uint64)
    for frame in (1, 2):
        trig.sendto(b'TRIG', ('127.0.0.1', p))
        packets = {}
        while len(packets) < 128:
            d = rx.recv(9000)
            if slow:
                time.sleep(0.001)
            assert len(d) == 48 + 8192
            h = simsls.HEADER.unpack(d[:48])
            assert h[0] == frame and h[5] == 0x2a0 and h[11] == simsls.JUNGFRAU
            packets[h[2]] = d[48:]
        img = np.frombuffer(b''.join(packets[k] for k in range(128)), np.uint16)
        assert np.array_equal(img, pattern.pattern(SEED, frame, idx, 16).astype(np.uint16))
    ok(p + 1, 20)                                              # F_STOP_ACQUISITION
    assert ok(p + 1, 21, fmt_ret='i') == simsls.IDLE
    assert ok(p, 108, fmt_ret='Q') == 3                        # F_GET_NEXT_FRAME_NUMBER
    c = sim.module.counts
    assert c['receiver_drops'] == 0 and c['room_timeouts'] == 0 and (c['room_waits'] > 0 or not slow), c
    rx.close()
    trig.close()


def test_udp_queue_reads_the_receivers_line(tmp_path):
    """udp_queue: rx_queue and drops of the socket bound to ip:port, from /proc/net/udp's format."""
    table = tmp_path / 'udp'
    table.write_text(
        '   sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops\n'
        '  901: 0100007F:7A50 00000000:0000 07 00000000:00041000 00:00000000 00000000  1000        0 123 2 0000000000000000 42\n')
    assert simsls.udp_queue('127.0.0.1', 0x7A50, str(table)) == (0x41000, 42)
    assert simsls.udp_queue('127.0.0.1', 0x7A51, str(table)) is None
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)       # and this host's own table
    rx.bind(('127.0.0.1', 0))
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(3):
        tx.sendto(b'x' * 8240, rx.getsockname())
    queued, drops = simsls.udp_queue(*rx.getsockname())
    assert queued >= 3 * 8240 and drops == 0
    rx.close()
    tx.close()


@pytest.mark.skipif(shutil.which('sls_detector_put') is None, reason='no slsDetectorPackage client')
def test_the_sls_client_drives_it(sim, tmp_path):
    env = dict(os.environ, SLSDETNAME=f'simsls_test_{os.getpid()}')
    host = f'127.0.0.1:{sim.port}'

    def run(*args):
        r = subprocess.run(list(args), capture_output=True, text=True, timeout=60, env=env)
        return r.returncode, r.stdout + r.stderr

    try:
        assert run('sls_detector_put', 'hostname', host)[0] == 0
        rc, out = run('sls_detector_get', 'type')
        assert rc == 0 and 'Jungfrau' in out
        assert run('sls_detector_put', 'exptime', '10us')[0] == 0
        rc, out = run('sls_detector_get', 'exptime')
        assert rc == 0 and '10us' in out
        rc, out = run('sls_detector_put', 'highvoltage', '250')
        assert rc != 0 and 'Bad value 250' in out
    finally:
        run('sls_detector_put', 'free')


SEED_CHECK = """
import json
import psdaq.configdb.configdb as cdb
def refuse(*args, **kwargs):
    raise AssertionError('the real configdb was contacted')
cdb.configdb = refuse
from psdaq.sim import configdb_seed, daq_sim
P = daq_sim.ports(5)
top = configdb_seed.type_cdict('jungfrau', 'jungfrau', 0)
configdb_seed.apply_sets(top, [s.format(**P) for s in daq_sim.SIM_TYPES['jungfrau']['sets']])
try:
    configdb_seed.apply_sets(top, ['user.no_such_key=1'])
    print('NOT REFUSED')
except ValueError:
    pass
print('JSON ' + json.dumps(top.typed_json()))
print('KWARGS ' + daq_sim.SIM_TYPES['jungfrau']['kwargs'].format(length=0, seed=0, work='', **P))
"""


def test_daq_sim_points_the_module_data_at_loopback():
    """The jungfrau config daq_sim seeds is its store's, with the module's data destination and
    source on loopback and its UDP port the one MemPoolSim binds (sim_udp_port), types kept."""
    if not os.environ.get('SUBMODULEDIR'):
        pytest.skip('needs $SUBMODULEDIR (the DAQ env)')
    pytest.importorskip('pyrogue')
    import json
    import sys
    r = subprocess.run([sys.executable, '-c', SEED_CHECK], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    lines = r.stdout.splitlines()
    assert 'NOT REFUSED' not in lines
    d = json.loads([x for x in lines if x.startswith('JSON ')][0][5:])
    kw = dict(kv.split('=', 1) for kv in [x for x in lines if x.startswith('KWARGS ')][0][7:].split(','))
    assert d['detType:RO'] == 'jungfrau'
    assert d['user']['kcu_ip'] == '127.0.0.1' and d['user']['jungfrau_ip'] == '127.0.0.1'
    assert d['user']['port'] == 31056 and d[':types:']['user']['port'] == 'UINT16'
    assert kw['slsHosts'] == '127.0.0.1:31054' and kw['sim_udp_port'] == '31056'
    assert kw['segNums'] == '0'


# ---- the hutch's beam (--beam FILE) -----------------------------------------------------------

def write_beam(path, transmission, is_open):
    """FILE as a beam feed writes it: a new file renamed over the old one."""
    tmp = str(path) + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'transmission': transmission, 'open': is_open, 'note': 'ignored'}, f)
    os.replace(tmp, str(path))


def stated_model(seed, n, t, is_open, known=True):
    """Frame n written out from the formula in simsls's module doc, not from its code."""
    i = np.arange(512 * 1024, dtype=np.uint64)
    dark = 1000 + (pattern.pattern(seed, n, i, 16).astype(np.int64) & 0x3f)
    row, col = np.divmod(np.arange(512 * 1024), 1024)
    dr, dc = row - 256., col - 512.
    x = (np.sqrt(dr * dr + dc * dc) - 180.) / 40.
    s = np.rint(12000. * np.maximum(0., 1. - x * x))
    e = (900 + int(pattern.mix((n * 0x9e37 + seed) & 0xffffffff)) % 201) / 1000.
    g = t * e if (known and is_open) else 0.
    img = np.minimum(dark + np.floor(s * g + 0.5).astype(np.int64), 0x3fff).astype(np.uint16)
    stamp = b'HS' + bytes([1, (1 if is_open else 0) | (2 if known else 0)]) + struct.pack('<dI', t, seed)
    img[:16] = np.frombuffer(stamp, np.uint8)
    return img


def signal_pixels(img):
    return np.asarray(img).ravel()[16:].astype(np.float64)


@pytest.mark.parametrize('t, is_open', [(1.0, True), (0.443303, True), (0.121119, True), (0.264907, False)])
def test_beam_frame_is_the_stated_model(tmp_path, t, is_open):
    f = tmp_path / 'beam.json'
    write_beam(f, t, is_open)
    m = simsls.Module(seed=SEED, beam=str(f))
    for n in (1, 2, 1000, 123456):
        img = m.frame_image(n)
        assert img.dtype == np.uint16 and img.shape == (512 * 1024,)
        assert np.array_equal(img, stated_model(SEED, n, t, is_open)), n
        assert simsls.read_stamp(img) == (t, is_open, True, SEED)
        assert int((img >> 14).max()) == 0                     # gain bits 0: no pixel is 'hot'
    assert np.array_equal(simsls.coupled_image(SEED, 7, t, is_open), stated_model(SEED, 7, t, is_open))


def test_without_beam_frames_are_unchanged():
    m = simsls.Module(seed=SEED)
    idx = np.arange(512 * 1024, dtype=np.uint64)
    for n in (1, 2, 99):
        assert np.array_equal(m.frame_image(n), pattern.pattern(SEED, n, idx, 16).astype(np.uint16))
    assert simsls.read_stamp(m.frame_image(1)) is None and 'beam_changes' not in m.counts


def test_beam_change_applies_from_the_next_frame(tmp_path):
    f = tmp_path / 'beam.json'
    write_beam(f, 1.0, True)
    m = simsls.Module(seed=SEED, beam=str(f))
    bright = m.frame_image(1)
    assert signal_pixels(bright).max() > 10000
    write_beam(f, 1.0, False)                                  # the stopper closes
    dark = m.frame_image(2)
    assert simsls.read_stamp(dark) == (1.0, False, True, SEED)
    px = signal_pixels(dark)
    assert px.min() >= 1000 and px.max() <= 1063               # the dark band: pedestal + 0-63 noise
    assert abs(px.mean() - 1031.5) < 0.2
    assert np.array_equal(dark, stated_model(SEED, 2, 1.0, False))
    write_beam(f, 0.25, True)
    assert simsls.read_stamp(m.frame_image(3))[:2] == (0.25, True)
    assert m.counts['beam_changes'] == 3


def test_mean_signal_follows_the_transmission(tmp_path):
    """The step check of a joint demo: (mean - 1031.5) / full-beam signal = T, within E_n."""
    f = tmp_path / 'beam.json'
    m = simsls.Module(seed=SEED, beam=str(f))
    s = simsls.beam_profile()[16:].mean()
    assert 1300 < s < 1450                                     # about 1380 ADU at full beam
    for n, t in enumerate((1.0, 0.443303, 0.264907, 0.121119), start=10):
        write_beam(f, t, True)
        got = signal_pixels(m.frame_image(n)).mean() - 1031.5
        want = t * simsls.pulse_energy(SEED, n) * s
        assert abs(got - want) < 0.002 * want + 0.2, (t, got, want)
    assert {simsls.pulse_energy(SEED, n) for n in range(1, 2000)} <= {x / 1000. for x in range(900, 1101)}


def test_beam_state_unknown_until_valid_and_bad_files_keep_the_last(tmp_path):
    f = tmp_path / 'beam.json'
    m = simsls.Module(seed=SEED, beam=str(f))
    img = m.frame_image(1)                                     # no file yet: unknown, dark
    assert simsls.read_stamp(img) == (0., False, False, SEED) and signal_pixels(img).max() <= 1063
    f.write_text('{"transmission": 0.5')                       # not JSON
    assert simsls.read_stamp(m.frame_image(2))[2] is False
    write_beam(f, 0.5, True)
    assert simsls.read_stamp(m.frame_image(3)) == (0.5, True, True, SEED)
    for bad in ('{"transmission": -1, "open": true}', '{"transmission": "nan", "open": true}',
                '{"transmission": 0.1, "open": 1}', '{"open": true}', '[]'):
        f.write_text(bad)
        assert simsls.read_stamp(m.frame_image(4)) == (0.5, True, True, SEED), bad
    assert m.beam.errors == 6


def test_one_frame_per_trigger_follows_the_beam(sim, tmp_path):
    """Through the module's own data path: each trigger's frame is made with FILE's state then."""
    f = tmp_path / 'beam.json'
    write_beam(f, 0.443303, True)
    sim.module.beam, sim.module.model = simsls.BeamFile(str(f)), simsls.BeamModel(sim.module.base)
    sim.module.counts['beam_changes'] = 0
    p = sim.port
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 128 << 10)
    rx.bind(('127.0.0.1', 0))
    rx.settimeout(5)
    sim.module.rcvbuf = rx.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
    configure(p, rx.getsockname()[1])
    ok(p, 107, 'Q', (1,))
    ok(p, 19)
    trig = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for frame, (t, is_open) in ((1, (0.443303, True)), (2, (0.443303, False))):
        write_beam(f, t, is_open)
        trig.sendto(b'TRIG', ('127.0.0.1', p))
        packets = {}
        while len(packets) < 128:
            d = rx.recv(9000)
            h = simsls.HEADER.unpack(d[:48])
            assert h[0] == frame
            packets[h[2]] = d[48:]
        img = np.frombuffer(b''.join(packets[k] for k in range(128)), np.uint16)
        assert np.array_equal(img, stated_model(SEED, frame, t, is_open))
    ok(p + 1, 20)
    rx.close()
    trig.close()
