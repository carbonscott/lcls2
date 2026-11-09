"""
Drive a BEB detector type's own config module (psdaq.configdb.<type>_config)
through the entry points the DRP (psdaq/drp/BEBDetector.cc) calls, in the
DRP's order, against a simulated device (psdaq.sim.rogue_dev):

  <type>_init(detName, device, laneMask, xpmpv, timebase, verbose)   DRP start
  <type>_connectionInfo(root, alloc_json)                            Connect
  <type>_config(root, connect_json, alias, detName, segment, group)   Configure
  <type>_scan_keys(update) / <type>_update(update)                   scan step
  <type>_enable(root) / <type>_disable(root)                         Enable/Disable
  <type>_unconfig(root)                                              Unconfigure

The config comes from a config DB stand-in (psdaq.sim.configdb_server,
started here on a free loopback port unless --configdb-url is given),
seeded with the type's own <type>_config_store default.

Usage:
    python -B -m psdaq.sim.rogue_drive --type epix100
    PSDAQ_SIM_ROGUE_FAULT='ePixBoard.ePix100aFPGA.EpixFpgaRegisters.DaqTriggerDelay' \\
        python -B -m psdaq.sim.rogue_drive --type epix100      # expect Configure to fail
Exit 0 when every step returned; 1 with the failing step and traceback otherwise.
"""

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback


def step(name):
    print('=== STEP %s' % name, flush=True)


def start_configdb(workdir):
    store = os.path.join(workdir, 'configdb.json')
    p = subprocess.Popen([sys.executable, '-B', '-m', 'psdaq.sim.configdb_server',
                          '--store', store, '--port', '0'],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    t0 = time.time()
    while time.time() - t0 < 30:
        line = p.stdout.readline()
        if line.startswith('CONFIGDB_URL='):
            return p, line.split('=', 1)[1].strip()
        if not line and p.poll() is not None:
            break
    p.kill()
    raise RuntimeError('configdb_server did not start')


def seed_type(url, inst, alias, det_type, detname, segm, yaml=None):
    """Store the type's own config (psdaq.sim.configdb_seed.type_cdict)."""
    from psdaq.configdb.configdb import configdb
    from psdaq.sim.configdb_seed import _store, type_cdict
    top = type_cdict(det_type, detname, segm, yaml)
    db = configdb(url, inst, create=True, root='configDB')
    db.add_alias(alias)
    return _store(db, alias, top)


def connect_json(url, inst, detname, segm, group):
    return json.dumps({'body': {
        'control': {'0': {'control_info': {'instrument': inst,
                                           'cfg_dbase': url.rstrip('/') + '/configDB'}}},
        'drp': {'1': {'proc_info': {'alias': '%s_%d' % (detname, segm)},
                      'det_info': {'readout': group},
                      'connect_info': {}}}}})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--type', default='epix100')
    ap.add_argument('--dev', default=None, help="default 'sim://<type>'")
    ap.add_argument('--detname', default=None, help='default <type>')
    ap.add_argument('--segm', type=int, default=0)
    ap.add_argument('--group', type=int, default=0, help='readout group')
    ap.add_argument('--timebase', default='186M')
    ap.add_argument('--inst', default='tst')
    ap.add_argument('--alias', default='BEAM')
    ap.add_argument('--configdb-url', default=None)
    ap.add_argument('--yaml', default=None, help='seed the config DB from this rogue YAML '
                    '(e.g. $SUBMODULEDIR/epix-100a-gen2/software/yml/ePix100a_asics_0123.yml)')
    ap.add_argument('--scan', default=None, help='JSON update for scan_keys/update, '
                    'e.g. \'{"user.start_ns": 90000}\'')
    ap.add_argument('--fault', default=None, help="'<register path>[=<value>]'")
    ap.add_argument('--log-writes', type=int, default=40, help='print this many writes')
    args = ap.parse_args(argv)

    t = args.type
    dev = args.dev or 'sim://%s' % t
    detname = args.detname or t
    work = tempfile.mkdtemp(prefix='rogue_drive-')
    srv = None
    current = 'install'
    cfg_writes = []
    try:
        current = 'configdb'
        step('configdb')
        if args.configdb_url:
            url = args.configdb_url
        else:
            srv, url = start_configdb(work)
        print('configdb:', url, '%s/%s/%s_%d (key, written):' % (args.inst, args.alias, detname,
              args.segm), seed_type(url, args.inst, args.alias, t, detname, args.segm, args.yaml),
              flush=True)

        current = 'install'
        step('install rogue_dev(%s)' % dev)
        from psdaq.sim import rogue_dev
        sim = rogue_dev.install(dev, det_type=t, fault=args.fault)
        print('seeds:', len(sim.seeds), 'fault:', sim.fault, flush=True)

        current = 'import'
        step('import psdaq.configdb.%s_config' % t)
        m = importlib.import_module('psdaq.configdb.%s_config' % t)
        f = lambda name: getattr(m, '%s_%s' % (t, name), None)

        current = '%s_init' % t
        step(current)
        root = f('init')(detname, dev, 1, None, args.timebase, 0)
        print('root keys:', sorted(root) if isinstance(root, dict) else type(root), flush=True)
        left = sim.pending()
        if left:
            raise rogue_dev.SimDeviceError('seed/fault paths never applied: %s' % left)
        print('seeds applied: %d' % len(sim.applied), flush=True)

        current = '%s_connectionInfo' % t
        step(current)
        info = f('connectionInfo')(root, json.dumps({'body': {}}))
        print('connectionInfo ->', info, ' paddr=0x%x' % info['paddr'], flush=True)

        current = '%s_config' % t
        step(current)
        n0 = len(sim.writes)
        cfg = f('config')(root, connect_json(url, args.inst, detname, args.segm, args.group),
                          args.alias, detname, args.segm, args.group)
        cfg = json.loads(cfg) if isinstance(cfg, str) else cfg
        cfg_writes = sim.writes[n0:]
        print('config -> detId:RO=%s, %d register writes during Configure' %
              (cfg.get('detId:RO') if isinstance(cfg, dict) else '?', len(cfg_writes)),
              flush=True)

        if args.scan and f('scan_keys'):
            current = '%s_scan_keys' % t
            step(current)
            print(f('scan_keys')(args.scan)[:300], flush=True)
            current = '%s_update' % t
            step(current)
            print(f('update')(args.scan)[:300], flush=True)

        for name in ('enable', 'disable', 'unconfig'):
            if f(name):
                current = '%s_%s' % (t, name)
                step(current)
                f(name)(root)

        print('=== REGISTER WRITES: %d in all; %d during Configure, first %d of them:' %
              (len(sim.writes), len(cfg_writes), args.log_writes))
        for w in cfg_writes[:args.log_writes]:
            print('  ', json.dumps(w))
        print('=== DONE: all entry points returned', flush=True)
        rc = 0
    except Exception:
        print('=== FAILED in %s' % current, flush=True)
        traceback.print_exc()
        rc = 1
    finally:
        if srv:
            srv.kill()
    sys.stdout.flush()
    os._exit(rc)      # rogue roots keep threads alive; do not wait on them


if __name__ == '__main__':
    main()
