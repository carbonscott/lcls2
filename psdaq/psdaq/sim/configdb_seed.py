"""
Seed a campaign-local config DB (psdaq.sim.configdb_server) with what a
hardware-free DAQ needs to Configure:

  <inst>/<alias>/<trigger>_0   detType 'teb': the trigger body control.py
                               fetches at Configure (control.py
                               condition_configure).  Same values as the
                               body control.py dummies up in --sim mode;
                               persistValue must be 0xdeadbeef, the value
                               libtmoTeb writes for an event to be recorded.
  <inst>/<alias>/<det>         detType 'fakecam': the simulated detector; or, with
                               --det-type <type>, that type's own default config
                               (psdaq.configdb.<type>_config_store, or with --det-yaml
                               a firmware YAML through yaml_config_store_example, as a
                               production config is made), for drp -D <type> -d sim://.

It writes through psdaq.configdb.configdb, the same HTTP client the DAQ
uses, and is idempotent: a device whose stored config already matches is
left alone.

Usage:
    python -m psdaq.sim.configdb_seed --url http://127.0.0.1:<port>/ws/
"""

import argparse
import importlib
import json
import sys

from psdaq.configdb.configdb import configdb
from psdaq.configdb.typed_json import cdict


def trigger_cdict(name, segm=0, script='tebMonRouter.py'):
    top = cdict()
    top.setAlg('tebConfig', [0, 1, 0])
    top.set('help:RO', '-- user --\nSeeded by psdaq.sim.configdb_seed', 'CHARSTR')
    top.set('soname', 'libtmoTeb.so', 'CHARSTR')
    top.set('pythonScript', script, 'CHARSTR')
    top.set('buildAll', 1, 'UINT32')
    top.set('buildDets', 'timing,bld,epics', 'CHARSTR')
    top.set('prescale', 1, 'UINT32')                # obsolete, still read
    top.set('persistValue', 0xdeadbeef, 'UINT32')   # record condition
    top.set('monitorValue', 0x12345678, 'UINT32')   # monitor condition
    for rog in range(8):
        top.set(f'rogRsrvdBuf[{rog}]', 0, 'UINT32')
    top.setInfo('teb', name, segm, 'sim-teb', 'Seeded by psdaq.sim.configdb_seed')
    return top


def fakecam_cdict(name, segm=0, sim_seed=0x1234, sim_length=1024):
    top = cdict()
    top.setAlg('fakecam', [0, 0, 1])
    top.set('help:RO', '-- user --\nsim_seed : value mixed into the simulated payload'
                       '\n-- expert --\nsim_length   : payload words per event', 'CHARSTR')
    top.set('user.sim_seed', sim_seed, 'UINT32')
    top.set('expert.sim_length', sim_length, 'UINT32')
    top.setInfo('fakecam', name, segm, 'sim-fakecam', 'Seeded by psdaq.sim.configdb_seed')
    return top


class _StoreCapture(object):
    """Stands in for the psdaq.configdb.configdb module while a type's
    <type>_config_store.write_to_daq_config_db builds its config: its configdb
    contacts nothing and keeps the config the store would write."""
    top = None

    class configdb(object):
        def __init__(self, *args, **kwargs):
            pass

        def add_alias(self, *args, **kwargs):
            pass

        def add_device_config(self, *args, **kwargs):
            pass

        def modify_device(self, alias, top, *args, **kwargs):
            _StoreCapture.top = top


def _store_cdict(mod, det_type, name, segm):
    """The config a store without <type>_cdict() writes, from its own write_to_daq_config_db
    run against _StoreCapture (its URL is never used)."""
    real = mod.cdb
    mod.cdb = _StoreCapture
    _StoreCapture.top = None
    try:
        mod.write_to_daq_config_db(argparse.Namespace(
            inst='tst', alias='BEAM', name=name, segm=segm, id='sim-%s' % det_type, yaml=None,
            prod=False, user='sim', password='sim'))
    finally:
        mod.cdb = real
    if _StoreCapture.top is None:
        raise RuntimeError('%s_config_store wrote no config' % det_type)
    return _StoreCapture.top


def type_cdict(det_type, name, segm=0, yaml=None):
    """The type's own config: <type>_config_store.<type>_cdict(), the config its
    write_to_daq_config_db writes (when it has no <type>_cdict), or with a rogue YAML file
    yaml_config_store_example.<type>_cdict(yaml)."""
    # The type's config module sets up sys.path for its firmware packages (psdaq.utils.enable_*)
    importlib.import_module('psdaq.configdb.%s_config' % det_type)
    if yaml:
        import pyrogue
        mod = importlib.import_module('psdaq.configdb.yaml_config_store_example')
        top = getattr(mod, '%s_cdict' % det_type)(pyrogue.yamlToData(fName=yaml))
    else:
        mod = importlib.import_module('psdaq.configdb.%s_config_store' % det_type)
        if hasattr(mod, '%s_cdict' % det_type):
            top = getattr(mod, '%s_cdict' % det_type)()
        else:
            top = _store_cdict(mod, det_type, name, segm)
    top.setInfo(det_type, name, segm, 'sim-%s' % det_type, 'Seeded by psdaq.sim.configdb_seed')
    return top


def _store(db, alias, top):
    value = json.loads(json.dumps(top.typed_json()))    # as stored and served
    device = value['detName:RO']
    if device in db.get_devices(alias):
        if db.get_configuration(alias, device) == value:
            return db.get_key(alias), False
    db.add_device_config(value['detType:RO'])
    return db.modify_device(alias, value), True


def seed(url, inst='tst', alias='BEAM', root='configDB', trigger='tmoteb',
         det='fakecam', segm=0, sim_seed=0x1234, sim_length=1024, det_type='fakecam',
         det_yaml=None):
    """Create inst/alias and store the trigger and detector configs.

    Returns {device: (key, changed)}."""
    db = configdb(url, inst, create=True, root=root)
    db.add_alias(alias)
    top = (fakecam_cdict(det, segm, sim_seed, sim_length) if det_type == 'fakecam'
           else type_cdict(det_type, det, segm, det_yaml))
    return {
        trigger + '_0': _store(db, alias, trigger_cdict(trigger, 0)),
        '%s_%d' % (det, segm): _store(db, alias, top),
    }


def main():
    parser = argparse.ArgumentParser(description='Seed a local config DB stand-in')
    parser.add_argument('--url', required=True, help='e.g. http://127.0.0.1:<port>/ws/')
    parser.add_argument('--root', default='configDB')
    parser.add_argument('--inst', default='tst')
    parser.add_argument('--alias', default='BEAM')
    parser.add_argument('--trigger', default='tmoteb', help='control.py -t value')
    parser.add_argument('--det', default='fakecam', help='detector name (alias)')
    parser.add_argument('--segm', type=int, default=0)
    parser.add_argument('--sim-seed', type=lambda s: int(s, 0), default=0x1234)
    parser.add_argument('--sim-length', type=int, default=1024)
    parser.add_argument('--det-type', default='fakecam',
                        help='store this type\'s own default config instead of fakecam\'s')
    parser.add_argument('--det-yaml', default=None,
                        help='with --det-type: make it from this firmware YAML')
    args = parser.parse_args()
    if 'ws-auth' in args.url or 'ws-kerb' in args.url or not args.url.startswith('http://127.'):
        sys.exit('configdb_seed: refusing non-local URL %s' % args.url)
    result = seed(args.url, args.inst, args.alias, args.root, args.trigger, args.det,
                  args.segm, args.sim_seed, args.sim_length, args.det_type, args.det_yaml)
    for device, (key, changed) in result.items():
        print('%s/%s/%s key=%d %s' % (args.inst, args.alias, device, key,
                                      'written' if changed else 'unchanged'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
