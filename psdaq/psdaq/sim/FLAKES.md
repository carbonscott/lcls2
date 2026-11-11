# Flake register of the hardware-free DAQ

One row per intermittent failure seen in the full check (`daq_sim matrix` over two milano nodes and a
GPU node, RUNBOOK §3p) or in one of its parts (a type run, the programs run, a feature, a DAQ's
shutdown). Each row says what the failure looks like, what is known of its cause, how often it was
seen, and what was done about it. How to use it when a run fails: MAINTAINING.md, step 11.

Status at 946ef0ff1 (sim-main), counts as of 2026-11-11T14:25Z. Commits: base 96ba26676 (sim-main before the sync),
sync head def58eaf8 (upstream 39afa18e3 merged in, merged into sim-main as d4e2217e0).

## Verdicts

| verdict | what it takes |
|---|---|
| FIXED | The cause is named by file and line. The failure reproduced k times in n tries before the fix and 0 times in m tries after, with m >= 10 and (1 - k/n)^m < 0.05. When production (non-sim) code changes, the same command is shown at base and at head. |
| FIXED-UPSTREAM | The same numbers as FIXED, naming the upstream commit that fixed it. |
| REPORTED | A cause, or a reproducer with its rate, not fixed here, written up as a draft issue on carbonscott/lcls2 in upstream's bug template (`.github/ISSUE_TEMPLATE/bug_report.yml`), its number in the last column. |
| NOT-REPRODUCED | The conditions tried, matching the original failure's detector type, node load and rate as far as known, and the try count: at least 100 runs of the affected kind for F1 and at least 30 for any other row, at the commit under test or after the sync. |
| pending | No verdict yet: the numbers so far and the planned verdict. |

(1 - k/n)^m is the chance that a failure with the rate seen before the fix would have missed all m
tries after it. Below 0.05, the m clean tries are unlikely to be luck.

**What a verdict means for a failed full-check run.** No row excuses a failure. A full check that
ends `MATRIX FAIL` at a commit is a failed run at that commit, whatever row it matches; only a run
cut short by the infrastructure (a node failure, the job's time limit, a cancelled allocation)
counts neither way, and its cause is written down. The row a `FAILED` line matches tells the
maintainer what to look for and what to rerun:

- FIXED or FIXED-UPSTREAM: the failure should no longer happen. A match means the fix regressed or
  the cause was wrong: reopen the row (verdict back to pending), rerun the row's reproducer at the
  failing commit, and for FIXED-UPSTREAM check the upstream commit is still an ancestor
  (`git merge-base --is-ancestor <commit> HEAD; echo $?`, 0).
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
| F1 | `tst-drp[PID]: <C> void Pds::Eb::TebContributor::_post(const Pds::Eb::CtrbBatch&): _pending queue overflow`, then `Received a sigChild for process PID. The process was killed by signal 6`, right after `TebRcvr saw Enable` (drp of epixquad1kfps, opal, epix100) | pending; planned FIXED (a fix is being measured) | `psdaq/psdaq/eb/src/TebContributor.cc:338-343` aborts when `_pending` is full; its capacity is the drp's buffer count (`psdaq/psdaq/eb/src/TebContributor.cc:51`; opal 128, epixquad1kfps 256). opal's in-flight count (`TCtbO_InFlt`) rises to 126-127 of 128 in the first ~0.6 s after Enable, one TEB batch per event. Why the TEB's answers lag then is not proven. Upstream ca4d4d2b4 (in 39afa18e3) does not remove the margin. | before: 3 of 16 epixquad1kfps+opal type runs in 8 full checks (c370014fc..b3d052088, all on sdfmilan023), plus 1 epix100 run outside a full check (913dcd195, sdfmilan048); 0 of 28 four-type runs at 96ba26676 on sdfada018 (opal peak 126-127 of 128 in 9 of 26 sampled); 0 of 13 so far at def58eaf8 on sdfada018 (peak >= 123 in 8 of the first 10) | pending | pending (with k/n = 3/16, m >= 15 is needed: (13/16)^15 = 0.044) | TBD |
| F2 | `teb0[PID]: <C> FATAL: Segmentation Fault - stack trace follows` (stack `EbLfServer::pollEQ` <- `EbLfServer::pend` <- `EbAppBase::process` <- `Teb::run`), or `tst-teb[PID]: <C> Uncaught exception: Receiver thread lost connection with a DRP` and signal 6; at teb0's first `received key = disconnect` | REPORTED | `psdaq/psdaq/eb/src/teb.cc:1172-1175`: `handleDisconnect` joins the `Teb::run` thread (via `_unconfigure`, `teb.cc:1121-1129`) only when an Unconfigure was queued. After a Configure that a DRP did not finish within control's 60 s, control sends Disconnect with no Unconfigure; `EbLfServer::disconnect` tears the links down while `Teb::run` is still in `EbLfServer::pend`, which then calls `pollEQ` on the deleted event queue (SEGV) or gets rc -125 and throws (abort). Trigger: any DRP's Configure that runs into control's 60 s timeout, then Disconnect. Upstream 39afa18e3 does not fix it. | induced (a fakecam drp stopped in gdb at `psdaq/drp/PGPDetectorApp.cc:563` across Configure, then Disconnect): 5/5 at 96ba26676, 5/5 at def58eaf8 (sdfmilan082); natural: 4 of 4 teb0 logs whose Configure hit the 60 s timeout before Disconnect, 0 of 1084 other teb0 logs | - | - (not FIXED) | TBD |
| F3 | `free(): double free detected in tcache 2` (drp) or `double free or corruption (!prev)` (drp_gpu, hsd's drp), then `@@@ Received a sigChild for process N. The process was killed by signal 6`; after `<W> Shutting down on INT signal` at `daq_sim down` | REPORTED | Cause candidate, not proven (no backtrace of the double free): `psdaq/psdaq/service/Collection.cc:61-74`, `shutdownHandler` runs the program's shutdown action, `exit(0)` (`psdaq/drp/drp.cc:191`, `psdaq/drpGpu/PGPDetectorApp.cc:882`, ...), inside the SIGINT handler, so static destructors run while the program's threads still run. teb and monReqServer, whose action is `lRunning = 0`, exit 0. The shutdown segfaults belong to this row too, as the same shutdown path: `epixm320_0[PID]: <C> FATAL: Segmentation Fault - stack trace follows` (CPU drp of epixm320, frames in `libcollection.so`, boost.python and rogue) and drp_gpu jungfrau's `jungfrau_0[PID]: <C> FATAL: Segmentation Fault - stack trace follows`, each right after `Shutting down on INT signal`. It comes after the run and its checks, so no assertion has failed from it. | near-deterministic: 175 of 186 CPU drp shutdowns and 20 of 30 drp_gpu shutdowns in the 6 full checks of PR #42; 30 of 30 drp and 3 of 3 drp_gpu in the full check at def58eaf8; the epixm320 segfault in 7 of 7 full checks; 107 of 112 drp shutdowns at 96ba26676 on sdfada018 | - | - (not FIXED) | TBD |
| F4 | drp_pva's Configure fails: `PV DAQ:SIM:CAM:IMAGE hasn't connected` | pending; planned REPORTED or NOT-REPRODUCED (the 10 tries with another client did not reproduce it; the reproducer is not settled) | Cause candidate: `psdaq/psdaq/epicstools/MonTracker.cc:77-84` starts the PVA monitor in the constructor (`:81`), before the `shared_ptr` that owns the tracker exists; `monitorEvent` (`MonTracker.cc:108-125`) then drops an event that arrives that early (`catch(std::bad_weak_ptr&) {}`), and pvAccessCPP sends no later update. The sim avoids it while drp_pva is the PV's first client: simxpm's camera PV opens 0.25 s after a client's first channel (145f3da63). | a reviewer's run in PR #42: 6 of 6 Configures failed with another client holding the PV; at def58eaf8 on sdfmilan082: 0 of 10 tries (20 Configures OK) with another client monitoring the PV from before Configure, 0 of 5 without it | - | pending | TBD |
| F5 | `subprocess.TimeoutExpired: Command '['procmgr', 'stop', 'daq_sim.cnf', ...` 120 s after `daq_sim: procmgr stop daq_sim.cnf` | pending; planned NOT-REPRODUCED (30 programs runs) | `psdaq/psdaq/sim/daq_sim.py:1683` gives `procmgr stop` 120 s; procmgr's stop (`psdaq/psdaq/procmgr/ProcMgr.py:1269`, `stopDictionary`) sends ^C, waits 5 s, ^X, retries once, then ^Q. The stuck process of the one occurrence is not on disk (its work dir was reused). Conditions tried: `daq_sim matrix --only programs` (the programs run of the full check), at def58eaf8 on sdfmilan031 (milano), load ~10 on 128 cores, a fresh work dir and evidence dir per run. | before: 1 of 57 programs runs (dc482a707, sdfmilan023); at def58eaf8: 0 of 12 so far (procmgr stop 8.7-9.7 s in the first 7) | - | - | TBD |

Sources: `work/recon/record.md`, `work/flake2/results.md`, `work/flake2/results-interim.txt` and the
logs they cite, under the campaign root on S3DF; PR #42's body for F4's reviewer run.

## How to add a row

1. Take the next id (F6, ...). Copy the first line of the failure from the log that has it
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
   fields of upstream's bug template; put its number in the last column.
