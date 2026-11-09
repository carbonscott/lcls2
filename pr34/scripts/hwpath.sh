#!/bin/bash
# usage: hwpath.sh <worktree> <type>...: the hardware path (a /dev/datadev_0 device, no sim://) of each
# BEB type, as run from <worktree>'s build: the type's python <type>_init and its drp. Paths and pids
# are normalized so base and head can be diffed; line 1 (not diffed) names the build that ran.
W=$1; shift
cd /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/$W || exit 2
source setup_env_daq.sh >/dev/null 2>&1
export PYTHONDONTWRITEBYTECODE=1
norm() { sed -e "s#/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/$W#<wt>#g; s#/sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/$W#<wt>#g; s#\[[0-9]*\]#[PID]#g; s#0x[0-9a-f]\{12\}#0xADDR#g" ; }
echo "== $W head=$(git rev-parse --short HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l) drp=$(command -v drp) PYTHONPATH=$PYTHONPATH"
for T in "$@"; do
  case $T in wave8|wave8he|hrencoder) ARG=SIM:HW:00; K="-k epics_prefix=$ARG";; *) ARG=$T; K="";; esac
  echo "-- $T python: ${T}_init('$ARG', '/dev/datadev_0', 1, None, '186M', 0)"
  timeout -k 2 60 python -B -c "
import importlib, rogue.hardware.axi as a
m = importlib.import_module('psdaq.configdb.${T}_config')
print('module', m.__file__, '; AxiMemMap is', a.AxiMemMap.__module__ + '.' + a.AxiMemMap.__qualname__)
getattr(m, '${T}_init')('$ARG', '/dev/datadev_0', 1, None, '186M', 0)
" 2>&1 | grep -v '^Rogue/pyrogue version\|p4p\|ClientProvider\|^Traceback (most recent call last):$\|^Exception ignored' | tail -4 | norm
  echo "rc=${PIPESTATUS[0]}"
  echo "-- $T drp -D $T -d /dev/datadev_0 $K"
  timeout -k 2 30 drp -p 7 -u ${T}_0 -P tst -C 127.0.0.1 -D $T -d /dev/datadev_0 -l 0x1 -o /tmp/none $K 2>&1 | head -8 | norm
  echo "rc=${PIPESTATUS[0]}"
done
