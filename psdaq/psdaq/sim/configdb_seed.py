"""
Seed a campaign-local config DB (psdaq.sim.configdb_server) with what a
hardware-free DAQ needs to Configure:

  <inst>/<alias>/<trigger>_0   detType 'teb': the trigger body control.py
                               fetches at Configure (control.py
                               condition_configure).  Same values as the
                               body control.py dummies up in --sim mode;
                               persistValue must be 0xdeadbeef, the value
                               libtmoTeb writes for an event to be recorded.
  <inst>/<alias>/<det>         detType 'fakecam': the simulated detector.

It writes through psdaq.configdb.configdb, the same HTTP client the DAQ
uses, and is idempotent: a device whose stored config already matches is
left alone.

Usage:
    python -m psdaq.sim.configdb_seed --url http://127.0.0.1:<port>/ws/
"""

import argparse
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


def _store(db, alias, top):
    value = json.loads(json.dumps(top.typed_json()))    # as stored and served
    device = value['detName:RO']
    if device in db.get_devices(alias):
        if db.get_configuration(alias, device) == value:
            return db.get_key(alias), False
    db.add_device_config(value['detType:RO'])
    return db.modify_device(alias, value), True


def seed(url, inst='tst', alias='BEAM', root='configDB', trigger='tmoteb',
         det='fakecam', segm=0, sim_seed=0x1234, sim_length=1024):
    """Create inst/alias and store the trigger and detector configs.

    Returns {device: (key, changed)}."""
    db = configdb(url, inst, create=True, root=root)
    db.add_alias(alias)
    return {
        trigger + '_0': _store(db, alias, trigger_cdict(trigger, 0)),
        '%s_%d' % (det, segm): _store(db, alias, fakecam_cdict(det, segm, sim_seed,
                                                               sim_length)),
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
    args = parser.parse_args()
    if 'ws-auth' in args.url or 'ws-kerb' in args.url or not args.url.startswith('http://127.'):
        sys.exit('configdb_seed: refusing non-local URL %s' % args.url)
    result = seed(args.url, args.inst, args.alias, args.root, args.trigger, args.det,
                  args.segm, args.sim_seed, args.sim_length)
    for device, (key, changed) in result.items():
        print('%s/%s/%s key=%d %s' % (args.inst, args.alias, device, key,
                                      'written' if changed else 'unchanged'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
