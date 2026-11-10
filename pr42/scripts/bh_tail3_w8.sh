#!/bin/bash
# base (wt-base-t4, b6f370d9f) vs head (wt-final) of wave8pvs with no simulated device: lab3-wave8.cnf's 'wave8pvs --l 0'
# in the DAQ env, and with python -m psdaq.cas.wave8pvs --l 0 in site envs with the site's wave8 sources on PYTHONPATH
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
L=$R/work/tail3
SITE=/sdf/group/lcls/ds/ana/sw/conda2/inst/envs
pp() {  # python path of an unpacked wave8 source
  local X=$L/w8src/$1 P
  P=$X/wave8/firmware/python
  for s in $(ls $X/wave8/firmware/submodules); do [ -d $X/wave8/firmware/submodules/$s/python ] && P=$P:$X/wave8/firmware/submodules/$s/python; done
  echo $P
}
for wt in wt-base-t4 wt-final; do
  echo "== $wt $(git -C $R/$wt rev-parse --short HEAD) tracked-dirty=$(git -C $R/$wt status --porcelain --untracked-files=no | wc -l)"
  ( W=$R/$wt; source $L/denv.sh; cd /tmp
    echo "\$ wave8pvs --l 0   (DAQ env, $(which wave8pvs))"
    timeout -k 5 120 wave8pvs --l 0 2>&1 | grep -v "^Rogue/" | tail -1; echo "EXIT=${PIPESTATUS[0]}" )
  for combo in ps-4.5.16:wave8-1.0.1 ps-4.5.23:wave8-1.0.0 ps-4.5.16:wave8-1.0.0; do
    E=$SITE/${combo%%:*}; V=${combo##*:}
    echo "\$ ${combo%%:*}/bin/python -m psdaq.cas.wave8pvs --l 0   (PYTHONPATH: site $V source, $wt/psdaq)"
    ( cd /tmp; env -i PATH=$E/bin:/usr/bin:/bin HOME=/tmp LD_LIBRARY_PATH=$E/epics/lib/linux-x86_64:$E/pcas/lib/linux-x86_64 \
        PYTHONPATH=$(pp $V):$R/$wt/psdaq timeout -k 5 300 $E/bin/python -W ignore -m psdaq.cas.wave8pvs --l 0 2>&1 \
        | grep -v "^Rogue/" | grep -A1 "^  File .*\(wave8pvs\|Top\).py" | tail -2; echo "EXIT=${PIPESTATUS[0]}"
      env -i PATH=$E/bin:/usr/bin:/bin HOME=/tmp LD_LIBRARY_PATH=$E/epics/lib/linux-x86_64:$E/pcas/lib/linux-x86_64 \
        PYTHONPATH=$(pp $V):$R/$wt/psdaq timeout -k 5 300 $E/bin/python -W ignore -m psdaq.cas.wave8pvs --l 0 2>&1 | tail -1 )
  done
done
date -Is
