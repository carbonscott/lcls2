#!/bin/bash
# web40_session.sh D -- ONE srun step (under the node lock): a fresh simulated DAQ (daq_sim up --segments 2 --detach),
# the device simulators of this PR's pages (simhsd + a simxpm at XPM 7 for hsdPs; the config DB stand-in for
# configdb_GUI; simxpms at XPM 5 (xtpg) and 6 (Kcu1500) for xpmpva), and one daq_webgui serving seqplot, seq_epixhr,
# hsdPs, configdb_GUI and xpmpva on 127.0.0.1:31063, with the arguments the parity walks gave the PyQt programs.  It
# answers read-back requests (D/readback.req -> D/readback.out, its own p4p and HTTP clients in the DAQ env) and, on
# D/stop (or after 90 min), stops all of it and runs daq_sim down.  Everything it starts, it stops.
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof40/penv.sh
D=$1; WD=$D/dsw
cd $T || exit 9
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONPATH=$PWD/psdaq${PYTHONPATH:+:$PYTHONPATH}
echo "on $(hostname), Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID (node lock held), wt-gui4 at $(git rev-parse --short HEAD), local changes $(git status --short | wc -l)"
echo "listening on 30050 (XPM pull) or 15075 (PVA) before: $(ss -ltn | grep -cE ':(30050|15075) ')"
timeout -k 5 400 daq_sim up -w $WD --segments 2 --detach > $D/up.log 2>&1; echo "daq_sim up -w $WD --segments 2 --detach: exit $?"
daq_sim status -w $WD | sed -n '2,8p'
PIDS=()
start_sim() { local tag=$1 n=$2; shift 2; python -m psdaq.sim.$n "$@" > $D/$tag.log 2>&1 & PIDS+=($!); TAGS+=($tag); }
TAGS=()
start_sim simhsd-ps simhsd -P DAQ:SIM:HSD:1_PS:A
start_sim simxpm-7 simxpm -P DAQ:SIM -x 7 --frames tcp://127.0.0.1:31077 --pull none
start_sim simxpm-5 simxpm -P DAQ:SIM -x 5 --frames tcp://127.0.0.1:31075 --pull none --fwbuild 'simxpm xtpg (psdaq/psdaq/sim/simxpm.py): software XPM, no firmware'
start_sim simxpm-6 simxpm -P DAQ:SIM -x 6 --frames tcp://127.0.0.1:31076 --pull none --fwbuild 'simxpm Kcu1500 (psdaq/psdaq/sim/simxpm.py): software XPM, no firmware'
start_sim configdb configdb_server --store $D/configdb.json --port 47321 --seed-gui
for n in ${TAGS[@]}; do
  for i in $(seq 120); do grep -qw 'ready' $D/$n.log 2>/dev/null && break; sleep 0.5; done
  echo "  $n: $(grep -m1 -w 'ready' $D/$n.log | cut -c1-110 || echo "not ready")"
done
daq_webgui -p 5 -H 127.0.0.1 --port 31063 --configdb-url http://127.0.0.1:31050/ws/ --configdb-root configDB \
  --events-source pva --events-pv DAQ:SIM:XPM:0:PART:5:NumL0Acc \
  --seqplot '--seq 0:33k_35k.py 1:10k.py --time 0 0.01' --seq-epixhr '--test --plot --rate 1000' \
  --hsdps '--base DAQ:SIM:HSD:1_PS:A --xpm DAQ:SIM:XPM:7 --range 0 24 8' \
  --configdb-gui '--url http://127.0.0.1:47321/ws-auth/ --hutch tst --password sim' \
  --pvgui 'xpmpva:DAQ:SIM:XPM:5 DAQ:SIM:XPM:6' > $D/webgui.log 2>&1 &
WP=$!
echo "  daq_webgui pid $WP: --seqplot, --seq-epixhr, --hsdps, --configdb-gui, --pvgui xpmpva"
for i in $(seq 240); do grep -q 'listening on' $D/webgui.log && break; sleep 0.5; done
grep -m1 'listening on' $D/webgui.log | cut -c1-140
echo SESSION_UP
SECONDS=0
while [ ! -e $D/stop ] && [ $SECONDS -lt 5400 ] && kill -0 $WP 2>/dev/null; do
  if [ -e $D/readback.req ]; then
    mv $D/readback.req $D/readback.json
    { echo "== on $(hostname), Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID (the step that started this DAQ and the simulators), tree $(git rev-parse --short HEAD)"
      daq_sim status -w $WD | grep -E '^  (simxpm|control|teb0|fakecam_[01]) '
      for k in ${!PIDS[@]}; do echo "  ${TAGS[$k]} pid ${PIDS[$k]} $(kill -0 ${PIDS[$k]} 2>/dev/null && echo alive || echo GONE)"; done
      timeout -k 5 120 python $Q/readback40.py $D/readback.json; echo "readback exit $?"; } > $D/readback.out 2>&1
    echo READBACK_DONE >> $D/readback.out
  fi
  sleep 0.5
done
echo "stopping (stop file: $([ -e $D/stop ] && echo yes || echo no), ${SECONDS}s)"
kill $WP 2>/dev/null; wait $WP 2>/dev/null; echo "daq_webgui stopped"
kill "${PIDS[@]}" 2>/dev/null; wait "${PIDS[@]}" 2>/dev/null; echo "simulators stopped: $(for p in ${PIDS[@]}; do kill -0 $p 2>/dev/null && echo -n "$p alive "; done)"
timeout -k 5 300 daq_sim down -w $WD > $D/down.log 2>&1; echo "daq_sim down: exit $?; $(tail -1 $D/down.log | cut -c31-)"
sleep 2
echo "listening on 30050, 15075, 31063 or 47321: $(ss -ltn | grep -cE ':(30050|15075|31063|47321) '); my procServ: $(pgrep -u $USER -x procServ | wc -l); simulators of this step still alive: $(for p in ${PIDS[@]}; do kill -0 $p 2>/dev/null && echo -n "$p "; done | wc -w)"
echo SESSION_DONE
