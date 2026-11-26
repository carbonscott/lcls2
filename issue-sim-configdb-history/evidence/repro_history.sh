#!/bin/bash
# repro_history.sh MODE OUTDIR : reproduce sim-configdb-history on a compute node, inside a private network namespace.
#   MODE asis  : psdaq from the lcls2 sim-main checkout, unchanged
#   MODE fixed : the same, with get_history giving cdict a deep copy of the stored config
# Starts psdaq.sim.configdb_server --seed-gui (fakecam_2 has an enum, user.mode), then runs repro_client.py against it.
# Writes OUTDIR/repro-MODE.log (client) and OUTDIR/server-MODE.log (server), each with a provenance header.
# Run from the login node:  bash repro_history.sh asis $PWD/evidence
set -u
MODE=$1; OUT=$2; mkdir -p "$OUT"
H=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-issues/agents/h1
SRC=$H/lcls2-sim
JOB=47203681
if [ "${INSIDE:-}" != 1 ]; then
  exec srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=2 --mem=4G \
    unshare -rn env INSIDE=1 bash "$0" "$@"
fi
# ---- inside the namespace, on the compute node ----
ip link set lo up
W=$H/configdb-history/work-$MODE; rm -rf "$W"; mkdir -p "$W"
SHA=$(git -C $SRC rev-parse HEAD)
PKG=$SRC/psdaq
if [ "$MODE" = fixed ]; then
  mkdir -p $W/src && cp -r $SRC/psdaq/psdaq $W/src/psdaq && PKG=$W/src
  sed -i 's/cl = cdict(self._find_config(r, entry\[.configs.\]\[0\]))/cl = cdict(copy.deepcopy(self._find_config(r, entry["configs"][0])))/' \
    $PKG/psdaq/sim/configdb_server.py
fi
export PATH=/sdf/group/lcls/ds/ana/sw/conda2/inst/envs/daq_20250402_r9/bin:$PATH   # the DAQ's conda env
export PYTHONPATH=$PKG
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
hdr() {
  echo "# host: $(hostname)"; echo "# date: $(date -u +%FT%TZ)"
  echo "# commit: lcls2 $SHA (carbonscott/lcls2 sim-main)${1:+ $1}"
  echo "# cmd: repro_history.sh $MODE $OUT ($2)"
  echo "# netns: private (unshare -rn), interfaces up: $(ip -o link show up | awk -F': ' '{print $2}' | tr '\n' ' ')"
}
PATCHNOTE=""; [ "$MODE" = fixed ] && PATCHNOTE="+ local fix: get_history passes copy.deepcopy(stored config) to cdict"
{ hdr "$PATCHNOTE" "server: python -m psdaq.sim.configdb_server --store $W/store.json --port 0 --seed-gui"
  echo; } > $OUT/server-$MODE.log
python -u -m psdaq.sim.configdb_server --store $W/store.json --port 0 --url-file $W/url --seed-gui \
  >> $OUT/server-$MODE.log 2>&1 &
SP=$!
for i in $(seq 1 60); do grep -q 'configdb_server: ready' $OUT/server-$MODE.log && break; sleep 0.5; done
{ hdr "$PATCHNOTE" "client: python repro_client.py $(cat $W/url) $W/store.json"
  echo "# python: $(command -v python)"
  [ "$MODE" = fixed ] && { echo "# the local fix, diff against sim-main:"; diff -u $SRC/psdaq/psdaq/sim/configdb_server.py $PKG/psdaq/sim/configdb_server.py | sed 's/^/#   /'; }
  echo
  python -u $H/configdb-history/repro_client.py "$(cat $W/url)" $W/store.json 2>&1
  echo "client exit: $?"; } > $OUT/repro-$MODE.log
kill $SP; wait $SP 2>/dev/null
echo "server stopped" >> $OUT/server-$MODE.log
tail -3 $OUT/repro-$MODE.log
