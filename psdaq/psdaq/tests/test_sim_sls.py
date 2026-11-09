"""Tests for psdaq.sim.simsls, the stand-in for a Jungfrau module's slsDetector servers.

A small client here speaks the slsDetectorPackage 9.0.0 protocol as sls::Detector does (one call
per TCP connection: <int32 fnum><args>, reply <int32 ret>[1000-byte message on FAIL]<retval>);
with the env's own client tools (sls_detector_put/get) on PATH, one test also drives simsls
through them.  Every socket is on 127.0.0.1."""

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


def test_one_frame_per_trigger(sim):
    p = sim.port
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
    if rx.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) < 2 * 128 * 8240:
        rx.close()          # the sender thread shares this process's GIL: a frame must fit
        pytest.skip('UDP receive buffer below 2 MiB (net.core.rmem_max): a frame would overflow it')
    rx.bind(('127.0.0.1', 0))
    rx.settimeout(5)
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
            assert len(d) == 48 + 8192
            h = simsls.HEADER.unpack(d[:48])
            assert h[0] == frame and h[5] == 0x2a0 and h[11] == simsls.JUNGFRAU
            packets[h[2]] = d[48:]
        img = np.frombuffer(b''.join(packets[k] for k in range(128)), np.uint16)
        assert np.array_equal(img, pattern.pattern(SEED, frame, idx, 16).astype(np.uint16))
    ok(p + 1, 20)                                              # F_STOP_ACQUISITION
    assert ok(p + 1, 21, fmt_ret='i') == simsls.IDLE
    assert ok(p, 108, fmt_ret='Q') == 3                        # F_GET_NEXT_FRAME_NUMBER
    rx.close()
    trig.close()


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
