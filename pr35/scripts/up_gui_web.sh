#!/bin/bash
# On sdfiana025: in its own Slurm step on the node, a daq_webgui serving /gui/procstat, /gui/groupca and /gui/pvant
# for the simulated DAQ of $WD (the command of psdaq/psdaq/webgui/README.md); the step lives until down_gui_web.sh.
source /sdf/scratch/users/c/cwang31/guiproof/penv.sh
NAME=$1; [ -n "$NAME" ] || { echo "usage: up_gui_web.sh <run name>"; exit 2; }
D=$P/$NAME; [ -e $D ] && { echo "$D exists: pick a new run name"; exit 2; }
mkdir -p $D
setsid nohup srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=4 --mem=8G bash -c "
  cd $R/wt-gui2 && source ./setup_env_daq.sh >/dev/null 2>&1 && source psdaq/psdaq/sim/sim_env.sh
  export PYTHONPATH=\$PWD/psdaq:\$PYTHONPATH
  echo \"on \$(hostname), Slurm job \$SLURM_JOB_ID step \$SLURM_STEP_ID, wt-gui2 at \$(git rev-parse HEAD), local changes \$(git status --short | wc -l)\"
  set -x
  daq_webgui -p 5 -H 127.0.0.1 --port 31063 --configdb-url http://127.0.0.1:31050/ws/ --procstat-cnf $WD/daq_sim.cnf --procstat-logdir $WD/pmlogs --pvgui 'groupca:DAQ:SIM 0 5' --pvgui 'pvant:--bases DAQ:SIM:XPM:0:PART:5 DAQ:SIM:XPM:0:PART:0 --fields NumL0Acc NumL0Inp L0AccRate' > $D/webgui.log 2>&1 &
  { set +x; } 2>/dev/null
  SP=\$!; echo \$SP > $D/pid; echo \"daq_webgui pid \$SP\"
  while [ -e $D/pid ] && kill -0 \$SP 2>/dev/null; do sleep 1; done
  kill \$SP 2>/dev/null; wait \$SP; echo \"daq_webgui stopped (exit \$?)\"" > $D/up.log 2>&1 < /dev/null &
for i in $(seq 1 90); do grep -q 'listening on' $D/webgui.log 2>/dev/null && break; sleep 1; done
sed 's,^+ ,  + ,' $D/up.log | cut -c1-400; grep -E 'listening|started|rror' $D/webgui.log | cut -c1-200
