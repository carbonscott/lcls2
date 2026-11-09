#!/bin/bash
# proof37 step 1, ONE srun step: at the merge head, build; simxpm PV names counted; sim unit tests; the ts type cycle
# (logs/xpm/typerun.sh pattern); a fresh DAQ with the groupca/partca/xpmpatt web tests; every DAQ started here taken down.
source /sdf/scratch/users/c/cwang31/proof37/penv.sh
E=$Q/s1; mkdir -p $E
cd $T || exit 9
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONPATH=$PWD/psdaq${PYTHONPATH:+:$PYTHONPATH}
echo "host=$(hostname) job=$SLURM_JOB_ID step=$SLURM_STEP_ID date=$(date -Is)"
echo "head=$(git rev-parse HEAD) parents=$(git log -1 --format=%P) local changes: $(git status --short | wc -l)"
echo "== build"; time ./build_all.sh -d -j 16 > $E/build.log 2>&1; echo BUILD_EXIT=$?; grep -cE '^\[[0-9]+/[0-9]+\]' $E/build.log; tail -2 $E/build.log
echo "== simxpm PV names"; timeout -k 5 120 python $Q/pvdup.py; echo PVDUP_EXIT=$?
echo "== sim unit tests"
timeout -k 5 900 python -m pytest -q -p no:cacheprovider psdaq/psdaq/tests/test_sim_{coverage,rogue_dev,framer,configdb_seed_store,configdb,lgbk,xpmdet_types}.py psdaq/psdaq/tests/test_simxpm.py > $E/unit.log 2>&1; echo UNIT_EXIT=$?; tail -1 $E/unit.log
echo "listening on 30050 or 15075 before the ts run: $(ss -ltn | grep -cE ':(30050|15075) ')"
WD=$E/wd-ts
echo "== up --det ts"
timeout -k 5 300 daq_sim up -w $WD --det ts --detach > $E/ts-up.log 2>&1; echo UP_EXIT=$?; tail -3 $E/ts-up.log | cut -c1-160
echo "== cycle"
timeout -k 5 400 daq_sim cycle -w $WD --events 1000 > $E/ts-cycle.log 2>&1; echo CYCLE_EXIT=$?; grep -iE 'PASS|FAIL|NumL0Acc|events|evidence' $E/ts-cycle.log | tail -8 | cut -c1-200
grep -h -E 'rxready|RxLink locked|setting xpm link enables' $WD/pmlogs/*/*/*ts_0*.log 2>/dev/null | head -4 | cut -c1-200
F=$(ls $WD/data/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2 2>/dev/null)
SEED=$(python -c "import json,glob;print(hex(json.load(open(glob.glob('$WD/*state*.json')[0]))['seed']))" 2>/dev/null || echo 0x1234)
if [ -n "$F" ]; then
  for a in '' '--self-test-offset 1'; do
    echo "== xtc2_check $(basename $F) --det ts --seed $SEED $a"
    timeout -k 5 600 python -m psdaq.sim.xtc2_check $F --det ts --seed $SEED $a 2>&1 | grep -v '^Rogue' | tail -4; echo rc=${PIPESTATUS[0]}
  done
else echo "no xtc2 file"; fi
echo "== down"
timeout -k 5 120 daq_sim down -w $WD > $E/ts-down.log 2>&1; echo DOWN_EXIT=$?; tail -1 $E/ts-down.log
sleep 2; echo "listening on 30050 or 15075 after the ts run: $(ss -ltn | grep -cE ':(30050|15075) ')"
W=$E/dsw
echo "== up --segments 2 (for the web tests)"
timeout -k 5 300 daq_sim up -w $W --segments 2 --detach > $E/up.log 2>&1; echo UP_EXIT=$?
daq_sim status -w $W | head -9
echo "== groupca, partca, xpmpatt web tests on it"
timeout -k 5 1200 env WEBGUI_SIM_DAQ=$W WEBGUI_SHOTS=$E/shots bash psdaq/psdaq/webgui/tests/run_webgui_tests.sh -v -p no:warnings -k 'test_gui_groupca or test_gui_partca or test_gui_xpmpatt' --junitxml=$E/web3.junit.xml > $E/web3.log 2>&1; echo WEB3_EXIT=$?
grep -E '(PASSED|FAILED|ERROR|SKIPPED)' $E/web3.log | sed 's/ *\[ *[0-9]*%\]//' | cut -c1-150; tail -1 $E/web3.log
echo "== down"
timeout -k 5 120 daq_sim down -w $W > $E/down.log 2>&1; echo DOWN_EXIT=$?; tail -1 $E/down.log
sleep 2; echo "listening on 30050 or 15075 after: $(ss -ltn | grep -cE ':(30050|15075) ')"
echo "my procServ / psdaq.sim / webgui processes left: $(pgrep -u $USER -f 'procServ|psdaq.sim.sim|psdaq.webgui.server' | wc -l)"
echo "checkout local changes: $(git status --short | wc -l)"
echo S1_DONE $(date -Is)
