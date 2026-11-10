#!/bin/bash
# The one production file touched (psdaq/psdaq/tpr/Client.cc): with no simulated device selected (PSDAQ_SIM_TPR unset),
# tprtrig and tpr_trigger's tpr::Client behave as before: the same command at base (wt-prog3, 5bd891385) and head
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/work/progtail/denv.sh
ulimit -c 0
echo "host=$(hostname) date=$(date -Is) /dev/tpra: $(ls /dev/tpra 2>&1)"
for wt in wt-base-t4 wt-final; do
  cd $R/$wt
  echo "== $wt $(git rev-parse --short HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l) Client.cc $(git hash-object psdaq/psdaq/tpr/Client.cc) libtpr $(md5sum install/lib/libtpr.so 2>/dev/null | cut -c1-12)"
  echo "\$ env -u PSDAQ_SIM_TPR $wt/install/bin/tprtrig -t a -c 0 -o 1 -d 2 -w 10 -p 5"
  env -u PSDAQ_SIM_TPR LD_LIBRARY_PATH=$R/$wt/install/lib:$LD_LIBRARY_PATH timeout 30 $R/$wt/install/bin/tprtrig -t a -c 0 -o 1 -d 2 -w 10 -p 5 2>&1 | tail -4; echo "EXIT=${PIPESTATUS[0]}"
  echo "\$ ldd $wt/install/bin/tprtrig | grep libtpr"; LD_LIBRARY_PATH=$R/$wt/install/lib:$LD_LIBRARY_PATH ldd $R/$wt/install/bin/tprtrig | grep libtpr
done
date -Is
