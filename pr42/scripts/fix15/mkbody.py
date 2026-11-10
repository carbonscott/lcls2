#!/usr/bin/env python3
"""mkbody.py OLD_BODY ASSETS OUT: PR #42's body at H (b14885af3) from the body at 7695dfdae (proof15's), the matrix
summaries of runs h1 and h2 at H and m2 at 7695dfdae, and the texts below."""
import json, os, re, sys

old_path, A, out = sys.argv[1:4]
OLD = open(old_path).read().split('\n')
def L(a, b):                     # old body lines a..b, 1-indexed, inclusive
    return '\n'.join(OLD[a - 1:b])
def oldline(prefix):
    return next(l for l in OLD if l.startswith(prefix))

H, HS = 'b14885af349db9d58d24f6a5670e925286b3737b', 'b14885af3'
PA = 'https://github.com/carbonscott/lcls2/blob/pr-assets/pr42'
RAW = 'https://raw.githubusercontent.com/carbonscott/lcls2/pr-assets/pr42'
h2 = json.load(open(os.path.join(A, 'matrix-summary-h2.json')))
h1 = json.load(open(os.path.join(A, 'matrix-summary-h1.json')))
m2 = json.load(open(os.path.join(A, 'matrix-summary-m2.json')))
assert h2['sha'] == H and h1['sha'] == H

def teb(t):
    for a in t.get('assertions', []):
        if a['name'].endswith('/counts'):
            m = re.search(r'TEB_WrtCt (\w+)', a['detail'])
            return m.group(1) if m else None
def cnt(t):
    return str(t.get('daq')) if t.get('pass') else '**FAIL**'

rows = []
for k, t in h2['types'].items():
    drp, typ = k.split(':') if ':' in k else ('drp', k)
    node = t['node'].replace('sdf', '')
    ok = t.get('pass')
    h1t, m2t = h1['types'].get(k, {}), m2['types'].get(k, {})
    rows.append(f"| {typ} | {drp} | {node} | **{t.get('daq')}** | {teb(t)} | {t.get('psana2')} | {t.get('with_data')} | "
                f"{t.get('per_event')} | `{t.get('evidence') or '-'}` | {cnt(h1t)} | {cnt(m2t)} |" if ok else
                f"| {typ} | {drp} | {node} | **FAIL** | - | - | - | - | - | {cnt(h1t)} | {cnt(m2t)} |")
p = h2['programs']
rows.append(f"| **programs run** (fakecam_0 + the MEB, AMI, system DRPs, GUIs, PV servers) | drp | {p['node'].replace('sdf', '')} | "
            f"**{p.get('daq')}** | {teb(p)} | {p.get('psana2')} | {p.get('with_data')} | {p.get('per_event')} | "
            f"`{p.get('evidence')}` (42 rows) | {cnt(h1['programs'])} | {cnt(m2['programs'])} |")
TABLE = ('| type | DRP | node | DAQ | TEB_WrtCt | psana2 | with data | per-event | evidence record (h2) | h1 | m2 |\n'
         '|---|---|---|---|---|---|---|---|---|---|---|\n' + '\n'.join(rows))

def rep(f, key):
    for l in h2['features'][f]['report']:
        if key in l:
            return l
    return ''
cov = h2['coverage']
COV = cov['assertions'][0]['detail']
n_pass = sum(1 for a in h2['assertions'] if a['ok'])
n_all = len(h2['assertions'])
EXIT = h2['exit']
GPU_WAIT = open(os.path.join(A, 'logs', 'h2', 'ready-h2.txt')).read().strip()
V = json.load(open(os.path.join(A, 'logs', 'h2', 'vals.json')))       # times, steps, counts filled by hand from the logs

body = f"""{OLD[0]}
## Motivation

{L(4, 4)}

{L(6, 6)}

{L(8, 12)}
- **After review** (three commits on 7695dfdae): d136e1b25 makes `daq_sim up` wait for every `drp_gpu` type's `Ready for transitions` (only epixuhr3x2 waited, so a slow CUDA start on a shared GPU made the others miss control's rollcall); d50c276a7 makes coverage take a record as one run, so another run's files and witness can no longer be added to a record unchanged; b14885af3 adds what a first-time reader of the docs had to guess (below).

{L(14, 23)}

{L(25, 25)}

## How to test the behavior?
```
{L(29, 35)}
python -m pytest -q psdaq/psdaq/tests/test_sim*.py psdaq/psdaq/webgui/tests/test_walk_guard.py    # 420 passed, 1 skipped
# THE matrix: one step on A (RUNBOOK 3p, "Everything, over every node of the campaign"; mx.sh in the assets is this run's copy):
srun --jobid=$JOB --overlap -w A --ntasks=1 --cpus-per-task=16 --mem=32G bash mx.sh h2 G $GJOB
{L(39, 41)}
#   -> MATRIX PASS (201 assertions), MATRIX_EXIT=0 when every assertion passes (at this head h1 failed 3 and h2 1 of 201:
#      see Proof); one TYPE line per type (26), PROGRAMS, FEATURE a..e, coverage: 78 rows, 63 run, 6 stand-in, 9 N/A, 0 unproven
{L(44, 48)}
```

## Proof it works

Ran on S3DF at **{H}** (pr/final, this PR's head: 7695dfdae plus three commits, committed 2026-11-10 03:28:49Z), on 2026-11-10 03:29-{V['end']} UTC: sdfmilan023 and sdfmilan082 (milano, Slurm job 44000948), the GPU DRP's types on sdfada010 (run h1, job 44062096) and sdfada013 (run h2, job 43970564), one NVIDIA L40S each. Steps: the build (sdfada010 step 1), the unit tests (sdfmilan082 steps 344 and 347), matrix run h1 (sdfmilan023 step 350), the breaks (sdfmilan023 step 366), matrix run h2 (sdfmilan023 step {V['h2_step']}), the coverage negatives and forgeries (sdfmilan023), CUDA init timings (sdfada010 steps 3 and 5, sdfada013 step 283). The DAQ env was `daq_20250402_r9` (Python 3.9.21); every script sources `setup_env_daq.sh` and then `sim_env.sh` ([scripts]({PA.replace('/blob/', '/tree/')}/scripts), [this run's]({PA.replace('/blob/', '/tree/')}/scripts/fix15)).

> **Result: THE matrix did not exit 0 at this head, but every one of its 201 assertions passed in one of its two runs here.** Run h2 (the GPU DRP's types on sdfada013): `MATRIX FAIL (1 of 201 assertions failed)`, `MATRIX_EXIT=1`. All 21 `drp` types and all 5 `drp_gpu` types passed, the programs run, features a, b, d and e, and coverage: **`{COV}`**, so every row has evidence at this head. Feature c failed only on `MEB_EvtCt None: the MEB served no event`: the matrix read none of the MEB's Prometheus counters after Disable (one read of its exporter, 3 s timeout), while in the same run the MEB did serve: shmemClient took 1060 L1Accepts from it and AMI, on the MEB, matched 1050 of 1050 events with psana2 (its screenshot PASS). Feature c passed in run h1 at this head (`MEB_EvtCt` 2422) {V['fc_diag']}. Run h1 (GPU types on sdfada010) failed 3 of 201: `drp_gpu` jungfrau's per-event check (the module stand-in's UDP packets of 5 frames were lost on the node's loopback, so 3 events differ from their frames; [DRP log]({PA}/logs/h1/drp_gpu-jungfrau-h1.log): `MemPoolSim: module 127.0.0.1:31054 sent 85 of 128 packets of frame 1`), that row's evidence and so coverage; it passed in h2. No code changed between h1 and h2. h2's GPU types ran on sdfada013, where CUDA starts slowly and d136e1b25's wait was needed ({GPU_WAIT}); before that fix, run m2 at 7695dfdae failed there (13 of 201; below). The plan allowed one rerun after a run whose only failures were GPU rows; h2 was it.

**The head.** {HS} is pr/final's last commit; the base is agentify at 5aaf09617737887aef5f196f13754d7ad6f6b98c (the merge of #41), still origin/agentify. The diff against it is 99 files (16016 insertions, 371 deletions) in 150 commits (129 not merges). Since 7695dfdae: d136e1b25, d50c276a7, {HS}, 7 files (`daq_sim.py`, `coverage.py`, their tests, `RUNBOOK.md`, the web GUI's `README.md`, `CHANGELOG.md`: 223 insertions, 45 deletions; recording 3 shows `git diff --stat 7695dfdae HEAD`). The checkout had 0 local changes (tracked or untracked) before and after each recording.

**Build and unit tests.** `build_all.sh -d -j 12` with conda-forge's CUDA 12.9 `nvcc` on PATH at {HS} on sdfada010 (step 1): `BUILD_EXIT=0`, `ninja: no work to do.` (no C++ changed since the CUDA build at c370014fc), `psdaq` reinstalled, the installed `psdaq/sim`, `webgui`, `control` and `configdb` identical to the checkout, `install/bin/drp_gpu` and 8 GPU libraries ([out]({PA}/logs/fix15/build-H.out), [log]({PA}/logs/fix15/build-H.log)). The sim unit tests and `test_walk_guard` (AMI on `PYTHONPATH`, under sdfmilan082's DAQ lock): **`420 passed, 1 skipped`, `PYTEST_EXIT=0`** (step 344, 216 s, [out]({PA}/logs/fix15/pyt-H.out); again in recording 3, step 347). The 3 new tests fail on 7695dfdae's code, run against this head's tests ([pyt-old.out]({PA}/logs/fix15/pyt-old.out): the FG3 splice is accepted, `fakecam` has no `ready_s`).

**THE matrix** (RUNBOOK §3p, "Everything, over every node of the campaign"; [`mx.sh`]({PA}/scripts/fix15/mx.sh), proof15's with only its output dir changed), one command in one step on sdfmilan023:

```
{L(64, 65)}
  --gpu-host sdfada013 --gpu-job 43970564 --gpu-gres gpu:l40s:1 --gpu-lock /tmp/agentify-daq-ada013.lock \\
{L(67, 69)}
```

| run | HEAD | GPU node | time (UTC) | result | failed assertions |
|---|---|---|---|---|---|
| m1 (recording 1) | c370014fc at start; 7695dfdae from 02:01:50Z | sdfada013 | 01:41:49-02:14:58 | `MATRIX FAIL (15 of 201 assertions failed)`, exit 1 | epixquad1kfps (5): its DRP aborted 1 s into Running, `TebContributor::_post: _pending queue overflow` ([log]({PA}/logs/m1/drp-epixquad1kfps-m1.log)); drp_gpu epixuhremu (5): Configure did not complete in 60 s, then teb0 segfaulted in libfabric at Disconnect ([drp_gpu]({PA}/logs/m1/drp_gpu-epixuhremu-m1.log)); drp_gpu jungfrau (4): no answer to rollcall, its log stops at `Global memory: 45457 MB` ([log]({PA}/logs/m1/drp_gpu-jungfrau-m1.log)); coverage: 23 rows recorded at c370014fc |
| m2 (recording 2) | 7695dfdae | sdfada013 | 02:20:30-02:48:43 | `MATRIX FAIL (13 of 201 assertions failed)`, exit 1 | drp_gpu fakecam, epixuhremu, jungfrau (4 each): `drp/<type>_0 did not respond to rollcall` ([fakecam]({PA}/logs/m2/drp_gpu-fakecam-m2.log): its log reaches `Output dir: ready` after the rollcall); coverage: those 3 rows |
| h1 (recording 3) | {HS} | sdfada010 | 03:38:33-04:08:04 | `MATRIX FAIL (3 of 201 assertions failed)`, exit 1 | drp_gpu jungfrau per-event and evidence (UDP packets of 5 frames lost on loopback; `DRP_Damage 5`); coverage: that row ([log]({PA}/logs/h1/mx-h1.log)) |
| **h2 (recording 4)** | {HS} | sdfada013 | {V['h2_time']} | `MATRIX FAIL (1 of 201 assertions failed)`, exit 1 | features/c: `MEB_EvtCt None: the MEB served no event` (no MEB counter read; shmemClient 1060 L1Accepts, AMI 1050 of 1050 matched) ([log]({PA}/logs/h2/mx-h2.log), [summary]({PA}/matrix-summary-{HS}.json)); every type and coverage passed |

**Why m2's GPU types failed, and the fix** (a reviewer's finding, D2). drp_gpu says `Ready for transitions` only after its CUDA start (cuInit, the context, its DMA buffers) and its detector's init, and control's rollcall finds only a DRP that has. `daq_sim up` waited for that line only where a type set `ready_s`, which among the GPU types only epixuhr3x2 did (since 6cc7f3e95). On sdfada013 the GPU is shared with another user's GPU jobs and its persistence mode is off: `cuInit` took 28.4, 35.8 and 1.6 s in fresh processes at 02:30Z, 0.1, 1.6 and 37.1 s at 02:53Z ([1]({PA}/logs/cuinit-ada013.log), [2]({PA}/logs/cuinit-ada013-2.log)), and 10.25, 1.55 and 28.50 s at 04:23Z (recording 4). d136e1b25 gives every `GPU_SIM_TYPES` entry `ready_s` (300 s) and a `ready_why` that its timeout prints; `up` now prints how long each DRP took. In h2 on sdfada013: {GPU_WAIT}; on sdfada010 (persistence on, `cuInit` 0.06-0.08 s, [log]({PA}/logs/fix15/cuinit-ada010.log)) 0 to 2 s, and 51 s for epixuhr3x2, whose readout system's init takes about 40 s. The GPU nodes: sdfada011's L40S fails `cuInit` with error 999 (a GPU step there at 02:20:19Z), so it ran only CPU DAQs (the web GUI run below) and its job ended at 03:03Z; sdfada013 is shared and slow to start CUDA; sdfada010, allocated at 03:04Z, is fast. h1 used sdfada010 and h2 sdfada013, the one rerun the plan allowed after a run whose only failures were GPU rows.

**Per type, run h2 at {HS}** (each type on a fresh DAQ: `daq_sim up --det <T> --detach`, one recorded cycle of 1000 L1Accepts or more, `down`; `--rate 100` for jungfrau). DAQ is simxpm's L1Accepts, TEB_WrtCt the TEB's recorded events, then psana2's events and its events with the type's data; the per-event check is `xtc2_check --det <T>` (`--drp drp_gpu` for the GPU DRP), which compares every event's data, through the type's own psana interface, with what the simulated device was set to send. The last two columns are the DAQ counts of h1 (at {HS}) and m2 (at 7695dfdae). [matrix-summary-{HS}.json]({PA}/matrix-summary-{HS}.json) (= h2), [per-type-{HS}.md]({PA}/per-type-{HS}.md), [h1]({PA}/matrix-summary-h1.json), [m2]({PA}/matrix-summary-m2.json), [full log h2]({PA}/logs/h2/mx-h2.log):

{TABLE}

In h2 every type has `up` exit 0, 14 transitions reset .. running .. reset each read back with no error message, its DRP alive after the run, `down: clean`, and an evidence record coverage accepts.

**Programs** (h2: one DAQ with the MEB and AMI, `--pva --epics --udp --gui --pvservers --tpr --hps --wave8pvs --rate 100`): `programs/checks`: `{V['prog_checks']}`. Its record lists 42 rows, each accepted by coverage: `det:drp:fakecam`; `ami-client`, `ami-global`, `ami-manager`, `ami-node`, `ami-worker`; `monReqServer`, `shmemClient`; `drp_pva`, `epicsArch`, `drp_udpencoder`, `sim_udpencoder`; `control`, `drp`, `teb`; `control_gui`, `groupca`, `partca`, `pvant`, `procstat`, `epics_exporter`, `daqstat`; `hsdpva`, `pvatable`, `tprca`, `dtica`, `xpmpva`, `deadca`; `bldcas`, `hpsdbuscas`; `tprtrig`, `tpr_trigger`, `lclsBldServer`, `hpsBldServer`, `hpsBldCopy`, `wave8pvs`; the STAND-IN rows `pyxpm`, `pykcuxpm`, `hsdpvs`, `hsd134PVs`, `tprcas`, `tprioc`. (`drp_bld` is proven by feature e.) AMI's own viewer of the camera while Running:

![AMI's image viewer of fakecam:raw:raw while Running, from the programs run of h2]({RAW}/ami-shot-h2-programs.png)

**Features** (each `daq_sim feature <x>` on its own DAQ, report with job 44000948 step {V['h2_step']}, host, HEAD {H}, files changed 0):
- **a** PASS: three DRP types in two readout groups at different rates: {V['fa']}
- **b** PASS: a three-step scan (`generic_timing_scan.py` over `epix100_0:user.start_ns`): {V['fb']} (a8bda341f).
- **c** FAIL in h2, PASS in h1: the MEB serving AMI. h2: {V['fc_h2']} ([AMI's viewer]({RAW}/ami-shot-h2-feature-c.png)). h1: {V['fc']}.
- **d** PASS: one partition over two nodes: {V['fd']}
- **e** PASS: drp_bld, drp_pva, drp_udpencoder and epicsArch beside fakecam_0: {V['fe']}

**Coverage at {HS}** (h2's evidence): `{COV}`. Every RUN and STAND-IN row has a record made at {HS}, and each N/A row prints its reason ([covpos-h2.log]({PA}/logs/h2/covpos-h2.log) lists each row with its record or reason).

**Negatives, forgeries and breaks at {HS}.**
- **Coverage negative** ([`covneg.sh`]({PA}/scripts/fix15/covneg.sh)): in a COPY of h2's {V['h2_records']} records, the 3 that list `det:drp:epix100` removed: `det:drp:epix100 RUN NO VALID EVIDENCE at HEAD {HS}`, `{V['covneg_line']}`, exit 1; over h2's evidence itself: exit 0 ([covneg-h2.log]({PA}/logs/h2/covneg-h2.log), [covpos-h2.log]({PA}/logs/h2/covpos-h2.log)). The same over h1's records (recording 3): exit 1 naming `det:drp:epix100` ([covneg-h1.log]({PA}/logs/h1/covneg-h1.log)).
- **Forgeries by record edits only** ([`forge.sh`]({PA}/scripts/fix15/forge.sh), with a reviewer's `fg23.py` and `fg1.py`; no file written, no hash computed; coverage over each record alone; [own]({PA}/logs/h2/forge-own.log), [FG2]({PA}/logs/h2/forge-fg2.log), [FG3]({PA}/logs/h2/forge-fg3.log), [FG1]({PA}/logs/h2/forge-fg1.log)). MINE is h2's programs record, OTHER the programs record of another run (finalinteg's, at 29f1be4a7):
  - MINE alone: the program rows are RUN (`prog:groupca`, `tprtrig`, `tpr_trigger`, `lclsBldServer`, `hpsBldServer`, `hpsBldCopy`, `wave8pvs` ... `evidence {V['mine']}`).
  - FG2, MINE with its witness swapped for OTHER's: rejected, `its gui_witness witness names no listed xtc2 file of run tstx00001/r0001`.
  - **FG3**, FG2 plus OTHER's 4 xtc2 files and 7 program logs, unchanged: at c370014fc six rows were accepted (tprtrig, tpr_trigger, lclsBldServer, hpsBldServer, hpsBldCopy, wave8pvs). **Now every row is rejected**: `its xtc2 files of run tstx00001/r0001 have 2 different BeginRuns ({V['fg3_begins']}): a record is one run, so it cannot list another run's files` (d50c276a7, D3).
  - **FG1 still passes**: OTHER with only its `sha` field changed to {HS} is accepted for all its 42 rows (`78 rows, 36 run, 6 stand-in, ...`). Records are not signed (COV-LIMIT, below).
- **Breaks** (recording 3, `daq_sim matrix --break <k>`, sdfmilan023 step 366, at {HS}; [`brk.sh`]({PA}/scripts/fix15/brk.sh), [logs]({PA.replace('/blob/', '/tree/')}/logs/h1)), each exit 1 naming the assertions:
  - `register`: `MATRIX FAIL (5 of 7 assertions failed)`: `types/epix100/transitions` (`epix100_0 did not respond to configure`; `rogue_dev: FAULT ePixBoard.ePix100aFPGA.EpixFpgaRegisters.DaqTriggerDelay ... reads back 0x7fffffff`), `drp-alive`, `counts`, `per-event`, `evidence`.
  - `kill-drp`: `MATRIX FAIL (5 of 7)`: `types/fakecam/drp-alive` (`GONE after the run`), `transitions` (`fakecam_0 did not respond to disable`), `counts` (simxpm 1817, psana2 0), `per-event` (file empty), `evidence`.
  - `corrupt`: `MATRIX FAIL (2 of 7)`: `types/fakecam/per-event` (`event 500: payload pattern broken: 1 of 60 payload words differ, first lane 0 w32 0xa8d35fb5 != 0xa8d35f4a`), `evidence`; every count agreed.

**Hardware path, base 5aaf09617 vs this head** (no simulated device: the commands a hardware run takes). {L(133, 133).split('). ', 1)[1].replace('7695dfdae differs from c370014fc only in `CHANGELOG.md` (3 lines), which no program reads.', 'Since c370014fc only `CHANGELOG.md` (7695dfdae) and, at this head, `psdaq/psdaq/sim`, its tests and two docs changed, none of which a hardware run takes, so it was not run again.')}

{L(135, 146)}

{L(148, 163)}

{L(165, 187)}

**Recordings.** Made from an exe.dev VM: every command was typed into a headless tmux pane running `ssh -t sdfiana025 bash --rcfile $R/work/fix15/rc.sh -i` ([rc.sh]({PA}/scripts/fix15/rc.sh)). There `$S` is `srun --jobid=44000948 --overlap -w sdfmilan023 -N 1 --ntasks=1 --cpus-per-task=16 --mem=32G`, `$S2` the same on sdfmilan082, `$G` and `$G13` a GPU step on sdfada010 and sdfada013, so each `$S <script>` line is a new Slurm step; the matrix adds its steps on sdfmilan082 and the GPU node. `git log -1`, the date and the job ids are in the first frames of each. The pane shows the matrix lines `$MXF` picks (every `TYPE`, `PROGRAMS`, `FEATURE` and assertion line; the whole output is in the logs). Each GIF is under 6 MB.

Recording 3 (03:34Z, {HS}):

**3.1** The jobs; HEAD {HS}, the three commits since 7695dfdae and their diff (sim, tests, docs); the build state (`ninja: no work to do.`, installed == checkout); the unit tests, `420 passed, 1 skipped` (step 347); `cuInit` on sdfada010, 0.06-0.08 s.

![Recording 3.1: HEAD {HS}, 420 unit tests passed, cuInit on sdfada010]({RAW}/terminal-h1-1.gif)

**3.2** Matrix run h1 (step 350), in two parts: the types, then the programs run, features a-e, coverage and `MATRIX FAIL (3 of 201 assertions failed)` (drp_gpu jungfrau).

![Recording 3.2a: matrix run h1 starts]({RAW}/terminal-h1-2a.gif)

![Recording 3.2b: matrix run h1 ends, only drp_gpu jungfrau failed]({RAW}/terminal-h1-2b.gif)

**3.3** The summary; each GPU type's `ready for transitions after <n> s`; the coverage negative over h1's records; the forgeries FG2, FG3 (rejected) and FG1 (accepted).

![Recording 3.3: coverage negative and the forgeries at {HS}]({RAW}/terminal-h1-3.gif)

**3.4** The three breaks (step 366), each `exit 1` naming its assertions; the checkout clean.

![Recording 3.4: the breaks register, kill-drp, corrupt each exit 1]({RAW}/terminal-h1-4.gif)

Recording 4 ({V['rec4_start']}, {HS}):

{V['rec4_gifs']}

Recordings 1 and 2 (at c370014fc and 7695dfdae, before the fixes: the build, 417 unit tests, runs m1 and m2, the breaks and the hardware path at 7695dfdae): [1 of 7]({RAW}/terminal-1.gif), [2]({RAW}/terminal-2.gif), [3]({RAW}/terminal-3.gif), [4]({RAW}/terminal-4.gif), [5]({RAW}/terminal-5.gif), [6]({RAW}/terminal-6.gif), [7]({RAW}/terminal-7.gif).

<sub>The GIFs cap each wait at 1.2 s and hold each finished output 2.5 s, so their clock is not real time. The asciinema casts play at real speed: [recording 3]({PA}/recording3.cast), [4]({PA}/recording4.cast), [1]({PA}/recording1.cast), [2]({PA}/recording2.cast), [web GUI session]({PA}/tunnel.cast); transcripts: [3]({PA}/recording3.txt), [4]({PA}/recording4.txt), [1]({PA}/recording1.txt), [2]({PA}/recording2.txt), [web]({PA}/tunnel.txt).</sub>

<details><summary>Raw output: the end of matrix run h2 (its summary; the {n_pass - 0} PASS lines are in the log)</summary>

```
{V['h2_raw']}
```

</details>

<details><summary>Raw output: the breaks (recording 3, step 366), the coverage negative and the forgeries (recording 4, over h2), at {HS}</summary>

```
{V['neg_raw']}
```

</details>

### What to know (disclosures and judgment calls)

- **GPU nodes.** See "Why m2's GPU types failed" above: sdfada011 cannot run CUDA (error 999), sdfada013 is shared and slow to start CUDA, sdfada010 is fast. h2's GPU types ran on sdfada013, so the passing run includes the slow-CUDA case d136e1b25 fixes. drp_gpu ran from a build with conda-forge's CUDA 12.9 toolkit (no toolkit on the nodes; RUNBOOK §3h); `DAQ_SIM_CUDA_LIB` gives procServ's drp_gpu its `libcudart`.
- **drp_gpu jungfrau's UDP loss (h1).** simsls sends each frame as 128 UDP packets on loopback; in h1 on sdfada010 the DRP got 78 to 127 of 128 for 5 frames (`DRP_Damage 5`) and the per-event check failed 3 events. The same `sent N of 128 packets` lines are in an earlier campaign run at 1 kHz (finalinteg m1, drp and drp_gpu); at 100 Hz no other run of the campaign has them. Not fixed here; the DRP marks the events damaged and the check catches them.
{oldline('- **Rulings**').replace("**COV-LIMIT: coverage is an evidence-binding check, not a security boundary.** Removing evidence fails it (shown below); a witness or log rewritten and re-hashed would pass.", "**COV-LIMIT: coverage is an evidence-binding check, not a security boundary.** Removing evidence fails it (shown above). The commit binding is the record's own `sha` field and records are not signed, so cheap forgeries pass: an older commit's record with only its `sha` changed is accepted for all its rows (a reviewer's FG1: the 29f1be4a7 programs record gave 42 rows at c370014fc, and again at this head, above), and a witness or log rewritten and re-hashed would pass. A record that also listed another run's witness, xtc2 files and program logs, unchanged (FG3), was accepted for tprtrig, tpr_trigger, lclsBldServer, hpsBldServer, hpsBldCopy and wave8pvs at c370014fc, because every daq_sim run is run tstx00001/r0001 and lo/hi spanned both runs' L1Accepts; d50c276a7 now rejects it (a record's xtc2 files of its run must have one BeginRun; all 58 records of m1 and m2 have one), as the GUI rows' procmgr-instance check already did. RUNBOOK §3d says what the rules catch and what still passes.")}
{oldline('- **Stand-ins**')}
{oldline('- **MonTracker race').replace("The production race is left as it is; it could happen on hardware too.", "The production race is left as it is; it could happen on hardware too. Reproduced with c370014fc's code by a reviewer: with another client holding `DAQ:SIM:CAM:IMAGE` open before drp_pva's first Connect (as a camera IOC's PV is) and strace on drp_pva, 6 of 6 Configures failed (`hasn't connected`); with strace and no other client, 0 of 4. So 145f3da63 avoids the race only while drp_pva is the PV's first client.")}
{oldline('- **drp_gpu and drp abort at shutdown')}
{oldline('- **tt')}
{oldline('- **jungfrau runs at 100 Hz')}
{oldline('- **One unexplained')}
{oldline('- **BLD layout')}
{oldline('- **Merge decisions')}
- **A cold reader** (a fresh agent with only the docs at c370014fc, its own DAQ on sdfada011): verdict **usable**. It built, recorded run 1 with 1942 L1Accepts, read it back with psana2 (PASS), got live values from a second web GUI (`/api/pvgui/values?gui=pvant`: `NumL0Acc` 12885 → 15885 in 3 s) and took the DAQ down. Fixed in b14885af3 from its friction list: how to stop the second `daq_webgui` (`DAQ_SIM_WORKDIR=$WD`, so `daq_sim down` stops it), its environment (`sim_env.sh`), its value routes (`/api/pvgui/values`, `/api/pvgui/spec`, `/api/procstat/status`, ...), which Python runs the coverage fallback on sdfiana025 (its `python3` is 3.6), the evidence line (`prog:pykcuxpm`), fetching this PR's head (`git fetch origin pull/42/head:pr-42`), the harmless Open MPI lines on a GPU node, and RUNBOOK §7's stale lines (xpmpva runs; the web GUI tunnel was tested through sdfiana025). Left: headless Chromium hangs on sdfada011's GPU node (a GPU child in D state); the RUNBOOK names only milano nodes (an ada node with `--overlap` and fewer CPUs worked); the browser venv is a 600 MB one-time setup; the RUNBOOK is 1700+ lines.
- **Review.** skeptic15 reviewed c370014fc with its own DAQ on sdfada011 (job 44016690): its D2 (GPU types without a ready wait) and D3 (another run's files spliced into a record) are fixed here, its body edits are applied, and its D5 (MonTracker) is the disclosure above. The three commits of this head have had no second review yet.

### Not run

- **A run of THE matrix with exit 0 at this head.** h1 failed 3 of 201 (drp_gpu jungfrau, UDP loss on sdfada010) and h2 1 of 201 (feature c, the MEB's counters not read); each failure passed in the other run. A third run was not made (one rerun was allowed). The last run with exit 0 is at 29f1be4a7 (`MATRIX PASS (201 assertions)`, 2026-11-10 00:54-01:21Z), before the three fixes and the CHANGELOG links.
- No hardware: everything ran against stand-ins and emulated devices; the hardware path above shows only that the commands a hardware run takes behave as at base.
{oldline('- `xpmPVs`')}
- The web GUI's `/gui/<name>` pages were not part of these recordings (PRs #31, #35, #37 and #40 have theirs); the web GUI run above is at 7695dfdae (the web GUI's code is unchanged since; its README changed).
{oldline('- The GPU DRP')}
- No fresh `build_all.sh -f` at this head (incremental: no C++ changed since the fresh CUDA build of this branch, bfc1ccd3d). The hardware path was not rerun at this head (no non-sim code changed since c370014fc).
- No CI run is shown here (below).

### To rerun

```
# on sdfiana025, in the campaign root ($R); scripts in pr-assets/pr42/scripts and scripts/fix15
S="srun --jobid=44000948 --overlap -w sdfmilan023 -N 1 --ntasks=1 --cpus-per-task=16 --mem=32G"
srun --jobid=44062096 --overlap -w sdfada010 -N 1 --ntasks=1 --cpus-per-task=16 --mem=32G --gres=gpu:l40s:1 bash build.sh H   # CUDA 12.9 build
$S bash pyt.sh all                                  # unit tests, under the node lock
srun --jobid=43970564 --overlap -w sdfada013 -N 1 --ntasks=1 --cpus-per-task=2 --mem=4G --gres=gpu:l40s:1 bash cuinit.sh   # CUDA init time
$S bash mx.sh <tag> sdfada013 43970564              # THE matrix (RUNBOOK 3p); MATRIX_EXIT=0 expected
$S bash covneg.sh $R/work/fix15/mx-<tag>-ev det:drp:epix100   # negative exit 1, the evidence itself exit 0
$S bash forge.sh $R/work/fix15/mx-<tag>-ev          # FG2, FG3 rejected; FG1 accepted
$S bash brk.sh <tag>                                # the three breaks, each exit 1
# the recordings: python3 mksteps_h.py h1; python3 mksteps_h2.py h2; python3 recdrive.py pr42-term3 steps/pr42-term3-h1.json
# (and pr42-term4); render_split.py (with --no-sandbox, --disable-gpu, --disable-dev-shm-usage), splitgif.py (redo/ toolkit)
```

{L(393, len(OLD))}"""
body = body.rstrip('\n') + '\n'
open(out, 'w').write(body)
print(f'{out}: {len(body)} characters, {body.count(chr(10))} lines')
