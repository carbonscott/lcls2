#!/bin/bash
# On sdfiana025: in a second step on the node, what the DAQ itself counted and what psana2 reads, per segment file.
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/redo/p2/env.sh
WD=$P/$1; [[ "$2" =~ ^[0-9]+$ ]] || { echo "usage: readback_web.sh <run name> <page count>  (got '$2')"; exit 2; }
N=$2
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=4 --mem=8G bash -c "
  cd $R/wt-pr34 && source ./setup_env_daq.sh >/dev/null 2>&1 && source psdaq/psdaq/sim/sim_env.sh
  export PYTHONPATH=\$PWD/psdaq:\$PYTHONPATH
  echo \"== on \$(hostname), Slurm job \$SLURM_JOB_ID step \$SLURM_STEP_ID, tree \$(git rev-parse --short HEAD)\"
  daq_sim status -w $WD | grep -E '^  (control|teb0|fakecam_[01]|webgui) |control +state|NumL0Acc'
  for F in $WD/data/tst/tstx00001/xtc/*-c000.xtc2; do
    echo \"== xtc2_check \$(basename \$F) --seed 0x1234 --expect $N\"
    python -m psdaq.sim.xtc2_check \$F --seed 0x1234 --expect $N > /tmp/xc.\$\$ 2>&1; rc=\$?
    if grep -q 'KeyError: 0' /tmp/xc.\$\$; then echo \"   exit \$rc: no segment 0 in this file (psana's fakecam det.raw.raw() reads segment 0 only)\"
    else grep -E 'L1Accept events|seq|PASS|FAIL' /tmp/xc.\$\$; echo \"   XTC2_CHECK_EXIT=\$rc\"; fi; rm -f /tmp/xc.\$\$
  done
  echo \"== seg_check.py, both files, every segment in them (det.raw._segments)\"
  python $P/seg_check.py $WD/data/tst/tstx00001/xtc/*-c000.xtc2 --seed 0x1234 --expect $N 2>&1 | grep -v 'Problem reading dgram header'"
