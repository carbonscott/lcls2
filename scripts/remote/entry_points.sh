#!/bin/bash
# The stand-ins from their entry points: config DB server + seed + configdb CLI + control.py's own
# fetch (get_config_with_params), the run DB stub; then the seed refusing a non-local URL.
T=$(mktemp -d)
python -m psdaq.sim.configdb_server --store $T/cdb.json --port 0 > $T/cdb.out 2>&1 & CPID=$!
python -m psdaq.sim.lgbk_server --state $T/lg.json --log $T/lg.jsonl --port 0 > $T/lg.out 2>&1 & LPID=$!
for i in $(seq 50); do grep -q CONFIGDB_URL $T/cdb.out && grep -q LGBK_URL $T/lg.out && break; sleep 0.2; done
cat $T/cdb.out $T/lg.out | grep -E 'URL='
CURL=$(grep -o 'http://127.0.0.1:[0-9]*/ws/' $T/cdb.out | head -1); LURL=$(grep -o 'http://127.0.0.1:[0-9]*/' $T/lg.out | head -1)
echo "+ configdb_seed --url $CURL"; python -m psdaq.sim.configdb_seed --url $CURL
echo "+ configdb ls tst/BEAM"; python -m psdaq.configdb.configdb --url ${CURL} ls tst/BEAM 2>&1 | tail -3
python - "$CURL" "$LURL" <<'PY'
import sys, requests
from psdaq.configdb.get_config import get_config_with_params
c, l = sys.argv[1], sys.argv[2]
db_url, db_name = (c + 'configDB').rsplit('/', 1)
cfg = get_config_with_params(db_url, 'tst', db_name, 'BEAM', 'tmoteb_0')
print('control.py fetch: tmoteb_0 persistValue', hex(cfg['persistValue']), 'soname', cfg['soname'])
cfg = get_config_with_params(db_url, 'tst', db_name, 'BEAM', 'fakecam_0')
print('control.py fetch: fakecam_0 user.sim_seed', hex(cfg['user']['sim_seed']))
r = requests.get(l + 'lgbk/ws/activeexperiment_for_instrument_station', params={'instrument_name': 'tst', 'station': 0}).json()
print('run DB stub: activeexperiment', r)
PY
echo "+ configdb_seed --url https://pswww.slac.stanford.edu/ws-auth/devconfigdb/ws/   (must refuse)"
python -m psdaq.sim.configdb_seed --url https://pswww.slac.stanford.edu/ws-auth/devconfigdb/ws/; echo SEED_NONLOCAL_EXIT=$?
kill $CPID $LPID; wait 2>/dev/null; rm -rf "${T:?}"
