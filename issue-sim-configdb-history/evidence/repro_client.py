"""repro_client.py URL : what a DAQ client sees from the configdb stand-in's get_history for a device with an enum.

Uses psdaq.configdb.configdb, the client the DRPs, handover checks and configdb_GUI use. Steps:
  1. get_configuration of fakecam_2 (seeded with enum modeEnum, user.mode = 1): is ':enum:' in its ':types:'?
  2. get_history of fakecam_2 for user.mode, twice
  3. get_configuration again: is ':enum:' still there?  Can a client still build a cdict from it?
  4. get_history of fakecam_0 (no enum) as the control
  5. one write (add_alias NOBEAM), then read the store file the server saved: is fakecam_2's ':enum:' still on disk?
"""
import json
import sys

import requests
from psdaq.configdb.configdb import configdb
from psdaq.configdb.typed_json import cdict
import psdaq.sim.configdb_server as srvmod

url = sys.argv[1]
store = sys.argv[2]
print("psdaq.sim.configdb_server from:", srvmod.__file__)
cdb = configdb(url, 'tst', create=False, root='configDB')


def enum_state(tag):
    cfg = cdb.get_configuration('BEAM', 'fakecam_2')
    enum = cfg.get(':types:', {}).get(':enum:')
    print("%s: get_configuration fakecam_2 -> ':enum:' in ':types:': %s" % (tag, json.dumps(enum)))
    try:
        c = cdict(cfg)
        print("%s: cdict(config) OK, user.mode = %s" % (tag, c.get('user.mode')))
    except Exception as e:
        print("%s: cdict(config) FAILS: %s: %s" % (tag, type(e).__name__, e))


def history(dev, key, n):
    raw = requests.get('%sconfigDB/get_history/tst/BEAM/%s/' % (url, dev), json=[key])
    body = raw.json()
    print("get_history #%d %s %s -> HTTP %d success=%s msg=%r value=%s"
          % (n, dev, key, raw.status_code, body.get('success'), body.get('msg'), json.dumps(body.get('value'))))
    return raw.status_code


print()
enum_state("step 1 (before any history call)")
print()
s1 = history('fakecam_2', 'user.mode', 1)
s2 = history('fakecam_2', 'user.mode', 2)
print()
enum_state("step 3 (after get_history)")
print()
s3 = history('fakecam_0', 'user.sim_seed', 3)
print()
cdb.add_alias('NOBEAM')
with open(store) as f:
    root = json.load(f)['roots']['configDB']
on_disk = [d['config'][':types:'].get(':enum:') for d in root['collections']['fakecam']
           if d['config'].get('detName:RO') == 'fakecam_2']
print("step 5: after one write (add_alias NOBEAM), fakecam_2 configs in %s: ':enum:' = %s"
      % (store.split('/')[-1], json.dumps(on_disk)))
print()
ok = s1 == 200 and s2 == 200
print("RESULT: get_history of an enum device %s (HTTP %d, %d); control fakecam_0 HTTP %d"
      % ("works" if ok else "FAILS", s1, s2, s3))
sys.exit(0 if ok else 1)
