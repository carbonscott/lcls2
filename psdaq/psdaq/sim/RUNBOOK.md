# Hardware-free lcls2 DAQ on one S3DF milano node: runbook

This runbook takes a fresh checkout to one recorded run with no hardware. The run uses a
simulated timing source (`simxpm`, which stands in for the XPM), one simulated detector DRP
(`drp -D fakecam -d sim://`), the TEB and the DRP's file writer. procmgr and control.py
(normal mode) run it, as they do in a hutch. The config DB and the run DB (eLog) are
campaign-local stand-ins on 127.0.0.1. Then it reads the xtc2 file back with psana2 and
takes everything down. The same run can be driven through the web control GUI
(`psdaq/psdaq/webgui`), by hand in a browser (§3b) or unattended by a headless browser with
one command, `daq_sim e2e` (§3c).

Everything in `psdaq/psdaq/sim/`:

| file | role |
|---|---|
| `daq_sim.py` (console script `daq_sim`) | `up` / `status` / `cycle` / `e2e` / `down`: the one command |
| `sim_env.sh` | Isolation env. EPICS CA and PVA stay on loopback, on ports 15064/15065/15075/15076. HTTP(S) goes to a dead proxy at `http://127.0.0.1:9`. Production credentials are emptied. `FI_PROVIDER=tcp`. `daq_sim` sources it itself. |
| `preflight.sh` | Fail-closed check that `daq_sim up` runs first. It must print `PREFLIGHT PASS`. |
| `configdb_server.py`, `configdb_seed.py` | Config DB stand-in, seeded with `tst/BEAM/tmoteb_0` (persistValue 0xdeadbeef) and `tst/BEAM/fakecam_0` (`user.sim_seed`). |
| `lgbk_server.py` | Run DB / eLog stand-in. Experiment `tstx00001`; runs are numbered from 1. |
| `simxpm.py` | Software XPM: the pyxpm PVs over PVA, timing frames to `sim://` DRPs, and the `control -X` PULL receiver. |
| `xtc2_check.py` | psana2 read-back with a per-event payload check. |
| `coverage.py`, `coverage_status.json` | `daq_sim coverage` and `daq_sim matrix` (§3d): which detector types and programs are proven to run without hardware, at HEAD. |
| `procmgrd.s3df.conf` | procmgr rcfile for S3DF: the rhel9 procServ. |
| `../webgui/server.py` (console script `daq_webgui`) | The web GUI server; `up --webgui` starts it on 127.0.0.1:31053. |
| `../webgui/e2e.py`, `../webgui/e2e_browser.py` | `daq_sim e2e`: the checks (DAQ env), and the headless-browser driver (Playwright venv). |

## 0. Rules
- **Where processes run.**
  - DAQ processes run only on the milano node, inside `srun` steps of your own allocation.
  - The interactive node (sdfiana*) is for git and editing only; `daq_sim up` refuses to run there.
  - Never use a hutch or DAQ host.
- **Steps hold the processes.** A Slurm step kills its processes when the step's main process exits.
  - `daq_sim up` therefore stays in the foreground and keeps its step alive.
  - Drive the run from a second step started with `srun --overlap`.
- **The bridge shell.** In a `/bin/sh` shell, such as the bridge shell, wrap commands in `bash -c '...'`, because `source` needs bash.

## 1. One-time setup (on sdfiana025)
```bash
# allocation: one exclusive milano node; reuse it for everything below
salloc --no-shell --account=lcls:prjdat21 --qos=normal --partition=milano --exclusive \
       --cpus-per-task=120 --time=1-00:00:00 --job-name=daq-sim
squeue -u $USER                       # note the JOBID; below: JOB=<that id>
JOB=<jobid>

# fresh checkout of the branch that holds psdaq/psdaq/sim (agentify)
ROOT=/sdf/data/lcls/ds/prj/<your project>/scratch/<you>     # any directory on a shared filesystem
cd $ROOT && git clone https://github.com/carbonscott/lcls2.git && cd lcls2 && git checkout agentify

# build on the node (about 1.5 min the first time, about 30 s after a small change)
export XDG_CACHE_HOME=/sdf/scratch/users/${USER:0:1}/$USER/.cache UV_CACHE_DIR=/sdf/scratch/users/${USER:0:1}/$USER/.uv-cache
srun --jobid=$JOB --ntasks=1 --cpus-per-task=32 --mem=64G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && ./build_all.sh -d -j 32; echo BUILD_EXIT=\$?"
```
Always pass `--ntasks=1`, `--cpus-per-task` and `--mem` on every `srun`:
- Without `--ntasks=1` the step runs once per CPU.
- Under `--exclusive` a job-level memory cap does not bind, so give `--mem` on the step.

Set the cache variables if uv or pip hangs on /sdf/data. The build ends with `BUILD_EXIT=0`; uv's
`warning: Failed to hardlink files; falling back to full copy` (the cache and the checkout are on
different filesystems) is harmless. The `srun` stays in the foreground for the whole build: in a
shell that cuts commands off (an agent's remote shell, often 120 s), run it under `nohup ... &`
with its output in a file and poll the file.

## 2. Bring the DAQ up (step A, stays in the foreground)
```bash
WD=$ROOT/daq_sim_run                  # work dir: state, logs, config DB, data
nohup srun --jobid=$JOB --ntasks=1 --cpus-per-task=32 --mem=64G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim up -w $WD" > $ROOT/daq_sim_up.log 2>&1 &
sleep 45; cat $ROOT/daq_sim_up.log
```
`up` takes about 30 s:
- The preflight takes about 22 s and must print `PREFLIGHT PASS`.
- The config DB is seeded, and the run DB and simxpm start.
- procmgr starts control, teb0 and fakecam_0.
- `up` waits for all three to be RUNNING and for control to answer in state `reset`.
- Then it prints `UP. Endpoints (also in endpoints.json):` and stays in the foreground.

Options:

| option | effect |
|---|---|
| `-p <platform>` | Platform; default 5. Changes every port. |
| `--rate <Hz>` | L1Accept rate; default 1000. |
| `--seed <n>` | sim_seed stored in the config DB; default 0x1234. |
| `--length <words>` | Payload words per event; default 64. |
| `--segments <n>` | Run n fakecam DRPs (fakecam_0 .. fakecam_<n-1>, segments of one detector, each seeded in the config DB); default 1. `cycle` and `e2e` check fakecam_0's file (the first `-s<n>` file holding segment 0). |
| `-S <Hz>` | control's SlowUpdate rate; default 1. |
| `-v` | Run teb and drp with -v. |
| `--webgui` | Also start the web GUI on 127.0.0.1:31000+10p+3 (31053), see §3b. |

If anything fails, `up` prints the reason, takes down what it started, and exits 1.

Ports for platform p; p = 5 gives the values in brackets:

| port | what |
|---|---|
| 31000+10p (31050) | config DB stand-in |
| +1 (31051) | run DB stand-in |
| +2 (31052) | simxpm frames |
| +3 (31053) | web GUI (`up --webgui`), 127.0.0.1 only |
| 29985-30045 | control ZMQ |
| 29502- | procServ |
| 30050 | `control -X` → simxpm PULL |
| 9200-9299 | Prometheus exporters of the teb and drp; discovery files in `$WD/prom/` |
| 15075/15076, 15064/15065 | EPICS PVA and CA |

All peers are on 127.0.0.1.

## 3. Drive a run with the CLI (step B)
```bash
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=4 --mem=8G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim cycle -w $WD --events 1000; echo CYCLE_EXIT=\$?"
```
`cycle` drives the run with `psdaq.control.DaqControl`, the client the GUIs use:
1. It sets recording on.
2. It walks reset → unallocated → allocated → connected → configured → starting → paused → running, one state at a time, and reads every state back.
   - After rollcall it does the GUI's `selectPlatform`.
3. It waits until simxpm has counted at least `--events` L1Accepts.
4. It walks back down to `reset`.
   - 1 s after Disable it records simxpm's `NumL0Acc` and the TEB's `TEB_WrtCt` from Prometheus.
5. It reads the run's xtc2 file with psana2.

It prints the transitions with their timestamps, then a count table. Expected end (the rows that
matter; the table also lists simxpm NumL0Inp, TEB_EvtCt, TEB_TrCt, the DRP counters, the xtc2 file
and the psana2 seq; at 1 kHz N is about 1900-2100):
```
  simxpm NumL0Acc        <N>
  TEB_WrtCt              <N>
  psana2 events          <N>
  psana2 with data       <N>
  psana2 checks          PASS
  equal (simxpm NumL0Acc == TEB_WrtCt == psana2 events) >= 1000: True
... evidence <id>: det:drp:fakecam prog:control prog:drp prog:pyxpm prog:teb
... cycle PASS
CYCLE_EXIT=0
```
The `evidence` line is the record that `daq_sim coverage` reads (§3d).
`cycle` exits 1 on any of these:
- a state that does not read back,
- an `error` message on control's status stream,
- counts that are not equal,
- a failed psana2 check,
- not ending in the start state.

`daq_sim status -w $WD` shows the processes, control's state, simxpm's counts and the Prometheus counters.

To drive by hand, use `daqstate -p 5 -P tst -C localhost --state <state>` (`--record 1` before beginrun). **daqstate exits 0 even when a transition fails**, because control answers setstate before it runs the transition. Always read the state back (`daqstate -p 5 -P tst -C localhost`) and check `$WD/pmlogs/*/*/*control.log`.

## 3b. The web GUI (by hand)
Bring the DAQ up with the web GUI: add `--webgui` to the `daq_sim up` line of §2. `up` then
starts `daq_webgui` after control answers `reset`, and prints
```
daq_sim: web GUI up: http://127.0.0.1:31053/ (pid <pid>) control state reset
...
  webgui       http://127.0.0.1:31053/  (pid <pid>; from your machine: ssh -L 31053:127.0.0.1:31053 <node>, via the login host)
```
What it runs (logs in `$WD/logs/webgui.log`):
- the real `psdaq.control.DaqControl` backend against this platform's control (`-p 5 -H 127.0.0.1`);
- aliases from the config DB stand-in (`--configdb-url http://127.0.0.1:31050/ws/`);
- the **events** number = simxpm's accepted-L1 counter `DAQ:SIM:XPM:0:PART:5:NumL0Acc`, read over
  PV Access (`--events-source pva`; the PV is `<pvbase>:XPM:<xpm>:PART:<platform>:NumL0Acc`, as
  pyxpm names it). The server refuses to start (exit 2) unless `EPICS_PVA_AUTO_ADDR_LIST=NO` and
  `EPICS_PVA_ADDR_LIST` holds loopback addresses only; `sim_env.sh` sets both. Drops =
  NumL0Inp - NumL0Acc. After a run is disabled, the number becomes final (`data-final="1"` on
  `#edi_evt`) and stays on the page through EndRun, Unconfigure and Reset, until the next
  Configure/BeginRun.

The web copies of the other PyQt GUIs are pages of the same server, at `/gui/<name>`: `/gui/procstat` (with
`--procstat-cnf $WD/daq_sim.cnf`), `/gui/groupca` (`--pvgui 'groupca:DAQ:SIM 0 5'`) and `/gui/pvant`
(`--pvgui 'pvant:--bases ... --fields ...'`). `up --webgui` does not pass these; start a `daq_webgui` with them
(`psdaq/psdaq/webgui/README.md`, "Parity with the other PyQt GUIs").

It listens on 127.0.0.1 of the node only. To open it from your own machine, tunnel to the node
that holds the job (S3DF lets you ssh to a compute node only while you have a job on it; this
tunnel was not tested in this campaign):
```bash
ssh -L 31053:127.0.0.1:31053 -J <you>@s3dflogin.slac.stanford.edu <you>@<node>     # e.g. <node>=sdfmilan119
# then browse http://127.0.0.1:31053/
```
In the page: **Select** (rollcall) → tick processes → **Apply** (allocated) → **recording** on →
target state CONNECTED, CONFIGURED, ... RUNNING (one at a time), and back down to ALLOCATED and
RESET (the target-state box is disabled in UNALLOCATED, as in the PyQt GUI). `daq_sim down`
stops the web GUI first.

## 3c. One command: the end-to-end test (`daq_sim e2e`)
```bash
srun --jobid=$JOB --ntasks=1 --cpus-per-task=32 --mem=64G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim e2e -w $ROOT/e2e_run --events 1000; echo E2E_EXIT=\$?"
```
This is a step of its own; it brings a DAQ up in `-w` (on platform 5's ports, so first take any
DAQ from §2 down with §5, or give it another `-p`; else it stops at once with
`daq_sim e2e: ports already in use: [31050, ...]`) and takes it down again. To test the DAQ that
is already up from §2 instead, run the same line with `srun --overlap` and that DAQ's `-w $WD`
(e2e starts the web GUI there if `up` was run without `--webgui`, inside its own step, so that web
GUI stops when e2e ends and `up` logs `WARNING: webgui (pid ...) has exited`; the DAQ is left up
only if you add `--keep-up`, otherwise e2e takes it down). After a `cycle` recording is already
on; e2e then does not click the record button (it toggles), it prints `RECORD already on`.

It needs the browser venv below (`--browser-python`, default `$DAQ_SIM_BROWSER_PYTHON`, else
`$AGENTIFY_WEBTEST/venv/bin/python`, else `/sdf/scratch/users/<u>/<you>/agentify-webtest/venv/bin/python`;
chromium from `--browsers-path`, default `$PLAYWRIGHT_BROWSERS_PATH`, else `<venv>/../browsers`), and
says so and exits 1 before starting anything if it is missing.

Options (besides `up`'s `-p`, `--rate`, `--seed`, `--length`, `-S`, `-v`):

| option | effect |
|---|---|
| `--events N` | L1Accepts the run must record; default 1000. The test waits for N × 1.1. |
| `--edit-seed V` | Before Configure, edit `user.sim_seed` of BEAM/fakecam_0 to V in the web config editor (see 3). |
| `--expect-seed V` | The sim_seed the checks expect; default `--edit-seed`, else `--seed` (0x1234). |
| `--break kill-drp` | SIGKILL the DRP once RUNNING (the test must fail: 1 and 2). |
| `--break truncate-xtc2` | After RESET, before psana2 reads it, cut the last 100 L1Accepts off the run's xtc2 file (the test must fail: 6 only). |
| `--keep-up`, `--timeout S`, `--shots DIR` | Leave the DAQ up; per-transition timeout (60 s); screenshot dir. |

What it does, unattended (about 1 minute):
1. checks the browser venv; prints the host, Slurm job, `git rev-parse HEAD` of the current
   directory and `ls /dev/datadev* /dev/pcie_adc* /dev/tpr*`;
2. `daq_sim up --webgui --detach` in `-w` (preflight first), or uses the DAQ already up there
   (then it requires that up's `logs/preflight.log` to end in `PREFLIGHT PASS`) and must find
   control in `reset`;
3. a headless chromium (`e2e_browser.py`, run by the venv's python) clicks, as a user would:
   Select, Apply, (with `--edit-seed V`: **Edit** → type BEAM → device fakecam_0 → Edit →
   Expand → click `sim_seed`, type V, Enter → **Apply** → **OK** in "Save changes in
   configuration DB" → Close), recording on, CONNECTED, CONFIGURED, STARTING, PAUSED, RUNNING;
   then, after the checks, PAUSED, STARTING, CONFIGURED, CONNECTED, ALLOCATED, RESET. The driver
   only clicks and prints what the page shows (`DRV {...}`, `DOM ...` and `CFGEDIT ... page:` lines);
4. the checks, all in the `daq_sim` process with its own reads:
   1. its own PV read of NumL0Acc reaches `--events` × 1.1 while RUNNING, and over the next
      2 s it rises by at least half of `--rate` per second (the DAQ is still taking data);
   2. its own `DaqControl.getState` returns every clicked state, printed as
      `<STATE> clicked <iso ms> reported <iso ms>`, with no error on control's status stream and
      no KeyError in the control log;
   3. after Disable `#edi_evt` has `data-final="1"`, a `data-ts` later than the Disable, and two
      equal readings;
   4. the number is `^\d+$`;
   5. the page still shows it after RESET;
   6. page == `TEB_WrtCt` (Prometheus, in CONFIGURED) == psana2 events == psana2 events with
      fakecam data ≥ `--events`, page == its own NumL0Acc read after Disable, the run number on
      the page is control's, and psana2's per-event checks pass with the expected seed
      (`xtc2_check --seed`, so w3 == seed in every event); a count that differs is named
      (`MISMATCH: psana2 events 3434 != page 3534`);
   7. the DRP's own config read at Configure. Between the click to CONFIGURED and control
      reporting it (printed as `CONFIGURE ...` lines):
      - the config DB stand-in's `logs/configdb-access.jsonl` gains the DRP's
        `get_configuration/tst/BEAM/fakecam_0/`;
      - the page makes no `/api/configdb` request (the browser's own resource timing);
      - the DRP's log (`pmlogs/.../*:fakecam_0.log`, its pid) gains exactly one
        `Sim payload seed <seed> (0x...) from configdb BEAM/fakecam_0`, with the expected seed.

      With `--edit-seed V` also (printed as `CFGEDIT ...` lines): the editor reports
      `saved BEAM/fakecam_0 in tst: new key <k>`, the access log shows that save
      (`modify_device/tst/BEAM/`), and `daq_sim`'s own GET of the stand-in returns
      `user.sim_seed` = V;
5. with `--break truncate-xtc2`, the cut (the whole file is kept as `*.xtc2.untruncated`);
   `daq_sim down` (unless `--keep-up`), then the table.

Expected end (at 1 kHz N is about 3400-4600, 3464-4532 in 8 runs: the test waits for 1100, then 2 s more, then the
clicks down take about 1 s):
```
assertions:
  1 PASS  own NumL0Acc read <n> >= 1100 while RUNNING, then <n+2000> after 2.01 s: +2000 >= 1007 (half of --rate 1000 Hz), before the click down
  2 PASS  control read back 13/13 clicked states; 0 error message(s) on control's status stream; 0 KeyError line(s) in the control log
  3 PASS  after Disable (reported <t>): data-final 1,1; data-ts <t'> > Disable; readings at ...: 'N' == 'N'; source pva
  4 PASS  page events 'N' parse as ^\d+$
  5 PASS  after RESET the page shows 'N' (data-final 1), after Disable it showed 'N'
  6 PASS  page N == TEB_WrtCt N == psana2 events N == with data N >= 1000: True; page == own NumL0Acc after Disable N: True; psana2 checks (--seed 0x1234) PASS; run 1 (page 1)
  7 PASS  Configure: 1 get_configuration/tst/BEAM/fakecam_0 in the window (page: 0 /api/configdb); DRP pid <pid> (log pids ['<pid>']) logged ['4660 (0x1234) from configdb BEAM/fakecam_0']; expected 4660 (0x1234) from configdb BEAM/fakecam_0
E2E PASS
E2E_EXIT=0
```
With `--edit-seed 0x2a2a`, 6 says `psana2 checks (--seed 0x2a2a) PASS` and 7 starts
`edit: web editor status 'saved BEAM/fakecam_0 in tst: new key 3', 1 modify_device in the save
window, own read user.sim_seed 10794 (edited to 0x2a2a);` and ends `logged ['10794 (0x2a2a) from
configdb BEAM/fakecam_0']; expected 10794 (0x2a2a) ...`.

On any failed check it prints `E2E FAIL: assertion <k>: <why>` per failure, then `E2E FAIL`, and
exits 1. To see it fail:
- `--edit-seed 0x2a2a --expect-seed 0x1234` (edit one value, expect another): 6 fails
  (`psana2 checks (--seed 0x1234) FAIL ['event 1: w3 0x2a2a != seed 0x1234', ...]`) and 7 fails
  (`logged ['10794 (0x2a2a) ...']; expected 4660 (0x1234)`); 1-5 pass.
- `--break kill-drp` SIGKILLs the DRP once RUNNING: the count stalls about one DRP buffer pool
  (~1020, credit deadtime) after the kill, about 1080 (assertion 1: `1082 < 1100`; a stall that
  lands above `--events` × 1.1 fails the 2-s "still rising" part instead), and Disable never
  completes (assertion 2: `PAUSED: control getState -> 'running' after 60 s`; 3, 5, 6: `not
  reached`); it takes about 2.5 minutes.
- `--break truncate-xtc2`: the DAQ runs cleanly and 1-5 and 7 pass; 6 fails on the count alone
  (`MISMATCH: psana2 events N-100 != page N, psana2 with data N-100 != page N`; psana2's own
  checks still pass, since the cut is at a datagram boundary).

Screenshots go to `$WD/e2e-shots/`, the driver's stderr to `$WD/logs/e2e-driver.log`.

### The browser venv (once, on sdfiana025: it needs the internet; compute nodes have none)
```bash
export XDG_CACHE_HOME=/sdf/scratch/users/${USER:0:1}/$USER/.cache UV_CACHE_DIR=/sdf/scratch/users/${USER:0:1}/$USER/.uv-cache
W=/sdf/scratch/users/${USER:0:1}/$USER/agentify-webtest          # any shared directory
export PLAYWRIGHT_BROWSERS_PATH=$W/browsers
uv venv --python 3.12 $W/venv
uv pip install --python $W/venv/bin/python playwright pytest-playwright
$W/venv/bin/playwright install chromium                          # into $W/browsers, about 600 MB
```
The run then needs no internet. Pass `--browser-python $W/venv/bin/python` (chromium is found in
`$W/browsers`), or export `DAQ_SIM_BROWSER_PYTHON`. The same venv runs the web GUI's own tests:
`psdaq/psdaq/webgui/tests/run_webgui_tests.sh` (emulator; `AGENTIFY_WEBTEST=$W`), and, against a
DAQ up with `--webgui`, `WEBGUI_REAL_URL=http://127.0.0.1:31053/ psdaq/psdaq/webgui/tests/run_webgui_tests.sh -k real`
inside an `srun --overlap` step.  The parity check counts a control only if its browser test ran against
the simulated DAQ: bring it up with `daq_sim up -w $WD --segments 2` (two fakecam segments, so the
partition table's collapse / expand can be driven), then, in an `srun --overlap` step with
`setup_env_daq.sh` and `sim_env.sh` sourced, `WEBGUI_SIM_DAQ=$WD psdaq/psdaq/webgui/tests/run_webgui_tests.sh
--junitxml=$WD/webgui-sim.xml` and `python -m psdaq.webgui.parity.check_parity --junit $WD/webgui-sim.xml --run-walk`
(`psdaq/psdaq/webgui/README.md`).  The same junit serves the other PyQt GUIs:
`python -m psdaq.webgui.parity.check_gui_parity --run-walks --sim-daq $WD --junit $WD/webgui-sim.xml` lists every
psdaq file outside `control_gui` that constructs a `QApplication`, runs the offscreen walks of those GUIs against
the DAQ now, and prints one line per file (`file | web path or N/A reason | N/M/K | PASS|FAIL`); exit 0 only if
every file passes.

## 3d. Coverage: `daq_sim coverage` and `daq_sim matrix`
```bash
cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim coverage; echo COVERAGE_EXIT=$?
```
It only reads the checkout, so it runs anywhere, also on sdfiana025. Without the DAQ env, any
Python 3.9 or later works: `PYTHONPATH=psdaq python -m psdaq.sim.coverage` from the checkout.

**Rows.** They are enumerated from the source at HEAD, never from a list:
- `det:drp:<type>` and `det:drp_gpu:<type>`: one per `register_type("<type>")` call in
  `psdaq/drp/PGPDetectorApp.cc` and `psdaq/drpGpu/PGPDetectorApp.cc`.
- `prog:<program>`: one per distinct program that a config in `psdaq/psdaq/cnf` (`*.cnf`, `*.py`)
  starts.
  - The configs are executed the way procmgr executes them, so variables such as `drp_cmd0` are resolved.
  - An AST pass also finds the `cmd` entries in branches that are not taken.
  - Wrappers (`VAR=value`, `taskset`, `numactl`, `procServ`, ...) are skipped.
  - A program is named by the file it runs, without `.py`: `/reg/.../procstat.py` is `procstat`,
    and `launch_py .../partca.py` is `partca`.

**Status.** `psdaq/psdaq/sim/coverage_status.json` is keyed by row id. Each entry is one of:
- `RUN`: the row ran in a hardware-free run.
- `STAND-IN`: a simulated program ran in its place. The entry names it (`stand_in`) and the
  interface it serves (`interface`), as simxpm serves pyxpm's PVs.
- `N/A`: a hardware diagnostic or firmware tool with no role in a run. The entry gives a one-line `reason`.

A row with no entry is UNPROVEN. An entry for a row that the enumeration does not find is an error.

**Evidence.** Each passing run writes one JSON record with
`psdaq.sim.coverage.record_evidence(rows, kind, files, ...)`:
- **Fields:** `{sha, rows, kind, run_id, job_id, host, files, started, ended, counts}`, plus `dirty`
  when tracked files differ from HEAD.
- **Where:** `$DAQ_SIM_EVIDENCE`, else `<checkout>/.daq_sim/evidence` (gitignored).
- **From `daq_sim cycle`:** a passing recorded cycle writes one. It covers the programs in
  `daq_sim.cnf` (control, teb, drp), the drp's `-D fakecam`, and `prog:pyxpm`, because the status
  file names simxpm as its stand-in. It prints
  `evidence <id>: det:drp:fakecam prog:control prog:drp prog:pyxpm prog:teb`.
- **Files:** the record lists the run's xtc2 file and logs from the work dir. If you delete the
  work dir, the record no longer counts.

**Verdict.** The tool prints every row on its own line with its status and either its evidence id
or its reason. Then it prints `N rows, R run, S stand-in, K N/A, U unproven`. It ends with one of:
- **PASS (exit 0):** no row is UNPROVEN, and every RUN and STAND-IN row has a record whose `sha` is
  `git rev-parse HEAD` and whose files all exist.
- **FAIL (exit 1):** the failing rows follow.

A record made at another commit is rejected, and the row's line says
`rejected <id>: recorded at <sha>, not at HEAD <sha>`. So after every new commit, the runs must be
repeated.

Options:

| option | effect |
|---|---|
| `--repo DIR` | Checkout to check. Default: the checkout that holds the module, else the one that holds the current directory. |
| `--status FILE` | Another status file. |
| `--evidence DIR` | Another evidence dir. |
| `-v` | Show where each row comes from (`file:line`, or the configs that start it). |
| `--json` | Print the result as JSON. |

`daq_sim matrix` (same options) is the one command for the whole hardware-free matrix. For now it
only runs the coverage check and returns its exit code; later changes add the runs that write the
evidence. Until every row has a run, both commands end in FAIL.

## 4. Read the file back with psana2
```bash
F=$WD/data/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2      # run 1; see the fileReport line of cycle
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=4 --mem=8G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && source psdaq/psdaq/sim/sim_env.sh && \
              python -m psdaq.sim.xtc2_check $F --seed 0x1234 --expect <N>; echo EXIT=\$?"
```
`xtc2_check` reads with `DataSource(files=[F], skip_calib_load='all')`. `LCLS_CALIB_HTTP` defaults to a dead loopback URL, so no calibration DB is contacted. psana2's Prometheus push is off by default. For every L1Accept it checks:
- fakecam's raw data is present;
- w3 == sim_seed;
- w[k] = seed + w0 + k + (lane<<16);
- w2 (simxpm's L1 sequence number) runs 1..N with no gap;
- the pulseId in w0/w1 rises and matches the event's timestamp.

It prints `PASS` and exits 0, or prints the problems and exits 1. psana2 prints `Problem reading dgram header.` once at the end of the file; this is its normal end-of-file StopIteration.

In your own code:
```python
from psana import DataSource
ds = DataSource(files=[F], skip_calib_load='all')
run = next(ds.runs()); det = run.Detector('fakecam')
n = sum(1 for evt in run.events() if det.raw.raw(evt) is not None)
```

## 5. Take it down
```bash
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=2 --mem=4G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim down -w $WD; echo DOWN_EXIT=\$?"
tail -2 $ROOT/daq_sim_up.log          # "... daq_sim down already took everything down; exiting"
```
`down` stops only what `up` started, in this order:
1. The web GUI, if `up --webgui` started it.
2. `procmgr stop` for control, teb0 and fakecam_0.
3. The PIDs that `up` recorded: simxpm, the run DB and the config DB.
4. Any process of yours whose environment carries `DAQ_SIM_WORKDIR=$WD`, such as the caRepeater that libca spawns.

Then it checks that the ports are free and prints `down: clean`; it exits 1 otherwise. Step A then exits on its own. Ctrl-C or SIGTERM to the `up` process does the same teardown.

Release the allocation when you are done: `scancel $JOB` (your own job only).

## 6. Where to look
- `$WD/logs/`:
  - `preflight.log`
  - `configdb.log`, `configdb-access.jsonl` (every config DB request, e.g. the drp's `get_configuration/tst/BEAM/fakecam_0/` at Configure)
  - `lgbk.log`, `lgbk.jsonl` (start_run, end_run, register_file)
  - `simxpm.log` (every transition frame, `L0 enable/disable ... NumL0Acc [...]`)
  - `procmgr.log`
  - `cycle.jsonl`
  - `webgui.log` (`up --webgui`: every command the page sent, control's status messages)
  - `e2e-driver.log` (`daq_sim e2e`: the browser driver's stderr)
- `$WD/pmlogs/<yyyy>/<mm>/<dd_HH:MM:SS>_<host>:<id>.log`: the control, teb0 and fakecam_0 logs. Expected lines:
  - drp: `Simulated PGP device 'sim://127.0.0.1:31052'`
  - drp: `MemPoolSim: simxpm registered fakecam_0 as XPM 0 link 0`
  - drp: `EbLfClient: libfabric 2.1.0, provider 'tcp' ..., domain 'lo'`
  - drp, at Configure: `Sim payload seed 4660 (0x00001234) from configdb BEAM/fakecam_0` (after an
    edit in the web config editor, its value: `daq_sim e2e --edit-seed 0x2a2a` gives
    `Sim payload seed 10794 (0x00002a2a) ...`)
  - drp: `Opening file '.../xtc/tstx00001-r0001-s000-c000.xtc2'`
  - teb: `EbLfServer: libfabric 2.1.0, provider 'tcp'`
- Harmless lines:
  - drp/teb: `<C> Inadequate RTPRIO limit: got 0, require 99`, at critical level but non-fatal.
  - control: `<W> ami NOT supported in absence of MEB`.
- SlowUpdates exist only in state running, by control.py's design. At `-S 1` the xtc2 holds about one per second of running.
- `$WD/data/tst/tstx00001/xtc/` holds the xtc2 files, with `smalldata/` beside them.
- `$WD/e2e-shots/` holds the e2e's screenshots (reset, running, paused after Disable, reset).
- `daq_sim e2e -w $WD` with `--break truncate-xtc2` leaves the whole file beside the cut one as
  `...-c000.xtc2.untruncated`.

## 7. Known limits
- **Network listeners.** Every connection is between 127.0.0.1 peers (checked with `ss -tnp` during a run). But some processes listen on all interfaces:
  - control's ZMQ on `*`;
  - the Prometheus exporters on `0.0.0.0:92xx`;
  - procServ `--allow`;
  - pvAccess UDP 15076.

  Isolation relies on every peer being on this node and on the non-default EPICS ports.
- **HTTP.** The node has an IP route to pswww. The dead proxy stops only HTTP clients that honour the proxy env.
- **Partition size.** There is one detector DRP and one lane. Rates above about 1 kHz are untested.
- **Web GUI.** It listens on 127.0.0.1 only and refuses non-loopback endpoints. Its events number
  comes from simxpm's counter, not from the recorded file; `daq_sim e2e` checks the two against
  each other. The `ssh -L` route of §3b was not tested. The e2e covers one run of one detector
  at 1 kHz, platform 5.
- **Web GUI requests.** It answers 403 to any request whose Host header is not loopback, and to a
  POST whose Origin is another host:port (`webgui/tests/test_webgui_hostorigin.py`). It does not
  refuse `Origin: null`; a browser page with that origin still cannot send it a command, because
  the server takes only `Content-Type: application/json` (other types: 415) and answers no CORS
  preflight (OPTIONS: 501). It has no authentication: any process on the node that can reach
  127.0.0.1 can drive the DAQ through it.
