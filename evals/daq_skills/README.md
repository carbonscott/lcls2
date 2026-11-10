# Evals for the DAQ diagnostic skills

These tools measure whether the `psana-daq*` skills (`psana/psana/skills/`, upstream PRs
#131, #181, #191) lead an agent to the right diagnosis of a DAQ problem, and what they add
over the same agent with no skills.

Each case is a question about real DAQ logs whose cause is known. The logs come from the
hardware-free sim (`psdaq/psdaq/sim`), which runs the real `control`, `teb`, `meb` and `drp`
programs, so the files have the production layout and messages:
`YYYY/MM/<DD_HH:MM:SS>_<host>:<component>.log[.zst]`.

## Quick start for skill authors

Everything needed is in this folder: the tools, the cases, and the logs the cases are
about (`data/pools.tar.gz`, 8.3 MB, 45 log directories). You do not need the sim, S3DF
group access or `harvest.py`. You need the `claude` CLI logged in to your own account, and
`bwrap` and `zstd` (both are on the S3DF interactive nodes).

```bash
git clone --depth 1 https://github.com/carbonscott/lcls2 daq-evals   # the default branch, sim-main
cd daq-evals/evals/daq_skills
python3 -m unittest discover -s tests                          # 32 tests, OK, no model calls
WORK=$HOME/daq-eval-work && mkdir -p $WORK && tar xzf data/pools.tar.gz -C $WORK      # any folder of yours
OUT=$HOME/daq-eval-results                                       # your results go here
SK=/path/to/your/lcls2/psana/psana/skills                        # the skills you are working on

python3 run.py --work $WORK --arm mine --skills $SK  --out $OUT --case reg-cfg-tt --case day-window-utc   # 2 runs, about a minute
python3 run.py --work $WORK --arm none --skills none --out $OUT --case reg-cfg-tt --case day-window-utc
python3 judge.py --results $OUT && python3 grade.py --results $OUT

# the whole core set (34 cases per arm, about 15 minutes with --jobs 3, about $1.30 of usage per run on the default model)
python3 run.py --work $WORK --arm mine --skills $SK  --out $OUT --jobs 3 --resume
python3 run.py --work $WORK --arm none --skills none --out $OUT --jobs 3 --resume
python3 judge.py --results $OUT && python3 grade.py --results $OUT && python3 report.py --results $OUT --out $OUT/report.html
```

- Use any arm name; edit a skill, pick a new name (`--arm mine-v2`) and compare the summary lines.
- If `claude` is not under `~/.local` or a system directory, add `--expose <its folder>`.
- To test the skills when they are certainly read, add `--preface "Load the psana-daq skill before you start."` under its own arm name.
- Unpack with `tar` so the files keep their modification times; the logs skill's helper picks sessions by them.
- Tested: the unit tests, the sandbox and a scripted agent on S3DF (Python 3.6); real agent runs on a Linux VM
  (Python 3.12). A real Claude Code run on S3DF itself has not been tried yet.

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

An **arm** is one configuration under test: the skills at some commit, or `none`.

```bash
cd evals/daq_skills
python3 -m unittest discover -s tests -v                       # 32 tests, no model calls
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
