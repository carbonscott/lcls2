#!/bin/bash
# forge.sh EVDIR: a reviewer's forgeries of a programs record at wt-final's HEAD, by record edits only (no file written,
# no hash computed; fg23.py and fg1.py are the reviewer's): FG2 EVDIR's programs record (MINE) with its gui_witness
# swapped for another run's (finalinteg's programs record at 29f1be4a7); FG3 FG2 plus that run's xtc2 files and the logs
# of its HPS chain, wave8pvs, lclsBldServer and TPR programs; FG1 that other record with only its sha changed to HEAD.
# Coverage over each alone, and over MINE alone (own).
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2; F=$R/work/fix15; cd $R/wt-final
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1
MINE=$(grep -l '"prog:wave8pvs"' $1/*.json | head -1)
OTHER=$R/work/finalinteg/mx-m2-ev/20261109T170955-cycle-29f1be4a7-1146979.json
echo "=== forgeries at wt-final HEAD $(git rev-parse --short HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) on $(hostname -s) $(date -u +%FT%TZ): MINE $(basename $MINE), OTHER $(basename $OTHER)"
D=$F/forge; rm -rf $D; mkdir -p $D/own; cp $MINE $D/own/
python $F/fg23.py $MINE $OTHER $D | sed -E 's/files of the other run: .*/files of the other run (its 4 xtc2 files and 7 logs)/'
python $F/fg1.py $OTHER $D/fg1 $(git rev-parse HEAD)
for t in own fg2 fg3 fg1; do
  daq_sim coverage --evidence $D/$t > $F/forge-$t.log 2>&1; echo "== $t: coverage exit $? $(grep -E '^[0-9]+ rows' $F/forge-$t.log)"
  grep -E 'prog:(hpsBldServer|hpsBldCopy|wave8pvs|lclsBldServer|tprtrig|tpr_trigger|groupca) ' $F/forge-$t.log | sed -E 's/  +/ /g' | cut -c1-250
done
echo "=== forgeries done $(date -u +%FT%TZ)"
