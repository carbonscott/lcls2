#!/bin/bash
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/redo/env.sh
TREE=$R/redo/$1; WD=$R/redo/out/$2
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=2 --mem=4G bash -c "cd $TREE && source ./setup_env_daq.sh >/dev/null 2>&1 && daq_sim down -w $WD; echo DOWN_EXIT=\$?" 2>&1 | tail -3
