# Sources of the screenshots

- `01-code-evidence-dir.png` (1400x1333): rendered from `../evidence/cycle-code.log` (lines 1-3, 5-51) by `lib/render.py`, caption "daq_sim cycle at sim-main 6f0a24dae writes its evidence record into the checkout that holds the code, unless DAQ_SIM_EVIDENCE is set"; highlights `^\s+2112 `, `^\s+198 `, `^\s+538 `, `^\s+578 `, `^\s+2975 @@yellow`, `^\s+2977 @@yellow`; callouts 6. Unedited text of the capture.
- `02-cycle-from-own-folder.png` (1500x733): rendered from `../evidence/cycle-run.log` (lines 1-22) by `lib/render.py`, caption "A user runs daq_sim cycle from their own folder with someone's build sourced; before the run the checkout has no .daq_sim"; highlights `links up: lo @@green`, `the user.s own folder@@yellow`, `cannot access`, `evidence 2026`; callouts 4. Unedited text of the capture.
- `03-checkout-written-git-clean.png` (1500x1043): rendered from `../evidence/cycle-run.log` (lines 1-5, 24-50) by `lib/render.py`, caption "After the cycle the checkout holds a new file that git status does not show, and the checkout's coverage counts the visitor's run"; highlights `^\$ git .* status --short$@@yellow`, `^  /.*\.daq_sim/evidence/2026.*\.json$`, `^!! \.daq_sim`, `^(det:drp|prog:)`, `rows, 4 run`; callouts 5. Unedited text of the capture.
- `04-control-evidence-env.png` (1500x667): rendered from `../evidence/cycle-run.log` (lines 1-5, 52-64) by `lib/render.py`, caption "Control: the same cycle with DAQ_SIM_EVIDENCE set passes and leaves the checkout untouched (0 files changed)"; highlights `\(0 files\)@@green`, `cycle PASS@@green`; callouts 3. Unedited text of the capture.

## Where the captures came from (S3DF, project root `/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-issues/`)

| Evidence file | S3DF capture | Written by |
|---|---|---|
| `evidence/cycle-run.log` | `agents/h4/runs/cycle-20261126T073121Z/capture.log` | `agents/h4/scripts/cycle-writes-demo.sh` in Slurm job 47203689 step 14 on sdfrome044, inside a private network namespace (`unshare -rnm` + sim-hutch `74dfe60` `simhutch.netns`) |
| `evidence/20261125T233222-cycle-6f0a24dae-1162933.json` | `agents/h4/lcls2/.daq_sim/evidence/20261125T233222-cycle-6f0a24dae-1162933.json` | written by `daq_sim cycle` itself in that run (the file this issue is about), copied unchanged |
| `evidence/cycle-code.log` | `agents/h4/captures/cycle-code.log` | `agents/h4/scripts/code-capture.sh` (`git show` of carbonscott/lcls2 `6f0a24dae`) on sdfiana025 |

The lcls2 checkout is a fresh `git clone --branch sim-main https://github.com/carbonscott/lcls2` at `agents/h4/lcls2`, built in place (`source ./setup_env_daq.sh && ./build_all.sh -d -j 32`, BUILD_EXIT=0). Each capture was copied byte for byte with `bridge read --raw`. The PNGs were rendered from these files with `lib/render.py`: the capture text is set in an HTML page styled like a terminal and screenshotted with headless Chromium.
