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
PR #52, merged into sim-main as 5257855b1); 0448b6c5c (F6's first fix, branch fix/f6-pva-context,
merged with 5257855b1); 1f56dd354 (F6's revised fix, the same branch); 667dc551c (F7's fix, branch
fix/f7-hps-start). F6-F9's fixes go to sim-main together, from branch fix/f6-f7-f8 (P below,
a94d89310; P^ is its parent 63a552b3f; its pull request is TBD), and F11's fix goes on the same
branch. Line numbers are at upstream 39afa18e3 unless a cell names a fork commit.

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
ends `MATRIX FAIL` at a commit is a failed run at that commit, whatever row it matches, also when
the node was slow; only a run cut short by the infrastructure (it never printed its `MATRIX
PASS|FAIL` line because of a node failure, the job's time limit, a cancelled allocation or an OOM
kill) counts neither way, and its cause is written down (MAINTAINING.md, step 11). The row a `FAILED` line matches tells the
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
| F4 | control: `[warning] pvcam_0: PV DAQ:SIM:CAM:IMAGE hasn't connected`; drp_pva: `<E> Failed to get parameters for PV DAQ:SIM:CAM:IMAGE`, then `<E> Phase 1 error in Detector::configure()`; about 3 s after the configure request | REPORTED | `psdaq/psdaq/epicstools/MonTracker.cc:77-96`: both constructors start the PVA monitor in their initializer list (`_mon(_channel.monitor(this, _request))`, `:81`, `:93`), before any `shared_ptr` owns the tracker; `MonTracker::monitorEvent` (`:108-124`) calls `shared_from_this()`, and the `bad_weak_ptr` an early update raises is caught and dropped (`:117`). drp_pva makes its `PvMonitor` (a `MonTracker`) with `std::make_shared` at `psdaq/drp/PvaDetector.cc:679-680`, so the owner exists only after the constructor returns; if the PV's first update arrives in between, no later update comes during the wait, and `PvMonitor::getParams` (`PvaDetector.cc:195-210`) gives up after its 3 s wait. The sim avoids it while drp_pva is the PV's first client: simxpm's camera PV opens 0.25 s after a client's first channel (145f3da63). Not reproduced on hardware. | reproducer R4 (holder + `strace -f`): 6/6 at 946ef0ff1 on sdfada018 (after the sync); `strace -f` alone 0/4, holder alone 0/5, neither 0/5; the arms there and the reviewer's at c370014fc are in "F4 arms" below | - | - (not FIXED) | issue #54 |
| F5 | `subprocess.TimeoutExpired: Command '['procmgr', 'stop', 'daq_sim.cnf', ...` 120 s after `daq_sim: procmgr stop daq_sim.cnf` | NOT-REPRODUCED | `psdaq/psdaq/sim/daq_sim.py:1683-1684` (at def58eaf8) gives `procmgr stop` 120 s; procmgr's stop (`psdaq/psdaq/procmgr/ProcMgr.py:1269`, `stopDictionary`) sends ^C, waits 5 s, ^X, retries once, then ^Q. The stuck process of the one occurrence is not on disk (its work dir was reused). Conditions tried: `daq_sim matrix --only programs` (the full check's programs run, recipe R5), 30 runs at def58eaf8 (after the sync) on sdfmilan031 (milano, the original's node type), a fresh work dir and evidence dir per run; `procmgr stop` took 8.6-9.7 s in all 30, against the 120 s limit. Differences from the original: node sdfmilan031, not sdfmilan023; the original's node load is unknown and its node was busy, ours ran at load about 8 on 128 cores; the original reused a work dir. | before: 1 of 57 programs runs (dc482a707, sdfmilan023); after the sync: 0/30 | 30 | - (NOT-REPRODUCED: 30 runs, at least 30 needed) | - |
| F6 | `RuntimeError: Unable to bind random UDP6 port` (in a type's `cycle` output, from `daq_sim`'s `pv_get`, raised by p4p's `Context('pva')`), then the cycle fails (`the cycle wrote no record (exit 1)`) | pending (planned FIXED once P merges) | PVXS 1.2.1 `client.cpp:547-563` binds the client's IPv6 search socket to the port the kernel chose for its IPv4 socket and throws when that port is taken on IPv6. `daq_sim` built a new `Context('pva')` on every poll (`pv_get`, `psdaq/psdaq/sim/daq_sim.py:1801-1809` at 946ef0ff1, the `Context` outside its `try`), about once a second while it waits, so each poll is one more chance. Fix (1f56dd354 on fix/f6-pva-context, sim code only): `pv_get` and `pv_put` still make one Context per call, through `pva_context()` in `daq_sim.py`, which retries only the creation and only on the exact message `Unable to bind random UDP6 port`, at most 10 times, each retry a stderr line `daq_sim: PVA client context: Unable to bind random UDP6 port (attempt <n> of 10), retrying`; any other error, and the 10th failure, still raise (guardrails at 1f56dd354: an absent PV still fails after its timeout, 1.00 s at `timeout=1.0`; a bind that always fails, P=1.0, still fails the cycle, `MATRIX FAIL (4 of 7)`). An earlier fix (0448b6c5c, one Context per process) was dropped as a design choice (a smaller diff). | before: 10/10 cycles failed at 946ef0ff1 on sdfada016 with reproducer R6, which is fault injection: an `LD_PRELOAD` shim fails the cycle's UDP6 binds with probability P=0.3 (each failed cycle has exactly one `RuntimeError: Unable to bind random UDP6 port`). Natural: seen once in >= 515 cycles of this work (cee776d3c, sdfada016, F1's after-fix loop, try 9), in no other log of this work or the earlier one | 30: R6 at 1f56dd354 on sdfada016, 30/30 `MATRIX PASS (7 assertions)`, 0 `RuntimeError: Unable to bind random UDP6 port`; 158 injected bind failures, 158 retry lines, all absorbed | (1 - 10/10)^30 = 0 < 0.05. Without the retry, a cycle makes about 12 Contexts (inferred from the retry count), so at P=0.3 it would survive with 0.7^12 = 0.014 | PR TBD (fix/f6-f7-f8) |
| F7 | in `programs/pmlogs/.../*:hpsbldcpa.log` (hpsBldCopy): `Timeout getting the value of PV DAQ:SIM:HPSEX:PAYLOAD`, then `std::future_error` ... `Future already retrieved`, killed by signal 6; the matrix then has `FAILED programs/checks: ... gui witness: FAIL hpsBldCopy received 0 packet(s) on 239.254.34.1:31452` | REPORTED | Production: `EpicsPVA::getComplete` (`psdaq/psdaq/epicstools/EpicsPVA.cc:129-142`) can be called once only (it takes its promise's future); `PVBase::ready()` (`psdaq/psdaq/epicstools/PVBase.hh:17`) calls `getComplete()`, which waits 30 s (`EpicsPVA.hh:209`), and hpsBldCopy polls `ready()` in loops until its PVs answer (`psdaq/psdaq/app/hpsBldCopy.cc:142-148`, `:153-158`), so a PV that does not answer within the first call's 30 s makes the next call throw `std::future_error`, and hpsBldCopy aborts. procmgr starts hpsBldCopy together with the servers of its PVs (hpsBldServer, bldcas), so a late server is the trigger. Late: the PVA client (pvAccessCPP 7.1.6, `src/remote/channelSearchManager.cpp:62-63`, `:99`, `:356-359`) searches again for a channel it has not found at about 14.4-16 s and 28.8-32 s after it made it, so a server that comes up after the search near 15 s is next searched for near 30 s, around the end of the 30 s wait: with hpsBldServer serving 16 to 18 s after the start, hpsBldCopy aborted in 3 of 5 runs; with it serving 26 s or later, in 17 of 17. Sim-side work-around (667dc551c on fix/f7-hps-start, in P): `daq_sim up --hps` starts hpsBldCopy behind `psdaq.sim.pvwait`, which waits up to 120 s (`HPS_PV_WAIT`) for its five PVs and then execs it (same PID); on a timeout it prints `pvwait: timeout <PV>` and exits 1. pvwait reads each PV once; a PV whose server exits afterwards is not covered: with bldcas stopped, hpsBldServer itself exits 12-19 s after its start (`hps_connect`, `psdaq/psdaq/pyhpsbld/pyhpsbld.py:175-183`, gets `<base>:ADDR` and its `TimeoutError` ends in `throw` at `psdaq/psdaq/app/hpsBldServer.cc:64-70`: `terminate called after throwing an instance of 'char const*'`, exit status 6), and hpsBldCopy still aborts. The production abort remains, written up as issue #55. | induced with reproducer R7 at 0448b6c5c: 17/17 aborts with hpsBldServer (`hpsbldsvc`) stopped >= 20 s at its start (40 s 10/10, 25 s 2/2, 20 s 5/5); stopped 10 s 0/2 (f7b10a, f7b10b), stopped 5 s 1/2 (f7b05a aborted, f7b05b passed); also 3/3 with bldcas stopped 40 s (`... PV DAQ:SIM:HPSEX:ADDR`). Natural: 2, both programs runs at 0448b6c5c in the slow period of 2026-11-11 (from ~17:54Z): q1, the full check before F6's merge (`MATRIX FAIL (3 of 201 assertions failed)`), and a programs run on sdfada016; 2 of the 4 programs runs at 0448b6c5c in that period, 0 of 34 programs runs at other commits (s1 at def58eaf8, p1 at cee776d3c, the 30 F5 runs at def58eaf8, and 2 at 5257855b1 in the slow period). Whether 0448b6c5c's one-Context-per-process raised the rate is not established (2 of 4 against 0 of 2 in the same period, Fisher p = 0.40; the HPS chain searches on its own port, not `daq_sim`'s) | with the work-around, R7 at P (a94d89310): hpsBldServer stopped 20 s, 0 aborts in 10 counted (f7s01-f7s09, f7s11; each `MATRIX PASS (8 assertions)`, pvwait read PAYLOAD 26.0-34.3 s after the start; f7s10 not counted: its preflight failed, F11, nothing started); bldcas stopped 20 s, 3/3 aborts (f7c01-f7c03, on `:PAYLOAD`, hpsBldServer having exited first, `MATRIX FAIL (2 of 8 assertions failed)`); guardrail f7g01, hpsBldServer stopped 150 s: `pvwait: timeout DAQ:SIM:HPSEX:PAYLOAD`, exit status 1, `MATRIX FAIL (2 of 8 assertions failed)` | - (not FIXED: the production abort is unfixed and still happens at P, 3 of 3 with bldcas stopped) | PR TBD (fix/f6-f7-f8); issue #55 |
| F8 | in the programs run's matrix log: `ami check FAIL ["ami_count <N> != 4096 events in AMI's rows", "ami_pixsum ... != psana2 sum ... over the events AMI saw"]` (e.g. N = 4295) | FIXED | `psdaq/psdaq/sim/ami_check.py:44` (`MAX_ROWS = 4096`) sizes the RollingBuffer that keeps AMI's per-event rows (`:67-68`, `N=MAX_ROWS`); when AMI sees more events than that, the buffer keeps 4096 and the count no longer matches psana2's. AMI sees events for as long as Running lasts, and in the programs run Running lasts as long as the AMI screenshot takes (`cycle --ami-shot`): 37 s (s1), 42 s (p1), 65 s (q1), 94 s (a run at 0448b6c5c) on 2026-11-11 as the shared environment slowed; beyond ~85 s AMI sees more than 4096. Fix (a94d89310, P): `MAX_ROWS = 16384`, which moves the cliff ~4x, to ~6 min of Running; the check itself is unchanged (the same counts are compared), so it is not weakened. A run beyond 16384 events was not shown by a run. | before: 5/5 with reproducer R8 at P^ 63a552b3f (f8b01-f8b05: `ami_count <N> != 4096 events in AMI's rows` with N = 5578, 5061, 6478, 4807, 5540; Running 101.9-144.3 s; `MATRIX FAIL (2 of 8 assertions failed)`; f8b05's stop lasted 86.8 s, not 70 s). Natural: 8 of 42 AMI checks (`ami_check.json`) failed, all saturated at 4096 rows; the 34 passes had 1747-3918 rows | 10: R8 at P (a94d89310), f8a01, f8a03-f8a07, f8a09-f8a11, f8a13: 4526-6516 events each, all matched, ami check PASS, `MATRIX PASS (8 assertions)`. Not counted: f8a02 (ami check PASS with 5677 events, but `MATRIX FAIL (1 of 8 assertions failed)` from dtica's `malloc(): unaligned tcache chunk detected` before Running, F10's symptom); f8a08 (preflight failed, F11, nothing started); f8a12 (4049 events: the trigger did not happen) | (1 - 5/5)^10 = 0 < 0.05 | PR TBD (fix/f6-f7-f8) |
| F9 | `FAILED psdaq/psdaq/tests/test_sim_programs.py::test_lclsBldServer_sends_its_bld_for_the_frames_tprframes_delivers` with one of three assertions (lines of the test at 5257855b1): `:721`, the packet count (`assert 200 <= 105`; also 82, 39, 142, 30, 123, 194); `:720`, 0 packets; `:718`, an empty tprframes log (`''`) | FIXED | A unit-tier test (MAINTAINING.md steps 7 and 8), not part of `daq_sim matrix`; registered because it was seen in this campaign. `psdaq/psdaq/tests/test_sim_programs.py:706-711` (at 5257855b1) starts `psdaq.sim.tprframes` and lclsBldServer, sleeps a fixed 2 s, then receives for 3 s and asserts 200 to 400 packets (`:721`); on a slow node, where Python's imports took 2.3-5.2 s, the server is not yet sending when the receive starts. Fix (63a552b3f, in P): it waits until the first packet arrives (at most 30 s; with none, it fails `lclsBldServer sent no packet within 30 s`), then counts the next 3 s as before; the bounds (200 to 400) and every other assertion are unchanged. | before: 8/10 on sdfada018 (P with the test file as at 23d8eae8b, interleaved with the after runs under the node's DAQ lock). Supporting only, not the verdict: 1/10 on sdfada016 (`AssertionError: 116`), against 0/10 after there ((1 - 1/10)^10 = 0.35). Natural: fails on S3DF ada nodes in the slow period at every commit tried: 3/3 at 0448b6c5c and 3/3 at 667dc551c (sdfada018), also at 5257855b1 and 1f56dd354 (sdfada016); passes on GitHub's runners (CI runs 43090590334, 43092623334) | 10: 0/10 failed on sdfada018 at P (a94d89310). Negative run (P's test with lclsBldServer sending to another port): fails `AssertionError: lclsBldServer sent no packet within 30 s`, on sdfada018 and sdfada016 | (1 - 8/10)^10 = 0.2^10 = 1.0e-7 < 0.05 (sdfada018 alone) | PR TBD (fix/f6-f7-f8) |
| F10 | in the programs run's dtica pmlog (`python -m psdaq.cas.dtica`): `malloc(): unaligned tcache chunk detected`, then killed by signal 6, seconds after its start | pending (verdict to come from the loop below) | Cause not established. Both aborts were on milano nodes (sdfmilan023, sdfmilan031). A loop of standalone dtica starts is being run in this iteration to get a reproducer and its rate; its result is TBD. | 2 of 212 dtica procServ starts (log count, 2026-11-11 21:55Z) | - | - | - |
| F11 | in a type's or program's `preflight.log`: a probe killed by its outer timeout, `rc=124`, then either `PREFLIGHT FAIL: facility service reachable` (`python-requests rc=124 (1 would mean pswww answered)`) or `PREFLIGHT FAIL: loopback EPICS positive control failed` (the positive control's p4p or pvget); the matrix then has a `FAILED` line for that start (e.g. `FAILED types/epix100/up: preflight rc=1 ...`) | pending (planned FIXED: a fix in `psdaq/psdaq/sim/preflight.sh`, where a probe killed by its outer timeout prints `HUNG: ...` and runs once more and a second hang ends the preflight with exit 4, `PREFLIGHT FAIL: probe hung`, is being made and measured in this iteration) | Cause not established. The probe's process froze or was slow to start: it printed no `REACHED` or `blocked:` line before its outer timeout killed it, and the preflight read that rc 124 as a leak (exit 1) or as broken local EPICS (exit 3). Seen at four moments on 2026-11-11: 19:14Z on three nodes, 21:37Z, 21:58Z, 22:21Z (sdfmilan082, the epix100 type of a full check at P). | 6 of 774 preflights under this campaign's root (6 of 156 since 19:00Z, 0 of 625 before); 0 of 1016 in the earlier campaign's root (inherited) | - | - | - |

### F4 arms

Each try: `daq_sim up --pva --rate 100`, then optionally a holder (a p4p client monitoring
`DAQ:SIM:CAM:IMAGE`) and/or `strace -f` attached to every drp_pva thread, then one `daq_sim cycle`
(drp_pva's first Configure). A try fails when that Configure fails as in F4's symptom.

| arm | after the sync: 946ef0ff1, sdfada018 | the reviewer's, c370014fc (PR #42) |
|---|---|---|
| neither | 0/5 | - |
| holder only | 0/5; also 0/10 at def58eaf8 on sdfmilan082 (holder from before Configure) | 0/14 (0/6 and 0/8, two scripts) |
| `strace -f` only | 0/4 (a fifth try ran with the previous try's holder still alive: it is counted below, as holder + `strace -f`) | 0/4 |
| holder + `strace -f` | 6/6 (5 planned, plus that try) | 6/6 |

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

Expected (946ef0ff1): `CYCLE_EXIT=1` with the two lines of F4's symptom in every try (6/6). Kill
the holder by its own PID (`$HP`) and check it is gone before the next try: a holder left running
turns a `strace -f`-only try into a holder + `strace -f` try.

**R5 (F5).** `daq_sim matrix -w $WD --only programs --ami-src $AMI --lock $LOCK --evidence $WD-ev`
on a milano node, a fresh `WD` per run; a run fails F5's way when its log has `TimeoutExpired`.

**R6 (F6), fault injection.** F6 came once in >= 515 cycles, too rarely to measure a fix on, so R6
makes the failure: an `LD_PRELOAD` shim fails, with probability `UDP6FAIL_P`, every `bind()` of an
IPv6 UDP socket to a named port (PVXS's IPv6 search socket; binds to port 0 are left alone), with
`EADDRINUSE`, as when the port is taken. It is active only in the `daq_sim cycle` process (the one
that calls `pv_get`) and removes `LD_PRELOAD` from every other process, so no DAQ process loads it;
each injected failure is a line in `$UDP6FAIL_LOG`. Source, `udp6fail.c` (the shim the numbers were
measured with, less a hook for a standalone probe script):

```c
/* gcc -shared -fPIC -O2 -o udp6fail.so udp6fail.c -ldl */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>
#include <netinet/in.h>
#include <arpa/inet.h>

static int active;
static double prob;
static unsigned long long rng;
static int (*real_bind)(int, const struct sockaddr *, socklen_t);

static int cmdline_has(const char *buf, size_t n, const char *word)
{
    for (size_t i = 0; i < n; i += strlen(buf + i) + 1)
        if (strcmp(buf + i, word) == 0) return 1;
    return 0;
}

static int cmdline_suffix(const char *buf, size_t n, const char *suf)
{
    size_t m = strlen(suf);
    for (size_t i = 0; i < n; i += strlen(buf + i) + 1) {
        size_t l = strlen(buf + i);
        if (l >= m && strcmp(buf + i + l - m, suf) == 0) return 1;
    }
    return 0;
}

__attribute__((constructor)) static void udp6fail_init(void)
{
    char buf[8192];
    size_t n = 0;
    int fd = open("/proc/self/cmdline", O_RDONLY);
    if (fd >= 0) {
        ssize_t r;
        while (n < sizeof(buf) - 1 && (r = read(fd, buf + n, sizeof(buf) - 1 - n)) > 0) n += (size_t)r;
        close(fd);
    }
    buf[n] = 0;
    int is_cycle = cmdline_has(buf, n, "psdaq.sim.daq_sim") && cmdline_has(buf, n, "cycle");
    int is_matrix = cmdline_has(buf, n, "matrix") &&       /* `daq_sim matrix` hands it to its cycle child */
                    (cmdline_suffix(buf, n, "/daq_sim") || cmdline_has(buf, n, "psdaq.sim.daq_sim"));
    if (!is_matrix) unsetenv("LD_PRELOAD");          /* nothing below this process inherits the shim */
    if (!is_cycle) return;
    const char *p = getenv("UDP6FAIL_P");
    prob = p ? atof(p) : 0.0;
    rng = (unsigned long long)getpid() * 6364136223846793005ULL ^ (unsigned long long)time(NULL);
    active = 1;
    fprintf(stderr, "udp6fail: ACTIVE pid %d P=%g\n", (int)getpid(), prob);
}

static double uniform(void)
{
    rng = rng * 6364136223846793005ULL + 1442695040888963407ULL;
    return (double)(rng >> 11) / 9007199254740992.0;
}

int bind(int fd, const struct sockaddr *addr, socklen_t len)
{
    if (!real_bind) real_bind = (int (*)(int, const struct sockaddr *, socklen_t))dlsym(RTLD_NEXT, "bind");
    if (active && addr && addr->sa_family == AF_INET6 && ((const struct sockaddr_in6 *)addr)->sin6_port != 0) {
        int type = 0;
        socklen_t tl = sizeof(type);
        if (getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &tl) == 0 && type == SOCK_DGRAM && uniform() < prob) {
            const char *log = getenv("UDP6FAIL_LOG");
            fprintf(stderr, "udp6fail: injected EADDRINUSE on UDP6 bind fd %d pid %d port %u\n", fd, (int)getpid(),
                    (unsigned)ntohs(((const struct sockaddr_in6 *)addr)->sin6_port));
            if (log) {
                FILE *f = fopen(log, "a");
                if (f) { fprintf(f, "%d %ld injected\n", (int)getpid(), (long)time(NULL)); fclose(f); }
            }
            errno = EADDRINUSE;
            return -1;
        }
    }
    return real_bind(fd, addr, len);
}
```

Build it once (`gcc -shared -fPIC -O2 -o $ROOT/work/udp6fail.so udp6fail.c -ldl`), then per try:

```bash
for i in $(seq 30); do
  WD=$ROOT/work/f6-r6-$i; mkdir -p $WD-ev
  LD_PRELOAD=$ROOT/work/udp6fail.so UDP6FAIL_P=0.3 UDP6FAIL_LOG=$WD.inject.log \
    daq_sim matrix -w $WD --only types --types fakecam --lock $LOCK --lock-timeout 600 --evidence $WD-ev > $WD.log 2>&1
  echo "try $i MATRIX_EXIT=$? deaths $(grep -c 'RuntimeError: Unable to bind random UDP6 port' $WD.log)" \
       "injected $(cat $WD.inject.log 2>/dev/null | wc -l) retried $(grep -c 'PVA client context: .*retrying' $WD.log)"
done
```

Expected before the fix (946ef0ff1): `MATRIX_EXIT=1` and one death in every try (10/10). After it
(1f56dd354): `MATRIX_EXIT=0`, 0 deaths, and as many `retried` as `injected` (158 of 158 over 30
tries). With `UDP6FAIL_P=1.0` the cycle must still fail (10 attempts, then the `RuntimeError`).

**R7 (F7).** The programs run with hpsBldServer (procmgr id `hpsbldsvc`) stopped for `S` seconds as
soon as procServ has started it (with `hpsbldcas` in place of `hpsbldsvc`, it stops bldcas, which serves
the `ADDR` and `PORT` PVs):

```bash
S=40; WD=$ROOT/work/f7-r7-$(date -u +%H%M%S); mkdir -p $WD-ev
daq_sim matrix -w $WD --only programs --ami-src $AMI --lock $LOCK --lock-timeout 3600 --evidence $WD-ev > $WD.log 2>&1 & M=$!
until P=$(grep -aho 'The PID of new child .* is: [0-9]*' $WD/programs/pmlogs/*/*/*:hpsbldsvc.log 2>/dev/null | head -1 | grep -o '[0-9]*$'); do sleep 0.1; done
kill -STOP $P; sleep $S; kill -CONT $P
wait $M; echo MATRIX_EXIT=$?
grep -a -n -E 'Timeout getting|Future already|signal|pvwait' $WD/programs/pmlogs/*/*/*:hpsbldcpa.log
```

Expected at 0448b6c5c (without the work-around): hpsBldCopy aborts in every try with `S` >= 20
(17/17), `MATRIX FAIL`. With the work-around (667dc551c): no abort, `pvwait` prints how long
`DAQ:SIM:HPSEX:PAYLOAD` took (longer than `S`); with `S=40` the run can still fail its GUI witness,
because hpsBldServer itself is late for Running (the stop's own effect, not F7); with `S=25`, 4/4
`MATRIX PASS (8 assertions)` there. With `S=150`, `pvwait: timeout DAQ:SIM:HPSEX:PAYLOAD` and
`MATRIX FAIL`: the wait is bounded. At P (a94d89310), `S=20`: 0 aborts in 10 counted tries, each
`MATRIX PASS (8 assertions)`; `S=150` (f7g01): `pvwait: timeout DAQ:SIM:HPSEX:PAYLOAD`, `MATRIX FAIL`.

What a bldcas stall looks like (`hpsbldcas` in place of `hpsbldsvc`): hpsBldServer exits by itself
12-19 s after its start, its `hpsbldsvc.log` ending in `TimeoutError` (from `hps_connect`), then
`terminate called after throwing an instance of 'char const*'` and `Normal exit status = 6`;
hpsBldCopy then aborts on `:PAYLOAD` even behind pvwait (3/3 at P with `S=20`), because pvwait read
the PV before its server went away.

**R8 (F8).** The programs run with the AMI screenshot's `ami-client` and its descendants stopped
for 70 s, 3 s after its `# PID:` line appears, so that Running (which lasts as long as the
screenshot takes) runs past 4096 events (the measurements ran this as `run.sh <SHA> <TAG> ami 70`):

```bash
WD=$ROOT/work/f8-r8-$(date -u +%H%M%S); mkdir -p $WD-ev
daq_sim matrix -w $WD --only programs --ami-src $AMI --lock $LOCK --lock-timeout 3600 --evidence $WD-ev > $WD.log 2>&1 & M=$!
L=$WD/programs/logs/ami-shot/ami-client.log
until P=$(grep -a -m1 '^# PID: ' $L 2>/dev/null | grep -o '[0-9]*$'); do sleep 0.1; done
sleep 3
desc() { local c; for c in $(cat /proc/$1/task/*/children 2>/dev/null); do echo $c; desc $c; done; }
PIDS="$P $(desc $P)"; kill -STOP $PIDS; sleep 70; kill -CONT $PIDS
wait $M; echo MATRIX_EXIT=$?
grep -a -E '^MATRIX |ami check|ami_count' $WD.log
```

Expected before the fix (P^ 63a552b3f): `ami check FAIL ["ami_count <N> != 4096 events in AMI's
rows", ...]` with N above 4096 and `MATRIX FAIL (2 of 8 assertions failed)` (5/5). After it (P):
ami check PASS with all events matched and `MATRIX PASS (8 assertions)` (10 counted). A try counts
only when AMI saw more than 4096 events (the check's event count, not `AMI fetched`, which prints
the buffer's raw rows); on a stalled node the `sleep 70` can last longer (86.8 s once).

**R9 (F9).** The one test, in step 7's environment of MAINTAINING.md (on the node and at the time of
the failure, and again at sim-main there):
`pytest -rs -p no:cacheprovider psdaq/psdaq/tests/test_sim_programs.py -k test_lclsBldServer_sends_its_bld_for_the_frames_tprframes_delivers`.

## How to add a row

1. Take the next id (F12, ...). Copy the first line of the failure from the log that has it
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
