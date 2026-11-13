#!/bin/bash
# preflight.sh -- fail-closed isolation check for the hardware-free DAQ.
# Run ON THE COMPUTE NODE, e.g.
#   srun --jobid=<job> --ntasks=1 --cpus-per-task=2 --mem=4G bash psdaq/psdaq/sim/preflight.sh
# Exit codes: 0 = isolated and local EPICS works
#             1 = something reached (or could reach) a facility service  -> STOP
#             2 = env not set up (sim_env.sh not sourced / DAQ env missing)
#             3 = isolation OK but the loopback positive control failed (local EPICS broken)
#             4 = a probe hung: killed by its outer timeout again after its one re-run, or once more after
#                 the 2 re-runs a preflight allows (flake register F11). Not a leak verdict, not an EPICS verdict.
# A probe killed by its outer timeout (rc 124, or 137 after the -k grace) is never read as a verdict, pass
# or fail: it prints 'HUNG: ...' and runs once more. Any other rc is read at the first attempt, as before.
# Worst case, every outer timeout and kill grace included: 148 s of probes + 4 s IOC start + the 2 re-runs
# (47 s + 22 s) + 2 s for a third hang = 223 s, under daq_sim up's 240 s.
# It never sends a packet to a facility host on purpose: the pswww probe goes
# through the env's dead proxy, and the no-proxy check is a local route lookup only.
SIMDIR=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
REPO=$(cd "$SIMDIR/../../.." && pwd)
if [[ -z "$CONDA_PREFIX" || "$ENV_TYPE" != daq ]]; then
  cd $REPO && source ./setup_env_daq.sh >/dev/null 2>&1 || { echo "PREFLIGHT: cannot source setup_env_daq.sh"; exit 2; }
fi
source $SIMDIR/sim_env.sh
[[ "$SIM_ENV_SOURCED" == 1 ]] || { echo "PREFLIGHT: sim_env.sh not sourced"; exit 2; }
leak=0; posfail=0; reruns=0; iocpid=
say() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*"; }
tmpd=$(mktemp -d /tmp/w3pf.XXXXXX)
# the end of every path out after the probes start: the loopback IOC (if up), our caRepeater, the temp dir
cleanup() {
  [[ -n $iocpid ]] && { kill $iocpid 2>/dev/null; wait $iocpid 2>/dev/null; iocpid=; }
  # libca auto-spawns caRepeater on EPICS_CA_REPEATER_PORT (15065); kill only the one on that port, owned by us
  # NB: with only -u, ss omits the Netid column, so match on the filter, not a column number
  rp=$(ss -Hulpn 'sport = :15065' 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u)
  for p in $rp; do [[ "$(stat -c %U /proc/$p 2>/dev/null)" == "$(id -un)" ]] && { echo "killing our caRepeater pid $p"; kill $p; }; done
  rm -rf $tmpd
}
# probe NAME SECS TAIL STDIN CMD ...: run CMD under its outer timeout (timeout -k 2 SECS) with STDIN ('-': this
# shell's) as its input, print the last TAIL lines of its output (0: all of it as it comes), set rc.  An rc
# other than 124/137 is returned at once for the caller to read.  A probe killed by the outer timeout is
# re-run once, at most 2 re-runs per preflight; a second hang, or a hang after those 2, ends the preflight
# with exit 4.
probe() {
  local name=$1 secs=$2 n=$3 in=$4 i=1; shift 4
  while :; do
    if [[ $n -gt 0 ]]; then
      if [[ $in == - ]]; then timeout -k 2 $secs "$@" 2>&1 | tail -$n | sed '$a\'; rc=${PIPESTATUS[0]}
      else timeout -k 2 $secs "$@" < "$in" 2>&1 | tail -$n | sed '$a\'; rc=${PIPESTATUS[0]}; fi
    else
      if [[ $in == - ]]; then timeout -k 2 $secs "$@"; rc=$?
      else timeout -k 2 $secs "$@" < "$in"; rc=$?; fi
    fi
    [[ $rc -ne 124 && $rc -ne 137 ]] && return 0
    say "HUNG: $name killed by its $secs s outer timeout (attempt $i)"
    if [[ $i -ge 2 || $reruns -ge 2 ]]; then
      say "=== summary: leak=$leak positive_control_fail=$posfail hung=$name rc=$rc"
      cleanup
      say "PREFLIGHT FAIL: probe hung (not a leak verdict, not an EPICS verdict)"; exit 4
    fi
    reruns=$((reruns + 1)); i=$((i + 1))
  done
}
say "=== preflight on $(hostname) ($(hostname -f 2>/dev/null)) job=${SLURM_JOB_ID:-none} step=${SLURM_STEP_ID:-none} user=$(id -un)"
say "=== OS: $(. /etc/os-release; echo $PRETTY_NAME)  kernel $(uname -r)"
say "=== device check: ls /dev/datadev* /dev/pcie_adc* /dev/tpr* 2>&1"
ls /dev/datadev* /dev/pcie_adc* /dev/tpr* 2>&1
say "=== isolation env"
env | grep -E '^(EPICS_|HTTPS?_PROXY|https?_proxy|ALL_PROXY|NO_PROXY|FI_PROVIDER)' | sort
printf 'CONFIGDB_AUTH is %s\n' "$( [[ -z "${CONFIGDB_AUTH}" ]] && echo 'set-but-EMPTY' || echo 'NON-EMPTY (BAD)')"
[[ -n "$CONFIGDB_AUTH" ]] && { say "LEAK-RISK: CONFIGDB_AUTH non-empty"; leak=1; }

say "=== 1. HTTPS to pswww through the env (must FAIL)"
probe curl 15 0 - curl -sS -m 10 -o /dev/null -w 'http_code=%{http_code}\n' https://pswww.slac.stanford.edu/ws/devconfigdb/ws/configDB/ 2>&1
say "curl rc=$rc (0 would mean pswww answered)"; [[ $rc -eq 0 ]] && { say "LEAK: curl reached pswww"; leak=1; }
# its own worst case: 2 URLs x (10 s connect + 10 s read) = 40 s, plus the import
cat > $tmpd/requests.py <<'PY'
import requests, sys
for url in ["https://pswww.slac.stanford.edu/ws/devconfigdb/ws/configDB/",
            "https://pswww.slac.stanford.edu/ws-auth/devlgbk/lgbk/ws/activeexperiment_for_instrument_station"]:
    try:
        r = requests.get(url, timeout=10); print("REACHED", url, r.status_code); sys.exit(1)
    except requests.exceptions.RequestException as e:
        print("blocked:", type(e).__name__, str(e)[:160])
sys.exit(0)
PY
probe python-requests 45 0 $tmpd/requests.py python -
say "python-requests rc=$rc (1 would mean pswww answered)"; [[ $rc -ne 0 ]] && { say "LEAK: requests reached pswww (or probe broke)"; leak=1; }
say "=== 1b. without the proxy env, would the node route to pswww? (local lookup only, no packet sent)"
ip=$(getent hosts pswww.slac.stanford.edu | awk '{print $1}' | head -1)
echo "pswww resolves to: ${ip:-<none>}"; [[ -n "$ip" ]] && ip route get "$ip" 2>&1 | head -1
echo "(a route here means the dead proxy env is the ONLY barrier for HTTP clients that honour it)"

say "=== 2. pvget (pvAccessCPP) of a production-looking PV (must time out)"
PV=DAQ:NEH:XPM:0:PART:5:Master
probe pvget 12 3 - pvget -w 5 $PV
say "pvget rc=$rc"; [[ $rc -eq 0 ]] && { say "LEAK: pvget got $PV"; leak=1; }
say "=== 2b. p4p (pvxs) client get, as control.py uses (must time out)"
probe p4p 20 0 - python $SIMDIR/preflight_p4p.py timeout "$PV"
say "p4p rc=$rc"; [[ $rc -ne 0 ]] && { say "LEAK: p4p got $PV (or probe broke)"; leak=1; }
say "=== 3. caget of a production-looking PV (must time out)"
CPV=DAQ:NEH:XPM:0:PART:5:L0Delay
probe caget 12 3 - caget -w 5 $CPV
say "caget rc=$rc"; [[ $rc -eq 0 ]] && { say "LEAK: caget got $CPV"; leak=1; }

say "=== 4. POSITIVE CONTROL: softIocPVA on loopback with the same env (must SUCCEED)"
cat > $tmpd/pf.db <<'DB'
record(ao, "SIMW3:PREFLIGHT:VAL") { field(VAL, "42.5") }
DB
( cd $tmpd && exec softIocPVA -S -d pf.db > $tmpd/ioc.log 2>&1 ) & iocpid=$!
sleep 4
# a hung probe here re-runs while the IOC is still up
probe 'local pvget' 12 2 - pvget -w 5 SIMW3:PREFLIGHT:VAL; prc=$rc
probe 'local caget' 12 2 - caget -w 5 SIMW3:PREFLIGHT:VAL; crc=$rc
probe 'local p4p' 20 0 - python $SIMDIR/preflight_p4p.py get SIMW3:PREFLIGHT:VAL; xrc=$rc
say "local pvget rc=$prc caget rc=$crc p4p rc=$xrc"
echo "listening sockets of the IOC (pid $iocpid):"; ss -tulpn 2>/dev/null | grep -E "pid=$iocpid[,)]" | awk '{print $1, $5}' | sort -u
cleanup
[[ $prc -ne 0 || $crc -ne 0 || $xrc -ne 0 ]] && posfail=1

say "=== summary: leak=$leak positive_control_fail=$posfail"
if [[ $leak -ne 0 ]]; then say "PREFLIGHT FAIL: facility service reachable"; exit 1; fi
if [[ $posfail -ne 0 ]]; then say "PREFLIGHT FAIL: loopback EPICS positive control failed"; exit 3; fi
say "PREFLIGHT PASS"; exit 0
