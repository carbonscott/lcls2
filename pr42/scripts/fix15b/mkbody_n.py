#!/usr/bin/env python3
"""mkbody_n.py OLD_BODY ASSETS VALS OUT: PR #42's body at H2 (b3d052088) from the body at b14885af3 (fix15's, kept as
assets/pr42/history/body-b14885af3.md), the matrix summaries of the runs at H2 (n1, n2 if run), h2 and h1 at b14885af3,
and VALS (a JSON of the values read from the logs: steps, times, loss numbers, negatives, breaks)."""
import json, os, re, sys

old_path, A, vals_path, out = sys.argv[1:5]
OLD = open(old_path).read().split('\n')
V = json.load(open(vals_path))
def L(a, b):                     # old body lines a..b, 1-indexed, inclusive
    return '\n'.join(OLD[a - 1:b])
def sub1(text, a, b):
    assert text.count(a) == 1, a[:80]
    return text.replace(a, b)

H2, HS = 'b3d052088615373e813d6027f1bd9fcdab169a14', 'b3d052088'
PA = 'https://github.com/carbonscott/lcls2/blob/pr-assets/pr42'
TR = 'https://github.com/carbonscott/lcls2/tree/pr-assets/pr42'
RAW = 'https://raw.githubusercontent.com/carbonscott/lcls2/pr-assets/pr42'
HIST = f'{PA}/history/body-b14885af3.md'
P = V['primary']                                   # the run at H2 the per-type table shows (n1 or n2)
S = {t: json.load(open(os.path.join(A, f'matrix-summary-{t}.json'))) for t in V['runs_h2']}
h2 = json.load(open(os.path.join(A, 'matrix-summary-h2.json')))
h1 = json.load(open(os.path.join(A, 'matrix-summary-h1.json')))
for t in V['runs_h2']:
    assert S[t]['sha'] == H2, t
d = S[P]

def teb(t):
    for a in t.get('assertions', []):
        if a['name'].endswith('/counts'):
            m = re.search(r'TEB_WrtCt (\w+)', a['detail'])
            return m.group(1) if m else None
def cnt(t):
    return str(t.get('daq')) if t.get('pass') in (True, 'True') else '**FAIL**'
def ok(t):
    return t.get('pass') in (True, 'True')

rows = []
others = [t for t in V['runs_h2'] if t != P]
for k, t in d['types'].items():
    drp, typ = k.split(':') if ':' in k else ('drp', k)
    node = t['node'].replace('sdf', '')
    extra = ' | '.join(cnt(S[o]['types'].get(k, {})) for o in others)
    extra = (extra + ' | ') if extra else ''
    if ok(t):
        rows.append(f"| {typ} | {drp} | {node} | **{t.get('daq')}** | {teb(t)} | {t.get('psana2')} | {t.get('with_data')} | "
                    f"{t.get('per_event')} | `{t.get('evidence') or '-'}` | {extra}{cnt(h2['types'].get(k, {}))} | {cnt(h1['types'].get(k, {}))} |")
    else:
        rows.append(f"| {typ} | {drp} | {node} | **FAIL** | {teb(t)} | {t.get('psana2')} | {t.get('with_data')} | "
                    f"{t.get('per_event')} | - | {extra}{cnt(h2['types'].get(k, {}))} | {cnt(h1['types'].get(k, {}))} |")
p = d['programs']
extra = ' | '.join(cnt(S[o]['programs']) for o in others)
extra = (extra + ' | ') if extra else ''
rows.append(f"| **programs run** (fakecam_0 + the MEB, AMI, system DRPs, GUIs, PV servers) | drp | {p['node'].replace('sdf', '')} | "
            f"**{p.get('daq')}** | {teb(p)} | {p.get('psana2')} | {p.get('with_data')} | {p.get('per_event')} | "
            f"`{p.get('evidence')}` ({V['prog_rows']} rows) | {extra}{cnt(h2['programs'])} | {cnt(h1['programs'])} |")
ocols = ''.join(f' {o} |' for o in others)
TABLE = (f'| type | DRP | node | DAQ | TEB_WrtCt | psana2 | with data | per-event | evidence record ({P}) |{ocols} h2 | h1 |\n'
         '|---|---|---|---|---|---|---|---|---|' + '---|' * len(others) + '---|---|\n' + '\n'.join(rows))

n_all = len(d['assertions'])
n_fail = sum(1 for a in d['assertions'] if not a['ok'])
COV = d['coverage']['assertions'][0]['detail'] if d['coverage'].get('assertions') else 'not run'

# ---- the runs table: every run of THE matrix at the four heads -----------------------------------------------------
RUNS = '\n'.join(V['run_rows'])

old13 = OLD[12]
after = sub1(old13, 'so another run\'s files and witness can no longer be added to a record unchanged;',
             'so another run\'s files and witness can no longer be added to a record unchanged (a record whose own '
             'xtc2 files are replaced by them still passes, as FG1 does: COV-LIMIT);')
after += (' Then, on b14885af3: 679ceb644 makes the counts after Disable ask a Prometheus exporter that does not answer '
          'again (feature c once lost `MEB_EvtCt` to a single 3 s read); 74d139eb2 makes `simsls` send a jungfrau frame in '
          'bursts that fit the DRP\'s receive buffer (drp_gpu jungfrau lost UDP packets on loopback); b3d052088 corrects '
          'the web GUI README\'s exit code and a CHANGELOG citation.')

howto = L(28, 50)
howto = sub1(howto, '# 420 passed, 1 skipped', '# 424 passed')
howto = sub1(howto, 'bash mx.sh h2 G $GJOB', f'bash mx.sh {P} G $GJOB')
howto = sub1(howto, '(at this head h1 failed 3 and h2 1 of 201:\n#      see Proof)', V['howto_result'])

LOSS = '\n'.join(V['loss_rows'])

body = f"""{OLD[0]}
{L(2, 12)}
{after}

{L(15, 26)}

{howto}

## Proof it works

Ran on S3DF at **{H2}** (pr/final, this PR's head: b14885af3 plus three commits, committed 2026-11-10 05:22:13Z), on 2026-11-10 {V['span']} UTC: sdfmilan023 and sdfmilan082 (milano, Slurm job 44000948), the GPU DRP's types on {V['gpu_nodes']}, one NVIDIA L40S each. Steps: {V['steps']}. The DAQ env was `daq_20250402_r9` (Python 3.9.21); every script sources `setup_env_daq.sh` and then `sim_env.sh` ([scripts](https://github.com/carbonscott/lcls2/tree/pr-assets/pr42/scripts), [this run's](https://github.com/carbonscott/lcls2/tree/pr-assets/pr42/scripts/fix15b)).

> {V['result']}

**The head.** {HS} is pr/final's last commit; the base is agentify at 5aaf09617737887aef5f196f13754d7ad6f6b98c (the merge of #41), still origin/agentify. The diff against it is 99 files (16236 insertions, 373 deletions) in 153 commits (132 not merges). Since b14885af3: 679ceb644, 74d139eb2, {HS}, 7 files (`daq_sim.py`, `feature.py`, `simsls.py`, their two test files, the web GUI's `README.md`, `CHANGELOG.md`: 243 insertions, 25 deletions; recording 5 shows `git diff --stat b14885af3 HEAD`): sim code, tests and docs only. The checkout had 0 local changes (tracked or untracked) before and after each recording.

**Build and unit tests.** `build_all.sh -d -j 12` with conda-forge's CUDA 12.9 `nvcc` on PATH at {HS} on sdfada010 (step 13): `BUILD_EXIT=0` in 13 s, `psdaq` reinstalled, the installed `psdaq/sim` (with `simsls.py` and `feature.py`), `webgui`, `control` and `configdb` identical to the checkout ([out]({PA}/logs/fix15b/build-H2.out)). The sim unit tests and `test_walk_guard` (AMI on `PYTHONPATH`, under sdfmilan082's DAQ lock): **`424 passed`, `PYTEST_EXIT=0`** (step 385, 213 s, [out]({PA}/logs/fix15b/pyt-H2.out)). b14885af3 had 420 passed and 1 skipped. The 4 more: `test_udp_queue_reads_the_receivers_line`, `test_run_counts_asks_again_an_exporter_that_does_not_answer`, and `test_one_frame_per_trigger` twice, which no longer skips where `net.core.rmem_max` is below 2 MiB: it reads two frames through a 256 KiB buffer, the second case at 1 ms per packet.

**The two fixes of this head, before and after.**
- **simsls' UDP loss (74d139eb2).** On loopback each of a jungfrau frame's 128 packets (8240 B) costs the receiving socket 16640 B of buffer, 2 MiB a frame. MemPoolSim asks for a 16 MiB `SO_RCVBUF` and gets twice `net.core.rmem_max`: 425984 B on sdfada010 and sdfmilan082 (rmem_max 212992, room for 25 packets), 32 MiB on sdfmilan023 (rmem_max 16 MiB, where drp jungfrau runs in the matrix). simsls sent a frame back to back, so whenever the DRP's reading thread fell 25 packets behind the kernel dropped what did not fit (the socket's `drops` in `/proc/net/udp`, the node's `RcvbufErrors`); MemPoolSim logs `sent N of 128 packets`, the DRP counts the event damaged, and the per-event check fails. simsls now reads the receiving socket's queue (`rx_queue` in `/proc/net/udp`, about 140-170 µs a read) before each burst and sends only what fits in three quarters of the buffer, waiting while none fits (at most 0.1 s, then it sends anyway); where a frame fits it sends as before. MemPoolSim and the DRPs are unchanged. In the runs after the fix and in n1 and n2 simsls never had to wait (`room_waits` 0 in its log): bursts of at most 19 packets, with a `/proc/net/udp` read between them, let the DRP keep up; the wait engaged only with a slow reader (348 times in the test below). The jungfrau type cycle of the matrix (`daq_sim matrix --only types --types jungfrau [--drp drp_gpu]`, [`loss.sh`]({PA}/scripts/fix15b/loss.sh): a sampler reads `/proc/net/udp` every 0.2 s beside it), before at b14885af3 and after at {HS}:

| run | HEAD | node (rmem_max) | step | simsls packets sent | dropped at the DRP's socket | damaged events | `sent N of 128` lines | exit |
|---|---|---|---|---|---|---|---|---|
{LOSS}

  {V['loss_note']} ([before]({PA}/logs/fix15b/lossrun-before-gpu.out), [after]({PA}/logs/fix15b/lossrun-after-gpu.out), [drp before]({PA}/logs/fix15b/lossrun-before-cpu.out), [drp after]({PA}/logs/fix15b/lossrun-after-cpu.out), [logs]({TR}/logs/fix15b)).
- **The MEB counter read (679ceb644).** In h2 at b14885af3 the counts after Disable took 4.1 s instead of the usual 1.1 s and held the TEB's and the DRP's Prometheus counters but none of the MEB's: one exporter missed its single 3 s read, and feature c failed with `MEB_EvtCt None: the MEB served no event` while the MEB had served (shmemClient 1060 L1Accepts, AMI 1050 of 1050 matched). `_run_counts` now asks an exporter that does not answer again after 0.5, 1, 2 and 4 s, for up to 20 s, and names one that never answers (`prometheus unread: 127.0.0.1:<port> no answer in <n> tries over <s> s (<error>)`), which feature c reports as `MEB_EvtCt not read: ...`. A unit test drives both cases with a stand-in scrape (twice no answer, then the counters; never an answer). {V['meb_note']}

**THE matrix** (RUNBOOK §3p, "Everything, over every node of the campaign"; [`mx.sh`]({PA}/scripts/fix15b/mx.sh), fix15's with only its output dir changed), one command in one step on sdfmilan023:

```
daq_sim matrix -w $F/mx-$TAG --hosts sdfmilan023,sdfmilan082 \\
  --locks /tmp/agentify-daq-milan023.lock,/tmp/agentify-daq-milan082.lock \\
  --gpu-host {V['cmd_gpu_host']} --gpu-job {V['cmd_gpu_job']} --gpu-gres gpu:l40s:1 --gpu-lock /tmp/agentify-daq-{V['cmd_gpu_host'][3:]}.lock \\
  --ami-src /sdf/group/lcls/ds/ana/sw/conda2/rel/ami_091526 --evidence $DAQ_SIM_EVIDENCE --lock-timeout 5400
{L(69, 71)}

Every run of it at this PR's last four heads ({V['n_runs_total']} runs; m1 to h2 in detail in [the body at b14885af3]({HIST})):

| run | HEAD | GPU node | time (UTC) | result | failed assertions and cause |
|---|---|---|---|---|---|
{RUNS}

**GPU nodes** ([the body at b14885af3]({HIST}), "Why m2's GPU types failed"). drp_gpu says `Ready for transitions` only after its CUDA start and its detector's init, and `daq_sim up` waited for that line only where a type set `ready_s`, which among the GPU types only epixuhr3x2 did: the GPU types came without a wait in 6cc7f3e95, the `ready_s` wait in bdba77fec (for `drp -D epixuhr3x2`), and the GPU epixuhr3x2 entry took it over in 0752cb83c. On sdfada013 (shared, persistence off) `cuInit` took up to 37.1 s, so m2's other GPU types missed the rollcall; d136e1b25 gives every GPU type the wait (h2 on sdfada013: 31, 20, 7, 20, 73 s). On sdfada010 `cuInit` takes 0.06-0.08 s ({V['cuinit']}); waits {V['ready']}. sdfada011's L40S fails `cuInit` (error 999).

**Per type, run {P} at {HS}** (each type on a fresh DAQ: `up`, one recorded cycle of 1000 L1Accepts or more, `down`; jungfrau at 100 Hz). DAQ is simxpm's L1Accepts, then the TEB's recorded events, psana2's events and its events with the type's data; the per-event check, `xtc2_check --det <T>`, compares every event's data, through the type's psana interface, with what the simulated device was set to send. The last columns are the DAQ counts of {', '.join(others + ['h2 and h1 at b14885af3']) if others else 'h2 and h1 at b14885af3'}. [matrix-summary-{HS}.json]({PA}/matrix-summary-{HS}.json) (= {P}), [per-type-{HS}.md]({PA}/per-type-{HS}.md), {', '.join(f'[{t}]({PA}/matrix-summary-{t}.json)' for t in V['runs_h2'])}, [full log {P}]({PA}/logs/{P}/mx-{P}.log):

{TABLE}

{V['types_note']}

**Programs** ({P}: one DAQ with the MEB and AMI, `--pva --epics --udp --gui --pvservers --tpr --hps --wave8pvs --rate 100`): `programs/checks`: `{V['prog_checks']}`. Its record lists {V['prog_rows']} rows, each accepted by coverage: `det:drp:fakecam`; `ami-client`, `ami-global`, `ami-manager`, `ami-node`, `ami-worker`; `monReqServer`, `shmemClient`; `drp_pva`, `epicsArch`, `drp_udpencoder`, `sim_udpencoder`; `control`, `drp`, `teb`; `control_gui`, `groupca`, `partca`, `pvant`, `procstat`, `epics_exporter`, `daqstat`; `hsdpva`, `pvatable`, `tprca`, `dtica`, `xpmpva`, `deadca`; `bldcas`, `hpsdbuscas`; `tprtrig`, `tpr_trigger`, `lclsBldServer`, `hpsBldServer`, `hpsBldCopy`, `wave8pvs`; the STAND-IN rows `pyxpm`, `pykcuxpm`, `hsdpvs`, `hsd134PVs`, `tprcas`, `tprioc`. (`drp_bld` is proven by feature e.) AMI's own viewer of the camera while Running:

![AMI's image viewer of fakecam:raw:raw while Running, from the programs run of {P}]({RAW}/ami-shot-{P}-programs.png)

**Features** (each `daq_sim feature <x>` on its own DAQ, report with job 44000948 step {V['mx_step']}, host, HEAD {H2}, files changed 0):
{V['features']}

**Coverage at {HS}** ({P}'s evidence): `{COV}`. {V['cov_note']}

**Negatives and breaks at {HS}.**
{V['negatives']}
- **Forgeries** (by record edits only) were last run at b14885af3, whose `coverage.py` is this head's: FG2 and FG3 rejected (FG3: `its xtc2 files of run tstx00001/r0001 have 2 different BeginRuns`), FG1 accepted for its 42 rows ([logs]({TR}/logs/h2), [the body at b14885af3]({HIST})). A second review's FG4 is accepted for six program rows (COV-LIMIT, below).

**Hardware path, base 5aaf09617 vs this head** (no simulated device: the commands a hardware run takes). The union of every branch's base-vs-head script, `hwall.sh`, ran in one GPU step on sdfada013 (job 43970564 step 268, 01:35-01:52Z, under the node's lock) with the base worktree at 5aaf09617 and this branch at c370014fc: every `drp` type's python entry points and `drp -D <type>` on `/dev/datadev_0`, `drp_gpu` likewise, `drp_bld`, `drp_pva`, `epicsArch`, `drp_udpencoder`, `sim_udpencoder` and `monReqServer` on their hardware options, `lclsBldServer`, `hpsBldServer`, `hpsBldCopy`, `wave8pvs` and `tprtrig`. Base and head print the same except where a production fix below changes the output (`_connectionInfo` added, tt's stored names, `lclsBldServer`'s usage, hpsBldServer and wave8pvs starting); every `.diff` equals that of the same scripts at 29f1be4a7. The table is in [the body at b14885af3]({HIST}) ([hwall15.log]({PA}/logs/hwpath/hwall15.log), [all outputs]({TR}/logs/hwpath)). Since c370014fc only `CHANGELOG.md`, `psdaq/psdaq/sim`, its tests and docs changed, none of which a hardware run takes, so it was not run again.

{L(156, 172).replace('` above |', '` (hardware path) |').replace('`typesfix-tthw.diff` above;', '`typesfix-tthw.diff` (hardware path);').replace('`bh-tail3.log` above', '`bh-tail3.log` (hardware path)').replace('`bh-tail3_w8.log` above', '`bh-tail3_w8.log` (hardware path)').replace('`bh-tail2.log` above', '`bh-tail2.log` (hardware path)')}
**The web GUI, driven from outside S3DF** (sdfada011, job 44016690 step 76, HEAD 7695dfdae; details in [the body at b14885af3]({HIST})). `daq_sim up --webgui` ran a CPU DAQ on the node; the exe.dev VM reached the page through two ssh hops joined by a private Unix socket, and `tunnel_drive.py` (Playwright, headless Chromium) clicked through CONNECTED, CONFIGURED, STARTING, PAUSED, RUNNING and back to RESET. The page's count moved 1321 → 3321 in 2 s (1 kHz) and ended at 4459, simxpm's `NumL0Acc` read on the node (`PAGE_EVENTS_FINAL=4459  ALL_STATES_OK=True`, `DOWN_EXIT=0`); the web GUI's code is unchanged since.

![Web GUI recording: Configure, Running with events 1321 -> 3321 -> 4459, back to Reset, through a two-hop tunnel]({RAW}/webgui.gif)

**Recordings.** Made from an exe.dev VM: every command was typed into a headless tmux pane running `ssh -t sdfiana025 bash --rcfile $R/work/fix15b/rc.sh -i` ([rc.sh]({PA}/scripts/fix15b/rc.sh)). There `$S` is `srun --jobid=44000948 --overlap -w sdfmilan023 -N 1 --ntasks=1 --cpus-per-task=16 --mem=32G`, `$S2` the same on sdfmilan082, `$G` and `$G13` a GPU step on sdfada010 and sdfada013, so each `$S <script>` line is a new Slurm step; the matrix adds its steps on sdfmilan082 and the GPU node. `git log -1`, the date and the job ids are in the first frames of each. The pane shows the matrix lines `$MXF` picks (every `TYPE`, `PROGRAMS`, `FEATURE` and assertion line; the whole output is in the logs). Each GIF is under 6 MB.

{V['recordings']}

Recordings 1-4 (c370014fc, 7695dfdae, b14885af3: runs m1, m2, h1, h2, the forgeries, the hardware path) and the web GUI session's terminal are listed in [the body at b14885af3]({HIST}).

<sub>The GIFs cap each wait at 1.2 s and hold each finished output 2.5 s, so their clock is not real time. The asciinema casts play at real speed: {V['casts']}; transcripts: {V['transcripts']}.</sub>

<details><summary>Raw output: the end of matrix run {P} (its summary; the PASS lines are in the log)</summary>

```
{V['raw_matrix']}
```

</details>

<details><summary>Raw output: the coverage negative over n2 (recording 6) and the breaks (recording 5) at {HS}; each break's FAILED lines, cut at 138 characters</summary>

```
{V['raw_neg']}
```

</details>

### What to know (disclosures and judgment calls)

{V['know_gpu']}
- **drp_gpu jungfrau's UDP loss: fixed in the stand-in (74d139eb2).** At b14885af3 simsls sent each frame's 128 packets back to back and the kernel dropped what did not fit the DRP's 416 KiB receive buffer (h1, and 3 of 3 runs on sdfada010 before the fix, above). The fix paces the stand-in by the receiving socket's queue, read from `/proc/net/udp` (a Linux-only file; without it simsls sends as before); it changes neither MemPoolSim nor the DRPs. A frame still costs 2 MiB of buffer where the DRP gets 416 KiB, so a reader stalled for more than 0.1 s would still lose packets (`room_timeouts` in simsls' log counts those; 0 in every run here). Where `rmem_max` is 1.5 MiB or more (sdfmilan023), simsls sends as before.
- **The TEB contributor's overflow (n1).** In n1 the `drp` of epixquad1kfps and of opal each aborted at Enable with `<C> void Pds::Eb::TebContributor::_post(const Pds::Eb::CtrbBatch&): _pending queue overflow` (signal 6), and teb0 then aborted (`TEB thread lost connection with a DRP`); the same abort ended epixquad1kfps in m1 at c370014fc. It is in production `drp` code that this PR does not change; both ran on sdfmilan023 (load 9 on 128 cores at 05:54Z); its cause was not investigated. These three are the only DRP logs with it under the campaign's `work/fix15`, `fix15b`, `proof15` and `skep15b`. n2 passed both types ({V['n2_eq']} and {V['n2_opal']} events).
{L(313, 313).replace('and again at this head, above)', 'and again at b14885af3)').replace('as the GUI rows\' procmgr-instance check already did.', "as the GUI rows' procmgr-instance check already did. It does not stop a record of this head whose own xtc2 files are dropped and another run's xtc2 files, witness and program logs are listed instead, since that is one run again. In a second review (FG4: its own programs record at b14885af3, with finalinteg's 29f1be4a7 run in place of its own), tprtrig, tpr_trigger, lclsBldServer, hpsBldServer, hpsBldCopy and wave8pvs were accepted, and det:drp:fakecam, groupca, drp_pva and ami-node were rejected. Like FG1, it is a record edit that the record's own `sha` field cannot catch.")}
{L(314, 314)}
- **MonTracker race, fixed only on the sim side.** `drp_pva`'s `MonTracker` (production) drops an update that arrives before its constructor returns, after which pvAccessCPP signals no later update; on loopback simxpm's camera PV answered within 1 ms, so drp_pva sometimes failed Configure ("PV DAQ:SIM:CAM:IMAGE hasn't connected"). The camera PV now opens 0.25 s after a client's first channel (145f3da63); the production race is left as it is, and a reviewer showed 145f3da63 avoids it only while drp_pva is the PV's first client (6 of 6 Configures failed with another client holding the PV).
{L(316, 318)}
- **Also described in [the body at b14885af3]({HIST})**: one unexplained `procmgr stop` timeout in a programs run before 12 that passed; two BLD layout oddities (RUNBOOK §3d, not fixed); the merge decisions (ce2bd2cfe, 09f5fe236); a cold reader's run of the docs at c370014fc (verdict usable; its friction list fixed in b14885af3; left: headless Chromium hangs on sdfada011's GPU node, the RUNBOOK names only milano nodes, the browser venv is a 600 MB setup, the RUNBOOK is 1700+ lines).
- **Review.** skeptic15 reviewed c370014fc with its own DAQ on sdfada011 (job 44016690): its D2 (GPU types without a ready wait) and D3 (another run's files spliced into a record) are fixed here, its body edits are applied, and its D5 (MonTracker) is the disclosure above. skeptic15b reviewed the three commits of b14885af3 with its own clone and CUDA 12.9 build at b14885af3 on sdfada013. drp_gpu fakecam, epixuhremu and jungfrau passed `daq_sim matrix --only types --drp drp_gpu` there (1720, 1769 and 1083 events), and passed again with drp_gpu started 45 s late (ready after 47, 50 and 63 s). With the same delay and `ready_s` removed, fakecam failed with `did not respond to rollcall`. At b14885af3 FG3 is rejected and FG1 accepted; its FG4 is described in COV-LIMIT. The second web GUI's README steps worked as written. Its verdict was merge after three edits, applied at this head: the README's exit code (2 → 1, b3d052088), the FG4 disclosure, and the commit that brought the `ready_s` wait (bdba77fec, not 6cc7f3e95; CHANGELOG and above). The three commits of this head ({V['review_h2']}) have had no second review yet.

### Not run

{V['not_run']}

### To rerun

```
# on sdfiana025, in the campaign root ($R); scripts in pr-assets/pr42/scripts, scripts/fix15 and scripts/fix15b
S="srun --jobid=44000948 --overlap -w sdfmilan023 -N 1 --ntasks=1 --cpus-per-task=16 --mem=32G"
G="srun --jobid=44062096 --overlap -w sdfada010 -N 1 --ntasks=1 --cpus-per-task=16 --mem=64G --gres=gpu:l40s:1"
$G bash build.sh H2                                 # CUDA 12.9 build (fix15b/build.sh)
$S bash pyt.sh all                                  # unit tests, under the node lock
$G bash loss.sh after-gpu drp_gpu 3                 # drp_gpu jungfrau x3: simsls packets, the DRP socket's drops
$S bash mx.sh <tag> sdfada010 44062096              # THE matrix (RUNBOOK 3p); MATRIX_EXIT=0 expected
$S bash covneg.sh $R/work/fix15b/mx-<tag>-ev det:drp:epix100   # negative exit 1, the evidence itself exit 0
$S bash brk.sh <tag>                                # the three breaks, each exit 1
# the recording: python3 mksteps_n.py n1 sdfada010 44062096 --negatives; python3 recdrive.py pr42-term5 steps/pr42-term5-n1.json;
# render_split.py (with --no-sandbox, --disable-gpu, --disable-dev-shm-usage), splitgif.py (redo/ toolkit)
```

## Checklist

{L(353, 357)}"""
open(out, 'w').write(body)
print(f'{out}: {len(body)} characters')
