#!/bin/bash
# usage: hwpath.sh <worktree> <type>...: the hardware path (no sim:// device) of each type, as run
# from <worktree>'s build: the python entry point the DRP calls first (xpmdet_init for the
# XpmDetector types, <type>_init for BEB types) with /dev/datadev_0, which psdaq.sim modules are
# loaded and what rogue's transports are, then 'drp -D <type> -d /dev/datadev_0'.  Paths and
# pids normalized so base and head can be diffed.  Run inside one srun step on the node, with
# the worktree's own setup_env_daq.sh and sim_env.sh.
W=$1; shift
cd /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/$W
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify
source setup_env_daq.sh >/dev/null 2>&1
source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1
norm() { sed -e "s#/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/$W#<wt>#g; s#/sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/$W#<wt>#g; s#\[[0-9][0-9]*\]#[PID]#g; s#0x[0-9a-f]\{12\}#0xADDR#g; s#/tmp/hw-[A-Za-z0-9]*#/tmp/hw-X#g" ; }
echo "== $W head=$(git rev-parse --short HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l)"
for T in "$@"; do
  case $T in
    fakecam|cspad|epixhremu|jungfrauemu|ts) MOD=xpmdet; CALL="xpmdet_init('/dev/datadev_0', 1, '186M', 0)";;
    *) MOD=$T; CALL="${T}_init('$T', '/dev/datadev_0', 1, None, '186M', 0)";;
  esac
  echo "-- $T python: psdaq.configdb.${MOD}_config.$CALL"
  timeout -k 2 60 python -B -c "
import importlib, sys, rogue.hardware.axi as a, rogue.protocols.xilinx as x, pyrogue as pr
m = importlib.import_module('psdaq.configdb.${MOD}_config')
try:
    getattr(m, '${CALL%%(*}')(${CALL#*(}
except BaseException as e:
    print('raised', type(e).__name__, str(e).splitlines()[0][:160] if str(e) else '')
print('psdaq.sim modules loaded:', sorted(k for k in sys.modules if k.startswith('psdaq.sim')))
print('AxiMemMap', a.AxiMemMap.__module__, a.AxiMemMap.__qualname__, '| AxiStreamDma', a.AxiStreamDma.__qualname__, '| Xvc', x.Xvc.__module__, x.Xvc.__qualname__, '| Device._start', pr.Device._start.__module__)
" 2>&1 | grep -v '^Rogue/pyrogue version\|p4p\|ClientProvider\|^Exception ignored' | tail -4 | norm
  echo "rc=${PIPESTATUS[0]}"
  D=$(mktemp -d /tmp/hw-XXXXXX)
  echo "-- $T drp -D $T -d /dev/datadev_0"
  timeout -k 2 30 drp -p 7 -u ${T}_0 -P tst -C 127.0.0.1 -D $T -d /dev/datadev_0 -l 0x1 -o $D 2>&1 | head -8 | norm
  echo "rc=${PIPESTATUS[0]}"
  rm -rf $D
done
