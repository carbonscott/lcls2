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
git merge --no-commit --no-ff upstream/master; echo MERGE_EXIT=$?   # 0 clean, 1 conflicts
git diff --name-only --diff-filter=U        # the conflicting files
git diff --cached --stat | tail -1          # size of what comes in
git log --oneline origin/sim-main..upstream/master | wc -l    # upstream commits not yet in sim-main
git merge --abort
cd $ROOT/lcls2 && git worktree remove $ROOT/wt-trial && git branch -D scratch/trial-$D
```

Never push a `scratch/*` branch. At the 2026-11-11 sync only `CHANGELOG.md` conflicted.

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
sdfiana025 (compute nodes have no internet). WT is the checkout under test (`$ROOT/wt-sync` here).

```bash
export WT=$ROOT/wt-sync
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

Expected, the run (exit 0; N at least 1000, about 1900-2100 at 1 kHz, the same three times):
```
TYPE fakecam      node <A> job <JOB> run <W>/types/fakecam/data/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2 DAQ <N> psana2 <N> with-data <N> per-event PASS PASS
MATRIX PASS (7 assertions)
MATRIX_EXIT=0 in <s> s
```
and the corrupted byte (exit 1):
```
FAILED types/fakecam/per-event: xtc2_check --det fakecam: FAIL ['event 500: payload pattern broken: 1 of 60 payload words differ, ...']
FAILED types/fakecam/evidence: no evidence record for det:drp:fakecam (the cycle failed)
MATRIX FAIL (2 of 7 assertions failed)
MATRIX_EXIT=1
```

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
per-event PASS PASS` with equal N >= 1000, `MATRIX PASS (21 assertions)`, `MATRIX_EXIT=0`; then
`PROGRAMS fakecam ... DAQ <N> psana2 <N> with-data <N> per-event PASS PASS`, `MATRIX PASS (8
assertions)`, `MATRIX_EXIT=0` (the programs run takes about 5 min). Each command's exit code is the
verdict of what it ran.

## 10. The full check

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
earlier results (`"carried": true` in the summary). The run takes 24-33 min (seven full checks
2026-11-09 to 2026-11-11). Poll `grep -E '^(TYPE|PROGRAMS|FAILED|MATRIX)' $ROOT/work/mx-c1.log`.
Expected end:

```
coverage: at <HEAD>: 78 rows, 63 run, 6 stand-in, 9 N/A, 0 unproven, 0 claimed without valid evidence
MATRIX PASS (201 assertions)
MATRIX_EXIT=0 <time>
```

with 21 `TYPE <type> node <A or B>` lines (11 on A, 10 on B), 5 `TYPE drp_gpu:<type> node <G>`
lines, one `PROGRAMS` line and `FEATURE a PASS` .. `FEATURE e PASS`. A different assertion or coverage row count after a sync must be traced to
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
to configure`), `BREAK kill-drp exit 1: MATRIX FAIL (5 of 7 assertions failed)` (`fakecam_0 drp pid
... GONE after the run`), `BREAK corrupt exit 1: MATRIX FAIL (2 of 7 assertions failed)` (`event 500:
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
the record, failed or not. Only a run cut short by the infrastructure (node failure, the job's time
limit, a cancelled allocation) counts neither way, with its cause written down.

1. List what failed: `grep '^FAILED ' <the run's log>` (or step 12's one-liner on
   `matrix-summary.json`). Each line is `FAILED <section>/<name>/<assertion>: <why>`.
2. For each failed type or section, open its DRP and teb0 pmlogs (step 12) and find the first
   error line.
3. Look that line up in [FLAKES.md](FLAKES.md) (first column: symptom). The row's verdict says what to
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

To find a register symptom in a failed run:
`grep -rn -E '_pending queue overflow|FATAL: Segmentation Fault|Uncaught exception|hasn.t connected|TimeoutExpired' W --include='*.log' | head`
(remember F3's shutdown lines appear in nearly every DRP log). RUNBOOK §6 lists the expected and
the harmless lines of a DAQ's logs.
