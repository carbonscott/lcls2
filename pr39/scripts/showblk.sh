#!/bin/bash
# showblk.sh: the first failure of each type that does not run, in its own DRP (drp -D <type>
# -d sim://, no control, nothing else up; each killed after 60 s) or, for a type whose config
# DB entry cannot be built, in configdb_seed.  Runs inside one srun step on the node.
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof39/env.sh
: sim_env.sh is sourced by env.sh
echo "host=$(hostname) head=$(git rev-parse --short HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l) date=$(date -Is) job=$SLURM_JOB_ID step=$SLURM_STEP_ID"
T=$(mktemp -d /tmp/p39-blk-XXXXXX); echo '{}' > $T/empty.json
run() {   # run <type> <kwargs> [env...]
  local t=$1 k=$2; shift 2
  echo "== drp -D $t -d sim://127.0.0.1:31999 -k $k $*"
  env "$@" timeout -k 5 60 drp -p 7 -u ${t}_0 -P tst -C 127.0.0.1 -D $t -d sim://127.0.0.1:31999 -l 0x1 -o $T -k ep_domain=lo,ep_provider=tcp,$k 2>&1 \
    | grep -v '^Rogue/pyrogue\|cannot tell\|^INFO' | grep -E -B2 -A1 'Error|error|Traceback|abort|critical|<C>|not found|No such' | head -24
  echo "rc=${PIPESTATUS[0]}"
}
run tt sim_seed=0x1234 PSDAQ_SIM_ROGUE_SEEDS=$T/empty.json
run hsd hsd_epics_prefix=SIM:HSD:00
run jungfrau sim_seed=0x1234,slsHosts=127.0.0.1 PSDAQ_SIM_ROGUE_SEEDS=$T/empty.json
echo "== configdb_seed --det-type epixuhr3x2 (its store's beam_cdict, as its __main__ writes)"
timeout -k 5 60 python -c "from psdaq.sim.configdb_seed import type_cdict; type_cdict('epixuhr3x2', 'epixuhr3x2')" 2>&1 | grep -v '^Rogue' | tail -4
echo rc=${PIPESTATUS[0]}
rm -rf $T
echo SHOWBLK_DONE
