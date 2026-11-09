#!/bin/bash
# defects.sh: the three config-code defects this PR fixes, run the same way in worktree $W
# (wt-base39 at 8830147da, the base; wt-types2, this head), inside one srun step on the node:
#  1. tb_config does not import: the DRP's BEBDetector imports psdaq.configdb.tb_config at start
#  2. tb_connectionInfo takes 1 argument; BEBDetector::connectionInfo calls it with 2 at Alloc
#  3. epixquad_config's import order: DevRoot gets epix-quad's older AxiPcieCore ('extended')
# The DRPs run alone (no control; sim:// device on a port nothing serves) and are stopped after
# 40 s.  The base has no seed file for tb or epixquad (this PR adds them), so there the DRPs get
# an empty one; neither defect depends on a register value.
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof39/env.sh
c() { cut -c1-138; }
echo "${W:-wt-types2} on $(hostname), Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID: HEAD $(git log -1 --format='%h %s' | cut -c1-70), local changes $(git status --short --untracked-files=no | wc -l)"
T=$(mktemp -d /tmp/p39-def-XXXXXX); mkdir -p $T/tst; echo '{}' > $T/empty.json
SEEDENV=""; [ -f psdaq/psdaq/sim/seeds/tb.json ] || SEEDENV="PSDAQ_SIM_ROGUE_SEEDS=$T/empty.json"
echo "seed files for tb, epixquad: $(ls psdaq/psdaq/sim/seeds/{tb,epixquad}.json 2>/dev/null | wc -l) ${SEEDENV:+(none: the DRPs get $SEEDENV)}" | sed "s#$T#\$T#"
drp1() {   # drp1 <type> [<kwargs>]: the DRP alone, its first lines of config code or error
  echo "-- drp -D $1 -d sim://127.0.0.1:31999 ${2:+-k $2 }(alone, stopped after 40 s)"
  env $SEEDENV PYTHONUNBUFFERED=1 timeout -k 5 40 drp -p 7 -u ${1}_0 -P tst -C 127.0.0.1 -D $1 -d sim://127.0.0.1:31999 -l 0x1 -o $T \
      -k ep_domain=lo,ep_provider=tcp,sim_seed=0x1234${2:+,$2} 2>&1 \
    | grep -E 'config runs against|Error|error:|Traceback|python error|Found image|init_feb|Making device AxiPcieCore|SimMemMap|Ready for transitions' \
    | grep -v -E 'RTPRIO|cannot tell' | awk '!s[$0]++' | head -8 | sed "s#$T#\$T#g" | c
  echo "rc=${PIPESTATUS[0]}"
}
echo "== 1. tb_config: import it, as the DRP does at start"
timeout -k 5 60 python -c '
import sys
try:
    import psdaq.configdb.tb_config as m
    print("import psdaq.configdb.tb_config: imported")
except Exception as e:
    print("import psdaq.configdb.tb_config raised", type(e).__name__ + ":", e); sys.exit(1)
' 2>&1 | grep -E '^import psdaq' | c
echo "rc=${PIPESTATUS[0]}"
drp1 tb
echo "== 2. tb_connectionInfo: BEBDetector's call at Alloc, the function's signature, and that call"
grep -n 'PyObject_CallFunction(pFunc,"Os",m_root,alloc_json' psdaq/drp/BEBDetector.cc | sed 's/^ *//; s/  */ /g' | c
timeout -k 5 60 python -c '
from psdaq.utils import enable_lcls2_pgp_pcie_apps   # put lcls2_pgp_pcie_apps on the path, so that the base module imports
import inspect, psdaq.configdb.tb_config as m
print("tb_connectionInfo" + str(inspect.signature(m.tb_connectionInfo)))
try:
    m.tb_connectionInfo({"pcie": None}, "{}")      # as BEBDetector calls it: (root, alloc json)
except Exception as e:
    print("tb_connectionInfo(root, alloc_json) raised", type(e).__name__ + ":", e)
' 2>&1 | grep -E '^tb_connectionInfo' | c
echo "== 3. epixquad_config: the DRP's epixquad_init builds lcls2_pgp_pcie_apps.DevRoot"
grep -n -E '^(from psdaq.utils import enable_(epix_quad|lcls2_pgp_pcie_apps)|import (ePixQuad|lcls2_pgp_pcie_apps))' psdaq/psdaq/configdb/epixquad_config.py | c
drp1 epixquad sim_dma_size=0x110000   # daq_sim up's DMA size for epixquad's 1 MB frames
rm -rf $T
echo DEFECTS_DONE
