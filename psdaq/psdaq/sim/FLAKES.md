# Flake register of the hardware-free DAQ

One row per intermittent failure seen in the full check (`daq_sim matrix` over two milano nodes and a
GPU node, RUNBOOK §3p) or in one of its parts (a type run, the programs run, a feature, a DAQ's
shutdown). Each row says what the failure looks like, what is known of its cause, how often it was
seen, and what was done about it. How to use it when a run fails: MAINTAINING.md, step 11.

Status at H = TBD. H is the commit the final proofs are bound to: sim-main's HEAD, or an ancestor of
it that differs from it only in `.md` files and files outside `psdaq/`, `psana/` and
`xtcdata/xtcdata/`. Counts as of 2026-11-11. Commits: base 96ba26676 (sim-main before the sync);
sync head def58eaf8 (upstream 39afa18e3, the merge of upstream PR #300, merged in; merged into
sim-main as d4e2217e0); 946ef0ff1 (sim-main after the cheap tier, PR #49); cee776d3c (F1's fix,
PR #52). Line numbers are at upstream 39afa18e3 unless a cell names a fork commit.

## Verdicts

| verdict | what it takes |
|---|---|
| FIXED | Cause named by file and line; the failure reproduced k times in n tries before the fix and 0 times in m tries after, with m at least 10 and (1 - k/n)^m below 0.05; base against head shown when production code changes. |
| FIXED-UPSTREAM | The same numbers, naming the upstream commit that fixed it. |
| REPORTED | A cause, or a reproducer with its rate, not fixed here, written up as a draft issue on carbonscott/lcls2 in upstream's bug template (`.github/ISSUE_TEMPLATE/bug_report.yml`), its number printed (last column). |
| NOT-REPRODUCED | The conditions tried, matching the original failure's detector type, node load and rate as far as known, and the try count: at least 100 runs of the affected kind for F1 and at least 30 for any other row, at H or after the sync. |
| pending | No verdict yet: the numbers so far and the planned verdict. Allowed only until the final commit (the one H is set at); at H every row has one of the four verdicts above. |

(1 - k/n)^m is the chance that a failure with the rate seen before the fix would have missed all m
tries after it. Below 0.05, the m clean tries are unlikely to be luck.

**What a verdict means for a failed full-check run.** No row excuses a failure. A full check that
ends `MATRIX FAIL` at a commit is a failed run at that commit, whatever row it matches; only a run
cut short by the infrastructure (a node failure, the job's time limit, a cancelled allocation)
counts neither way, and its cause is written down. The row a `FAILED` line matches tells the
maintainer what to look for and what to rerun:

- FIXED or FIXED-UPSTREAM: the failure should no longer happen. A match means the fix regressed or
  the cause was wrong: reopen the row (verdict back to pending), rerun the row's reproducer
  (below) at the failing commit, and for FIXED-UPSTREAM check the upstream commit is still an
  ancestor (`git merge-base --is-ancestor <commit> HEAD; echo $?`, 0).
- REPORTED: a known production bug with a known trigger. A match is expected only when the trigger
  happened; find the trigger in the logs (for F2: which DRP's Configure took over 60 s, and why),
  add the run to the issue's count, and treat the trigger as the failure to explain.
- NOT-REPRODUCED: a match is new evidence. The row's k is no longer 0; keep the logs, add the run's
  conditions, and decide the verdict again.
- pending: as NOT-REPRODUCED until the row has a verdict.
- no row matches: a new row (below, "How to add a row").

A full check is never rerun until it passes: a failed run stays in the record with its cause.

## Register

| id | symptom (first log line, verbatim) | verdict | cause (file:line) or conditions tried | k/n | m | arithmetic | PR or issue |
|---|---|---|---|---|---|---|---|
| F1 | `tst-drp[PID]: <C> void Pds::Eb::TebContributor::_post(const Pds::Eb::CtrbBatch&): _pending queue overflow`, then `The process was killed by signal 6`, right after `TebRcvr saw Enable` (drp of epixquad1kfps, opal, epix100) | FIXED | `psdaq/psdaq/eb/src/TebContributor.cc:338-343` (`_post`) aborts when `_pending` is full; its capacity is the drp's pebble count (`TebContributor.cc:51`, `_pending (numBuffers)`). `psdaq/drp/DrpBase.cc:226-240` (`MemPool::allocate`, at 946ef0ff1; `:214-230` at 39afa18e3) lets `nbuffers - 1` pebbles be in use; `psdaq/drp/TebReceiver.cc:153` frees a batch's pebble inside `EbCtrbInBase::_deliver` (its `process()` call, `psdaq/psdaq/eb/src/EbCtrbInBase.cc:852`) before `EbCtrbInBase.cc:617` pops the batch from `_pending`. With one event per batch (1 kHz) and a TEB lag of about the pebble count, the reader posts one more batch before the pop and the queue is full. Not explained: why the TEB lagged in the natural occurrences on sdfmilan023 (the reproducer makes the lag by stopping teb0). Fix (PR #52): `drp -d sim://` only, an opt-in kwarg `tebPendingDepth` (`daq_sim` passes twice the pebble count; drp rejects it without `sim://`); the batch region stays sized by the pebble count; production defaults unchanged (with the kwarg absent, the drp and teb sizing lines are identical at 946ef0ff1 and cee776d3c). | before: 3/30 at 946ef0ff1 on sdfada016 with reproducer R1 (opal, `pebbleBufCount=256`, teb0 SIGSTOPped for 1.0 s right after `TebRcvr saw Enable`; aborts at +1.31, +1.45, +1.61 s); same command at the default 128 pebbles 0/40. Natural: 3 of 16 epixquad1kfps+opal type runs in 8 full checks (c370014fc..b3d052088, all on sdfmilan023), plus 1 epix100 run outside a full check (913dcd195, sdfmilan048) | 39: R1 at cee776d3c on sdfada016, 40 run, 0 aborts (`tebPendingDepth 512 (numBuffers 256)` in all 40 drp logs); try 9 is not counted (lost to F6). Also 0/10 at the default count, 0/8 four-type runs without the induced lag | (1 - 3/30)^39 = (27/30)^39 = 0.016 < 0.05 | PR #52; issue #53 (the production edge case: zero margin in `_pending`) |
| F2 | `teb0[PID]: <C> FATAL: Segmentation Fault - stack trace follows` (stack `EbLfServer::pollEQ` <- `EbLfServer::pend` <- `EbAppBase::process` <- `Teb::run`), or `tst-teb[PID]: <C> Uncaught exception: Receiver thread lost connection with a DRP` and signal 6; at teb0's first `received key = disconnect` | REPORTED | Trigger: a Disconnect with no Unconfigure after teb's Configure phase 1 started `Teb::run` (`psdaq/psdaq/eb/src/teb.cc:1153-1155`), e.g. after a DRP's Configure that runs into control's 60 s timeout. `TebApp::handleDisconnect` (`teb.cc:1172-1175`) joins `Teb::run` (via `_unconfigure`, `teb.cc:1122-1129`) only when an Unconfigure was queued; `EbAppBase::disconnect` (`psdaq/psdaq/eb/src/EbAppBase.cc:95-102`) then tears the links down while `Teb::run` is in `EbAppBase::process` (the call at `teb.cc:462`), whose `EbLfServer::pend` calls `pollEQ` on the deleted event queue (`psdaq/psdaq/eb/src/EbLfServer.cc:306`, SEGV) or gets rc -125 and `Teb::run` throws (`teb.cc:475`/`:480`, abort). Upstream 39afa18e3 does not fix it. | induced with reproducer R2: 5/5 at 96ba26676 and 5/5 at def58eaf8 (sdfmilan082; 2 SEGV and 3 aborts each); natural: 4 of 4 teb0 logs whose Disconnect followed a Configure that hit the 60 s timeout, 0 of 1084 other teb0 logs | - | - (not FIXED) | issue #50 |
| F3 | `free(): double free detected in tcache 2` (drp) or `double free or corruption (!prev)` (drp_gpu, hsd's drp), then `@@@ Received a sigChild for process N. The process was killed by signal 6`; after `<W> Shutting down on INT signal` at `daq_sim down` | REPORTED | Cause candidate, not proven (no backtrace of the double free): `psdaq/psdaq/service/Collection.cc:61-74`, `shutdownHandler` runs the program's shutdown action inside the SIGINT handler; the action is `exit(0)` (`psdaq/drp/drp.cc:184`, `psdaq/drpGpu/PGPDetectorApp.cc:868`, `psdaq/drp/PvaDetector.cc:1570`, `BldDetector.cc:1525`, `BldDetectorSlow.cc:1316`, `UdpEncoder.cc:1603`, `psdaq/epicsArch/epicsArch.cc:797`), so static destructors run while the program's threads still run. teb (`teb.cc:1509`) and monReqServer (`monReqServer.cc:1285`), whose action is `lRunning = 0`, exit 0. The shutdown segfaults belong to this row, as the same shutdown path: the CPU drp of epixm320 (`epixm320_0[PID]: <C> FATAL: Segmentation Fault - stack trace follows`, frames in `libcollection.so`, boost.python and rogue) and drp_gpu jungfrau (`jungfrau_0[PID]: <C> FATAL: Segmentation Fault - stack trace follows`, signal 11), each right after `Shutting down on INT signal`. It comes after the run and its checks: no assertion has failed from it. | near-deterministic: 175 of 186 CPU drp shutdowns and 20 of 30 drp_gpu shutdowns in the 6 full checks of PR #42; 30 of 30 drp and 3 of 3 drp_gpu in the full check at def58eaf8; the epixm320 segfault in 7 of 7 full checks; 107 of 112 drp shutdowns at 96ba26676 on sdfada018 | - | - (not FIXED) | issue #51 |
| F4 | control: `[warning] pvcam_0: PV DAQ:SIM:CAM:IMAGE hasn't connected`; drp_pva: `<E> Failed to get parameters for PV DAQ:SIM:CAM:IMAGE`, then `<E> Phase 1 error in Detector::configure()`; about 3 s after the configure request | REPORTED | `psdaq/psdaq/epicstools/MonTracker.cc:77-96`: both constructors start the PVA monitor in their initializer list (`_mon(_channel.monitor(this, _request))`, `:81`, `:93`), before any `shared_ptr` owns the tracker; `MonTracker::monitorEvent` (`:108-125`) calls `shared_from_this()`, and the `bad_weak_ptr` an early update raises is caught and dropped (`:117`). drp_pva makes its `PvMonitor` (a `MonTracker`) with `std::make_shared` at `psdaq/drp/PvaDetector.cc:679-680`, so the owner exists only after the constructor returns; if the PV's first update arrives in between, no later update comes during the wait, and `PvMonitor::getParams` (`PvaDetector.cc:195-210`) gives up after its 3 s wait. The sim avoids it while drp_pva is the PV's first client: simxpm's camera PV opens 0.25 s after a client's first channel (145f3da63). Not reproduced on hardware. | reproducer R4 (holder + `strace -f`): 5/5 at 946ef0ff1 on sdfada018 (after the sync); the four arms there and the reviewer's at c370014fc are in "F4 arms" below | - | - (not FIXED) | issue TBD (to be filed) |
| F5 | `subprocess.TimeoutExpired: Command '['procmgr', 'stop', 'daq_sim.cnf', ...` 120 s after `daq_sim: procmgr stop daq_sim.cnf` | NOT-REPRODUCED | `psdaq/psdaq/sim/daq_sim.py:1683-1684` (at def58eaf8) gives `procmgr stop` 120 s; procmgr's stop (`psdaq/psdaq/procmgr/ProcMgr.py:1269`, `stopDictionary`) sends ^C, waits 5 s, ^X, retries once, then ^Q. The stuck process of the one occurrence is not on disk (its work dir was reused). Conditions tried: `daq_sim matrix --only programs` (the full check's programs run, recipe R5), 30 runs at def58eaf8 (after the sync) on sdfmilan031 (milano, the original's node type), a fresh work dir and evidence dir per run; `procmgr stop` took 8.6-9.7 s in all 30, against the 120 s limit. Differences from the original: node sdfmilan031, not sdfmilan023; the original's node load is unknown and its node was busy (a full check's node), ours ran at load about 8 on 128 cores; the original reused a work dir. | before: 1 of 57 programs runs (dc482a707, sdfmilan023); after the sync: 0/30 | 30 | - (NOT-REPRODUCED: 30 runs, at least 30 needed) | - |
| F6 | `RuntimeError: Unable to bind random UDP6 port` (in a type's `cycle` output, from `daq_sim`'s `pv_get`, raised by p4p's `Context('pva')`), then the cycle fails (`the cycle wrote no record (exit 1)`) | TBD (fix/f6-pva-context) | PVXS 1.2.1 `client.cpp:547-563` binds the client's IPv6 search socket to the port the kernel chose for its IPv4 socket and throws when that port is taken on IPv6. `daq_sim` built a new `Context('pva')` on every poll (`pv_get`, `psdaq/psdaq/sim/daq_sim.py:1801-1809` at 946ef0ff1, the `Context` outside its `try`), about once a second while it waits, so each poll is one more chance. Seen once: cee776d3c on sdfada016 (F1's after-fix loop, try 9); in no other log of this work. | TBD (fix/f6-pva-context) | TBD (fix/f6-pva-context) | TBD (fix/f6-pva-context) | TBD (fix/f6-pva-context) |

### F4 arms

Each try: `daq_sim up --pva --rate 100`, then optionally a holder (a p4p client monitoring
`DAQ:SIM:CAM:IMAGE`) and/or `strace -f` attached to every drp_pva thread, then one `daq_sim cycle`
(drp_pva's first Configure). A try fails when that Configure fails as in F4's symptom.

| arm | after the sync: 946ef0ff1, sdfada018 | the reviewer's, c370014fc (PR #42) |
|---|---|---|
| neither | 0/5 | - |
| holder only | 0/5; also 0/10 at def58eaf8 on sdfmilan082 (holder from before Configure) | 0/14 (0/6 and 0/8, two scripts) |
| `strace -f` only | 1/5 | 0/4 |
| holder + `strace -f` | 5/5 | 6/6 |

## Reproducers

Each runs in a Slurm step on a compute node of your own allocation (never on sdfiana025), in the env
of MAINTAINING.md step 2 (`source $ROOT/simenv.sh $WT`, which sets `$LOCK`), with `$WT` built
(step 6). `WD` is a fresh directory per try.

**R1 (F1).** opal with 256 pebbles (its DMA count stays 128), and teb0 stopped for 1.0 s right after
the drp sees Enable. The 256 pebbles come from an overlay of the installed `psdaq` package with
one line of `daq_sim.py` changed, first on `PYTHONPATH`:

```bash
OV=$ROOT/work/f1-overlay; rm -rf $OV; mkdir -p $OV
cp -r $(dirname $(dirname $(python3 -c 'import psdaq.sim.daq_sim as d; print(d.__file__)'))) $OV/psdaq
sed -i "/'opal':/s/sim_seed={seed:#x}'/sim_seed={seed:#x},pebbleBufCount=256'/" $OV/psdaq/sim/daq_sim.py
export PYTHONPATH=$OV:$PYTHONPATH
python3 -c 'import psdaq.sim.daq_sim as d; print(d.__file__, d.SIM_TYPES["opal"]["kwargs"])'   # ...,pebbleBufCount=256
for i in $(seq 30); do
  WD=$ROOT/work/f1-r1-$i; mkdir -p $WD-ev
  (until L=$(ls $WD/types/opal/pmlogs/*/*/*:opal_0.log 2>/dev/null) && grep -qE 'TebRcvr +saw +Enable' $L; do sleep 0.01; done
   T=$(for p in $(pgrep -u $USER -f "teb .*-M $WD/types/opal/prom -u teb0( |\$)"); do [ "$(cat /proc/$p/comm)" = teb ] && echo $p; done)
   kill -STOP $T; sleep 1.0; kill -CONT $T) & TRIG=$!
  daq_sim matrix -w $WD --only types --types opal --lock $LOCK --lock-timeout 600 --evidence $WD-ev > $WD.log 2>&1
  echo "try $i MATRIX_EXIT=$? overflow: $(grep -l '_pending queue overflow' $WD/types/opal/pmlogs/*/*/*opal_0.log)"
  kill $TRIG 2>/dev/null
done
```

Expected before the fix (946ef0ff1): an abort in about 1 of 10 tries (3/30), `MATRIX FAIL`
with `opal_0 did not respond to disable`; without the overlay 0/40. After it (cee776d3c): 0 aborts,
and the drp log has `tebPendingDepth 512 (numBuffers 256)`. The rates above were measured with a
Python poller doing the same steps every 10 ms (teb0 stopped 0.02-0.05 s after Enable).

**R2 (F2).** The steps and the driver script `f2drive.py` are in issue #50 ("Steps to Reproduce"):
`daq_sim up -w $WD --det fakecam --detach -p 5`; `python3 f2drive.py $WD fakecam_0 gdb` (stops the
fakecam drp in gdb at `psdaq/drp/PGPDetectorApp.cc:563` at the fork's def58eaf8, inside its
Configure, lets control's 60 s timeout run out, steps down to `reset`, then resumes the drp);
`grep -nE 'Segmentation Fault|Uncaught exception|pend\(\) error' $WD/pmlogs/*/*/*teb0.log`;
`daq_sim down -w $WD`. Expected: a teb0 crash every try.

**R3 (F3).** Any type run: `daq_sim matrix -w $WD --only types --types fakecam,epix100,opal`, then
`grep -n -E 'Shutting down on INT|double free|corruption|Segmentation Fault|killed by signal' $WD/types/*/pmlogs/*/*/*_0.log`
(`--types epixm320` for the segfault variant).

**R4 (F4).** Holder plus `strace -f` on drp_pva:

```bash
daq_sim up -w $WD --pva --rate 100 --detach
python3 -c "
import time
from p4p.client.thread import Context
ctx = Context('pva'); n = [0]
sub = ctx.monitor('DAQ:SIM:CAM:IMAGE', lambda v: n.__setitem__(0, n[0] + 1))
t0 = time.time()
while time.time() - t0 < 120: time.sleep(2); print('holder', n[0], flush=True)
" > $WD.holder.log 2>&1 & HP=$!
P=$(for q in $(pgrep -u $USER -x drp_pva); do tr '\0' ' ' < /proc/$q/cmdline | grep -q -- "$WD/data" && echo $q; done | head -1)
strace -f -tt -e trace=socket,connect,sendto,sendmsg,recvfrom,recvmsg -o $WD.st.txt \
  $(for t in /proc/$P/task/*; do echo -n "-p ${t##*/} "; done) 2> $WD.st.err & SP=$!
sleep 2
daq_sim cycle -w $WD --events 200 > $WD.cycle.log 2>&1; echo CYCLE_EXIT=$?
grep -hE "hasn.t connected|Failed to get parameters" $WD.cycle.log $WD/pmlogs/*/*/*pvcam_0.log
kill $SP $HP; daqstate -p 5 -P tst -C localhost --state reset; daq_sim down -w $WD
```

Expected (946ef0ff1): `CYCLE_EXIT=1` with the two lines of F4's symptom in every try.

**R5 (F5).** `daq_sim matrix -w $WD --only programs --ami-src $AMI --lock $LOCK --evidence $WD-ev`
on a milano node, a fresh `WD` per run; a run fails F5's way when its log has `TimeoutExpired`.

## How to add a row

1. Take the next id (F7, ...). Copy the first line of the failure from the log that has it
   (a pmlog, `<WD>/.../pmlogs/<yyyy>/<mm>/<dd_HH:MM:SS>_<host>:<id>.log`, or the matrix log),
   verbatim, with the PID replaced by `PID`.
2. Before adding, check the existing rows: the same first line, or the same code path (as the
   shutdown segfaults are F3's), is the same row; add the occurrence to its k/n instead.
3. Write the conditions of the occurrence: commit, node, detector type, the type run before it,
   node load if known, the command, and the full check or loop it was part of. Count the
   denominator: how many runs of the same kind there were.
4. Set the verdict to pending. A verdict needs the numbers its definition above asks for: a
   reproducer and its rate before a fix; m clean tries after it with (1 - k/n)^m < 0.05; or 30
   (F1: 100) clean runs of the affected kind for NOT-REPRODUCED.
5. A REPORTED row's draft issue goes on carbonscott/lcls2, titled `[DRAFT for upstream] ...` with the
   fields of upstream's bug template; put its number in the last column. Cite commits, pull
   requests and issues in the row, not paths outside the repository.
