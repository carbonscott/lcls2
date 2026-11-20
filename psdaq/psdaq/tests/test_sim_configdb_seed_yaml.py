"""configdb_seed's config for a type made from a firmware YAML (--det-yaml, epix100): the type's
config module imports its firmware package inside psdaq.utils.firmware_packages.isolated(), which
takes the package off sys.path again, and yaml_config_store_example imports the same package at
its top; type_cdict imports and runs that store inside the package's own block.

In subprocesses: the firmware packages' modules stay in sys.modules for the life of a process."""

import json
import os
import subprocess
import sys
import textwrap

import pytest

# The mechanism, with a stand-in firmware package and stand-in configdb modules: an
# epix100_config that imports its package as upstream's does, and a yaml_config_store_example
# that imports it at its top.
FAKE = """
import json, os, sys, types
tmp = sys.argv[1]
import psdaq.configdb
psdaq.configdb.__path__.insert(0, os.path.join(tmp, 'configdb'))
pyrogue = types.ModuleType('pyrogue')
pyrogue.yamlToData = lambda fName: {'ePixBoard': {'Gain': 7}}
sys.modules['pyrogue'] = pyrogue
from psdaq.sim import configdb_seed
top = configdb_seed.type_cdict('epix100', 'epix100', 0, yaml='any.yml')
print('JSON ' + json.dumps(top.typed_json()))
"""

FAKE_FILES = {
    'epix-100a-gen2/software/python/epix100a_gen2.py': 'GAIN_KEY = "user.gain"\n',
    'epix-100a-gen2/firmware/submodules/surf/python/surf.py': '',
    'configdb/epix100_config.py': textwrap.dedent("""\
        from psdaq.utils import firmware_packages
        with firmware_packages.isolated('epix-100a-gen2'):
            import epix100a_gen2
        """),
    'configdb/yaml_config_store_example.py': textwrap.dedent("""\
        from psdaq.configdb.typed_json import cdict
        import epix100a_gen2
        def epix100_cdict(data):
            top = cdict()
            top.set(epix100a_gen2.GAIN_KEY, data['ePixBoard']['Gain'], 'UINT32')
            return top
        """),
}


def _fake_tree(tmp_path):
    for rel, text in FAKE_FILES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def test_yaml_store_imports_inside_the_package_block(tmp_path):
    pytest.importorskip('psdaq.utils.firmware_packages')
    tmp = _fake_tree(tmp_path)
    env = dict(os.environ, SUBMODULEDIR=str(tmp))
    env.pop('PSDAQ_SIM_PYTHONPATH', None)
    r = subprocess.run([sys.executable, '-c', FAKE, str(tmp)], capture_output=True, text=True,
                       timeout=120, env=env)
    assert 'No module named' not in r.stderr, r.stderr[-2000:]
    assert r.returncode == 0, r.stderr[-2000:]
    d = json.loads([l for l in r.stdout.splitlines() if l.startswith('JSON ')][0][5:])
    assert d['detType:RO'] == 'epix100' and d['detName:RO'] == 'epix100_0'
    assert d['user']['gain'] == 7


# The real one: the YAML daq_sim up seeds epix100 from, through the real firmware packages
REAL = """
import json, sys
from psdaq.sim import configdb_seed
d = configdb_seed.type_cdict('epix100', 'epix100', 0, yaml=sys.argv[1]).typed_json()
print('JSON ' + json.dumps({'detType': d['detType:RO'], 'detName': d['detName:RO'],
                            'expert': sorted(d['expert'])}))
"""


def test_epix100_config_from_its_firmware_yaml():
    if not os.environ.get('SUBMODULEDIR'):
        pytest.skip('needs $SUBMODULEDIR (the DAQ env)')
    pytest.importorskip('pyrogue')
    from psdaq.sim import daq_sim
    yaml = daq_sim.SIM_TYPES['epix100']['det_yaml'].format(**os.environ)
    if not os.path.isfile(yaml):
        pytest.skip('no %s' % yaml)
    r = subprocess.run([sys.executable, '-c', REAL, yaml], capture_output=True, text=True,
                       timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    d = json.loads([l for l in r.stdout.splitlines() if l.startswith('JSON ')][0][5:])
    assert d['detType'] == 'epix100' and d['detName'] == 'epix100_0'
    assert d['expert'], d
