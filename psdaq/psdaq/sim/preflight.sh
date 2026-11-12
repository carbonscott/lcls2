#!/bin/bash
# preflight.sh -- fail-closed isolation check for the hardware-free DAQ.
# Run ON THE COMPUTE NODE, e.g.
#   srun --jobid=<job> --ntasks=1 --cpus-per-task=2 --mem=4G bash psdaq/psdaq/sim/preflight.sh
# Exit codes: 0 = isolated and local EPICS works
#             1 = something reached (or could reach) a facility service  -> STOP
#             2 = env not set up (sim_env.sh not sourced / DAQ env missing)
#             3 = isolation OK but the loopback positive control failed (local EPICS broken)
# It never sends a packet to a facility host on purpose: the pswww probe goes
# through the env's dead proxy, and the no-proxy check is a local route lookup only.
#
# Time bounds. A probe's network part is bounded inside the client: pvget/caget -w 5, p4p get timeout=5.0
# (preflight_p4p.py). Starting a client is not part of that bound: the interpreter, its imports, the EPICS tools'
# shared libraries and the loopback IOC load from the DAQ's conda env, on a shared filesystem whose metadata
# latency varies (on S3DF, weka /sdf/group: importing p4p is ~3,400 stat/open calls, 5-7 s on 2026-11-12, and
# more when the filesystem is slow). Start-up is bounded only by one budget for the whole preflight, PF_BUDGET
# seconds (default 200; daq_sim.py gives the preflight 240 s, so it always prints its own verdict). A client
# stopped by that budget (rc 124/137) proved nothing, and the log says it was stopped.
SIMDIR=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
REPO=$(cd "$SIMDIR/../../.." && pwd)
if [[ -z "$CONDA_PREFIX" || "$ENV_TYPE" != daq ]]; then
  cd $REPO && source ./setup_env_daq.sh >/dev/null 2>&1 || { echo "PREFLIGHT: cannot source setup_env_daq.sh"; exit 2; }
fi
source $SIMDIR/sim_env.sh
[[ "$SIM_ENV_SOURCED" == 1 ]] || { echo "PREFLIGHT: sim_env.sh not sourced"; exit 2; }
leak=0; posfail=0
say() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*"; }
PF_BUDGET=${PF_BUDGET:-200}
left() { local l=$(( PF_BUDGET - SECONDS )); (( l < 1 )) && l=1; echo $l; }   # what is left of the budget, s
stopped() { [[ $1 -eq 124 || $1 -eq 137 ]]; }                                  # rc of a client `timeout` stopped
say "=== preflight on $(hostname) ($(hostname -f 2>/dev/null)) job=${SLURM_JOB_ID:-none} step=${SLURM_STEP_ID:-none} user=$(id -un)"
say "=== OS: $(. /etc/os-release; echo $PRETTY_NAME)  kernel $(uname -r)"
say "=== device check: ls /dev/datadev* /dev/pcie_adc* /dev/tpr* 2>&1"
ls /dev/datadev* /dev/pcie_adc* /dev/tpr* 2>&1
say "=== isolation env"
env | grep -E '^(EPICS_|HTTPS?_PROXY|https?_proxy|ALL_PROXY|NO_PROXY|FI_PROVIDER)' | sort
printf 'CONFIGDB_AUTH is %s\n' "$( [[ -z "${CONFIGDB_AUTH}" ]] && echo 'set-but-EMPTY' || echo 'NON-EMPTY (BAD)')"
[[ -n "$CONFIGDB_AUTH" ]] && { say "LEAK-RISK: CONFIGDB_AUTH non-empty"; leak=1; }

say "=== 1. HTTPS to pswww through the env (must FAIL)"
timeout -k 2 20 curl -sS -m 10 -o /dev/null -w 'http_code=%{http_code}\n' https://pswww.slac.stanford.edu/ws/devconfigdb/ws/configDB/ 2>&1; rc=$?
say "curl rc=$rc (0 would mean pswww answered)"; [[ $rc -eq 0 ]] && { say "LEAK: curl reached pswww"; leak=1; }
timeout -k 2 25 python - <<'PY'; rc=$?
import requests, sys
for url in ["https://pswww.slac.stanford.edu/ws/devconfigdb/ws/configDB/",
            "https://pswww.slac.stanford.edu/ws-auth/devlgbk/lgbk/ws/activeexperiment_for_instrument_station"]:
    try:
        r = requests.get(url, timeout=10); print("REACHED", url, r.status_code); sys.exit(1)
    except requests.exceptions.RequestException as e:
        print("blocked:", type(e).__name__, str(e)[:160])
sys.exit(0)
PY
say "python-requests rc=$rc (1 would mean pswww answered)"; [[ $rc -ne 0 ]] && { say "LEAK: requests reached pswww (or probe broke)"; leak=1; }
say "=== 1b. without the proxy env, would the node route to pswww? (local lookup only, no packet sent)"
ip=$(getent hosts pswww.slac.stanford.edu | awk '{print $1}' | head -1)
echo "pswww resolves to: ${ip:-<none>}"; [[ -n "$ip" ]] && ip route get "$ip" 2>&1 | head -1
echo "(a route here means the dead proxy env is the ONLY barrier for HTTP clients that honour it)"

say "=== 2. pvget (pvAccessCPP) of a production-looking PV (must time out)"
PV=DAQ:NEH:XPM:0:PART:5:Master
timeout -k 2 20 pvget -w 5 $PV 2>&1 | tail -3; rc=${PIPESTATUS[0]}
say "pvget rc=$rc"; [[ $rc -eq 0 ]] && { say "LEAK: pvget got $PV"; leak=1; }
say "=== 2b. p4p (pvxs) client get, as control.py uses (must time out)"
timeout -k 2 25 python - "$PV" <<'PY'; rc=$?
import sys
from p4p.client.thread import Context, TimeoutError
c = Context('pva')
try:
    v = c.get(sys.argv[1], timeout=5.0); print("REACHED", sys.argv[1], v); sys.exit(1)
except TimeoutError as e:
    print("p4p timeout:", e); sys.exit(0)
finally:
    c.close()
PY
say "p4p rc=$rc"; [[ $rc -ne 0 ]] && { say "LEAK: p4p got $PV (or probe broke)"; leak=1; }
say "=== 3. caget of a production-looking PV (must time out)"
CPV=DAQ:NEH:XPM:0:PART:5:L0Delay
timeout -k 2 20 caget -w 5 $CPV 2>&1 | tail -3; rc=${PIPESTATUS[0]}
say "caget rc=$rc"; [[ $rc -eq 0 ]] && { say "LEAK: caget got $CPV"; leak=1; }

say "=== 4. POSITIVE CONTROL: softIocPVA on loopback with the same env (must SUCCEED)"
tmpd=$(mktemp -d /tmp/w3pf.XXXXXX)
cat > $tmpd/pf.db <<'DB'
record(ao, "SIMW3:PREFLIGHT:VAL") { field(VAL, "42.5") }
DB
( cd $tmpd && exec softIocPVA -S -d pf.db > $tmpd/ioc.log 2>&1 ) & iocpid=$!
# wait for the IOC's own start (it loads from the conda env too), not a fixed time: iocInit ends with this line
t=${EPOCHREALTIME/./}
until grep -q 'iocRun: All initialization complete' $tmpd/ioc.log 2>/dev/null; do
  kill -0 $iocpid 2>/dev/null && (( SECONDS < PF_BUDGET )) || break
  sleep 0.2
done
if grep -q 'iocRun: All initialization complete' $tmpd/ioc.log 2>/dev/null; then
  say "loopback IOC (pid $iocpid) started in $(( (${EPOCHREALTIME/./} - t) / 1000 )) ms"
else
  say "loopback IOC (pid $iocpid) did not finish starting ($( kill -0 $iocpid 2>/dev/null && echo "still starting when the budget ran out" || echo exited)):"
  tail -5 $tmpd/ioc.log
fi
timeout -k 2 $(left) pvget -w 5 SIMW3:PREFLIGHT:VAL 2>&1 | tail -2; prc=${PIPESTATUS[0]}
timeout -k 2 $(left) caget -w 5 SIMW3:PREFLIGHT:VAL 2>&1 | tail -2; crc=${PIPESTATUS[0]}
timeout -k 2 $(left) python $SIMDIR/preflight_p4p.py get SIMW3:PREFLIGHT:VAL 2>&1 | tail -3; xrc=${PIPESTATUS[0]}
say "local pvget rc=$prc caget rc=$crc p4p rc=$xrc"
for x in pvget:$prc caget:$crc p4p:$xrc; do
  stopped ${x#*:} && say "NOT-PROVEN: ${x%%:*} was stopped by the preflight budget (PF_BUDGET=$PF_BUDGET s) before it finished"
done
echo "listening sockets of the IOC (pid $iocpid):"; ss -tulpn 2>/dev/null | grep -E "pid=$iocpid[,)]" | awk '{print $1, $5}' | sort -u
kill $iocpid 2>/dev/null; wait $iocpid 2>/dev/null
# libca auto-spawns caRepeater on EPICS_CA_REPEATER_PORT (15065); kill only the one on that port, owned by us
# NB: with only -u, ss omits the Netid column, so match on the filter, not a column number
rp=$(ss -Hulpn 'sport = :15065' 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u)
for p in $rp; do [[ "$(stat -c %U /proc/$p 2>/dev/null)" == "$(id -un)" ]] && { echo "killing our caRepeater pid $p"; kill $p; }; done
rm -rf $tmpd
[[ $prc -ne 0 || $crc -ne 0 || $xrc -ne 0 ]] && posfail=1

say "=== summary: leak=$leak positive_control_fail=$posfail"
if [[ $leak -ne 0 ]]; then say "PREFLIGHT FAIL: facility service reachable"; exit 1; fi
if [[ $posfail -ne 0 ]]; then say "PREFLIGHT FAIL: loopback EPICS positive control failed"; exit 3; fi
say "PREFLIGHT PASS"; exit 0
