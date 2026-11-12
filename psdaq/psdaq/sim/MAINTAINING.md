# Maintaining the hardware-free DAQ: bring upstream in, re-prove the sim

This is the one document to follow, start to end, to merge new upstream (slac-lcls/lcls2) work into
the fork's `sim-main` and prove the hardware-free DAQ (`psdaq/psdaq/sim`) still works. For depth,
each step names its section of [RUNBOOK.md](RUNBOOK.md); the known intermittent failures are in
[FLAKES.md](FLAKES.md).

Terms:
- **Full check**: `daq_sim matrix` over two milano nodes and a GPU node (step 10): every detector
  type, the programs run, the system features a-e and coverage. 201 assertions at def58eaf8.
- **Cheap tier**: the sim unit tests in CI on every pull request, plus one fakecam DAQ run on one
  S3DF node (step 8).
- **Deliberate breaks**: three runs with a known fault (`--break register|kill-drp|corrupt`) that
  must fail, to show the check can fail.

The runs quoted as expected output were at def58eaf8 (the merge of upstream 39afa18e3, 2026-11-11)
unless a step says otherwise.

## 1. Allocations (on sdfiana025)

Everything DAQ runs in Slurm steps of your own allocations; sdfiana025 is for git, editing and short
commands (`daq_sim up` refuses to run there). Never use a hutch or DAQ host. You need:

```bash
# two milano nodes in one job: the full check (step 10); also the cheap tier and subset (steps 8, 9)
salloc --no-shell --account=lcls:prjdat21 --qos=normal --partition=milano --exclusive \
       --nodes=2 --ntasks=2 --cpus-per-task=120 --time=1-00:00:00 --job-name=daq-sim-full
# one GPU slice on ada: the build (drp_gpu links against libcuda.so.1, which milano nodes lack)
# and the GPU DRP's types of the full check
salloc --no-shell --account=lcls:prjdat21 --qos=normal --partition=ada --gres=gpu:l40s:1 \
       --cpus-per-task=32 --mem=128G --time=1-00:00:00 --job-name=daq-sim-gpu
squeue -u $USER -o '%.10i %.12j %.8T %.20R'
```

A request can pend: the account has a node cap per partition, and squeue's reason then reads
`AssocGrpNodeLimit`. Wait, or release a job of yours you no longer need (`scancel <your job id>`).
Then name what you got (every later step uses these variables; export them in each new shell):

```bash
export JOB=<milano job id> GJOB=<ada job id>
read A B <<< "$(scontrol show hostnames $(squeue -j $JOB -h -o %N) | xargs)"
export A B G=$(squeue -j $GJOB -h -o %N)
echo "A=$A B=$B G=$G"
```

Check that G's GPU starts CUDA (a node whose GPU fails here, e.g. `cuInit` rc 999, cannot run the
GPU types; release it and take another):

```bash
srun --jobid=$GJOB --overlap -w $G --ntasks=1 --cpus-per-task=2 --mem=4G --gres=gpu:l40s:1 bash -c \
  "nvidia-smi --query-gpu=name,driver_version --format=csv,noheader; python3 -c \"import ctypes,time; t=time.time(); r=ctypes.CDLL('libcuda.so.1').cuInit(0); print('cuInit rc', r, round(time.time()-t, 2), 's')\""
# expected: NVIDIA L40S, 575.57.08 (or another driver)   then   cuInit rc 0 0.07 s
```

Always pass `--ntasks=1`, `--cpus-per-task` and `--mem` on every `srun` (without `--ntasks=1` a step
runs once per CPU; under `--exclusive` only the step's `--mem` binds). A step's processes die when the
step ends: anything long runs under `nohup ... &` with its output in a file you poll.

## 2. Workspace, caches, toolkit and one env file (once, on sdfiana025)

```bash
export ROOT=/sdf/data/lcls/ds/prj/<your project>/scratch/<you>/sim-maint   # a shared filesystem
mkdir -p $ROOT/work $ROOT/cache && cd $ROOT
export XDG_CACHE_HOME=$ROOT/cache/xdg UV_CACHE_DIR=$ROOT/cache/uv   # uv, pip, meson, conda hang less here
git clone git@github.com:carbonscott/lcls2.git && cd lcls2
git remote add upstream https://github.com/slac-lcls/lcls2.git && git fetch origin && git fetch upstream
```

The CUDA 12.x toolkit for drp_gpu (RUNBOOK §3h; ada's driver 575 runs CUDA 12.9 and refuses CUDA 13),
from conda-forge into a directory of your own:

```bash
export CUDA=$ROOT/tools/cuda-12.9
(cd $ROOT/lcls2 && source ./setup_env_daq.sh && \
 conda create -y -p $CUDA --override-channels -c conda-forge cuda-version=12.9 cuda-nvcc \
       cuda-cudart-dev cuda-cccl cuda-nvtx-dev libcufile-dev cuda-driver-dev cuda-profiler-api)
echo '{"cuda": {"name": "CUDA SDK", "version": "12.9"}}' > $CUDA/version.json
ln -s targets/x86_64-linux/lib $CUDA/lib64
ln -s . $CUDA/targets/x86_64-linux/include/cccl
```

The env file every DAQ step sources (the inputs of the last passing full checks; `$SUBMODULEDIR`
stays literal, `up --det tt|epixhr2x2` expands it):

```bash
cat > $ROOT/simenv.sh <<'EOF'
# source $ROOT/simenv.sh <checkout>: the env of a DAQ step (needs ROOT and CUDA exported)
cd "$1" || return 1
export XDG_CACHE_HOME=$ROOT/cache/xdg UV_CACHE_DIR=$ROOT/cache/uv PYTHONDONTWRITEBYTECODE=1
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export DAQ_SIM_CUDA_LIB=$CUDA/targets/x86_64-linux/lib
export PSDAQ_SIM_WAVE8PVS_ENV=/sdf/group/lcls/ds/ana/sw/conda2/inst/envs/ps-4.5.16
export PSDAQ_SIM_WAVE8PVS_SRC=/sdf/group/lcls/ds/ana/sw/source_files/wave8-1.0.1.tar.gz
export PSDAQ_SIM_PYTHONPATH_tt='$SUBMODULEDIR/lcls2-pgp-pcie-apps/firmware/submodules/surf/python'
H='$SUBMODULEDIR/lcls2-epix-hr-pcie/firmware'; E='$SUBMODULEDIR/epix-hr-single-10k'
export PSDAQ_SIM_PYTHONPATH_epixhr2x2="$H/python:$H/submodules/surf/python:$H/submodules/axi-pcie-core/python:$H/submodules/lcls2-pgp-fw-lib/python:$H/submodules/lcls-timing-core/python:$H/submodules/l2si-core/python:$E/firmware/python:$E/software/scripts:$E/firmware/submodules/epix-hr-core/python"
unset PSDAQ_SIM_PYTHONPATH          # every type's rogue_dev would read a plain one
export AMI=/sdf/group/lcls/ds/ana/sw/conda2/rel/ami_091526
export LOCK=/tmp/daq-$(hostname -s).lock     # this node's DAQ lock: every DAQ run here takes it
echo "=== $(hostname -s) job $SLURM_JOB_ID HEAD $(git rev-parse --short HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) $(date -u +%FT%TZ)"
EOF
export CUDA ROOT
```

`dirty` must print 0: a run is bound to the commit only when the checkout has no local change.

## 3. Trial merge (a scratch branch, never pushed)

See what a merge of upstream would do before making the real one:

```bash
cd $ROOT/lcls2 && git fetch origin && git fetch upstream
D=$(date -u +%F)
git worktree add $ROOT/wt-trial -b scratch/trial-$D origin/sim-main
cd $ROOT/wt-trial
echo "upstream commits not in sim-main: $(git log --oneline origin/sim-main..upstream/master | wc -l)"
git merge --no-commit --no-ff upstream/master; echo MERGE_EXIT=$?   # 0 clean or nothing to merge, 1 conflicts
git diff --name-only --diff-filter=U        # the conflicting files
git diff --cached --stat | tail -1          # size of what comes in
git rev-parse -q --verify MERGE_HEAD >/dev/null && git merge --abort    # only if a merge is in progress
cd $ROOT/lcls2 && git worktree remove $ROOT/wt-trial && git branch -D scratch/trial-$D
```

Never push a `scratch/*` branch. At the 2026-11-11 sync only `CHANGELOG.md` conflicted.

**Nothing to merge.** If the first line prints 0, upstream has nothing new: `git merge` prints
`Already up to date.` with `MERGE_EXIT=0`, the next two commands print nothing, and no merge is in
progress to abort (a plain `git merge --abort` would print `fatal: There is no merge to abort
(MERGE_HEAD missing)`, which is harmless). Then steps 4 and 5 have nothing to do: skip them and
test sim-main itself, from step 6 with the first-visit checkout.

## 4. Fast-forward the fork's master to upstream's

The fork's `master` mirrors slac-lcls/lcls2 `master` and moves only by fast-forward:

```bash
cd $ROOT/lcls2 && git fetch origin && git fetch upstream
git merge-base --is-ancestor origin/master upstream/master && echo FF-OK    # must print FF-OK
git push origin upstream/master:refs/heads/master                         # never --force
git fetch origin && git rev-parse origin/master upstream/master            # the same SHA twice
```

If `FF-OK` does not print, the fork's master has a commit upstream does not: stop and find out why.

## 5. The sync branch and the merge

Upstream comes in by a merge commit on a branch of its own, never by rebase:

```bash
D=$(date -u +%F); U=$(git -C $ROOT/lcls2 rev-parse --short upstream/master)
git -C $ROOT/lcls2 worktree add $ROOT/wt-sync -b sync/upstream-$D origin/sim-main
cd $ROOT/wt-sync
git merge --no-ff upstream/master -m "Merge upstream master ($U) into sim-main"; echo MERGE_EXIT=$?
```

On conflicts (`git diff --name-only --diff-filter=U`):
- `CHANGELOG.md`: keep both sides. Upstream's entries stay where upstream put them, sim-main's stay
  under `## [Unreleased]`; delete the conflict markers. `grep -c '^<<<<<<<\|^=======\|^>>>>>>>' CHANGELOG.md`
  must print 0.
- Any other file: keep both sides' changes. Take upstream's version of production code and re-apply
  the sim's edit on top (the sim's edits to upstream files are small, so this stays short); never drop
  an upstream change to make a sim test pass.
- Then `git add <files> && git commit --no-edit`, and list each conflicting file and how it was
  resolved in the pull request's description.

```bash
git log -1 --format='%h %p'      # two parents: sim-main's head and upstream's
git push origin sync/upstream-$D
gh pr create --repo carbonscott/lcls2 --base sim-main --head sync/upstream-$D \
   --title "Merge upstream master ($U) into sim-main"
```

Then steps 6 to 10 at the branch's head. Merge the pull request (`gh pr merge <n> --repo
carbonscott/lcls2 --merge`, a merge commit) only after its CI is green and the full check passed at
that same head; any later push to the branch needs a new full check. Afterwards
`git fetch origin && git merge-base --is-ancestor upstream/master origin/sim-main; echo $?` prints 0.

## 6. Build (on the ada node)

drp_gpu links against `libcuda.so.1`, which milano nodes do not have (`cannot find
/lib64/libcuda.so.1`, `BUILD_EXIT=1`), so build on G. The GPU subprojects are git wraps: fetch them on
sdfiana025 (compute nodes have no internet).

WT is the checkout under test. After a sync it is step 5's worktree: `export WT=$ROOT/wt-sync`.
On a first visit, or when step 3 found nothing to merge, it is a detached worktree of sim-main
(no branch, nothing to push):

```bash
git -C $ROOT/lcls2 fetch origin
git -C $ROOT/lcls2 worktree add --detach $ROOT/wt-main origin/sim-main
export WT=$ROOT/wt-main
git -C $WT log -1 --format='%h %s'     # the commit every later step reports as HEAD
```

On a later visit, move it to the new sim-main with `git -C $WT checkout --detach origin/sim-main`
after a fetch. Then build:

```bash
(cd $WT && source ./setup_env_daq.sh && meson subprojects download lc pfpl sleek)
nohup srun --jobid=$GJOB --overlap -w $G --ntasks=1 --cpus-per-task=32 --mem=120G --gres=gpu:l40s:1 bash -c \
  "cd $WT && source ./setup_env_daq.sh && export CUDA_ROOT=$CUDA PATH=\$PATH:$CUDA/bin && ./build_all.sh -d -j 32; echo BUILD_EXIT=\$?" \
  > $ROOT/work/build.log 2>&1 &
tail -f $ROOT/work/build.log        # until BUILD_EXIT
ls $WT/install/bin/{drp,drp_gpu,teb,control}
```

Expected: `BUILD_EXIT=0` (minutes the first time; 28 s for an incremental one), and the four files
exist. The milano nodes run the same `install/` from the shared filesystem. `warning: Failed to
hardlink files; falling back to full copy` is harmless.

## 7. Sim unit tests (on S3DF)

Every `psdaq/psdaq/tests/test_sim*.py`, by glob, in the isolation env (without `sim_env.sh` sourced,
a test that calls `daq_sim.main` re-executes itself and replaces pytest):

```bash
srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=8 --mem=16G bash -c '
  source $ROOT/simenv.sh $WT && export PATH=$WT/install/bin:$PATH QT_QPA_PLATFORM=offscreen &&
  pyver=$(python -V 2>&1 | grep -oP "\d+\.\d+" | head -1) &&
  export PYTHONPATH=$WT/install/lib/python$pyver/site-packages:$PYTHONPATH &&
  files=(psdaq/psdaq/tests/test_sim*.py); echo "files ${#files[@]}" &&
  pytest -rs -p no:cacheprovider "${files[@]}"; echo PYTEST_EXIT=$?' > $ROOT/work/ut.log 2>&1
tail -4 $ROOT/work/ut.log
```

Expected: `0 failed`, `PYTEST_EXIT=0`; at def58eaf8, 16 files, `421 passed, 1 skipped` (skip:
`could not import 'ami'`). A skip for any other reason is a finding.

CI (step 8) is the authoritative run of the unit tier; this S3DF run is a second look, on nodes that
can be slow (FLAKES.md F9 is a timing test that fails there). When a test fails here and passes in CI,
tell an environment failure from a regression: rerun that one test (`pytest -rs -p no:cacheprovider
<file>::<test>`) on the same node at the same time in a built checkout of sim-main (step 6's
`wt-main`). Failing there too: the environment (or an older defect), not the change; register it.
Passing at sim-main and failing at the head: a regression of the change.

## 8. The cheap tier

**In CI (every pull request to sim-main).** `.github/workflows/sim_cheap_tier.yaml` builds the tree
on a GitHub-hosted runner and runs `bash psdaq/psdaq/sim/ci_cheap_tier.sh unit`: every
`psdaq/psdaq/tests/test_sim*.py` found by glob. Its log prints `sim test files collected: <n>` and
ends with e.g. `412 passed, 10 skipped` (at 946ef0ff1; skips name `needs $SUBMODULEDIR (the DAQ env)`
or `could not import 'ami'`), in about 7-10 min. Read it with `gh pr checks <n> --repo
carbonscott/lcls2` and `gh run view <run id> --repo carbonscott/lcls2 --log | grep -E 'collected|passed|SKIPPED|FAILED'`.

**The DAQ part, on one S3DF node.** The fakecam DAQ run is not on GitHub's runners: fakecam's drp
imports `l2si_drp` (`psdaq/psdaq/configdb/xpmdet_config.py`) from slaclab/l2si-drp, which is
SLAC-internal. It runs on one node, no GPU, in a few minutes (well under 15):

```bash
srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=16 --mem=32G bash -c '
  source $ROOT/simenv.sh $WT && W=$ROOT/work/cheap-$(date -u +%m%dT%H%M) && mkdir -p $W-ev && t0=$(date +%s) &&
  daq_sim matrix -w $W --only types --types fakecam --lock $LOCK --evidence $W-ev; echo "MATRIX_EXIT=$? in $(( $(date +%s)-t0 )) s";
  daq_sim matrix -w $W --break corrupt --lock $LOCK; echo MATRIX_EXIT=$?' > $ROOT/work/cheap.log 2>&1
grep -E '^TYPE|^FAILED|^MATRIX' $ROOT/work/cheap.log
```

Expected, the run (exit 0; N at least 1000, typically 1800-2200 at 1 kHz, the same three times):
```
TYPE fakecam      node <A> job <JOB> run <W>/types/fakecam/data/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2 DAQ <N> psana2 <N> with-data <N> per-event PASS PASS
TYPE fakecam      (the same line again)
MATRIX PASS (7 assertions)
MATRIX_EXIT=0 in <s> s
```
and the corrupted byte (exit 1):
```
TYPE fakecam      node <A> ... run <W>/break-corrupt/types/fakecam/... DAQ <N> psana2 <N> with-data <N> per-event FAIL FAIL
TYPE fakecam      (the same line again)
FAILED types/fakecam/per-event: xtc2_check --det fakecam: FAIL ['event 500: payload pattern broken: 1 of 60 payload words differ, ...']
FAILED types/fakecam/evidence: no evidence record for det:drp:fakecam (the cycle failed)
MATRIX FAIL (2 of 7 assertions failed)
MATRIX_EXIT=1
```

**Reading a run's output (steps 8 to 10).** `daq_sim matrix` prints each `TYPE`/`PROGRAMS` line
when that run ends and again in its summary, under `==== MATRIX SUMMARY`: the same result twice,
not two runs. The summary also prints `whole matrix at this HEAD (with carried results): ...`, the
state of the whole matrix given only what this work dir holds. A partial run (steps 8 and 9, the
breaks) prints `FAIL; not run: types/cspad ... programs coverage; failed:
types/det:drp_gpu:<type>/runnable ...` there (without `--gpu-host`, the five GPU DRP types the
coverage status marks RUN count as not runnable): expected, not a failure of this run. The verdict
of what a command ran is its exit code (`MATRIX_EXIT`) and its `MATRIX PASS|FAIL` line; only the
full check (step 10) must also print `whole matrix ...: PASS`.

## 9. First run: a subset smaller than the full check

On a first visit, before the full check, prove three detector types and the programs run on one node:

```bash
srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=16 --mem=32G bash -c '
  source $ROOT/simenv.sh $WT && W=$ROOT/work/first-$(date -u +%m%dT%H%M) && mkdir -p $W-ev &&
  daq_sim matrix -w $W --only types --types fakecam,epix100,opal --lock $LOCK --evidence $W-ev; echo MATRIX_EXIT=$?;
  daq_sim matrix -w $W --only programs --ami-src $AMI --lock $LOCK --evidence $W-ev; echo MATRIX_EXIT=$?' > $ROOT/work/first.log 2>&1
grep -E '^TYPE|^PROGRAMS|^FAILED|^MATRIX' $ROOT/work/first.log
```

Expected: three `TYPE` lines (fakecam, epix100, opal), each `DAQ <N> psana2 <N> with-data <N>
per-event PASS PASS` with the three counts of a line equal and N >= 1000 (N differs between types),
then the same three lines again (the summary, see step 8), `MATRIX PASS (21 assertions)`,
`MATRIX_EXIT=0`; then `PROGRAMS fakecam ... DAQ <N> psana2 <N> with-data <N> per-event PASS PASS`
twice, `MATRIX PASS (8 assertions)`, `MATRIX_EXIT=0` (the types take about 3 min, the programs run
about 5 min). Each command's exit code is the verdict of what it ran; its `whole matrix ...: FAIL`
line is expected (step 8).

## 10. The full check

**Pre-flight (before every full check).** A full check on slow nodes can fail for reasons that are
not the code's (FLAKES.md F7, F8). Probe A, B and G first, keep the lines with the run, and do not
start the check while a probe is more than 2x its baseline. A run not started is not an attempt; a
run started is always listed, whatever its end. The gate (below) is these probes plus a
sentinel. The probe, once:

```bash
cat > $ROOT/probe.sh <<'EOF'
#!/bin/bash
# probe.sh: one line about this node (in a step on A, B or G; needs ROOT and WT exported)
F=$ROOT/work/probe-1G.bin; [ -s $F ] || dd if=/dev/urandom of=$F bs=4M count=256 status=none
cd $WT && source ./setup_env_daq.sh >/dev/null 2>&1
others=$(ps -e -o uid= | awk -v me=$(id -u) '$1>=1000 && $1!=me' | wc -l)    # other users' processes
t0=$(date +%s.%N); python -c "import psana, psdaq.control"; t1=$(date +%s.%N)
dd_s=$(dd if=$F of=/dev/null bs=4M iflag=direct 2>&1 | tail -1 | awk -F, '{print $(NF-1)}' | awk '{print $1}')
cu=$(python -c "import ctypes,time; t=time.time(); r=ctypes.CDLL('libcuda.so.1').cuInit(0); print('%.3f rc%d' % (time.time()-t, r))" 2>/dev/null || echo none)
echo "PROBE $(hostname -s) $(date -u +%FT%TZ) load $(cut -d' ' -f1-3 /proc/loadavg) others $others import_s $(echo "$t1 - $t0" | bc) dd_s $dd_s cuinit_s $cu"
EOF
export WT ROOT
for n in $A $B; do srun --jobid=$JOB --overlap -w $n --ntasks=1 --cpus-per-task=2 --mem=4G bash $ROOT/probe.sh; done
srun --jobid=$GJOB --overlap -w $G --ntasks=1 --cpus-per-task=2 --mem=4G --gres=gpu:l40s:1 bash $ROOT/probe.sh
```

and one fakecam try: step 8's first command, on A (its `MATRIX_EXIT=0 in <s> s`). The baselines,
medians of 14 probes and 10 fakecam tries on an ada node, 2026-11-11 19:00-19:32Z:

| probe | baseline | do not start above |
|---|---|---|
| `import_s` (`import psana, psdaq.control` from the build) | 2.89 s | 5.8 s |
| `dd_s` (the 1 GB file, `O_DIRECT` read) | 0.69 s | 1.4 s |
| `cuinit_s` (G only; `none` on milano) | 0.083 s | 0.17 s |
| fakecam try, wall | 63 s | 126 s |

`load` and `others` have no gate; write them down (that day: load1 median 15, others median 140).
Probe again before each run of a series (step 11).

A probe taken once misses short stalls of a whole node (seconds in which a process is frozen or a
file lookup on the shared filesystems hangs; FLAKES.md F11). So keep one sentinel per node (A, B, G)
running for the whole series, each in a step of its own (it holds no lock and starts no DAQ
process). It writes about one line a second, with millisecond times, to
`$ROOT/work/sentinel/<node>.log`:

```bash
mkdir -p $ROOT/work/sentinel
cat > $ROOT/sentinel.sh <<'EOF2'
#!/bin/bash
# sentinel.sh: about once a second, one line to $D/<node>.log (D defaults to $ROOT/work/sentinel):
#   <UTC time, ms>Z group_stat=<s> tmp_stat=<s> root_stat=<s> sleep_over=<s> prev_write=<s>
#   group_stat: os.stat() of a conda file under /sdf/group; tmp_stat: of a file under /tmp;
#   root_stat: of this script, a file under $ROOT (/sdf/data); sleep_over: how far sleep(1) overran;
#   prev_write: writing and flushing the previous line (the log is under $ROOT too).
# A stat that raises prints ERR:<name> in place of its time.
# Stops when $D/STOP or $D/STOP.<node> exists (checked every line), or when the step ends.
D=${SENT_DIR:-$ROOT/work/sentinel}
exec /usr/bin/python3 -u - "$D" "$(hostname -s)" "$(readlink -f "$0")" <<'PY'
import os, sys, time, datetime
D, node, F = sys.argv[1:4]
G = '/sdf/group/lcls/ds/ana/sw/conda2/inst/envs/daq_20250402_r9/bin/python3.9'
T = '/tmp/sentinel-%s.touch' % node
open(T, 'a').close()
log = open(os.path.join(D, node + '.log'), 'a', buffering=1)
stops = [os.path.join(D, 'STOP'), os.path.join(D, 'STOP.' + node)]
def tstat(p):
    t0 = time.monotonic()
    try:
        os.stat(p)
    except OSError as e:
        return 'ERR:' + e.__class__.__name__
    return '%.4f' % (time.monotonic() - t0)
def utc():
    return datetime.datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'
log.write('# sentinel start node=%s pid=%d group_file=%s tmp_file=%s root_file=%s\n' % (node, os.getpid(), G, T, F))
pw = 0.0
while True:
    if any(os.path.exists(s) for s in stops):
        log.write('# sentinel stop file seen %s\n' % utc()); break
    now = utc(); g, t, r = tstat(G), tstat(T), tstat(F)
    s0 = time.monotonic(); time.sleep(1); so = time.monotonic() - s0 - 1.0
    w0 = time.monotonic()
    log.write('%s group_stat=%s tmp_stat=%s root_stat=%s sleep_over=%.4f prev_write=%.4f\n' % (now, g, t, r, so, pw))
    pw = time.monotonic() - w0
PY
EOF2
export ROOT; rm -f $ROOT/work/sentinel/STOP*
for n in $A $B; do nohup srun --jobid=$JOB --overlap -w $n --ntasks=1 --cpus-per-task=1 --mem=256M bash $ROOT/sentinel.sh > /dev/null 2>&1 & done
nohup srun --jobid=$GJOB --overlap -w $G --ntasks=1 --cpus-per-task=1 --mem=256M bash $ROOT/sentinel.sh > /dev/null 2>&1 &
```

To stop one node's sentinel, `touch $ROOT/work/sentinel/STOP.<node>`; to stop all of them,
`touch $ROOT/work/sentinel/STOP`. Each sees the file within about a second, writes `# sentinel stop
file seen <time>` and exits, which ends its step. Remove the STOP files before the next series.

This is the sentinel that ran from 2026-11-11 22:55:56Z (`work/sentinel/sentinel.sh` of the campaign
root: the same /sdf/group and /tmp files, fields, millisecond times, log and stop files) with one field
added, `root_stat`. That one did not time a file under $ROOT: its only lookup there was the
untimed check for the STOP files, and the 18 same-second stalls recorded on three nodes that night
(2.8-5.1 s, FLAKES.md F11) showed only as gaps between lines, with every timed field at most 0.04 s.
So the gate reads the gaps between lines as well as the fields:

```bash
# the gate's sentinel half, per node: over the last 15 min, the largest field, the largest gap between
# consecutive lines, ERR count and the age of the last line; OK only if field <= 3 s, gap <= 4 s, no ERR, age <= 60 s
for n in $A $B $G; do tail -n 2000 $ROOT/work/sentinel/$n.log | python3 -c '
import sys, datetime
node = sys.argv[1]; now = datetime.datetime.now(datetime.timezone.utc).timestamp()
mx = gap = 0.0; err = nl = 0; prev = last = None
for L in sys.stdin:
    f = L.split()
    if L.startswith("#") or len(f) < 4: continue
    t = datetime.datetime.strptime(f[0], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=datetime.timezone.utc).timestamp()
    last = t
    if now - t <= 900:
        nl += 1
        if prev is not None: gap = max(gap, t - prev)
        for kv in f[1:]:
            v = kv.split("=")[1]
            if v.startswith("ERR"): err += 1
            else: mx = max(mx, float(v))
    prev = t
age = now - last if last else 1e9
ok = nl > 0 and mx <= 3 and gap <= 4 and err == 0 and age <= 60
print("SENT %s lines15=%d max_field=%.3f max_gap=%.2f err=%d last_age=%.0fs %s" % (node, nl, mx, gap, err, age, "OK" if ok else "SHUT"))
' $n; done
```

A line normally follows the one before it by 1.0-1.1 s (the sleep plus the stats); a gap of more
than 4 s means about 3 s in which the loop was stalled somewhere it does not time.

**The gate before each full check.** Start a run only when every probe is under its "do not start
above" value (within 2x of its baseline) and every node's sentinel line above says `OK`. Write the
gate's lines down with the run. The gate is a precaution; it has not been shown to lower the odds,
and it does not protect: on 2026-11-11 a gate passed at about 22:10Z (the probes alone, `PROBE`
lines at 22:10:42Z and 22:13:11Z; no sentinel ran before 22:55:56Z) and F11 hit the run started
after it at 22:21Z.

The one command (RUNBOOK §3p, "Everything, over every node of the campaign"), in a step on A: the
types shared between A and B (each under its node's lock), the GPU DRP's types on G, the programs
run and features a, b, c, e on A, d over both, then coverage over all of their evidence. Write it
as a script once:

```bash
cat > $ROOT/mx.sh <<'EOF'
#!/bin/bash
# mx.sh TAG: the full check at $WT's HEAD over $A,$B (job $JOB) and $G (job $GJOB); a fresh dir per TAG
TAG=$1; source $ROOT/simenv.sh $WT || exit 9
W=$ROOT/work/mx-$TAG; EV=$W-ev
[ -e $W ] && { echo "$W exists: take a new TAG"; exit 2; }
mkdir -p $EV
echo "=== full check $TAG on $(hostname -s) job $SLURM_JOB_ID gpu $G job $GJOB $(date -u +%FT%TZ)"
daq_sim matrix -w $W --hosts $A,$B --locks /tmp/daq-$A.lock,/tmp/daq-$B.lock \
  --gpu-host $G --gpu-job $GJOB --gpu-gres gpu:l40s:1 --gpu-lock /tmp/daq-$G.lock \
  --ami-src $AMI --evidence $EV --lock-timeout 5400
echo "MATRIX_EXIT=$? $(date -u +%FT%TZ)"
EOF
export WT A B G JOB GJOB ROOT CUDA
nohup srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=16 --mem=32G \
  bash $ROOT/mx.sh c1 > $ROOT/work/mx-c1.log 2>&1 &
```

Every run gets a new TAG, so a new work dir and a new evidence dir: a reused one would carry
earlier results (`"carried": true` in the summary). The run takes 25-40 min (one run took 38 min
in a slow period). Poll `grep -E '^(TYPE|PROGRAMS|FAILED|MATRIX)' $ROOT/work/mx-c1.log`
(A's 11 types and the programs run print a line as each ends; B's and G's lines are prefixed
`[<host>]` until the summary). When it has ended, read the summary only:

```bash
sed -n '/^==== MATRIX SUMMARY/,$p' $ROOT/work/mx-c1.log | grep -E '^(TYPE|PROGRAMS|FEATURE|coverage:|whole|FAILED|MATRIX)'
```

Expected: 21 `TYPE <type> node <A or B>` lines (11 on A, 10 on B), 5 `TYPE drp_gpu:<type> node <G>`
lines, one `PROGRAMS` line, `FEATURE a PASS` .. `FEATURE e PASS`, then

```
coverage: at <HEAD>: 78 rows, 63 run, 6 stand-in, 9 N/A, 0 unproven, 0 claimed without valid evidence
whole matrix at this HEAD (with carried results): PASS
MATRIX PASS (201 assertions)
MATRIX_EXIT=0 <time>
```

(`MATRIX_EXIT` comes from `mx.sh`, after the summary.) A different assertion or coverage row count after a sync must be traced to
an upstream commit (a type or program added or removed) before the run counts.

**The three deliberate breaks**, each its own command and each must exit 1 (on A, after the check):

```bash
nohup srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=16 --mem=32G bash -c '
  source $ROOT/simenv.sh $WT && W=$ROOT/work/brk-$(date -u +%m%dT%H%M)
  for k in register kill-drp corrupt; do
    daq_sim matrix -w $W --break $k --lock $LOCK --lock-timeout 5400 > $W-$k.log 2>&1
    echo "BREAK $k exit $?: $(grep -E "^MATRIX (PASS|FAIL)" $W-$k.log | tail -1)"; grep "^FAILED " $W-$k.log
  done' > $ROOT/work/brk.log 2>&1 &
```

Expected: `BREAK register exit 1: MATRIX FAIL (5 of 7 assertions failed)` (`epix100_0 did not respond
to configure`), `BREAK kill-drp exit 1: MATRIX FAIL (5 of 7 assertions failed)`, or 4 of 7 (`fakecam_0 drp pid
... GONE after the run`; either count is the break failing as it must), `BREAK corrupt exit 1: MATRIX FAIL (2 of 7 assertions failed)` (`event 500:
payload pattern broken`).

**Coverage on its own**, over the full check's evidence:
```bash
srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=4 --mem=8G bash -c \
  'source $ROOT/simenv.sh $WT && daq_sim coverage --evidence $ROOT/work/mx-c1-ev; echo COV_EXIT=$?' > $ROOT/work/cov.log 2>&1
tail -4 $ROOT/work/cov.log
```
Expected: `78 rows, 63 run, 6 stand-in, 9 N/A, 0 unproven, 0 claimed without valid evidence`, then
the status file's claims, then `PASS` and `COV_EXIT=0` (at def58eaf8).

## 11. When a run fails, and when to rerun what

A failed run is read, not retried. Never rerun a check until it passes: every run you start stays in
the record, failed or not.

**Cut short by the infrastructure** means the run never reached its `MATRIX PASS|FAIL` summary line
because of a node failure, the Slurm job's time limit, a cancelled allocation or an OOM kill. Only
such a run counts neither way, with its cause written down (e.g. `sacct -j <job> -o
JobID,State,ExitCode,Elapsed`, the node's or the OOM killer's message). A run that completes with
`MATRIX FAIL` because the node was slow is a failure, not a cut: the pre-flight (step 10) is there so
that such a run is not started.

**A series** (several full checks at one commit, to show it repeats): stop the series at the first
`MATRIX FAIL`. That run gets a register row, or adds to its row's counts (below); the commit cannot
be the one the series proves, and a fix is a new commit with a new series. Never move the commit the
proofs are bound to (H) to a child that changes only `.md` files to escape a failure: the code is
the same, so the failed run stands against the child too.

1. List what failed: `grep '^FAILED ' <the run's log>` (or step 12's one-liner on
   `matrix-summary.json`). Each line is `FAILED <section>/<name>/<assertion>: <why>`.
2. For each failed type or section, open its DRP and teb0 pmlogs (step 12) and find the first
   error line.
3. Look that line up in [FLAKES.md](FLAKES.md) (the symptom column). The row's verdict says what to
   do; no verdict excuses the failure:
   - FIXED / FIXED-UPSTREAM: should not happen any more. Reopen the row and rerun its reproducer at
     this commit; for FIXED-UPSTREAM check the named commit is still an ancestor of HEAD.
   - REPORTED: a known production bug; find its trigger in the logs (F2: which DRP's Configure ran
     past control's 60 s, and why) and add the run to the row's k/n and to its issue.
   - NOT-REPRODUCED or pending: new evidence; add the run's conditions and rate to the row and
     decide the verdict again.
   - no row: add one (FLAKES.md, "How to add a row").
4. F3 (a double free or a segfault at shutdown) is in nearly every DRP log after `Shutting down on INT
   signal`; it has never failed an assertion. Do not stop at it: look for the first error before it.

**Preflight exit 4** (`PREFLIGHT FAIL: probe hung (not a leak verdict, not an EPICS verdict)`). Each
DAQ start runs `psdaq/psdaq/sim/preflight.sh` first. Since F11's fix, a probe killed by its outer
timeout prints `HUNG: <probe> killed by its <N> s outer timeout (attempt <i>)` and runs once more;
exit 4 means a probe hung again, or hung after the 2 re-runs a preflight allows. Nothing was
started, and it is not a leak or EPICS verdict (those stay exit 1 and exit 3, read at the first
attempt). In a full check it shows as a `FAILED` line with `preflight rc=4` and the run ends `MATRIX
FAIL`: a failed run (F11's row), not a cut. Stop the series, compare the `HUNG` times
(`grep -n HUNG <the DAQ's dir>/logs/preflight.log`) with the sentinel lines, and start no run until
the gate is open again.

A preflight failure takes two other forms in a full check:
- `up FAILED: Command ... timed out after 240 seconds`, with no `preflight rc=` line: the preflight
  as a whole ran past `daq_sim up`'s 240 s (a stall outside the probes, which the 223 s bound of the
  probes does not cover). `daq_sim up` then tears down what carries the work dir's tag and starts
  nothing. A failed run, not a cut.
- `preflight rc=1` with `LEAK: p4p got ... (or probe broke)` in `preflight.log` and a traceback
  ending `RuntimeError: Unable to bind random UDP6 port` before it: the p4p probe could not make its
  client context (FLAKES.md F12), not a leak. A failed run all the same. Any other `LEAK:` line
  is a real leak verdict: stop everything and find what reached the facility service.

What to run after what:

| after | run |
|---|---|
| a sync (step 5) | build (6), unit tests (7), the cheap tier (8: CI on the pull request and the S3DF run with its corrupt break), the full check, the three breaks and coverage (10) at the sync head, before the merge |
| a sim change (`psdaq/psdaq/sim`, the sim parts of the drp) | build, unit tests, cheap tier; the types or sections it touches (`daq_sim matrix -w <new dir> --types <T>` or `--only <section>`); the full check before it merges if it touches anything the full check runs |
| a production (non-sim) change | the same command at the base and at the head (the row's reproducer, or the affected types), so the change shows as the difference; then the full check at the head |
| a change to `.md` files only | nothing: the last full check still stands for the code |
| a failed full check | the list above; a fix is a new commit, which needs its own full check |

## 12. Where the logs are and how to read a failure

A full check's work dir `W` (`$ROOT/work/mx-<TAG>`) holds:
- `W/matrix-summary.json`: `sha`, `dirty`, `exit`, `whole` (`pass`, `failed`, `missing`), every
  assertion (`name`, `ok`, `detail`), the runs. List the failures with
  `python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['sha'], d['exit'], d['whole']); [print(a['name'], '|', a['detail']) for a in d['assertions'] if not a['ok']]" W/matrix-summary.json`
- `W/types/<T>/` (A's types), `W/hosts/<B>/types/<T>/` (B's), `W/gpu/<G>/types/<T>/` (the GPU
  DRP's), `W/programs/`, `W/features/<x>/`: one DAQ's work dir each, with
  - `pmlogs/<yyyy>/<mm>/<dd_HH:MM:SS>_<host>:<id>.log`: each process's procServ log (`<T>_0` the
    DRP, `teb0`, `control`); times in them are local (US Pacific);
  - `logs/`: `procmgr.log`, `simxpm.log` (transitions, `NumL0Acc`), `cycle.jsonl`, `configdb.log`,
    `preflight.log`;
  - `data/tst/tstx00001/xtc/`: the recorded xtc2 file.
- the run's log (`$ROOT/work/mx-<TAG>.log`): the `TYPE`/`PROGRAMS` lines, each assertion, the
  `FAILED` lines and `MATRIX PASS|FAIL`.

**The sim drps' TEB pending depth (F1's fix, PR #52).** `daq_sim` gives every `drp -d sim://` the
kwarg `tebPendingDepth`, twice its pebble count rounded up to a power of 2
(`teb_pending_depth` in `psdaq/psdaq/sim/daq_sim.py`), so TebContributor's queue of posted batches
has room beyond the pebbles. drp accepts the kwarg only with `-d sim://` (`psdaq/drp/drp.cc`);
production defaults are unchanged. Each sim drp's pmlog shows it as
`tebPendingDepth <N> (numBuffers <M>)` (e.g. opal `tebPendingDepth 256 (numBuffers 128)`), and its
`-k` on the `# CMDLINE:` line. A `_pending queue overflow` in a sim drp whose log lacks that line
means the kwarg was not passed; with the line, it is F1 coming back (FLAKES.md).

To find a register symptom in a failed run (F8's is in the run's own log):
`grep -rn -E '_pending queue overflow|FATAL: Segmentation Fault|Uncaught exception|hasn.t connected|TimeoutExpired|RuntimeError: Unable to bind|Future already retrieved|pvwait: timeout|ami_count' W $ROOT/work/mx-<TAG>.log --include='*.log' | head`
(remember F3's shutdown lines appear in nearly every DRP log). `daq_sim: PVA client context: Unable to
bind random UDP6 port (attempt <n> of 10), retrying` is benign, F6's fix absorbing the race; only
`RuntimeError: Unable to bind` is F6. F9 is in the unit tests' log: `grep -n 'assert 200 <='
$ROOT/work/ut.log`. RUNBOOK §6 lists the expected and
the harmless lines of a DAQ's logs.
