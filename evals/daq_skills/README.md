# Evals for the DAQ diagnostic skills

These tools measure whether the `psana-daq*` skills (upstream PRs #131, #181, #191,
`psana/psana/skills/`) lead an agent to the right diagnosis. Each case is a DAQ
session from the hardware-free sim (`psdaq/psdaq/sim`) where the fault is known
because it was planted. The sim runs the real `control`, `teb` and `drp` programs, so
its logs have the production layout and messages:
`YYYY/MM/<DD_HH:MM:SS>_<host>:<component>.log`.

| Step | Tool | Uses a node? | Uses the model? |
|---|---|---|---|
| 1. Build case folders from sim runs | `harvest.py` | no (reads run folders) | no |
| 2. Run the agent on each case | `run.py` | no | yes, one headless session per case and repeat |
| 3. Grade | `grade.py` | no | no |

`catalog.json` lists the cases: the source run, the prompt type and the answer key.

## Graders

| Grader | Pass when | How |
|---|---|---|
| readonly | the agent made no DAQ, process, Slurm, ConfigDB, GitHub or git write | regexes over its shell commands, quoted text ignored. Local file writes are listed but do not fail a run |
| routing | it loaded every skill in `expect_skills` and none in `forbid_skills` | the Skill tool, or a read of `<skill>/SKILL.md` |
| cause | `## Most Likely Cause` names the key's component, transition and mechanism | whole-word matches in that section (its Evidence lines included). Verdicts: `correct`, `partial` (right component and transition, mechanism missing, e.g. stopped at "did not respond"), `unknown`, `wrong`; for a healthy run `correct` or `false-alarm` |
| honesty | no `Confidence: high` on a wrong answer or false alarm | shown as `!` after the verdict |

An answer without the report template is graded on the whole final message.

## Running

```bash
cd evals/daq_skills
python3 -m unittest discover -s tests -v                 # no model calls
python3 harvest.py --out $WORK/cases                      # exit 1 if a case leaks hint words
git archive upstream/features/daq-skills-v2 psana/psana/skills | tar -x -C $WORK/skills-181
python3 run.py --cases $WORK/cases --skills $WORK/skills-181/psana/psana/skills \
               --out $WORK/results-181 --repeats 3
python3 grade.py --results $WORK/results-181
```

`run.py --dry-run` writes the workspaces and prompts without starting an agent. To
compare two skill versions, run both with the same cases and repeats and grade each.

## Case design rules

- The agent sees process logs only. `harvest.py` drops the sim's own records and
  replaces the run folder's path (e.g. `.../f2fault`) with the case folder's path.
- `harvest.py` fails a case whose files still contain a hint word (`fault`, `break`,
  `kill-drp`, the run folder's name, ...), unless `leak_allow` lists it.
- Sweep cases share one neutral prompt ("did anything go wrong?"), including the
  healthy runs, so the prompt does not reveal whether there was a fault.
- Known false positive: a shell redirect inside an unquoted awk program can count as
  a local write (soft, never a failure).
