#!/bin/bash
# details.sh: each passing GUI's full check_gui_parity report, from the walks the recorded run wrote ($P/walks; read,
# not run now), and the junit of its suite run.  No DAQ needed.
source /sdf/scratch/users/c/cwang31/fix35/penv.sh
cd $R/wt-gui2 || exit 9
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONPATH=$PWD/psdaq${PYTHONPATH:+:$PYTHONPATH}
echo "host $(hostname) job $SLURM_JOB_ID step $SLURM_STEP_ID date $(date -Is) head $(git rev-parse HEAD) changes $(git status --short | wc -l)"
for g in groupca procstat pvant; do
    python -m psdaq.webgui.parity.check_gui_parity --walks $P/walks --junit $P/sim.junit.xml --only $g --details
    echo "EXIT_$g=$?"
done
