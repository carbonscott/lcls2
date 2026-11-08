#!/bin/bash
# On sdfiana025: in a second step on the node, what the DAQ itself counted and what psana2 reads.
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/redo/env.sh
TREE=$R/redo/$1; WD=$R/redo/out/$2
[[ "$3" =~ ^[0-9]+$ ]] || { echo "usage: readback.sh <worktree> <run name> <page count> [seed]  (count must be a number, got: '$3')"; exit 2; }
N=$3; SEED=${4:-0x1234}
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=4 --mem=8G bash -c "
  cd $TREE && source ./setup_env_daq.sh >/dev/null 2>&1 && source psdaq/psdaq/sim/sim_env.sh
  echo \"== on \$(hostname), Slurm job \$SLURM_JOB_ID step \$SLURM_STEP_ID, tree \$(git rev-parse --short HEAD)\"
  daq_sim status -w $WD | grep -E 'control +state|webgui|NumL0Acc|NumL0Inp|TEB_WrtCt|DRP_Damage'
  F=\$(ls -t $WD/data/tst/tstx00001/xtc/*.xtc2 | head -1); echo \"== python -m psdaq.sim.xtc2_check \$(basename \$F) --seed $SEED --expect $N\"
  python -m psdaq.sim.xtc2_check \$F --seed $SEED --expect $N > /tmp/xc.\$\$ 2>&1; rc=\$?; grep -v 'Problem reading dgram header' /tmp/xc.\$\$; rm -f /tmp/xc.\$\$; echo XTC2_CHECK_EXIT=\$rc
  for f in $WD/pmlogs/*/*/*fakecam_0.log; do grep -h 'Sim payload seed' \$f | tail -1; done"
