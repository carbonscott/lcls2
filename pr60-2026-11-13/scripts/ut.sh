#!/bin/bash
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/pr60/env.sh
srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=8 --mem=16G bash -c '
  source $ROOT/simenv.sh $WT && export PATH=$WT/install/bin:$PATH QT_QPA_PLATFORM=offscreen &&
  pyver=$(python -V 2>&1 | grep -oP "\d+\.\d+" | head -1) &&
  export PYTHONPATH=$WT/install/lib/python$pyver/site-packages:$PYTHONPATH &&
  files=(psdaq/psdaq/tests/test_sim*.py); echo "files ${#files[@]}" &&
  pytest -rs -p no:cacheprovider "${files[@]}"; echo PYTEST_EXIT=$? $(date -u +%FT%TZ)' > $P/work/ut.log 2>&1
