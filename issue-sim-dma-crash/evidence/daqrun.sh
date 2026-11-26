#!/bin/bash
# daqrun.sh <mode> <out dir> [lcls2 tree]
#   mode sigabrt: daq_sim up (fakecam, 1 DRP, 120 Hz), a passing `daq_sim cycle`, then before `daq_sim down`:
#                 the DRP's mapped libCom builds (/proc/<pid>/maps) and gdb attached to the DRP, which prints the
#                 backtrace when the DRP aborts during the shutdown that `down` starts.
#   mode dma:     daq_sim up with --length $LENGTH (payload words, default 16384 = 64 KiB), `daq_sim cycle --events 1200`,
#                 then the DRP's buffer sizes, MemPoolSim's clamp line, any XTC overflow and abort from its log,
#                 control's errors, and the cycle's counts.
#   mode deaddrp: daq_sim up, upstream `daqstate` takes the DAQ to running, the DRP is SIGKILLed, then control's state
#                 (daqstate) and procmgr's process status (daq_sim status) are read every 10 s for 60 s; then
#                 daqstate asks for configured (Disable) and the result is printed.
# Runs as one Slurm step on a compute node. Re-executes itself inside a private user+network+mount namespace
# (unshare -rnm, the node's address on lo, lo the only link up, a private tmpfs /tmp) and refuses to start a DAQ
# otherwise. The first lines of <out>/run.log are the provenance header, written here.
set -u
MODE=$1
OUT=$(readlink -f "$2")
L2=$(readlink -f "${3:-/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-issues/agents/h3/lcls2}")
A=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-issues/agents/h3
SELF=$(readlink -f "$0")
if [ -z "${H3_INSIDE:-}" ]; then
  mkdir -p "$OUT"
  {
    echo "# host: $(hostname)"
    echo "# date: $(date -u +%FT%TZ)"
    echo "# commit: lcls2 $(git -C "$L2" rev-parse HEAD) ($(git -C "$L2" log -1 --format=%s | cut -c1-70)) daqrun.sh $(sha1sum "$SELF" | cut -c1-12)"
    echo "# cmd: ${LENGTH:+LENGTH=$LENGTH }daqrun.sh $MODE $OUT $L2"
    echo "# slurm: job ${SLURM_JOB_ID:-none} step ${SLURM_STEP_ID:-none} cpus ${SLURM_CPUS_PER_TASK:-?}; user $(id -un)"
  } > "$OUT/run.log"
  ip=$(hostname -i | awk '{print $1}')
  IPB=$(command -v ip || echo /usr/sbin/ip)
  H3_INSIDE=1 exec unshare -rnm bash -c '
    mount -t tmpfs -o size=2g tmpfs /tmp || exit 9
    "$0" addr add "$1"/32 dev lo scope host && "$0" link set lo up || exit 9
    shift; exec "$@"' "$IPB" "$ip" bash "$SELF" "$MODE" "$OUT" "$L2" >> "$OUT/run.log" 2>&1
  echo "re-exec failed" >> "$OUT/run.log"; exit 2
fi
log() { echo "$(date -u +%FT%TZ) $*"; }
up=$(ip -o link show up | awk -F': ' '{print $2}' | tr '\n' ' ')
log "netns $(readlink /proc/self/ns/net); links up: $up; lo: $(ip -o -4 addr show dev lo | awk '{print $4}' | tr '\n' ' '); /tmp: $(findmnt -no FSTYPE /tmp)"
[ "$up" = "lo " ] || { log "REFUSING: lo is not the only link up"; exit 3; }
set +u
cd "$L2" && source ./setup_env_daq.sh > /dev/null 2>&1 || { log "FAIL env"; exit 2; }
export UV_CACHE_DIR=$A/cache/uv XDG_CACHE_HOME=$A/cache/xdg PYTHONDONTWRITEBYTECODE=1
log "conda env: $CONDA_DEFAULT_ENV; drp: $(command -v drp); daq_sim: $(command -v daq_sim)"
WD=$OUT/wd; rm -rf "$WD"; mkdir -p "$WD"

drp_pid() { daq_sim status -w "$WD" 2>/dev/null | awk '$1=="fakecam_0" && $2=="pid" {print $3; exit}'; }

LEN=64; [ "$MODE" = dma ] && LEN=${LENGTH:-16384}
log "\$ daq_sim up -w $WD -p 0 --rate 120 --segments 1 --length $LEN --detach"
daq_sim up -w "$WD" -p 0 --rate 120 --segments 1 --length $LEN --detach > "$WD/up.log" 2>&1
log "up exit $?; $(grep -m1 'UP. Endpoints' "$WD/up.log" | cut -c1-120)"
log "\$ daq_sim status"; daq_sim status -w "$WD" 2>&1 | cut -c1-160

if [ "$MODE" = sigabrt ]; then
  log "\$ daq_sim cycle -w $WD --events 1200"
  daq_sim cycle -w "$WD" --events 1200 > "$WD/cycle.log" 2>&1; crc=$?
  grep -E 'setState|equal|psana2 events|cycle (PASS|FAIL)' "$WD/cycle.log" | cut -c1-160
  log "cycle exit $crc"
  pid=$(drp_pid)
  log "DRP fakecam_0 pid $pid: $(tr '\0' ' ' < /proc/$pid/cmdline | cut -c1-200)"
  log "\$ grep libCom /proc/$pid/maps   (EPICS libCom builds mapped into the DRP)"
  grep libCom /proc/$pid/maps | awk '{print $1, $2, $5, $6}'
  log "the conda packages these files belong to:"
  for f in $(grep libCom /proc/$pid/maps | awk '{print $6}' | sort -u); do
    b=$(basename "$f"); pk=$(grep -l "$b" "$CONDA_PREFIX"/conda-meta/*.json 2>/dev/null | xargs -r -n1 basename | tr '\n' ' ')
    echo "  $f -> $pk"
  done
  log "\$ gdb -p $pid (batch: pass INT/TERM through, stop on SIGABRT, print the backtrace)"
  gdb -p "$pid" -batch -nx -ex 'set pagination off' -ex 'handle SIGINT nostop noprint pass' \
      -ex 'handle SIGTERM nostop noprint pass' -ex 'handle SIGPIPE nostop noprint pass' -ex 'continue' \
      -ex 'echo \n=== stopped: backtrace of the aborting thread ===\n' -ex 'bt' \
      -ex 'info sharedlibrary libCom' -ex 'detach' > "$OUT/gdb.txt" 2>&1 &
  gpid=$!
  sleep 8
  log "\$ daq_sim down"
  daq_sim down -w "$WD" > "$WD/down.log" 2>&1; log "down exit $?: $(tail -1 "$WD/down.log" | cut -c1-140)"
  wait $gpid; log "gdb exit $?"
  log "--- gdb output (signals, the abort, the backtrace):"
  grep -vE '^\[New LWP|^\[Thread debugging|^Using host libthread|^\[Inferior|^warning: (Could not|Unable)|^Reading symbols|^\(No debugging' "$OUT/gdb.txt" | grep -E -A40 'Program received|SIGABRT|=== stopped' | head -60 | cut -c1-220
elif [ "$MODE" = dma ]; then
  log "\$ daq_sim cycle -w $WD --events 1200"
  daq_sim cycle -w "$WD" --events 1200 > "$WD/cycle.log" 2>&1; crc=$?
  grep -E 'setState|NumL0|xtc2 file|psana2|equal|error|FAIL|PASS' "$WD/cycle.log" | sed "s|$WD/||" | cut -c1-200
  log "cycle exit $crc"
  log "DRP fakecam_0's log: buffer sizes, MemPoolSim, XTC space, abort:"
  grep -h -E 'dmaSize|pebble buffer size|MemPoolSim: (sim_length|readout)|Insufficient space|killed by signal|DMA overflowed' "$WD"/pmlogs/*/*/*fakecam_0.log | cut -c1-200
  log "control log, error lines:"; grep -h -E '<E>' "$WD"/pmlogs/*/*/*control.log | cut -c1-180 | head -8
  log "\$ daq_sim down"
  daq_sim down -w "$WD" > "$WD/down.log" 2>&1; log "down exit $?: $(tail -1 "$WD/down.log" | cut -c1-140)"
elif [ "$MODE" = deaddrp ]; then
  DS="daqstate -p 0 -P tst"
  for st in configured running; do
    log "\$ $DS --state $st"; $DS --state $st 2>&1 | tail -3
  done
  log "\$ $DS   (control's state before the kill)"; $DS 2>&1 | tail -2
  pid=$(drp_pid)
  log "\$ kill -9 $pid   (the DRP fakecam_0, while running)"
  kill -9 "$pid"
  for i in 1 2 3 4 5 6; do
    sleep 10
    log "t+$((i*10))s \$ $DS   ->  $($DS 2>&1 | tail -1)"
    daq_sim status -w "$WD" 2>&1 | grep -E 'fakecam_0|teb0|control +state|NumL0' | cut -c1-160
  done
  log "\$ $DS --state configured   (Disable; control learns about the DRP only now)"
  $DS --state configured 2>&1 | tail -5
  log "\$ $DS"; $DS 2>&1 | tail -2
  log "control log, error lines:"; grep -h -E '<E>|error|did not respond' "$WD"/pmlogs/*/*/*control.log | cut -c1-180 | tail -8
  log "\$ daq_sim down"
  daq_sim down -w "$WD" > "$WD/down.log" 2>&1; log "down exit $?: $(tail -1 "$WD/down.log" | cut -c1-140)"
fi
log "DRP log tail (procmgr log of fakecam_0):"
tail -12 "$WD"/pmlogs/*/*/*fakecam_0.log | cut -c1-200
log "processes with signal 6 / 9 in their procmgr logs:"
grep -H -E 'killed by signal' "$WD"/pmlogs/*/*/*.log | sed "s|$WD/||" | cut -c1-200
rm -f "$WD"/data/*/*/xtc/*.xtc2 2>/dev/null
log "done"
