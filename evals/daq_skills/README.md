# Evals for the DAQ diagnostic skills

These tools measure whether the `psana-daq*` skills (`psana/psana/skills/`, upstream PRs
#131, #181, #191) lead an agent to the right diagnosis of a DAQ problem, and what they add
over the same agent with no skills.

Each case is a question about real DAQ logs whose cause is known. The logs come from the
hardware-free sim (`psdaq/psdaq/sim`), which runs the real `control`, `teb`, `meb` and `drp`
programs, so the files have the production layout and messages:
`YYYY/MM/<DD_HH:MM:SS>_<host>:<component>.log[.zst]`.

## Quick start for skill authors

Three families of cases. **A** hands the agent the log folder and the window (mode `m0`, the
v2 cases). **B** is a cold start (mode `m1`): the prompt names the hutch and a vague time,
and the agent must find the logs in an MFX-shaped tree built from the bundled logs. **C** is
a cold start on real MFX logs.

Families A and B need only this folder: the tools, the cases, and the logs the cases are
about (`data/pools.tar.gz`, 8.3 MB, 45 log directories). You do not need the sim, S3DF
group access or `harvest.py`. Family C needs the real MFX logs, which are not in the
repository: `real_mfx.py fetch` copies them from S3DF with your own login. Agent runs need
the `claude` CLI logged in to your own account, and `bwrap` and `zstd` (both are on the
S3DF interactive nodes).

```bash
git clone --depth 1 https://github.com/carbonscott/lcls2 daq-evals   # the default branch, sim-main
cd daq-evals/evals/daq_skills
python3 -m unittest discover -s tests          # 152 tests, OK, no model calls (a few skip without zstd or a skills checkout)
WORK=$HOME/daq-eval-work && mkdir -p $WORK && tar xzf data/pools.tar.gz -C $WORK      # any folder of yours
python3 tree.py --work $WORK                   # family B's tree in $WORK/roots, about a minute; ends "8 cases, window check passed for all"
OUT=$HOME/daq-eval-results                     # your results go here
SK=/path/to/your/lcls2/psana/psana/skills      # the skills under test
MAP=/path/to/skills                            # the folder holding hutch-resources/ (the hutch map)

# Family B by hand: one case, no skills and with them (add --dry-run to write the prompts without an agent)
python3 run.py --work $WORK --mode m1 --arm m1-none   --skills none --out $OUT --case ctl-blames-meb
python3 run.py --work $WORK --mode m1 --arm m1-skills --skills $SK  --out $OUT --case ctl-blames-meb

# Family C by hand: fetch the real MFX logs first (rsync over ssh from sdfiana025; at most 2 GB, --max-bytes)
REAL=$HOME/mfx-root
python3 real_mfx.py fetch --dest $REAL         # checks every case file's sha256
python3 real_mfx.py keys  --root $REAL         # exit 1 if a file or key drifted
python3 real_mfx.py check --root $REAL         # each vague window holds only keyed launches
python3 run.py --work $WORK --mode m1 --family C --real-root $REAL --arm C-none --skills none --out $OUT --case real-qadc-run

# Score what you ran: facts per report (model calls), then calls to evidence (no model)
python3 score.py --results $OUT --out $OUT/scored.json --summary $OUT/scored.txt
python3 evidence.py --results $OUT --work $WORK --write

# The pilot: pilot.py runs cells (FAMILY/ARM[/MODEL[/CASES[/REPEATS]]]) at most --jobs at a time,
# then score.py and evidence.py, and writes rows.json; --dry-run prints the plan and the projected usage only
PILOT=$HOME/daq-eval-pilot
P="python3 pilot.py --out $PILOT --work $WORK --real-root $REAL --skills $SK --map $MAP --jobs 2 --resume"
$P --dry-run       --cell B/none --cell B/skills --cell B/map --cell B/both --cell B/pointer --cell B/starved --repeats 2
$P --budget-left 200 --cell B/none --cell B/skills --cell B/map --cell B/both --cell B/pointer --cell B/starved --repeats 2
$P --budget-left 150 --cell C/none --cell C/skills --cell C/map --cell C/both --cell C/pointer --repeats 2
$P --budget-left 15  --cell A/none/haiku --cell A/crib/haiku --cell A/starved/haiku --repeats 3    # the M0 controls
python3 verdict.py $PILOT/rows.json            # the pre-registered verdicts (P2-P6, P3m)
```

- `pilot.py` refuses to start (exit 2) when its projection exceeds `--budget-left` (USD); it
  estimates $2.00 a default-model run and $0.10 a Haiku run until finished runs say otherwise,
  plus $0.06 of scoring, so the B cells above project about $190.
- Controls: `pointer` (B, C) hands over the folder and window, `crib` (A) the key's mechanism,
  `starved` (A, B) removes the root-cause files. They show whether the eval can move at all.
- Family C's per-case views decompress the week before each case's "now": about 19 GB under
  `$WORK/roots/real` for the seven cases.
- Family A as in v2 (`judge.py`, `grade.py`, `report.py`): see [The tools](#the-tools).
- Use any arm name; edit a skill, pick a new name (`--arm mine-v2`) and compare the summary lines.
- If `claude` is not under `~/.local` or a system directory, add `--expose <its folder>`.
- To test the skills when they are certainly read, add `--preface "Load the psana-daq skill before you start."` under its own arm name.
- Unpack with `tar` so the files keep their modification times; the logs skill's helper picks sessions by them.
- Tested: the unit tests on S3DF (Python 3.6) and on a Linux VM (Python 3.12); the sandbox and a scripted
  agent on S3DF (v2); real agent runs on the VM. A real Claude Code run on S3DF itself has not been tried yet.

## v3: cold start (mode m1) and the controls

`cases_v3.json` holds the 8 cases of the v3 eval (6 fault cases most often missed in v2, 2 healthy
floor checks; the rule and the counts are in the file). Family A runs them as before (mode `m0`);
family B runs the same launches re-housed in an MFX-shaped tree (mode `m1`): the prompt names the hutch,
a vague time ("last night", "Friday afternoon") and the current date, and gives no path and no window.

```bash
python3 tree.py --work $WORK          # builds $WORK/roots (about a minute); exit 1 if a window check fails or a node name is left
# family B, one arm per guidance set (--skills twice installs both sets in one folder)
python3 run.py --work $WORK --mode m1 --arm m1-none   --skills none --out $OUT
python3 run.py --work $WORK --mode m1 --arm m1-skills --skills $SK  --out $OUT
python3 run.py --work $WORK --mode m1 --arm m1-map    --skills $MAP --out $OUT     # MAP: the folder holding hutch-resources/
python3 run.py --work $WORK --mode m1 --arm m1-both   --skills $SK --skills $MAP --out $OUT
python3 run.py --work $WORK --mode m1 --arm m1-pointer --skills none --control pointer --out $OUT
python3 run.py --work $WORK --mode m1 --arm m1-starved --skills none --control starved --out $OUT
# the M0 controls on family A
python3 run.py --work $WORK --mode m0 --arm m0-crib    --skills none --control crib    --out $OUT
python3 run.py --work $WORK --mode m0 --arm m0-starved --skills none --control starved --out $OUT
python3 evidence.py --results $OUT --work $WORK       # calls to evidence per run
```

- **The tree** (`tree.py`): one calendar of launches mounted read-only at `/sdf`: the current MFX root
  `/sdf/home/m/mfxopr/daq/logs/<YYYY>/<MM>`, the root used before 2026-09-17 09:29
  `/sdf/home/m/mfxopr/<YYYY>/<MM>`, seven partition configs in `daq/scripts` (rebuilt from one launch's
  log headers each), a month boundary, and a second hutch at `/sdf/home/t/tmoopr/daq/logs`. Each case
  sees the calendar up to its own "now". Every launch is a bundled pool's launch moved by whole days
  (names, directory, dates in the text, modification times; `tst` becomes `mfx`); no line is added
  or removed.
- **Real host names.** The sim ran every process on one S3DF node (`sdfmilan082`, `sdfada013`, ...).
  `tree.py` gives each process the host MFX runs it on (`HOSTS`, from the hutch-resources map), in the
  file names and in the text: `control` and `teb0` on `drp-srcf-cmp014` (so the map's
  `<restart-stamp>_drp-srcf-cmp014:control.log` works as on the real tree), the timing, EPICS, BLD,
  PVA-camera and encoder DRPs there too, the GUIs and the sim's helper servers on `mfx-daq`, AMI and the
  monitoring MEB on `drp-srcf-mon006`, and each detector DRP on one of MFX's `drp-srcf-cmpNNN` DRP nodes
  (`jungfrau_N` and `epix100_0` where MFX has them, others by a fixed hash of the name). In the text a node
  name takes the host of its own process (the `# HOST:` header, the `alias` of the dict it is in, the
  process of a log-file name). The build fails if any S3DF node name is left; the second hutch gets TMO's
  hosts. As at MFX, the AMI chain and the monitoring MEB carry the instance suffix `_first`
  (`meb0_first`, `ami-node_0_first`, `ami-client_first`; program names such as `bin/ami-global` keep
  theirs), and the partition configs in `daq/scripts` have the shape of MFX's `mfx.py` (double-quoted
  literals, `host: collect_host` for control, GUIs with no host key, the AMI/MEB processes made by a
  `for instance ...` loop at the end), so the map's `mfx.py` recipes read them as at MFX.
- **Rotation as at "now"** (families B and C). MFX's daily rotation (`daq/logs/mfx_rotate_logs.log`, 14:00)
  compresses a current-tree file to `.zst` once it is 7 days old. The rotation log is not in the fetched
  root; the rule was read off the fetched November folder (last run 2026-11-18 14:00: newest `.zst` modified
  2026-11-11 10:35, oldest plain `.log` 17:10, one launch split across the mark, so it goes by each file's
  modification time; `real_mfx.rotation_cutoff`). Each case's tree shows `daq/logs/<YYYY>/<MM>/` as the
  rotation had left it at the case's "now": files modified after the last run's 7-day mark are plain
  `.log` (a decompressed copy, modification time kept), older ones `.zst`. The old root and the second
  hutch keep their names. `cases_v3.json` holds the keyed files' names as the case's tree shows them
  (`tree.py --write-cases`). The build fails unless each case's widest reading of its vague time holds only its
  keyed launch in the MFX roots. The second hutch has launches inside some windows on purpose (a
  wrong-tree trap; `manifest.json` counts them).
- **ask-operator** (mode m1): a command on the agent's PATH. It answers from the case's fixed table
  (when, which hutch, what was seen; anything else gets "I don't know more than what I told you.")
  and every question goes to `<run>/operator.jsonl`. The table stays outside the sandbox.
- **Controls**: `pointer` (m1) adds the log directory and the exact window; `crib` (m0) puts the
  key's mechanism, verbatim from the key, before the prompt; `starved` removes the keyed launch's
  root-cause files (its component's log and every file stating the key's mechanism).
- **Calls to evidence** (`evidence.py`): tool calls before the first call that reads a file of the
  keyed launch; never read = total + 1. A call reads one when its output shows one of its lines (a
  40-character line start unique to the keyed launch, anywhere in an output line: after a line number or
  file name, in the skills helper's `daq-logs.py list` row, inside its JSON `"line"`/`"first_error"`
  strings), or when it is a Read of a plain keyed `.log` that did not fail. A Read of a `.zst` counts only
  if its output shows such a line. Each row also gets `calls_no_guidance` (the same count with Skill calls
  and reads under `.claude/skills/` left out; a helper run on `/sdf` is not a guidance read), which
  `verdict.py` prints as a descriptive sensitivity check only.

### Family C, scoring cold-start runs, `pilot.py` and `verdict.py`

```bash
REAL=$HOME/mfx-root                                   # python3 real_mfx.py fetch --dest $REAL (see "Real MFX cases")
python3 real_mfx.py view --root $REAL --dest $WORK/roots/real     # optional: run.py builds the views itself
python3 run.py --work $WORK --mode m1 --family C --real-root $REAL --arm C-none --skills none --out $OUT
python3 run.py --work $WORK --mode m1 --family C --real-root $REAL --arm C-pointer --skills none --control pointer --out $OUT
python3 score.py --results $OUT --out $OUT/scored.json    # m0 and m1 runs of every family
python3 evidence.py --results $OUT --work $WORK --write
```

- **Root view** (family C): each case mounts at `/sdf`, read-only as in family B, a view of the prepared root
  that holds only what existed at the case's "now" (its `today` at `now_time`, 10:00 Pacific, in
  `cases_real.json`): launch files whose name stamp is before it, other files (`.psdaq`) modified before it,
  and all of `daq/scripts/` whatever its time (an approximation: MFX's `mfx.py` was edited on 2026-11-16, so
  every view shows today's version and time; without it no view had a partition config, which MFX always
  has). Files are hard links under `$WORK/roots/real/<case>/root`, except current-tree files whose rotation
  state at "now" differs from today's (see "Rotation as at now"): those are converted copies shared under
  `$WORK/roots/real/.rotation`. `view.json` sits beside the root (outside the mount) and counts them. The prompt is `cases_v3.json`'s m1 context at that time plus
  `cases_real.json`'s question; `ask-operator` answers from the case's `operator` table (`operator_rules`);
  `pointer` adds the target launch's folder (`/sdf/home/m/mfxopr/<YYYY>/<MM>` before the 2026-09-17 cutover)
  and window. `TZ` is America/Los_Angeles in every sandbox, and stamps, `now` and the windows are Pacific.
- **Scoring cold-start runs** (`score.py`): keys come from the case tables, never from a report. Family B:
  the pool's `keys_v3.json` key with its launch moved to the case's `keyed_stamp`; Cause = Located +
  component + stage + mechanism. Family C fault cases (`cause_scope: component+stage`): Cause = Located +
  the target launch's scripted component and stage, the mechanism is not judged. Healthy cases of both
  families: clean, benign-defect-noted or false-alarm. Located (cold start): the launch the report
  concludes about (the launch of its main cause; for a report that finds no fault, the session it says it
  reviewed), from a second report-only extraction call, resolves to the keyed launch (stamp,
  file name, or a time in it or within 2 minutes of its start; UTC times use that day's PDT/PST offset).
  Naming the keyed launch elsewhere (a list of the sessions examined) does not count by itself;
  `facts.keyed_named_anywhere` keeps that looser reading for comparison.
- **`pilot.py`** runs a batch of cells (family/arm/model/cases/repeats) with at most `--jobs` agents at once
  (default 2), then `score.py` and `evidence.py`, and writes `OUT/rows.json` (one row per run, the schema
  `verdict.py` reads) and `OUT/usage.json` (agent and scorer usage). It prints a per-run estimate and
  refuses to start when the projection exceeds `--budget-left`:

```bash
P="python3 pilot.py --out $OUT --work $WORK --real-root $REAL --skills $SK --map $MAP --jobs 2 --resume"
$P --budget-left 100 --cell B/none --cell B/skills --cell B/map --cell B/both --cell B/pointer --cell B/starved --repeats 2
$P --budget-left 100 --cell C/none --cell C/skills --cell C/map --cell C/both --cell C/pointer --repeats 2
$P --budget-left 5 --cell A/none/haiku --cell A/crib/haiku --cell A/starved/haiku --repeats 3
python3 verdict.py $OUT/rows.json                         # P2-P6 and P3m, the pre-registered rules in verdict.py's docstring
```

## Using another agent

`run.py --agent-cmd CMD` runs any program in place of Claude Code, in the same sandbox. The
contract is small: the prompt arrives on stdin, the working directory is `/work`, the logs
are at `/sdf/home/t/tstopr/daq/logs`, and whatever the program prints is its report.

```bash
python3 run.py --work $WORK --arm my-agent --skills $SK --skills-path .agents/skills --out $OUT \
    --agent-cmd "my-agent --non-interactive" --expose /path/to/my-agent/install --bind $HOME/.my-agent
```

`--skills-path` is where that agent looks for skills, `--expose` shows a directory
read-only, `--bind` read-write (a login or state folder). For such runs `grade.py` cannot
see the agent's commands, so read-only and skills-loaded show as not checked; cause,
launch, known issue and structure are graded as usual. The judge is replaceable the same
way (`judge.py --judge-cmd`: the rubric on stdin, a JSON object with a `result` string on
stdout); without any judge, `grade.py` falls back to its keyword check.

## The cases

`catalog.json` has 53 cases over 45 log directories ("pools"). 34 are the `core` set, 17
more repeat a fault on other detector types (`--set full`), and 2 are `disputed` and never
scored (see below).

| Tier | The agent is given | Cases | What makes it hard |
|---|---|---|---|
| 1 | one launch, 3 to 5 processes | 38 (22 core) | the symptom and the cause are in different files; the loudest log is often a casualty; control sometimes blames the wrong process; two faults have no error line at all |
| 2 | one launch of a full partition, 23 to 36 processes | 6 (3 core, 2 disputed) | one fault among dozens of processes that all die noisily at shutdown |
| 3 | one node's whole day: 149 launches, 1429 files, the older ones `.zst` | 9 | the right launch must be found first: by local time, by UTC, by counting every failed launch in a window, or by showing that a window was clean while others were not |

Where the answer keys come from (`key_source` in the catalog):

- **planted** (33 cases): the sim broke one thing on purpose and wrote down what. For a
  register fault the sim's own log line names the register; `harvest.py` removes that line
  from the copy and keeps it in `pool.json`. Healthy runs passed the sim's own checks.
- **observed** (20 cases): a real failure that happened while the sim was being built
  (a hang, a CUDA error, a queue overflow, a PV that never connected, ...). The key is the
  first failing component, the stage and the mechanism as the logs establish them, written
  by a reviewer who read every file and cited line numbers, with what the logs cannot show
  stated. Treat these keys as careful readings, not ground truth from outside the logs.
- **disputed** (2 cases, `big-healthy-31` and `big-healthy-36`): the sim counted these
  launches as passing, so they were keyed "no fault". Agents in both arms then reported
  12 to 16% of triggers lost to dead time and a few damaged events. Until someone checks,
  "no fault" is not a safe key, so `run.py`, `judge.py` and `grade.py` skip them.

## The tools

| Step | Tool | Uses the model? |
|---|---|---|
| 0. Unpack the bundled logs | `tar xzf data/pools.tar.gz -C $WORK` | no |
| 1. Only for new cases: build log directories from sim runs, then re-pack `data/pools.tar.gz` | `harvest.py` | no |
| 2. Run the agent on each case, per arm | `run.py` | yes, one headless session per case and repeat |
| 3. Judge each report against its key | `judge.py` | yes, one small call per report |
| 4. Grade and tabulate | `grade.py` | no |
| 5. One HTML page of the results | `report.py` | no |
| 3b. v3: score each report fact by fact against `keys_v3.json` (written by `make_keys_v3.py`) | `score.py` | yes, one extraction and three one-sentence judgements per report |

An **arm** is one configuration under test: the skills at some commit, or `none`.

```bash
cd evals/daq_skills
python3 -m unittest discover -s tests -v                       # 152 tests, no model calls
tar xzf data/pools.tar.gz -C $WORK                             # the bundled logs; or rebuild them from the sim runs:
# python3 harvest.py --root $SIM_RUNS --out $WORK              # exit 1 if a hint word leaks
mkdir -p $WORK/skills-181 && git archive upstream/features/daq-skills-v2 psana/psana/skills | tar -x -C $WORK/skills-181
python3 run.py --work $WORK --arm skills-181 --skills $WORK/skills-181/psana/psana/skills --out $WORK/results --jobs 3
python3 run.py --work $WORK --arm none --skills none --out $WORK/results --jobs 3
python3 judge.py --results $WORK/results
python3 grade.py --results $WORK/results
python3 report.py --results $WORK/results --out $WORK/report.html
```

`run.py --dry-run` writes the prompts without starting an agent; `--resume` keeps finished
runs; `--repeats N` repeats each case; `--model M` picks the agent's model.

## What is checked

| Check | Pass when | How |
|---|---|---|
| cause | the report's main conclusion is the key's component, stage and mechanism | `judge.py`: a model reads the report against the key with one rubric for every arm, three times, majority verdict. Verdicts: `correct`, `partial`, `unknown`, `wrong`; for a healthy case `correct` or `false-alarm` |
| cause (keywords) | the key's words appear in the cause section | `grade.py`: cheap and repeatable; used when there is no judge verdict, and shown beside it |
| launch | a tier 3 report names the key's launch | script. A diagnosis of another launch is `wrong` whatever the judge says |
| read-only | no DAQ, process, Slurm, ConfigDB, GitHub or git write | regexes over the agent's shell commands, quoted text ignored. Local file writes are listed, not failed |
| skills loaded | every skill in `expect_skills`, none in `forbid_skills` | the Skill tool, or a read of `<skill>/SKILL.md`. Not applicable to the `none` arm |
| known issue | the report cites the upstream issue that tracks something visible in the logs (`known_issues` in the key; today #134, the double free at exit) | script: `#134` or `issues/134` in the report |
| honesty | no `Confidence: high` on a wrong answer or false alarm | script |
| structure | reported only: template sections present, a confidence stated | script |

### The judge is calibrated, not trusted

`tests/judge_set.json` holds 32 reports with verdicts set by hand: hand-written right,
partial, wrong and "right words, wrong conclusion" reports, six real agent reports, and
traps such as the right mechanism in the wrong launch.

```bash
python3 judge.py --calibrate tests/judge_set.json    # sonnet: 30 of 32 on 2026-11-10
```

Its two misses are lenient ones: a report with the right register but the wrong stage,
and the wrong-launch trap (which the launch check then catches). Re-run the calibration
when the rubric or the judge model changes, and quote it with any score.

### The v3 scorer: facts, not one verdict

`score.py` scores each report fact by fact against `keys_v3.json`, and only one fact is judged:

```bash
python3 score.py --results $OUT --out $OUT/scored.json --summary $OUT/scored.txt   # 2 model calls at a time
```

1. **Extract.** One model call sees only the report (no key, no arm, no question) and returns a
   record: the verdict (fault, no-fault, unsure), the launches named, each problem with its role
   (cause, side issue, consequence, possible), component, stage and a verbatim quote of the
   mechanism, and the report's asks to the operator. Cached by the report's sha256. Cold-start runs
   get a second report-only call: the launch the report concludes about (for Located).
2. **Facts by script.** Launch (only in a pool of many launches), component and stage by aliases;
   `located`: the report names the keyed launch (stamp, file prefix, or a time inside it or within
   2 minutes of its start); for cold-start runs, the launch from the second call must be the keyed one.
3. **Mechanism by judge.** A model sees the extracted quote and the key's closed lists of accepted
   statements and near-misses, three times; the majority of accepted, near-miss or other wins.
4. **Outcome.** A fault case passes Cause when every fact passes (also given strict: all votes
   accepted, and lenient: any vote). A healthy case is clean, benign-defect-noted or false-alarm.

`make_keys_v3.py` writes `keys_v3.json` from `catalog.json`, the bundled pools and mechanism
statements written by hand from the logs (`--check` tells whether the file is current). The
replaceable commands are `--extract-cmd` and `--judge-cmd`, with the same contract as
`judge.py --judge-cmd`. `--traps tests/judge_set.json` runs the scorer on the hand-labelled reports.

## How a run is kept honest

- **Only process logs.** The sim's state and evidence files are never copied.
- **Paths are neutralised.** A run folder such as `.../break-register/types/epix100`
  becomes `/sdf/data/lcls/ds/tst/tstx00001/scratch/daq/s<hash>`.
- **Hint words fail the harvest.** `fault`, `break`, `skeptic`, ..., and the distinctive
  parts of each run folder's name, as whole words.
- **Nothing is invented.** No line is added, reordered or re-timed. Files keep their
  modification times; older launches are compressed as log rotation would.
- **The agent is sandboxed** (bubblewrap): it sees its working directory, the logs
  read-only at `/sdf/home/t/tstopr/daq/logs`, and system directories. No home directory,
  no ssh keys, no other runs, no answer keys. In an earlier unsandboxed pilot three of six
  agents went looking in a project folder they guessed from the working directory's path.
- **Prompts are the same for every arm** and say nothing about a fault. Healthy cases use
  the same question as faulty ones.
- **Folder names are opaque** (`p<hash>`, `r<hash>`), so a path never names a case.

## The bundled logs

`data/pools.tar.gz` holds `pools/<id>/logs/YYYY/MM/...` and a `pool.json` per pool (the
launches, their files, and the sim lines that were removed). It is the output of
`harvest.py` for this `catalog.json`; a unit test checks that the two match. The agent
never sees `pool.json`: only `logs/` is mounted in its sandbox. The logs are from the
simulator, carry no experiment data, and were scanned for credentials, e-mail addresses
and home-directory names before being committed. To add cases, harvest into a work
folder and re-pack: `tar --sort=name --owner=0 --group=0 --numeric-owner -cf - pools | gzip -n -9`.

## Real MFX cases (family C)

`cases_real.json` holds cold-start cases on **real** MFX DAQ logs. The logs are not in the
repository and never will be: the file holds only window specs (today's date, a vague phrase
such as "yesterday evening", the keyed launch's stamp, its file names and their sha256) and
the keys `real_mfx.py` computes from the logs. You get the logs from S3DF with your own login;
the MFX trees under `/sdf/home/m/mfxopr` are world-readable there.

```bash
python3 real_mfx.py fetch --dest $HOME/mfx-root            # rsync over ssh from sdfiana025; checks every case file's sha256
python3 real_mfx.py keys  --root $HOME/mfx-root            # recompute the keys; exit 1 if a file or key drifted
python3 real_mfx.py check --root $HOME/mfx-root            # each vague window holds only keyed launches
```

`fetch` builds a prepared root laid out as the real paths (`<ROOT>/home/m/mfxopr/...`), which
the cold-start mode mounts read-only at `/sdf`: the months the cases touch from both trees
(`daq/logs/<YYYY>/<MM>/` from 2026-09-17 09:29, `<YYYY>/<MM>/` before that), plus
`daq/scripts/` and `.psdaq/`. Past `--max-bytes` (default 2 GB) it drops the largest files that
no case needs and lists them in `<ROOT>.manifest.json`. Add `--rsh "ssh -F <config>"` if your
S3DF host needs an ssh config, `--dry-run` to see the plan.

The seven cases (keys from `keys`, uniqueness from `check`, both run on S3DF and on a fetched copy):

| id | today | phrase | target launch | key | why chosen |
|---|---|---|---|---|---|
| real-pv-cfg | 2026-10-23 | Wednesday morning | `daq/logs/2026/10/21_08:21:25` | t_zero_alvium_0, configure, pv-get-parameters | fault, current tree; 3 idle launches beside it |
| real-qadc-run | 2026-11-05 | yesterday evening | `daq/logs/2026/11/04_16:52:14` | qadc_0, running, abort | fault during running; healthy launches on both sides |
| real-pre-cutover | 2026-09-17 | yesterday afternoon | `2026/09/16_15:05:23` (old root) | timing_1, alloc, xpm-remote-link-id | fault only in the previous tree |
| real-month-edge | 2026-11-02 | Friday morning | `daq/logs/2026/10/30_06:20:41` | healthy | today in November, launch in the October folder |
| real-healthy-sun | 2026-10-27 | Sunday afternoon | `daq/logs/2026/10/25_17:47:57` | healthy | alone in its window |
| real-healthy-nov | 2026-11-08 | Thursday afternoon | `daq/logs/2026/11/05_11:30:53` | healthy | alone in its window |
| real-pre-cutover-ok | 2026-09-18 | Tuesday afternoon | `2026/09/15_14:37:58` (old root) | healthy | daq/logs/2026/09 exists but starts on the 17th |

Every case has an `operator` table (symptom, when, what next, detectors) for the ask-operator
command, and `operator_default` for any other question. The answers are no more specific than family
B's (`operator_specificity`): the failing stage at most ("would not configure", "something went wrong in
the middle of a run"), never the keyed component, a word of its name, or a detector list ("the usual MFX
set"); a test checks both families.

How the keys are made (all by script, no reading by hand):

- A **launch** is a file-name stamp with a `control.log`; files of a stamp without one (a
  process restarted by hand) belong to the launch before it. Stamps and log lines are local
  Pacific time.
- **Inventory key**: per component (the file's process name), which error classes occur:
  `pv_connect`, `no_response` (did not respond to a transition), `state_failed`, `crash`
  (abort, core dump, signal, non-zero exit), `traceback`; whether control reached `running`.
- **Component key**: control.log's first failure (`<X> did not respond to <transition>`, a
  `Phase N error`, `<transition> failed to change state`, or the event builder not hearing
  from X), grouped over 60 s on the same transition. Keyed only if exactly one component is
  named there and that component's own log has an error line of its own; the mechanism label
  comes from that log (`detector-socket-connect`, `pv-get-parameters`, ...). Otherwise
  "not keyed", or "healthy" when control reached `running` with no failure line.
- A **window** is the widest reading of the phrase (morning 00-13 h, afternoon 11-19 h,
  evening 16-24 h, night 18-08 h, a whole day 00-24 h, a weekend Fri 18 h to Mon 08 h). `check`
  fails a case if any launch whose span (stamp to last control line) overlaps the window is
  not keyed.
- sha256 is taken over the decompressed bytes: a rotation job on S3DF compresses the current
  tree's files to `.zst` after about a week, which changes the stored bytes but not the log.

Caveats: the rotation job also has a deletion step (it had deleted nothing by 2026-11-17); if
it starts deleting, `fetch` will report the missing case files. The prepared root holds months
after a case's "today"; a run sees only the case's root view (above), which drops them. The view
keeps files as they are now, except the rotation (above): a launch still running at the case's "now"
(the last one before it) keeps its later lines and modification time, and `daq/scripts/` holds today's
files (`mfx.py` last modified 2026-11-16, after every case's "now"). A view decompresses the current-tree
files of the week before its "now": about 19 GB over the seven views (11 GB for real-pre-cutover-ok,
whose week holds the large detector logs of 2026-09-17 evening); copies are shared between views.

## Known limits

- The sim's faults are cleaner than a hutch's. All logs say "simulated device", and
  reports mention it.
- Only the control and logs skills (and the router) are exercised. The monitor and
  ConfigDB skills need Grafana and ConfigDB; the history skill is only checked for staying
  unused.
- The agent has network access (it must reach its model), so the skills' search of
  upstream issues works but is rate-limited and changes as issues change.
- One repeat per case says little about a single case; compare arms over the whole set,
  and repeat before drawing conclusions about one.
- "Observed" keys were written by a model reading the same logs the agents read.
