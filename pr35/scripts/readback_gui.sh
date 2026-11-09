#!/bin/bash
# On sdfiana025: in a second step on the node, read back with PV Access from the DAQ env (not through the web server)
# what the browser run left in simxpm, and that procmgr's processes are the ones daq_sim started (nothing restarted).
# usage: readback_gui.sh <groupca count the page showed> <InhEnable0> <InhInterval0> <DstSelect_Mask> (the values before)
source /sdf/scratch/users/c/cwang31/guiproof/penv.sh
[ $# -eq 4 ] || { echo "usage: readback_gui.sh N INH_ENABLE0 INH_INTERVAL0 DST_MASK"; exit 2; }
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=2 --mem=4G bash -c "
  cd $R/wt-gui2 && source ./setup_env_daq.sh >/dev/null 2>&1 && source psdaq/psdaq/sim/sim_env.sh
  export PYTHONPATH=\$PWD/psdaq:\$PYTHONPATH
  echo \"== on \$(hostname), Slurm job \$SLURM_JOB_ID step \$SLURM_STEP_ID, tree \$(git rev-parse --short HEAD)\"
  daq_sim status -w $WD | grep -E '^  (control|teb0|fakecam_[01]) |simxpm +pid'
  python - $1 $2 $3 $4 <<'PY'
import os, sys
from p4p.client.thread import Context
from psdaq.webgui.netguard import require_loopback_pva_env
n, inh, itv, mask = (float(x) for x in sys.argv[1:5])
c = Context('pva', conf=require_loopback_pva_env(os.environ), useenv=False)
B = 'DAQ:SIM:XPM:0:PART:5:'
got = dict(zip(['NumL0Acc', 'InhEnable0', 'InhInterval0', 'DstSelect_Mask'],
               [float(v) for v in c.get([B + k for k in ('NumL0Acc', 'InhEnable0', 'InhInterval0', 'DstSelect_Mask')], timeout=5.0)]))
want = {'NumL0Acc': n, 'InhEnable0': inh, 'InhInterval0': itv, 'DstSelect_Mask': mask}
for k in want:
    print('  pvget %s%-15s = %-8g  expected %-8g %s' % (B, k, got[k], want[k], 'ok' if got[k] == want[k] else 'DIFFERS'))
print('READBACK', 'PASS' if got == want else 'FAIL')
PY"
