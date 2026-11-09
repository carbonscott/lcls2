"""
Seed a campaign-local config DB (psdaq.sim.configdb_server) with what a
hardware-free DAQ needs to Configure:

  <inst>/<alias>/<trigger>_0   detType 'teb': the trigger body control.py
                               fetches at Configure (control.py
                               condition_configure).  Same values as the
                               body control.py dummies up in --sim mode;
                               persistValue must be 0xdeadbeef, the value
                               libtmoTeb writes for an event to be recorded.
  <inst>/<alias>/<det>         detType 'fakecam': the simulated detector (also for
                               --det-type cspad, epixhremu, jungfrauemu, epixuhremu, which
                               have no config script of their own); or, with --det-type <type>,
                               that type's own default config
                               (psdaq.configdb.<type>_config_store, or with --det-yaml
                               a firmware YAML through yaml_config_store_example, as a
                               production config is made; hsd_config_store is a script,
                               run as its command line would), for drp -D <type> -d sim://.
                               --set KEY=VALUE changes a key of it, keeping its type
                               (daq_sim points jungfrau's module data at loopback so).

It writes through psdaq.configdb.configdb, the same HTTP client the DAQ
uses, and is idempotent: a device whose stored config already matches is
left alone.

Usage:
    python -m psdaq.sim.configdb_seed --url http://127.0.0.1:<port>/ws/
"""

import argparse
import importlib
import json
import os
import runpy
import sys
import types

from psdaq.sim import sim_path

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


def fakecam_cdict(name, segm=0, sim_seed=0x1234, sim_length=1024, det_type='fakecam'):
    """The config of an XpmDetector type with no config script of its own (fakecam, and with
    det_type cspad, epixhremu, jungfrauemu or epixuhremu): only XpmDetector's sim_seed reads it."""
    top = cdict()
    top.setAlg(det_type, [0, 0, 1])
    top.set('help:RO', '-- user --\nsim_seed : value mixed into the simulated payload'
                       '\n-- expert --\nsim_length   : payload words per event', 'CHARSTR')
    top.set('user.sim_seed', sim_seed, 'UINT32')
    top.set('expert.sim_length', sim_length, 'UINT32')
    top.setInfo(det_type, name, segm, 'sim-%s' % det_type, 'Seeded by psdaq.sim.configdb_seed')
    return top


# XpmDetector types with no <type>_config.py: their DRP configures through xpmdet_config only,
# and their config DB entry holds what fakecam's does
XPMDET_TYPES = ('fakecam', 'cspad', 'epixhremu', 'jungfrauemu', 'epixuhremu', 'epixuhrsim')
# Stores whose default config is a function other than <type>_cdict(): ts_config_store's
# __main__ writes beam_cdict() for the BEAM alias (after tsdef.set_instrument), and so does
# epixuhr3x2_config_store's
STORE_CDICT = {'ts': 'beam_cdict', 'epixuhr3x2': 'beam_cdict'}
# Stores whose <type>_cdict() takes the firmware project's config directory, as their __main__
# passes --dir + '/software/config'
STORE_DIR = {'epixm320': 'epix-hr-m-320k/software/config'}


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


# Stores that are scripts: their module code writes the config to the config DB its command line
# names (hsd_config_store), with no function to call.  Run as __main__ would, with that command
# line, against _StoreCapture.
SCRIPT_STORES = ('hsd',)


def _script_store_cdict(store, det_type, name, segm):
    """The config a script store writes, from its module code run against _StoreCapture."""
    import psdaq.configdb as package
    real = sys.modules['psdaq.configdb.configdb']
    fake = types.ModuleType(real.__name__)
    fake.createArgs = real.createArgs
    fake.configdb = _StoreCapture.configdb
    argv = sys.argv
    sys.argv = ['%s_config_store' % store, '--inst', 'tst', '--alias', 'BEAM', '--name', name,
                '--segm', str(segm), '--id', 'sim-%s' % det_type, '--user', 'sim',
                '--password', 'sim']
    sys.modules[real.__name__] = fake
    package.configdb = fake
    _StoreCapture.top = None
    try:
        runpy.run_module('psdaq.configdb.%s_config_store' % store, run_name='__sim_store__')
    finally:
        sys.modules[real.__name__] = real
        package.configdb = real
        sys.argv = argv
    if _StoreCapture.top is None:
        raise RuntimeError('%s_config_store wrote no config' % det_type)
    return _StoreCapture.top


# Types with no <type>_config_store in the tree: the store whose config they take, and the
# keys their config script reads that it lacks.  wave8he shares wave8_common with wave8;
# wave8he_config.user_to_expert derives the HLS counts and scales from these region bounds
# (the values wave8he_config records as its defaults).
BORROWED_STORES = {
    # tb (TimingBEB) records the timing system's message as ts does, and tb_config.apply_config
    # reads ts_config_store's BEAM config (user.LINAC, user.SC.group<N>, expert.group<N>)
    'tb': ('ts', []),
    # epixquad1kfps reads epixquad_config_store's config (user.pixel_map_raw)
    'epixquad1kfps': ('epixquad', []),
    'wave8he': ('wave8', [('expert.HlsProcessor.BaselineBeg', 20, 'UINT8'),
                          ('expert.HlsProcessor.BaselineEnd', 52, 'UINT8'),
                          ('expert.HlsProcessor.SignalBeg', 100, 'UINT8'),
                          ('expert.HlsProcessor.SignalEnd', 114, 'UINT8')]),
}


# Types whose own store lacks a key their config script reads: (key, value, type or None for an
# array).  epixquad_config reads user.pixel_map, the per-ASIC gain map (16 x 178 x 192), which
# epixquad_config_store no longer writes (it writes user.pixel_map_raw, the (4, 352, 384) raw
# view epixquad1kfps_config reads); with the store's map all zeros, both views are all zeros.
STORE_KEYS = {
    'epixquad': [('user.pixel_map', lambda: __import__('numpy').zeros((16, 178, 192), 'uint8'),
                  None)],
    # the simulated hsd sends its fex stream as well as the raw one (MemPoolSim.cc hsdMessage), so
    # its config enables it: hsd_config_store's default has user.fex.prescale 0 (raw only)
    'hsd': [('user.fex.prescale', 1, 'UINT32')],
    # the ePixUHR 3x2 panel has six ASICs, all of which the simulated one sends; the store's default
    # user.asic_enable is 0xf (its numAsics 4), whose disabled ASICs 4 and 5 make epixuhr3x2_config's
    # setup_bypasses_for_disabled_asics write 24 into EventSeqMux[1].Bypass, a 4-bit register in the
    # firmware tree here (EventFrameSequencerMux numberSlaves 4): 'Value range error' at Configure
    'epixuhr3x2': [('user.asic_enable', 0x3f, 'UINT32')],
}


# Types whose store's __main__ gives the config DB entry another detType than the DRP's -D: the
# entry is the whole device's configuration, which the config script records as a detector of
# its own (epixhr2x2_config: <name>hw, read by psana's epixhr2x2hw_config_2_0_0) beside the
# type's segment
STORE_DETTYPE = {'epixhr2x2': 'epixhr2x2hw'}


def type_cdict(det_type, name, segm=0, yaml=None):
    """The type's own config: <type>_config_store.<type>_cdict(), the config its
    write_to_daq_config_db writes (when it has no <type>_cdict), or with a rogue YAML file
    yaml_config_store_example.<type>_cdict(yaml)."""
    # The type's config module sets up sys.path for its firmware packages (psdaq.utils.enable_*);
    # $PSDAQ_SIM_PYTHONPATH (psdaq.sim.sim_path) goes first
    sim_path.pin()
    importlib.import_module('psdaq.configdb.%s_config' % det_type)
    if yaml:
        import pyrogue
        mod = importlib.import_module('psdaq.configdb.yaml_config_store_example')
        top = getattr(mod, '%s_cdict' % det_type)(pyrogue.yamlToData(fName=yaml))
    else:
        store, extra = BORROWED_STORES.get(det_type, (det_type, STORE_KEYS.get(det_type, [])))
        if store != det_type:
            importlib.import_module('psdaq.configdb.%s_config' % store)
        mod = (None if store in SCRIPT_STORES
               else importlib.import_module('psdaq.configdb.%s_config_store' % store))
        if store in STORE_CDICT:
            if hasattr(mod, 'tsdef'):
                mod.tsdef.set_instrument('tst')
            top = getattr(mod, STORE_CDICT[store])()
        elif store in STORE_DIR:
            top = getattr(mod, '%s_cdict' % store)(os.path.join(os.environ['SUBMODULEDIR'],
                                                                STORE_DIR[store]))
        elif store in SCRIPT_STORES:
            top = _script_store_cdict(store, det_type, name, segm)
        elif hasattr(mod, '%s_cdict' % store):
            top = getattr(mod, '%s_cdict' % store)()
        else:
            top = _store_cdict(mod, store, name, segm)
        for key, value, typ in extra:
            if typ is None:
                top.set(key, value())
            else:
                top.set(key, value, typ)
    top.setInfo(STORE_DETTYPE.get(det_type, det_type), name, segm, 'sim-%s' % det_type,
                'Seeded by psdaq.sim.configdb_seed')
    return top


def apply_sets(top, sets):
    """Set existing keys of a config from 'KEY=VALUE' strings, each keeping its type."""
    for item in sets or ():
        key, eq, text = item.partition('=')
        cur = top.get(key, True)
        if not eq or not isinstance(cur, tuple):
            raise ValueError('--set %r: not KEY=VALUE for a key of the config' % item)
        typ = cur[0]
        value = text if typ == 'CHARSTR' else float(text) if typ in ('DOUBLE', 'FLOAT') else int(text, 0)
        top.set(key, value, typ)
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
         det_yaml=None, sets=None):
    """Create inst/alias and store the trigger and detector configs.

    Returns {device: (key, changed)}."""
    db = configdb(url, inst, create=True, root=root)
    db.add_alias(alias)
    top = (fakecam_cdict(det, segm, sim_seed, sim_length, det_type) if det_type in XPMDET_TYPES
           else type_cdict(det_type, det, segm, det_yaml))
    apply_sets(top, sets)
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
    parser.add_argument('--allow-host', default=None, metavar='ADDR',
                        help='also accept a URL on this address (daq_sim up --hosts: the first host\'s own, '
                             'where the config DB stand-in listens for the other host\'s DRPs)')
    parser.add_argument('--set', action='append', metavar='KEY=VALUE', default=[],
                        help='change this key of the detector config (its type kept); repeatable')
    args = parser.parse_args()
    local = args.url.startswith('http://127.') or bool(args.allow_host) and args.url.startswith(
        'http://%s:' % args.allow_host)
    if 'ws-auth' in args.url or 'ws-kerb' in args.url or not local:
        sys.exit('configdb_seed: refusing non-local URL %s' % args.url)
    result = seed(args.url, args.inst, args.alias, args.root, args.trigger, args.det,
                  args.segm, args.sim_seed, args.sim_length, args.det_type, args.det_yaml,
                  args.set)
    for device, (key, changed) in result.items():
        print('%s/%s/%s key=%d %s' % (args.inst, args.alias, device, key,
                                      'written' if changed else 'unchanged'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
