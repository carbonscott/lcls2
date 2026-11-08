"""Config DB stand-in for the config editor tests, and the DAQ-side helpers they run.

Imported by the tests (browser venv, no psdaq imports at module level) and run as a script with
the DAQ env's python (WEBGUI_PYTHON) for the parts that need psdaq:

    python configeditor_harness.py seed --url http://127.0.0.1:<port>/ws/
        psdaq.sim.configdb_seed (tst/BEAM/tmoteb_0 and fakecam_0, sim_seed 0x1234) plus
        tst/NOBEAM (no devices), tst/BEAM/treetest_0 (enum, lists, list of dicts, UINT64, :RO)
        and det/BEAM/fakecam_sn1_0 (the serial-number DB entry of fakecam_0)
    python configeditor_harness.py readback --url ... [--inst tst --alias BEAM --det fakecam --segm 0]
        prints, as JSON, user.sim_seed as the two config readers the DAQ uses at Configure see it:
        control.py's get_config_with_params (control.py:2299-2300) and the DRP's
        get_config_json(connect_json, alias, detName, segment) (drp/XpmDetector.cc:104-110)
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
SERNO = 'fakecam_sn1_0'


# ---------------- test side (browser venv) ----------------

def _harness():
    sys.path.insert(0, str(HERE))
    import webgui_harness
    return webgui_harness


class ConfigDbProc:
    """python -m psdaq.sim.configdb_server on 127.0.0.1 with a JSON store file."""

    def __init__(self, store):
        self.store = str(store)
        self.url = None

    def start(self, timeout=60):
        h = _harness()
        d = tempfile.mkdtemp(prefix='cfgdb-')
        url_file = os.path.join(d, 'url')
        self.log = os.path.join(d, 'configdb.log')
        self.p = subprocess.Popen([h.SERVER_PYTHON, '-m', 'psdaq.sim.configdb_server', '--store', self.store,
                                   '--url-file', url_file, '--access-log', os.path.join(d, 'access.jsonl')],
                                  env=h.server_env(), stdout=open(self.log, 'w'), stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < timeout:
            if os.path.exists(url_file) and open(url_file).read().strip():
                self.url = open(url_file).read().strip()
                self.access = os.path.join(d, 'access.jsonl')
                return self
            if self.p.poll() is not None:
                break
            time.sleep(0.1)
        self.stop()
        raise RuntimeError('config DB stand-in did not start:\n' + open(self.log).read())

    def stop(self):
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                self.p.kill()
        return self.p.returncode

    @property
    def cfg_dbase(self):          # what control.py -d and the DRP's connect info carry
        return self.url.rstrip('/') + '/configDB'


def daq_script(*args, timeout=60):
    """Run this file as a script with the DAQ env's python; return the parsed JSON on stdout."""
    h = _harness()
    r = subprocess.run([h.SERVER_PYTHON, str(pathlib.Path(__file__).resolve())] + [str(a) for a in args],
                       env=h.server_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError('%s failed (%d):\n%s\n%s' % (args, r.returncode, r.stdout, r.stderr))
    return json.loads(r.stdout.strip().splitlines()[-1])


_TEMPLATE = {}


def seeded_store(tmpdir):
    """A copy of a store seeded once per test session (the seed takes ~1 s of DAQ python)."""
    if 'path' not in _TEMPLATE:
        d = pathlib.Path(tempfile.mkdtemp(prefix='cfgdb-template-'))
        db = ConfigDbProc(d / 'store.json').start()
        try:
            _TEMPLATE['seed'] = daq_script('seed', '--url', db.url)
        finally:
            db.stop()
        _TEMPLATE['path'] = d / 'store.json'
    dst = pathlib.Path(tmpdir) / 'store.json'
    shutil.copy(_TEMPLATE['path'], dst)
    return dst


# ---------------- DAQ side (DAQ env python) ----------------

def treetest_cdict():
    from psdaq.configdb.typed_json import cdict
    top = cdict()
    top.setAlg('treetest', [0, 0, 1])
    top.set('help:RO', 'tree editor test device', 'CHARSTR')
    top.define_enum('boolEnum', {'False': 0, 'True': 1})
    top.define_enum('modeEnum', {'Fast': 0, 'Slow': 1, 'Off': 2})
    top.set('user.enable', 1, 'boolEnum')
    top.set('user.mode', 2, 'modeEnum')
    top.set('user.gain', 7, 'UINT8')
    top.set('user.offset', -5, 'INT32')
    top.set('user.ratio', 0.25, 'DOUBLE')
    top.set('user.label', 'cam A', 'CHARSTR')
    top.set('user.short', [1, 2, 3], 'UINT32')                 # data list, edited in line
    top.set('user.long', list(range(10, 22)), 'UINT16')        # >= 5 values: trimmed, popup editor
    top.set('expert.big', 2 ** 63 + 5, 'UINT64')               # beyond 2**53
    top.set('expert.secret:RO', 99, 'UINT32')                  # hidden
    top.set('expert.chan.0.gain', 1, 'UINT8')                  # list of dicts
    top.set('expert.chan.1.gain', 2, 'UINT8')
    top.setInfo('treetest', 'treetest', 0, 'sim-treetest', 'tree editor test device')
    return top


def seed_all(url):
    from psdaq.configdb.configdb import configdb
    from psdaq.sim.configdb_seed import seed, _store, fakecam_cdict
    if not url.startswith('http://127.'):
        raise SystemExit('refusing non-local URL %s' % url)
    out = {k: list(v) for k, v in seed(url, inst='tst', alias='BEAM').items()}
    db = configdb(url, 'tst', create=False, root='configDB')
    db.add_alias('NOBEAM')
    out['treetest_0'] = list(_store(db, 'BEAM', treetest_cdict()))
    det = configdb(url, 'det', create=True, root='configDB')
    det.add_alias('BEAM')
    out['det/' + SERNO] = list(_store(det, 'BEAM', fakecam_cdict(SERNO[:-2], 0, sim_seed=0x5555,
                                                                 sim_length=2048)))
    return out


def readback(url, inst, alias, det, segm):
    from psdaq.configdb.get_config import get_config_with_params, get_config_json
    cfg_dbase = url.rstrip('/') + '/configDB'              # control -d <url>configDB
    db_url, db_name = cfg_dbase.rsplit('/', 1)             # control.py:2299
    device = '%s_%d' % (det, segm)
    ctl = get_config_with_params(db_url, inst, db_name, alias, device)   # control.py:2300's call
    connect = {'body': {'control': {'0': {'control_info': {'instrument': inst, 'cfg_dbase': cfg_dbase}}}}}
    drp = json.loads(get_config_json(json.dumps(connect), alias, det, segm))   # XpmDetector.cc:104-110
    return {
        'cfg_dbase': cfg_dbase,
        'control_py': {'call': 'get_config_with_params(%r, %r, %r, %r, %r)' % (db_url, inst, db_name, alias, device),
                       'user.sim_seed': ctl['user']['sim_seed']},
        'drp': {'call': 'get_config_json(<connect_json cfg_dbase=%s instrument=%s>, %r, %r, %d)'
                        % (cfg_dbase, inst, alias, det, segm),
                'user.sim_seed': drp['user']['sim_seed']},
    }


def main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=('seed', 'readback'))
    ap.add_argument('--url', required=True)
    ap.add_argument('--inst', default='tst')
    ap.add_argument('--alias', default='BEAM')
    ap.add_argument('--det', default='fakecam')
    ap.add_argument('--segm', type=int, default=0)
    a = ap.parse_args(argv)
    if a.cmd == 'seed':
        print(json.dumps(seed_all(a.url)))
    else:
        print(json.dumps(readback(a.url, a.inst, a.alias, a.det, a.segm)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
