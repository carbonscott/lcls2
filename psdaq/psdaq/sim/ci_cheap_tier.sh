#!/bin/bash
# ci_cheap_tier.sh -- the cheap tier of the hardware-free DAQ, on a GitHub-hosted runner
# (.github/workflows/sim_cheap_tier.yaml). Run from the lcls2 checkout after ./build_all.sh -d,
# in the conda env of .daq_20250402_r9.txt.
#   bash psdaq/psdaq/sim/ci_cheap_tier.sh unit   every psdaq/psdaq/tests/test_sim*.py, by glob
# The fakecam DAQ run of the cheap tier is not here: fakecam's drp imports l2si_drp from
# slaclab/l2si-drp (SLAC-internal), so it runs on one S3DF node:
#   daq_sim matrix -w <WD> --only types --types fakecam      (exit 0)
#   daq_sim matrix -w <WD> --break corrupt                    (exit 1)
# The env below is what setup_env_daq.sh sets, without its S3DF conda base and auth.sh.
set -u
REPO=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../.." && pwd)
cd "$REPO" || exit 2

export ENV_TYPE=daq                     # preflight.sh sources setup_env_daq.sh (S3DF paths) otherwise
export TESTRELDIR=$REPO/install
export PATH=$TESTRELDIR/bin:$PATH
pyver=$(python -V 2>&1 | grep -oP '\d+\.\d+' | head -1)
export PYTHONPATH=$TESTRELDIR/lib/python$pyver/site-packages
export PROCMGR_EXPORT=RDMAV_FORK_SAFE=1,RDMAV_HUGEPAGES_SAFE=1,OPENBLAS_NUM_THREADS=1,OMP_NUM_THREADS=1,NUMEXPR_NUM_THREADS=1,PS_PARALLEL='none'
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
export QT_QPA_PLATFORM=offscreen

unit() {
    shopt -s nullglob
    local files=(psdaq/psdaq/tests/test_sim*.py)
    echo "sim test files collected: ${#files[@]} (glob psdaq/psdaq/tests/test_sim*.py at $(git rev-parse --short HEAD 2>/dev/null))"
    printf '  %s\n' "${files[@]}"
    (( ${#files[@]} > 0 )) || { echo "no sim test files found"; return 1; }
    # in the isolation env, as every sim process runs: some tests call daq_sim.main, which
    # re-executes itself through sim_env.sh (daq_sim.ensure_env) when it is not sourced
    source psdaq/psdaq/sim/sim_env.sh
    python -m pytest -rfEs "${files[@]}"
}

case "${1:-}" in
    unit) unit ;;
    *) echo "usage: $0 unit"; exit 2 ;;
esac
