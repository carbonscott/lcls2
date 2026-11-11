"""psdaq.sim.simhsdioc: the hsd PVs and IOC a sim:// hsd DRP configures through, and the hsd's
config DB default (configdb_seed, hsd_config_store run as a script against a capturing configdb).

The PVA server is isolated (127.0.0.1, its own ports), so the test meets no running DAQ.  The
client does what psdaq/configdb/hsd_config.py does with the PVs, in its order."""

import json
import subprocess
import sys
import time

import pytest

p4p = pytest.importorskip('p4p')
from p4p.client.thread import Context               # noqa: E402
from p4p.server import Server                         # noqa: E402

from psdaq.sim import simhsdioc                       # noqa: E402

A, B = 'T3:HSD:1_SIM:A', 'T3:HSD:1_SIM:B'


def num(v):
    """A scalar PV's value, whether the client unwrapped it (an int) or not (a Value)."""
    return int(v.value if hasattr(v, 'value') else v)


@pytest.fixture
def ioc():
    pytest.importorskip('psdaq.cas.hsdpvs')
    i = simhsdioc.SimHsdIoc([A, B], l0delay=81, linkid=0xfb001234)
    with Server(providers=[i.provider], isolate=True) as s:
        i.start()
        i.tick(1)
        ctxt = Context('pva', conf=s.conf(), useenv=False)
        yield i, ctxt
        ctxt.close()


def test_config_put_is_applied_as_hsd_config_waits_for(ioc):
    i, ctxt = ioc
    for p in (A, B):                                   # hsd_init -> hsd_unconfig: both disabled
        assert ctxt.get(p + ':CONFIG')['enable'] == 0
    ctxt.put(A + ':READY', 0, wait=True)               # apply_config
    assert num(ctxt.get(A + ':READY')) == 0
    v = ctxt.get(A + ':CONFIG')
    v['enable'], v['readoutGroup'] = 1, 3
    ctxt.put(A + ':CONFIG', v, wait=True)
    assert num(ctxt.get(A + ':READY')) == 1
    mon = ctxt.get(A + ':MONTIMING')
    assert (mon.group, mon.l0delay) == (3, 81)
    assert ctxt.get(A + ':MONRAWBUF').freesz > 0 and ctxt.get(A + ':MONFEXBUF').freesz > 0
    assert ctxt.get(B + ':MONTIMING').group == 0       # only the channel configured
    assert i.configs == 1


def test_connect_checks_pass(ioc):
    i, ctxt = ioc
    assert num(ctxt.get(A + ':PADDR_U')) == 0xff000000
    remote = ctxt.get(A + ':MONPGP').remlinkid
    assert [(x ^ (0xfb001234 | lane << 16)) & 0xffffffff for lane, x in enumerate(remote)] == [0] * 4
    raw = Context('pva', conf=ctxt.conf(), useenv=False, nt=False)
    age = time.time() - raw.get(A + ':FEXOOR').timeStamp.secondsPastEpoch
    raw.close()
    assert 0 <= age < 100                              # hsd_connect: 'hsdioc process may be dead'
    assert num(ctxt.get(A + ':KEEPROWS')) > 0 and num(ctxt.get(A + ':FWVERSION')) != 0


def test_card_link_id_is_hsd_connects():
    import socket
    ip = socket.gethostbyname(socket.gethostname()).split('.')
    assert simhsdioc.card_link_id() == 0xfb000000 | int(ip[2]) << 8 | int(ip[3])


CHECK = """
import json
import psdaq.configdb.configdb as cdb
def refuse(*args, **kwargs):
    raise AssertionError('the real configdb was contacted')
cdb.configdb = refuse
from psdaq.sim import configdb_seed
d = configdb_seed.type_cdict('hsd', 'hsd', 0).typed_json()
import sys
assert sys.modules['psdaq.configdb.configdb'] is cdb and cdb.configdb is refuse   # put back
print('JSON ' + json.dumps(d))
"""


def test_hsd_store_script_is_captured_and_nothing_is_contacted():
    import os
    if not os.environ.get('SUBMODULEDIR'):
        pytest.skip('needs $SUBMODULEDIR (the DAQ env)')
    r = subprocess.run([sys.executable, '-c', CHECK], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    d = json.loads([l for l in r.stdout.splitlines() if l.startswith('JSON ')][0][5:])
    assert d['detType:RO'] == 'hsd' and d['detName:RO'] == 'hsd_0'
    assert d['alg:RO']['version:RO'] == [3, 3, 0]      # hsd_config.configVersion
    assert d['user']['raw']['gate_ns'] == 200 and d['user']['fex']['prescale'] == 1
