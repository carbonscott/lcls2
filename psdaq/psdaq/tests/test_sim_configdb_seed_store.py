"""configdb_seed's config for a type whose store has no <type>_cdict(): the store's own
write_to_daq_config_db, run against a capturing configdb that contacts nothing.

In a subprocess: wave8_config imports pyrogue.pydm (through psdaq.cas.pgpmonitor), which cannot
use the Qt binding pytest-qt loads."""

import json
import subprocess
import sys

import pytest

CHECK = """
import json
import psdaq.configdb.configdb as cdb
def refuse(*args, **kwargs):
    raise AssertionError('the real configdb was contacted')
cdb.configdb = refuse
from psdaq.sim import configdb_seed
d = configdb_seed.type_cdict('wave8', 'wave8', 0).typed_json()
import psdaq.configdb.wave8_config_store as store
assert store.cdb is cdb                                         # put back
print('JSON ' + json.dumps(d))
"""


def test_store_config_is_captured_and_nothing_is_contacted():
    pytest.importorskip('pyrogue')
    r = subprocess.run([sys.executable, '-c', CHECK], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    d = json.loads([l for l in r.stdout.splitlines() if l.startswith('JSON ')][0][5:])
    assert d['detType:RO'] == 'wave8' and d['detName:RO'] == 'wave8_0'
    assert d['expert']['TriggerEventManager']['TriggerEventBuffer']['TriggerDelay'] == 0
    assert d['user']['delta_ns'] == -807692
