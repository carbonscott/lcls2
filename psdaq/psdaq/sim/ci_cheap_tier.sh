#!/bin/bash
# ci_cheap_tier.sh -- the cheap tier of the hardware-free DAQ, on a GitHub-hosted runner
# (.github/workflows/sim_cheap_tier.yaml). Run from the lcls2 checkout after ./build_all.sh -d,
# in the conda env of .daq_20250402_r9.txt, with procServ on PATH (apt package procserv).
#   bash psdaq/psdaq/sim/ci_cheap_tier.sh unit   every psdaq/psdaq/tests/test_sim*.py, by glob
#   bash psdaq/psdaq/sim/ci_cheap_tier.sh daq    daq_sim up / cycle / down (RUNBOOK §2-§5), one fakecam DRP
# The env below is what setup_env_daq.sh sets, without its S3DF conda base and auth.sh; daq_sim
# then sources sim_env.sh itself and runs preflight.sh as on S3DF.
set -u
REPO=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../.." && pwd)
cd "$REPO" || exit 2

export ENV_TYPE=daq                     # preflight.sh sources setup_env_daq.sh (S3DF paths) otherwise
export TESTRELDIR=$REPO/install         # condaProcServ puts its bin, lib and site-packages first
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

# The python of l2si-drp, which every XpmDetector type's drp imports at Configure
# (xpmdet_config.py -> psdaq/utils/enable_l2si_drp.py): the commits of S3DF's
# $SUBMODULEDIR (lcls2_submodules_10292026), only their python dirs, and the one edit its
# patch.sh makes to l2si-drp (its rogue ZmqServer on any free port).
L2SI_DRP=(
    "l2si-drp                                759fe14ec33ccc04a0bba4eb36d71928ac0e49a7 firmware/python"
    "l2si-drp/firmware/submodules/axi-pcie-core    5a814a114a7450d09be21453e503dddab96c4194 python"
    "l2si-drp/firmware/submodules/l2si-core        a96a5577cc6bb25e1286ceebc3b56ab993078f43 python"
    "l2si-drp/firmware/submodules/lcls-timing-core 7ce68a4b8e29642c7892fd99ec0991135e930919 python"
    "l2si-drp/firmware/submodules/lcls2-pgp-fw-lib af85e73e5a19fb395e16a55f9d30394d671de07e python"
    "l2si-drp/firmware/submodules/surf             65dc3e425d609fd14e4b3fc73fe5cbfa37b95f87 python"
)
submodules() {
    local top=$1 line path sha sub repo auth
    for line in "${L2SI_DRP[@]}"; do
        read -r path sha sub <<< "$line"
        repo=${path##*/}
        auth=()                         # l2si-drp is private: a token that reads it, never stored
        [[ $repo == l2si-drp && -n ${L2SI_DRP_TOKEN:-} ]] && \
            auth=(-c "http.https://github.com/.extraheader=AUTHORIZATION: basic $(printf 'x-access-token:%s' "$L2SI_DRP_TOKEN" | base64 -w0)")
        [[ -d $top/$path/$sub ]] && continue
        mkdir -p "$top/$path" && git -C "$top/$path" init -q && \
        git -C "$top/$path" remote add origin "https://github.com/slaclab/$repo" && \
        git -C "$top/$path" sparse-checkout set "$sub" && \
        git -C "$top/$path" "${auth[@]}" fetch -q --depth 1 --filter=blob:none origin "$sha" && \
        git -C "$top/$path" "${auth[@]}" -c advice.detachedHead=false checkout -q FETCH_HEAD || { echo "fetch of slaclab/$repo $sha failed"; return 1; }
        echo "SUBMODULEDIR/$path at $(git -C "$top/$path" rev-parse --short HEAD) ($sub)"
    done
    sed -i "s/ZmqServer(root=self, addr='127.0.0.1', port=10000)/ZmqServer(root=self, addr='127.0.0.1', port=0)/" \
        "$top/l2si-drp/firmware/python/l2si_drp/_Root.py"
}

daq() {
    local wd=${DAQ_SIM_CI_WORKDIR:-${RUNNER_TEMP:-/tmp}/daq_sim_ci}
    local events=${DAQ_SIM_CI_EVENTS:-1000}
    local procserv condabase rc_up=0 rc_cycle=0 rc_down=0
    procserv=$(command -v procServ) || { echo "procServ not on PATH (apt-get install procserv)"; return 2; }
    condabase=${CONDA_EXE:+$(dirname "$(dirname "$CONDA_EXE")")}
    [[ -f $condabase/etc/profile.d/conda.sh ]] || { echo "no conda base with etc/profile.d/conda.sh (CONDA_EXE=${CONDA_EXE:-unset})"; return 2; }
    mkdir -p "$wd"
    # procmgr start refuses to run without it (ProcMgr.py:964-967), and fakecam's drp imports
    # l2si-drp's python from it. On S3DF it names the site's firmware submodules (8 GB); here
    # it holds l2si-drp's python only. The unit tests run without it (their skips name it)
    export SUBMODULEDIR=${SUBMODULEDIR:-${RUNNER_TEMP:-/tmp}/lcls2_submodules}
    submodules "$SUBMODULEDIR" || return 2
    # procmgr's rcfile for this host, as procmgrd.s3df.conf is S3DF's (daq_sim reads DAQ_SIM_RCFILE)
    export DAQ_SIM_RCFILE=$wd.procmgrd.conf
    printf 'PORTBASE=29000\nPROCSERVBIN=%s\nCONDABASE=%s\n' "$procserv" "$condabase" > "$DAQ_SIM_RCFILE"
    echo "host $(hostname), $(nproc --all) CPUs, $(free -g | awk '/Mem:/{print $2}') GB; procServ $procserv; rcfile $DAQ_SIM_RCFILE:"
    cat "$DAQ_SIM_RCFILE"
    echo "$(hostname) resolves to: $(getent hosts "$(hostname)")"   # procmgr telnets procServ there
    [[ -n ${PSDAQ_SIM_CORRUPT_SEQ:-} ]] && echo "PSDAQ_SIM_CORRUPT_SEQ=$PSDAQ_SIM_CORRUPT_SEQ (deliberate break: one payload byte inverted)"

    # the teb and drp refuse to start below an unlimited MEMLOCK limit ("Inadequate MEMLOCK limit:
    # got 8388608, require -1", a runner's default); S3DF's nodes have it unlimited. RTPRIO stays
    # 0 there too, which they report and accept (RUNBOOK §6, harmless lines)
    if [[ $(ulimit -l) != unlimited ]]; then
        sudo -n prlimit --pid $$ --memlock=unlimited:unlimited || { echo "cannot raise MEMLOCK"; return 2; }
    fi
    echo "MEMLOCK $(ulimit -l), RTPRIO $(ulimit -r)"
    local t0=$SECONDS
    timeout -k 10 300 python -m psdaq.sim.daq_sim up -w "$wd" --detach; rc_up=$?
    echo "UP_EXIT=$rc_up ($((SECONDS - t0)) s)"
    if [[ $rc_up -eq 0 ]]; then
        t0=$SECONDS
        timeout -k 10 600 python -m psdaq.sim.daq_sim cycle -w "$wd" --events "$events"; rc_cycle=$?
        echo "CYCLE_EXIT=$rc_cycle ($((SECONDS - t0)) s)"
    fi
    timeout -k 10 180 python -m psdaq.sim.daq_sim down -w "$wd"; rc_down=$?
    echo "DOWN_EXIT=$rc_down"
    if [[ $rc_up -ne 0 || $rc_cycle -ne 0 || $rc_down -ne 0 ]]; then
        echo "=== logs (failure) ==="
        for f in "$wd"/logs/preflight.log "$wd"/logs/procmgr.log "$wd"/logs/simxpm.log; do
            [[ -f $f ]] && { echo "--- $f (last 60 lines)"; tail -n 60 "$f"; }
        done
        for f in $(find -L "$wd/pmlogs" -name '*.log' 2>/dev/null); do
            echo "--- $f (last 40 lines)"; tail -n 40 "$f"
        done
    fi
    [[ $rc_up -eq 0 && $rc_cycle -eq 0 && $rc_down -eq 0 ]]
}

case "${1:-}" in
    unit) unit ;;
    daq) daq ;;
    *) echo "usage: $0 unit|daq"; exit 2 ;;
esac
