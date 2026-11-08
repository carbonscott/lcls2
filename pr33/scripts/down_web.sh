#!/bin/bash
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/redo/p2/env.sh
WD=$P/$1
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=2 --mem=4G bash -c "cd $R/wt-pr34 && source ./setup_env_daq.sh >/dev/null 2>&1 && export PYTHONPATH=\$PWD/psdaq:\$PYTHONPATH && daq_sim down -w $WD; echo DOWN_EXIT=\$?" 2>&1 | tail -3
sleep 4; tail -1 $WD.up.log
