# Flake register of the hardware-free DAQ

One row per intermittent failure seen in the full check (`daq_sim matrix` over two milano nodes and a
GPU node, RUNBOOK §3p) or in one of its parts (a type run, the programs run, a feature, a DAQ's
shutdown). Each row says what the failure looks like, what is known of its cause, how often it was
seen, and what was done about it. How to use it when a run fails: MAINTAINING.md, step 11.

Status at H = 82a2868fe (the head of PR #57): 13 rows, 7 FIXED (F1, F6, F8, F9, F11, F12, F13), 5 REPORTED (F2, F3, F4, F7, F10), 1 NOT-REPRODUCED (F5); the full check passed 5 of 5 at H on 2026-11-12 (02:11:59Z to 04:24:39Z). H is the commit the final proofs are bound to: sim-main's HEAD, or an ancestor of
it that differs from it only in `.md` files and files outside `psdaq/`, `psana/` and
`xtcdata/xtcdata/`. Counts as of 2026-11-12. Commits: base 96ba26676 (sim-main before the sync);
sync head def58eaf8 (upstream 39afa18e3, the merge of upstream PR #300, merged in; merged into
sim-main as d4e2217e0); 946ef0ff1 (sim-main after the cheap tier, PR #49); cee776d3c (F1's fix,
PR #52, merged into sim-main as 5257855b1); 0448b6c5c (F6's first fix, branch fix/f6-pva-context,
merged with 5257855b1); 1f56dd354 (F6's revised fix, the same branch); 667dc551c (F7's fix, branch
fix/f7-hps-start). F6-F9's fixes go to sim-main together, from branch fix/f6-f7-f8 (P below,
a94d89310; P^ is its parent 63a552b3f; its pull request is #57), and F11's, F12's (e223e91cb) and F13's
(82a2868fe) fixes go on the same branch. Line numbers are at upstream 39afa18e3 unless a cell names a fork commit. 524378805 (branch
sim/preflight-slowfs-2, F11's start-up budget) changes `preflight.sh`, so once it is merged sim-main's HEAD no
longer differs from H in `.md` files only: H's full checks do not carry to it, and H moves only with a new full
check at the merge (MAINTAINING.md step 10).

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
| F6 | `RuntimeError: Unable to bind random UDP6 port` (in a type's `cycle` output, from `daq_sim`'s `pv_get`, raised by p4p's `Context('pva')`), then the cycle fails (`the cycle wrote no record (exit 1)`) | FIXED | PVXS 1.2.1 `client.cpp:547-563` binds the client's IPv6 search socket to the port the kernel chose for its IPv4 socket and throws when that port is taken on IPv6. `daq_sim` built a new `Context('pva')` on every poll (`pv_get`, `psdaq/psdaq/sim/daq_sim.py:1801-1809` at 946ef0ff1, the `Context` outside its `try`), about once a second while it waits, so each poll is one more chance. Fix (1f56dd354 on fix/f6-pva-context, sim code only): `pv_get` and `pv_put` still make one Context per call, through `pva_context()` in `daq_sim.py`, which retries only the creation and only on the exact message `Unable to bind random UDP6 port`, at most 10 times, each retry a stderr line `daq_sim: PVA client context: Unable to bind random UDP6 port (attempt <n> of 10), retrying`; any other error, and the 10th failure, still raise (guardrails at 1f56dd354: an absent PV still fails after its timeout, 1.00 s at `timeout=1.0`; a bind that always fails, P=1.0, still fails the cycle, `MATRIX FAIL (4 of 7)`). An earlier fix (0448b6c5c, one Context per process) was dropped as a design choice (a smaller diff). From e223e91cb on, `pva_context(attempts)` returns `psdaq.sim.pvwait.context(attempts, who='daq_sim')` (`psdaq/psdaq/sim/pvwait.py:46-61` at e223e91cb, F12's fix): the same loop, the same condition (only the exact message, at most 10 attempts, any other error and the last attempt's raised) and the same message; only the time stamp of the retry line differs. At e223e91cb the daq_sim path absorbed 23 injected bind failures (11 + 12 retry lines, 0 `RuntimeError`) in two programs runs with R6's shim at P=0.3, both `MATRIX PASS (8 assertions)` (F12's witness runs). | before: 10/10 cycles failed at 946ef0ff1 on sdfada016 with reproducer R6, which is fault injection: an `LD_PRELOAD` shim fails the cycle's UDP6 binds with probability P=0.3 (each failed cycle has exactly one `RuntimeError: Unable to bind random UDP6 port`). Natural: seen once in >= 515 cycles of this work (cee776d3c, sdfada016, F1's after-fix loop, try 9); seen a second time on 2026-11-11 23:56:44Z at another site, the preflight's p4p leak probe (F12) | 30: R6 at 1f56dd354 on sdfada016, 30/30 `MATRIX PASS (7 assertions)`, 0 `RuntimeError: Unable to bind random UDP6 port`; 158 injected bind failures, 158 retry lines, all absorbed | (1 - 10/10)^30 = 0 < 0.05. Without the retry, a cycle makes about 12 Contexts (inferred from the retry count), so at P=0.3 it would survive with 0.7^12 = 0.014 | PR #57 (fix/f6-f7-f8) |
| F7 | in `programs/pmlogs/.../*:hpsbldcpa.log` (hpsBldCopy): `Timeout getting the value of PV DAQ:SIM:HPSEX:PAYLOAD`, then `std::future_error` ... `Future already retrieved`, killed by signal 6; the matrix then has `FAILED programs/checks: ... gui witness: FAIL hpsBldCopy received 0 packet(s) on 239.254.34.1:31452` | REPORTED | Production: `EpicsPVA::getComplete` (`psdaq/psdaq/epicstools/EpicsPVA.cc:129-142`) can be called once only (it takes its promise's future); `PVBase::ready()` (`psdaq/psdaq/epicstools/PVBase.hh:17`) calls `getComplete()`, which waits 30 s (`EpicsPVA.hh:209`), and hpsBldCopy polls `ready()` in loops until its PVs answer (`psdaq/psdaq/app/hpsBldCopy.cc:142-148`, `:153-158`), so a PV that does not answer within the first call's 30 s makes the next call throw `std::future_error`, and hpsBldCopy aborts. procmgr starts hpsBldCopy together with the servers of its PVs (hpsBldServer, bldcas), so a late server is the trigger. Late: the PVA client (pvAccessCPP 7.1.6, `src/remote/channelSearchManager.cpp:62-63`, `:99`, `:356-359`) searches again for a channel it has not found at about 14.4-16 s and 28.8-32 s after it made it, so a server that comes up after the search near 15 s is next searched for near 30 s, around the end of the 30 s wait: with hpsBldServer serving 16 to 18 s after the start, hpsBldCopy aborted in 3 of 5 runs; with it serving 26 s or later, in 17 of 17. Sim-side work-around (667dc551c on fix/f7-hps-start, in P): `daq_sim up --hps` starts hpsBldCopy behind `psdaq.sim.pvwait`, which waits up to 120 s (`HPS_PV_WAIT`) for its five PVs and then execs it (same PID); on a timeout it prints `pvwait: timeout <PV>` and exits 1. pvwait reads each PV once; a PV whose server exits afterwards is not covered: with bldcas stopped, hpsBldServer itself exits 12-19 s after its start (`hps_connect`, `psdaq/psdaq/pyhpsbld/pyhpsbld.py:175-183`, gets `<base>:ADDR` and its `TimeoutError` ends in `throw` at `psdaq/psdaq/app/hpsBldServer.cc:64-70`: `terminate called after throwing an instance of 'char const*'`, exit status 6), and hpsBldCopy still aborts. The production abort remains, written up as issue #55. | induced with reproducer R7 at 0448b6c5c: 17/17 aborts with hpsBldServer (`hpsbldsvc`) stopped >= 20 s at its start (40 s 10/10, 25 s 2/2, 20 s 5/5); stopped 10 s 0/2 (f7b10a, f7b10b), stopped 5 s 1/2 (f7b05a aborted, f7b05b passed); also 3/3 with bldcas stopped 40 s (`... PV DAQ:SIM:HPSEX:ADDR`). Natural: 2, both programs runs at 0448b6c5c in the slow period of 2026-11-11 (from ~17:54Z): q1, the full check before F6's merge (`MATRIX FAIL (3 of 201 assertions failed)`), and a programs run on sdfada016; 2 of the 4 programs runs at 0448b6c5c in that period, 0 of 34 programs runs at other commits (s1 at def58eaf8, p1 at cee776d3c, the 30 F5 runs at def58eaf8, and 2 at 5257855b1 in the slow period). Whether 0448b6c5c's one-Context-per-process raised the rate is not established (2 of 4 against 0 of 2 in the same period, Fisher p = 0.40; the HPS chain searches on its own port, not `daq_sim`'s) | with the work-around, R7 at P (a94d89310): hpsBldServer stopped 20 s, 0 aborts in 10 counted (f7s01-f7s09, f7s11; each `MATRIX PASS (8 assertions)`, pvwait read PAYLOAD 26.0-34.3 s after the start; f7s10 not counted: its preflight failed, F11, nothing started); bldcas stopped 20 s, 3/3 aborts (f7c01-f7c03, on `:PAYLOAD`, hpsBldServer having exited first, `MATRIX FAIL (2 of 8 assertions failed)`); guardrail f7g01, hpsBldServer stopped 150 s: `pvwait: timeout DAQ:SIM:HPSEX:PAYLOAD`, exit status 1, `MATRIX FAIL (2 of 8 assertions failed)` | - (not FIXED: the production abort is unfixed and still happens at P, 3 of 3 with bldcas stopped) | PR #57 (fix/f6-f7-f8); issue #55 |
| F8 | in the programs run's matrix log: `ami check FAIL ["ami_count <N> != 4096 events in AMI's rows", "ami_pixsum ... != psana2 sum ... over the events AMI saw"]` (e.g. N = 4295) | FIXED | `psdaq/psdaq/sim/ami_check.py:44` (`MAX_ROWS = 4096`) sizes the RollingBuffer that keeps AMI's per-event rows (`:67-68`, `N=MAX_ROWS`); when AMI sees more events than that, the buffer keeps 4096 and the count no longer matches psana2's. AMI sees events for as long as Running lasts, and in the programs run Running lasts as long as the AMI screenshot takes (`cycle --ami-shot`): 37 s (s1), 42 s (p1), 65 s (q1), 94 s (a run at 0448b6c5c) on 2026-11-11 as the shared environment slowed; beyond ~85 s AMI sees more than 4096. Fix (a94d89310, P): `MAX_ROWS = 16384`, which moves the cliff ~4x, to ~6 min of Running; the check itself is unchanged (the same counts are compared), so it is not weakened. A run beyond 16384 events was not shown by a run. | before: 5/5 with reproducer R8 at P^ 63a552b3f (f8b01-f8b05: `ami_count <N> != 4096 events in AMI's rows` with N = 5578, 5061, 6478, 4807, 5540; Running 101.9-144.3 s; `MATRIX FAIL (2 of 8 assertions failed)`; f8b05's stop lasted 86.8 s, not 70 s). Natural: 8 of 42 AMI checks (`ami_check.json`) failed, all saturated at 4096 rows; the 34 passes had 1747-3918 rows | 10: R8 at P (a94d89310), f8a01, f8a03-f8a07, f8a09-f8a11, f8a13: 4526-6516 events each, all matched, ami check PASS, `MATRIX PASS (8 assertions)`. Not counted: f8a02 (ami check PASS with 5677 events, but `MATRIX FAIL (1 of 8 assertions failed)` from dtica's `malloc(): unaligned tcache chunk detected` before Running, F10's symptom); f8a08 (preflight failed, F11, nothing started); f8a12 (4049 events: the trigger did not happen) | (1 - 5/5)^10 = 0 < 0.05 | PR #57 (fix/f6-f7-f8) |
| F9 | `FAILED psdaq/psdaq/tests/test_sim_programs.py::test_lclsBldServer_sends_its_bld_for_the_frames_tprframes_delivers` with one of three assertions (lines of the test at 5257855b1): `:721`, the packet count (`assert 200 <= 105`; also 82, 39, 142, 30, 123, 194); `:720`, 0 packets; `:718`, an empty tprframes log (`''`) | FIXED | A unit-tier test (MAINTAINING.md steps 7 and 8), not part of `daq_sim matrix`; registered because it was seen in this campaign. `psdaq/psdaq/tests/test_sim_programs.py:706-711` (at 5257855b1) starts `psdaq.sim.tprframes` and lclsBldServer, sleeps a fixed 2 s, then receives for 3 s and asserts 200 to 400 packets (`:721`); on a slow node, where Python's imports took 2.3-5.2 s, the server is not yet sending when the receive starts. Fix (63a552b3f, in P): it waits until the first packet arrives (at most 30 s; with none, it fails `lclsBldServer sent no packet within 30 s`), then counts the next 3 s as before; the bounds (200 to 400) and every other assertion are unchanged. | before: 8/10 on sdfada018 (P with the test file as at 23d8eae8b, interleaved with the after runs under the node's DAQ lock). Supporting only, not the verdict: 1/10 on sdfada016 (`AssertionError: 116`), against 0/10 after there ((1 - 1/10)^10 = 0.35). Natural: fails on S3DF ada nodes in the slow period at every commit tried: 3/3 at 0448b6c5c and 3/3 at 667dc551c (sdfada018), also at 5257855b1 and 1f56dd354 (sdfada016); passes on GitHub's runners (CI runs 43090590334, 43092623334) | 10: 0/10 failed on sdfada018 at P (a94d89310). Negative run (P's test with lclsBldServer sending to another port): fails `AssertionError: lclsBldServer sent no packet within 30 s`, on sdfada018 and sdfada016 | (1 - 8/10)^10 = 0.2^10 = 1.0e-7 < 0.05 (sdfada018 alone) | PR #57 (fix/f6-f7-f8) |
| F10 | in the programs run's dtica pmlog (`python -m psdaq.cas.dtica`): `malloc(): unaligned tcache chunk detected`, then killed by signal 6, seconds after its start | REPORTED | Cause not established (hypothesis: Qt widget calls from p4p worker threads). With faulthandler on (R10), both aborts of the loop were raised on the GUI thread, inside Qt's event loop (the main thread at `psdaq/psdaq/cas/dtica.py:241`, `app.exec_()`), while p4p worker threads were part-way through `updateTable`, which calls `setChecked` on the worker thread between its `mon.pv.get()` calls (`dtica.py:146`, `:149`); the stacks do not show a worker inside a Qt call, so the cause stays a hypothesis. Both natural aborts were on milano nodes (sdfmilan023, sdfmilan031). Not fixed here; the production code is unchanged. | natural: 2 of 212 dtica procServ starts (log count, 2026-11-11 21:55Z); reproducer R10: 2 of 400 standalone starts (0.5 %, exact 95 % interval 0.06-1.8 %), sdfmilan082, build a94d89310, 2026-11-11 22:56-23:09Z (aborts in try-0038 and try-0103, exit 134; the other 398 ended by the 15 s SIGTERM, exit 124). Fisher p = 0.61 for loop against natural | - | - (not FIXED) | issue #56 |
| F11 | in a type's or program's `preflight.log`: a probe killed by its outer timeout, `rc=124`, then either `PREFLIGHT FAIL: facility service reachable` (`python-requests rc=124 (1 would mean pswww answered)`) or `PREFLIGHT FAIL: loopback EPICS positive control failed` (the positive control's p4p or pvget); the matrix then has a `FAILED` line for that start, e.g. `FAILED types/epix100/up: exit 1: <time> daq_sim: preflight rc=1: <time> PREFLIGHT FAIL: facility service reachable  (logs/preflight.log) \| ...` From 524378805 on (one budget for all probes): `HUNG: <probe> not finished when the preflight budget ran out (PF_BUDGET=200 s, stopped after <N> s, rc=124): not read as a verdict`, then `PREFLIGHT FAIL: probe hung (not a leak verdict, not an EPICS verdict)`, exit 4 | FIXED | Cause (`psdaq/psdaq/sim/preflight.sh` at a94d89310): a probe killed by its outer timeout was read as a verdict. `:32` with `:42`: the requests probe ran under `timeout -k 2 25` and any nonzero rc was a leak, exit 1. `:77-81` with `:90` and `:94`: the positive control's pvget, caget and p4p ran under 15/15/20 s and any nonzero rc was exit 3. `:30`, `:50`, `:67` with `:31`, `:51`, `:68`: curl, the leak pvget and the leak caget counted only rc 0 as a leak, so a killed probe passed silently. The six natural failures were 4 local p4p, 1 local pvget and 1 requests, all `rc=124`; at 21:37Z, 21:58Z and 22:21Z one node each (22:21Z: sdfmilan082, the epix100 type of a full check at P), at 19:14:11-13Z three nodes. Trigger not established. Consistent with stalls of the shared filesystems: same-second stalls on three nodes are recorded (a `/sdf/group` stat of 1.2-2.3 s in the same second on sdfmilan031, sdfmilan082 and sdfada018 at 2026-11-11 23:00:01Z and 2026-11-12 00:00:01Z; 18 gaps of 2.8-5.1 s between consecutive sentinel lines, in the same second on the three nodes, 9 from 23:18:44Z to 23:38:44Z, one at 00:00:04Z and 8 from 00:07:48Z to 00:15:50Z, while a full check ran, and 11 more of 3.2-5.3 s, also in the same second on the three nodes, from 00:42:29Z to 00:48:56Z on 2026-11-12, with no full check running (the build of e223e91cb ran on sdfada016 from 00:44:56Z to 00:47:54Z; whether it caused them is not known), so the gaps are not tied to the full check), and at 21:30Z a preflight on sdfmilan031 and a `sleep 70` on sdfada018 stalled together. None of the recorded stalls reached a probe's outer timeout, and no F11 failure happened while the sentinels ran (they started at 22:55:56Z). Fix (43b3c8d40 on fix/f6-f7-f8; `probe()` at `preflight.sh:41-60` of faecb0797): all 8 probes go through `probe()`. An rc other than 124 or 137 returns at once and is read as before; 124 or 137 prints `HUNG: <probe> killed by its <N> s outer timeout (attempt <i>)` and re-runs the probe once, at most 2 re-runs per preflight; a second hang of the same probe, or a hang after those 2 re-runs, ends the preflight with exit 4, `PREFLIGHT FAIL: probe hung (not a leak verdict, not an EPICS verdict)`, and `daq_sim up` starts nothing. A leak or broken-EPICS verdict is never retried. Outer timeouts, old to new: curl 20 to 15 s, requests 25 to 45 s, leak pvget 20 to 12 s, leak p4p 25 to 20 s, leak caget 20 to 12 s, local pvget 15 to 12 s, local caget 15 to 12 s, local p4p 20 s unchanged; the probes' outer timeouts, kill graces and re-runs add up to at most 223 s, under `daq_sim up`'s 240 s (commands outside the probes, such as the env set-up, `getent`, `hostname -f` and the wait for the IOC, are not in that bound; a stall there ends in the 240 s timeout, which also starts nothing). This adds a retry to a check: at P a hung requests or leak-p4p probe gave exit 1, at faecb0797 a hang followed by a clean re-run passes; at P a hung curl, pvget or caget leak probe passed silently (arm C), at faecb0797 it is re-run and read. Revised (64d6e414f and 524378805, branch sim/preflight-slowfs-2): what is slow is starting a probe, not its network part. Starting a client loads the DAQ's conda env from the shared filesystem: importing p4p is about 3,400 stat/openat calls on S3DF's weka `/sdf/group` (mounted with `dentry_max_age_negative=0`, so the failed lookups of the import are never cached), 3.4-8.5 s in 180 runs on sdfmilan216 on 2026-11-12, 0.37 s of it CPU, while the loopback get takes 16-50 ms. F11's outer timeouts bound that start-up too, so a filesystem that stays slow for longer than one probe's outer timeout stops the probe twice: with 2.5 ms added to every file-metadata syscall (R11), the preflight at 71958f4e8 ends `HUNG: p4p killed by its 20 s outer timeout (attempt 2)`, exit 4, 5 of 5. Fix: each probe's network part keeps its own bound inside the client (curl -m 10, requests 10 s, pvget and caget -w 5, the p4p get 5 s in `psdaq/psdaq/sim/preflight_p4p.py`), and every probe runs under `timeout -k 2` with what is left of one budget for the whole preflight, `PF_BUDGET` (200 s, inside `daq_sim up`'s 240 s). A probe still running when the budget runs out is still never read as a verdict: exit 4 (exit 1 if a leak was already seen), without a re-run, as the budget is spent. A stall shorter than what is left of the budget is waited out instead of re-run. The positive control waits for its IOC's `iocRun: All initialization complete` instead of 4 s. Given up: F11's re-run of a probe frozen past its outer timeout in its network part; a client frozen in its network part past its own bound (5 s) reads as no answer, before and after this change. | natural: 6 of 788 preflights at P or earlier (0 of 625 before 19:00Z on 2026-11-11, 6 of 163 from 19:00Z to 22:45Z, at four moments); 0 of 1016 in the earlier campaign's root (inherited). Induced at P (a94d89310) by SIGSTOP from an outside watcher, on sdfada016: arm A, the requests probe stopped 26 s: 5/5 `python-requests rc=124`, exit 1; arm B, the local p4p stopped 21 s: 5/5 `p4p rc=124`, exit 3; arm C, the leak pvget stopped 21 s: 3/3 `pvget rc=124` then PREFLIGHT PASS (the fail-open the fix closes) Slow filesystem (R11 at 2.5 ms, sdfmilan216, 2026-11-13): 5/5 at 71958f4e8, each two `HUNG: p4p killed by its 20 s outer timeout` lines then exit 4, in 70.5-76.2 s; the same preflight with no delay passed (22.9 s). Natural, at 96ba26676 (before 43b3c8d40): a DAQ start of the simulated MFX hutch on sdfmilan216 on 2026-11-12 at 22:00Z, the positive control's p4p killed at 20 s with no line printed (`p4p rc=124`, exit 3); the pvget and caget before it took ~18 s for ~0.17 s of work. | 10 + 10 at faecb0797 on sdfada016, interleaved with the before runs (A-after-1..10 with the requests probe stopped 46 s, B-after-1..10 with the local p4p stopped 21 s), each one `HUNG:` line then `PREFLIGHT PASS`; arm C after (the leak pvget stopped 13 s): 3/3 HUNG, then `pvget rc=1`, PASS. Guardrails at faecb0797, all failing as they must, none retried except G4: G1 no IOC, `local pvget rc=1 caget rc=1 p4p rc=1`, exit 3; G2 IOC frozen 60 s, exit 3; G3 a production-looking PV served on loopback, `LEAK: pvget got DAQ:NEH:XPM:0:PART:5:Master` at the first attempt, exit 1; G4 every requests instance stopped, 2 `HUNG:` lines, `PREFLIGHT FAIL: probe hung`, exit 4; G5 the same through `daq_sim up`, `up FAILED: preflight failed: not starting anything`. Natural: 0 `HUNG:` lines in 96 preflights (64 in the two full checks at faecb0797, 32 in full-check run 1 at e223e91cb), and 0 in the 160 of the five full checks at 82a2868fe, so the retry has not fired in a real run. At e223e91cb (F12's fix changed the p4p probes) the subset was rerun with the same verdicts: A-after rc 0 with 1 `HUNG:` then PASS, B-after rc 0 with 1 `HUNG:` then PASS (the stopped process was the new `pvwait.context` probe), G1 rc 3, G3 rc 1, G4 rc 4 with 2 `HUNG:` in 90.2 s. 82a2868fe (F13's fix) leaves `preflight.sh` unchanged and changes only the docstring of `pvwait.context` (`git diff e223e91cb 82a2868fe -- psdaq/psdaq/sim/preflight.sh` is empty), so that evidence carries At 524378805 on sdfmilan216 (2026-11-13): R11 at 2.5 ms 10/10 `PREFLIGHT PASS` with no `HUNG:` line, in 108.5-116.6 s; the client frozen by an outside watcher from its start, as F11's arms: the local p4p 21 s and 90 s, the leak p4p 46 s, the leak pvget 13 s, each `PREFLIGHT PASS` with no `HUNG:` line. Unchanged verdicts there: G3 exit 1 (also with `PF_BUDGET=8`, which stops a later probe: one `HUNG:` line, then exit 1); step 4's clients pointed at a wrong port or address, exit 3; `PF_BUDGET=12`, `HUNG: p4p ...`, exit 4; F12's R12 below. With a simulated hutch up on the node: 60 runs of step 4 and 5 whole preflights, 0 `HUNG:` lines. | (1 - 5/5)^10 = 0 < 0.05 for each of arms A and B. Limits: a probe that hangs twice, or a third hang in one preflight, still fails the run with exit 4. Not shown by a run: rc 137; the hang-after-2-re-runs branch; the curl, leak-p4p, caget, local-pvget and local-caget probes under the watcher; the 223 s worst case; the 240 s timeout path of `daq_sim up` R11: (1 - 5/5)^10 = 0 < 0.05. | PR #57 (fix/f6-f7-f8) ; branch sim/preflight-slowfs-2 (R11, the budget) |
| F12 | in a type's `preflight.log`, at `2b. p4p (pvxs) client get`: a traceback ending `RuntimeError: Unable to bind random UDP6 port`, then `p4p rc=1`, `LEAK: p4p got DAQ:NEH:XPM:0:PART:5:Master (or probe broke)`, `PREFLIGHT FAIL: facility service reachable`; the matrix then has `FAILED types/drp_gpu:epixuhr3x2/up: exit 1: ... daq_sim: preflight rc=1: ... PREFLIGHT FAIL: facility service reachable  (logs/preflight.log) \| ...` and `FAILED coverage: ... failing rows: det:drp_gpu:epixuhr3x2`. From e223e91cb on, only after 10 failed binds in a row: 9 lines `preflight p4p: PVA client context: Unable to bind random UDP6 port (attempt <n> of 10), retrying`, then `p4p probe broke: RuntimeError Unable to bind random UDP6 port`, `p4p rc=2` | FIXED | F6's error (PVXS 1.2.1 `client.cpp:547-563`, see F6) at another site: the preflight's own p4p probes make a bare `Context('pva')` (`psdaq/psdaq/sim/preflight.sh:99`, the leak probe, and `:125`, the positive control, at faecb0797), outside F6's `pva_context()` retry, and `preflight.sh:108` reads any nonzero rc of the leak probe as a leak (`(or probe broke)`), so the bind race failed the preflight with exit 1 and nothing was started. Also bare at faecb0797, not seen failing: `psdaq/psdaq/sim/gui_witness.py:920`, `psdaq/psdaq/webgui/events.py:163`, `psdaq/psdaq/webgui/plots_api.py:299`, `psdaq/psdaq/webgui/pvgui_api.py:86`. Seen once: full check run 2 at faecb0797 (mx-h2, 2026-11-11 23:56:44Z, sdfada018, the drp_gpu epixuhr3x2 type; `MATRIX FAIL (2 of 196 assertions failed)`); the sentinel on sdfada018 at that time had `group_stat` at most 0.032 s and `sleep_over` at most 0.001 s, so not a stall. Fix (e223e91cb on fix/f6-f7-f8, sim code only): every p4p client Context made by code under `psdaq/psdaq/sim` comes from `psdaq.sim.pvwait.context` (`psdaq/psdaq/sim/pvwait.py:46-61` at e223e91cb), F6's bounded retry with an optional `conf`: only `RuntimeError` with exactly `Unable to bind random UDP6 port`, at Context creation, at most 10 attempts, no sleep, one stderr line per retry (`<who>: PVA client context: Unable to bind random UDP6 port (attempt <n> of 10), retrying`); any other error and the 10th failure are raised. Its four callers: `daq_sim.pva_context`, `gui_witness.pva_context`, and preflight's leak p4p probe and positive-control p4p probe. This adds a retry to a check: at faecb0797 one failed bind failed the preflight (exit 1 or 3); now up to 9 in a row per context are absorbed. Other changes: a broken leak probe exits 2 with `p4p probe broke: <type> <text>` (still read as a leak, exit 1); the positive control prints all its output (it kept the last 2 lines); the probes import `psdaq.sim.pvwait` from the build, so without a built psdaq (or with an older build) the leak probe exits 1, `facility service reachable` (fail-closed, but the message misleads). Not covered: the web GUI's contexts (`psdaq/psdaq/webgui/events.py:163`, `plots_api.py:299`, `pvgui_api.py:86`; the full check does not start the web GUI), the tests' own (`test_sim_hsd.py:35`, `:62`, `test_simxpm.py:333`, `webgui/tests/webgui_harness.py:433`, `pvgui_checks.py:236`), and the DAQ programs' own contexts (production code). From 64d6e414f both p4p probes are `psdaq/psdaq/sim/preflight_p4p.py`, which takes `pvwait.context` from the `pvwait.py` next to it instead of `psdaq.sim.pvwait` from the build (the import-failure path above is gone) and prints `p4p probe broke: <type> <text>`, exit 2, on any other error. | before: R12 (P=0.3 on the two p4p probe pythons) at faecb0797 on sdfada016: 6/10 standalone preflights failed (before-7, 8, 9 exit 1, `LEAK: p4p got ... (or probe broke)`; before-4, 5, 10 exit 3, the positive control's `p4p rc=1`), each failing run with exactly one injected bind and one `RuntimeError: Unable to bind random UDP6 port`; per injection, 6 of 6 fatal. before-4 overlapped a sanity test of the shim on the node; without it 5/9. Natural: 1 of 852 preflights (each makes 2 p4p contexts), 1 of 64 at faecb0797 | 10 at e223e91cb on sdfada016, the same shim and scope: 10/10 `PREFLIGHT PASS`, exit 0; 7 injected binds in 4 runs (1, 1, 1, 4), 7 retry lines, 0 `RuntimeError`; per injection, 7 of 7 absorbed. The two arms ran as two blocks (00:46-00:57Z, then 00:57-01:05Z on 2026-11-12), not interleaved. Guardrails at e223e91cb, failing closed as they must: P=1.0 (g-p1-1), the leak probe 9 retry lines, `p4p probe broke: RuntimeError Unable to bind random UDP6 port`, `p4p rc=2`, `LEAK: ... (or probe broke)`, the positive control 9 retry lines then its traceback, `p4p rc=1`, exit 1; no shim (g-plain), `PREFLIGHT PASS`; `gui_witness.pva_context` at P=1.0 raised `RuntimeError` after 10 attempts (4.43 s), exit 1; F11's G3 (a production-looking PV served on loopback) still `REACHED DAQ:NEH:XPM:0:PART:5:Master`, `p4p rc=1`, exit 1. Witness path: two `daq_sim matrix --only programs` runs with R6's shim at P=0.3 in the `daq_sim cycle` process, `MATRIX PASS (8 assertions)` both (5161 and 5304 events), gui_witness 1 + 1 and daq_sim 11 + 12 retry lines, 0 `RuntimeError`. Not shown by a run: a natural bind failure at this head (0 retry lines in full-check run 1 at e223e91cb and its 32 preflights, and 0 in the 160 preflights of the five full checks at 82a2868fe), the import-failure path, exit 3 alone at P=1.0, the retry inside `daq_sim up`'s own preflight. 82a2868fe (F13's fix) changes only the docstring of `pvwait.context`, not `preflight.sh` or `gui_witness.py`, so this evidence carries At 524378805 on sdfmilan216 (R12 with the wrapper matching `*/preflight_p4p.py`): 10/10 `PREFLIGHT PASS` at P=0.3, 4 injected binds in 3 runs (2, 1, 1), 4 retry lines, 0 `RuntimeError`, the shim active in 2 processes per preflight; P=1.0: exit 1, `p4p probe broke: RuntimeError Unable to bind random UDP6 port` from both probes (`p4p rc=2`), 18 retry lines. | (1 - 6/10)^10 = 1.05e-4 < 0.05 (without before-4: (1 - 5/9)^10 = 3e-4) | PR #57 (fix/f6-f7-f8) |
| F13 | in the type's `control` pmlog: `<W> drp/tt_0 did not respond to rollcall`, then `<E> at least one DRP is required`; the matrix then has `FAILED types/tt/transitions: setState allocated -> unallocated; status stream error: at least one DRP is required; status stream error: alloc failed to change state; never reached running` (and `counts`, `per-event`, `evidence`, `coverage` after it); the DRP's own pmlog stops in its detector's init (tt: at the first `ConfigLclsTimingV2()`, no `Ready for transitions`). From 82a2868fe on: `up FAILED: <alias> not ready for transitions after 180 s: its detector's init ...`, or `... (not RUNNING): ...` for a DRP that died | FIXED | Control's rollcall waits 30 s (`--rollcall_timeout`, default 30, `psdaq/psdaq/control/control.py:2615` at 82a2868fe) and finds only a DRP that says `Ready for transitions` (printed once its detector's init has returned: `PGPDetectorApp.cc:376`, `drpGpu/PGPDetectorApp.cc:214`, `PvaDetector.cc:1191`, `UdpEncoder.cc:1206`, `epicsArch.cc:394`, `BldDetector.cc:1153`). `daq_sim up` waited for that line only for types with `ready_s` (`psdaq/psdaq/sim/daq_sim.py:1347-1348` at e223e91cb; the GPU types and epixuhr3x2, whose same failure was fixed the same way earlier) and only for the `--det` type's aliases (`:1617`); `daq_sim cycle` then starts rollcall 7 to 12 s after `procmgr start`. So a DRP of any other type whose init took more than about 40 s missed rollcall. Seen once naturally on a type without `ready_s`: full-check run 1 at e223e91cb (2026-11-12 00:53:40Z-01:32:51Z, `MATRIX FAIL (5 of 201 assertions failed)`), tt on sdfmilan082, `procmgr start` 17:05:20.399 (US Pacific), rollcall 17:05:31.592, `drp/tt_0 did not respond to rollcall` 17:06:01.615, tt_0 alive and still in its Python configuration. tt's start on sdfmilan082 had been getting slower all day (table below); the slow part is tt's Python (the seed step, a separate process, slowed the same way), not the DRP binary; the cause of the slowdown is not established (ruled out: a change of the surf tree tt uses, `.pyc` files, the sentinel's `/sdf/group` stat, any code change to the seed step). In 13 of 1954 control logs of this campaign and the earlier one: 7 natural slow starts (6 of them of types that since got `ready_s`), 1 induced, 5 after the process had died. Fix (82a2868fe on fix/f6-f7-f8, sim code only): `daq_sim up` calls `_wait_drps_ready` for every type (`daq_sim.py:1373-1374` at 82a2868fe) for every DRP alias, chosen by role (`drp_aliases`, `:527`: the type's segments, the `--also` DRPs, `pvcam_0`, `epics_0`, `encoder_0`, `bld_0`; not `ami-node_0`, `ami-worker_0`, `pvrtmon_0` or the event builders), for up to `DRP_READY_S` = 180 s (`:126`) or the type's own `ready_s` where that is longer (GPU types 300 s, epixuhr3x2 180 s), and prints `<alias> ready for transitions after N s` for each. Control's arguments and every assertion are unchanged. What the check gives up is an accidental bound: a DRP Ready within about 40 s of its start; the wait covers a start of up to 180 s, and the printed N keeps the time visible (at H, in the five full checks, a fast period, tt on sdfmilan082 seeded in 4.4/4.9/4.4/4.7/4.6 s and was ready after N = 2/2/2/5/2 s: those runs do not show the wait under a natural slow start; the 45 s stop arm does) (MAINTAINING.md step 10, "What the gate cannot see"). Separately, the seed step's fixed 60 s timeout (`daq_sim.py:1172` at e223e91cb), which tt's seed was approaching (43.4 s), is 240 s (`SEED_TIMEOUT_S`, `:129`), and a seed past it now fails `up` with `configdb_seed of <det> segment <n> not done after 240 s: <its stderr tail>` (`:1195`) instead of an uncaught `TimeoutExpired`. tt's start on sdfmilan082, as `preflight PASS` to `config DB seeded` and rollcall start to tt_0's answer: def58eaf8 08:52Z 6.2 s / 1.27 s; cee776d3c 16:17Z 6.4 / 1.55; 0448b6c5c 18:14Z 15.2 / 3.66; a94d89310 22:24Z 20.1 / 16.53; faecb0797 23:23Z 29.2 / 20.04; faecb0797 00:01Z 40.6 / 29.985; e223e91cb 01:05Z 43.4 / miss; e223e91cb, tt alone (`--only types --types tt`), 01:50Z, 01:52Z, 01:55Z 36.9 / 26.7, 36.0 / 26.5, 35.8 / 26.1 (all three `MATRIX PASS (7 assertions)`); 82a2868fe, full-check run 1, 02:21Z 4.4 s, Ready 8.1 s after `procmgr start` (N = 2 s) (in the earlier root on 2026-11-09: 0.97-3.74 s in 26 runs, 17 on sdfmilan082) | induced at e223e91cb on sdfada016 (job 44243826): fakecam's drp SIGSTOPped from its first appearance for 45 s by an outside watcher (it matches the drp by its command line and the work dir's environment tag, and logs the pid): 5/5 `drp/fakecam_0 did not respond to rollcall`, `at least one DRP is required`, `MATRIX FAIL (4 of 7 assertions failed)`, exit 1. A secondary DRP (the programs run's `epics_0`, epicsArch) stopped the same way: 2/2 `drp/epics_0 did not respond to rollcall`, the run went on without it and failed its system DRP checks (`no stream has the epicsArch variables sim_count/sim_const`), `MATRIX FAIL (2 of 8 assertions failed)`. Natural: 1 (above) | 10 at 82a2868fe on sdfada016 with the same 45 s stop: 10/10 `MATRIX PASS (7 assertions)`, exit 0, each with `fakecam_0 ready for transitions after N s`, N = 46, 46, 46, 46, 44, 45, 46, 45, 45, 45; DAQ = psana2 = with-data, 1669 to 2799, per-event PASS. The secondary DRP stopped 45 s in the programs run: `epics_0 ready for transitions after 42 s`, `MATRIX PASS (8 assertions)`. tt not stopped, 3/3 `MATRIX PASS (7 assertions)`, N = 2 s each (on sdfada016; tt's slow start was on sdfmilan082). Guardrails at 82a2868fe: the drp stopped and never continued, `up FAILED: fakecam_0 not ready for transitions after 180 s: its detector's init ...` 185.8 s after `procmgr start`, `down: clean`, `MATRIX FAIL (1 of 2 assertions failed)`, exit 1; the drp stopped at once and SIGKILLed 6.0 s after its appearance, `up FAILED: fakecam_0 not ready for transitions (not RUNNING): ...` 0.8 s after the kill, exit 1. (A SIGKILL 6.1 s after appearance without the stop came after fakecam was Ready and failed the cycle instead: `fakecam_0 did not respond to alloc`, `MATRIX FAIL (5 of 7 assertions failed)`.) Every DRP's N in full-check run 1 at 82a2868fe (`MATRIX PASS (201 assertions)`): 0-2 s for most; epixquad1kfps 10, epixUHR 10, epixquad 10, epixm320 11, epixhr2x2 8, epix100 5, wave8he 5, epixuhr3x2 52 (drp_gpu: 51) | (1 - 5/5)^10 = 0 < 0.05 (with 4 of 5 it would be 0.2^10 = 1e-7). The natural rate has no stationary value: tt's start climbed through seven full checks and then was fast again (4.4 s seed at 02:21Z); covers a start of up to 180 s | PR #57 (fix/f6-f7-f8) |

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

**R10 (F10).** Standalone dtica starts, as in issue #56 ("Steps to Reproduce"): the DTI PV
stand-in, then dtica started 400 times, 8 at a time, each stopped with SIGTERM after 15 s:
```bash
mkdir -p $WD/logs && cd $WD
EPICS_PVAS_SERVER_PORT=31354 EPICS_PVAS_BROADCAST_PORT=31355 EPICS_PVA_BROADCAST_PORT=31355 \
  python -m psdaq.sim.simdti -P DAQ:SIM:DTI > simdti.log 2>&1 & S=$!
until grep -q 'simdti: ready' simdti.log; do sleep 1; done
one() { env QT_QPA_PLATFORM=offscreen EPICS_PVA_ADDR_LIST=127.0.0.1 EPICS_PVA_AUTO_ADDR_LIST=NO \
          EPICS_PVA_BROADCAST_PORT=31355 \
          timeout -s TERM 15 python -X faulthandler -m psdaq.cas.dtica DAQ:SIM:DTI >> logs/try-$1.log 2>&1
        echo "# exit $?" >> logs/try-$1.log; }
export -f one; seq 400 | xargs -P 8 -I{} bash -c 'one {}'
kill $S
grep -h '^# exit' logs/*.log | sort | uniq -c
grep -l -E '^# exit 134|malloc\(\)' logs/*.log
```
The measured loop ran this in a step of its own on a milano node, under the node's DAQ lock
(`srun ... --cpus-per-task=16 --mem=32G timeout -k 10 2700 flock -w 600 $LOCK bash loop.sh <out> 400 8 15 1`),
with the environment procServ gives dtica in the sim (build a94d89310). Expected: exit 124 (the
SIGTERM) for nearly every start; an abort is exit 134 with `malloc(): unaligned tcache chunk
detected` in its log, a few seconds after `This plugin does not support propagateSizeHints()`
(2 of 400 on sdfmilan082).

**R11 (F11), a slow filesystem.** strace's fault injection adds 2.5 ms to every file-metadata
syscall of the preflight and of all its children (python, curl, pvget, caget, softIocPVA); nothing
else on the node is slowed and no root is needed. Run it on its own on the node (the preflight's
ports 15064-15076 are fixed):

```bash
INJ='strace -f -qq -o /dev/null -e trace=stat,lstat,newfstatat,openat,getdents64 -e inject=stat,lstat,newfstatat,openat,getdents64:delay_enter=2500'
cd $WT && source ./setup_env_daq.sh
for i in $(seq 10); do t=$SECONDS; $INJ bash psdaq/psdaq/sim/preflight.sh > $WD-$i.log 2>&1
  echo "try $i rc=$? $((SECONDS - t)) s HUNG $(grep -c 'HUNG:' $WD-$i.log) $(tail -1 $WD-$i.log)"; done
```

Expected at 71958f4e8: rc 4 with two `HUNG: p4p killed by its 20 s outer timeout` lines (70.5-76.2 s
on sdfmilan216); at 524378805: rc 0, `PREFLIGHT PASS`, no `HUNG:` line (108.5-116.6 s). Without the
delay both pass in 19-38 s.

**R12 (F12), fault injection.** R6's shim with another scope: `udp6fail2.so` is `udp6fail.c` above
with its constructor's test changed, so that it is active only in a process started with
`UDP6FAIL_ACTIVE` in its environment, and every process it loads into removes `LD_PRELOAD` and
`UDP6FAIL_ACTIVE` (no child inherits it). Replace the five lines from `int is_cycle` to
`if (!is_cycle) return;` with:

```c
    int want = getenv("UDP6FAIL_ACTIVE") != NULL;
    unsetenv("LD_PRELOAD");                          /* nothing below this process inherits the shim */
    unsetenv("UDP6FAIL_ACTIVE");
    if (!want) return;
```

and build it as `$ROOT/work/udp6fail2.so`. A `python` wrapper first on `PATH` loads it only into
preflight's two p4p probe pythons (`python - DAQ:NEH:...`, the leak probe, and `python -c
...SIMW3...`, the positive control's; from 64d6e414f on both are `python <sim dir>/preflight_p4p.py
timeout|get <PV>`, so the wrapper's test is `[[ "$1" == */preflight_p4p.py ]]`); the preflight runs
on its own, under the node's lock:

```bash
O=$ROOT/work/f12-r12; mkdir -p $O/bin; REAL=$(command -v python)
printf '%s\n' '#!/bin/bash' \
  'if [[ ( "$1" == - && "$2" == DAQ:NEH:* ) || ( "$1" == -c && "$2" == *SIMW3* ) ]]; then' \
  "  export LD_PRELOAD=$ROOT/work/udp6fail2.so UDP6FAIL_ACTIVE=1" \
  'fi' "exec $REAL \"\$@\"" > $O/bin/python
chmod +x $O/bin/python
cd $WT
for i in $(seq 10); do
  UDP6FAIL_P=0.3 UDP6FAIL_LOG=$O/inject-$i.log PATH=$O/bin:$PATH \
    flock -w 600 $LOCK bash psdaq/psdaq/sim/preflight.sh > $O/pf-$i.log 2>&1
  echo "try $i rc=$? injected $(cat $O/inject-$i.log 2>/dev/null | wc -l)" \
       "retried $(grep -c 'PVA client context: .*retrying' $O/pf-$i.log)" \
       "RuntimeError $(grep -c 'RuntimeError: Unable to bind random UDP6 port' $O/pf-$i.log)" \
       "$(grep -o 'PREFLIGHT [A-Z]*' $O/pf-$i.log | tail -1)"
done
```

Expected before the fix (faecb0797): a failed preflight (rc 1 with `LEAK: p4p got ... (or probe
broke)`, or rc 3) in every try that had an injection (6/10 at `UDP6FAIL_P=0.3`). After it
(e223e91cb): rc 0 and `PREFLIGHT PASS` in every try, as many `retried` as `injected`. With
`UDP6FAIL_P=1.0` the preflight must still fail: rc 1, with `p4p probe broke: RuntimeError Unable to
bind random UDP6 port`. (The measured runs set `UDP6FAIL_P` and `UDP6FAIL_LOG` in the wrapper and
listed every process that mapped the shim: only the two probe pythons.)

## How to add a row

1. Take the next id (F14, ...). Copy the first line of the failure from the log that has it
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
