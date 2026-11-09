#!/bin/bash
# web37_session.sh D -- ONE srun step: a fresh simulated DAQ (daq_sim up --segments 2 --detach), the campaign device
# simulators, and a daq_webgui serving this PR's pages on 127.0.0.1:31063; it answers read-back requests (D/readback.req
# -> D/readback.out, a separate p4p client in the DAQ env) and, on D/stop (or after 90 min), stops all of it and
# runs daq_sim down.  Everything it starts, it stops.
source /sdf/scratch/users/c/cwang31/proof37/penv.sh
D=$1; WD=$D/dsw
cd $T || exit 9
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONPATH=$PWD/psdaq${PYTHONPATH:+:$PYTHONPATH}
echo "on $(hostname), Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID, wt-gui3 at $(git rev-parse --short HEAD), local changes $(git status --short | wc -l)"
echo "listening on 30050 (XPM pull) or 15075 (PVA) before: $(ss -ltn | grep -cE ':(30050|15075) ')"
timeout -k 5 400 daq_sim up -w $WD --segments 2 --detach > $D/up.log 2>&1; echo "daq_sim up -w $WD --segments 2 --detach: exit $?"
daq_sim status -w $WD | sed -n '2,8p'
PIDS=()
start_sim() { local n=$1; shift; python -m psdaq.sim.$n "$@" > $D/$n.log 2>&1 & PIDS+=($!); }
start_sim simtpr -P DAQ:SIM:TPR
start_sim simhsd -P DAQ:SIM:HSD:1_1B:A DAQ:SIM:HSD:1_1B:B
start_sim simdti -P DAQ:SIM:DTI
start_sim simdetprot -P DAQ:SIM:JF16M:BLOCKER --trip-after 60
start_sim simdatadev --root $D/datadev
for n in simtpr simhsd simdti simdetprot simdatadev; do
  for i in $(seq 120); do grep -q 'ready' $D/$n.log 2>/dev/null && break; sleep 0.5; done
  echo "  $(grep -m1 'ready' $D/$n.log | cut -c1-120 || echo "$n: not ready")"
done
daq_webgui -p 5 -H 127.0.0.1 --port 31063 --configdb-url http://127.0.0.1:31050/ws/ --configdb-root configDB \
  --events-source pva --events-pv DAQ:SIM:XPM:0:PART:5:NumL0Acc \
  --pvgui 'groupca:DAQ:SIM 0 5' --pvgui 'deadca:DAQ:SIM 5 0' --pvgui 'partca:DAQ:SIM:XPM:0:PART:5' \
  --pvgui 'xpmpatt:DAQ:SIM:XPM:0' --pvgui 'tprca:DAQ:SIM:TPR' --pvgui 'hsdpva:DAQ:SIM:HSD:1_1B:A DAQ:SIM:HSD:1_1B:B' \
  --pvgui 'dtica:DAQ:SIM:DTI' --dpm '-b DAQ:SIM:JF16M:BLOCKER -d Jungfrau' --datadev-sim $D/datadev > $D/webgui.log 2>&1 &
WP=$!
echo "  daq_webgui pid $WP: --pvgui groupca, deadca, partca, xpmpatt, tprca, hsdpva, dtica; --dpm; --datadev-sim"
for i in $(seq 120); do grep -q 'listening on' $D/webgui.log && break; sleep 0.5; done
grep -m1 'listening on' $D/webgui.log | cut -c1-140
echo SESSION_UP
SECONDS=0
while [ ! -e $D/stop ] && [ $SECONDS -lt 5400 ] && kill -0 $WP 2>/dev/null; do
  if [ -e $D/readback.req ]; then
    mv $D/readback.req $D/readback.json
    { echo "== on $(hostname), Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID (the step that started this DAQ), tree $(git rev-parse --short HEAD)"
      daq_sim status -w $WD | grep -E '^  (simxpm|control|teb0|fakecam_[01]) '
      timeout -k 5 120 python $Q/readback37.py $D/readback.json; echo "readback exit $?"; } > $D/readback.out 2>&1
    echo READBACK_DONE >> $D/readback.out
  fi
  sleep 0.5
done
echo "stopping (stop file: $([ -e $D/stop ] && echo yes || echo no), ${SECONDS}s)"
kill $WP 2>/dev/null; wait $WP 2>/dev/null; echo "daq_webgui stopped"
kill "${PIDS[@]}" 2>/dev/null; wait "${PIDS[@]}" 2>/dev/null; echo "simulators stopped: $(for p in ${PIDS[@]}; do kill -0 $p 2>/dev/null && echo -n "$p alive "; done)"
timeout -k 5 300 daq_sim down -w $WD > $D/down.log 2>&1; echo "daq_sim down: exit $?; $(tail -1 $D/down.log | cut -c31-)"
sleep 2
echo "listening on 30050, 15075 or 31063: $(ss -ltn | grep -cE ':(30050|15075|31063) '); my procServ: $(pgrep -u $USER -x procServ | wc -l); simulators of this step still alive: $(for p in ${PIDS[@]}; do kill -0 $p 2>/dev/null && echo -n "$p "; done | wc -w)"
echo SESSION_DONE
