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
| `xtc2_check.py` | psana2 read-back with a per-event payload check (every pixel or sample for BEB types, §3e). |
| `rogue_dev.py`, `seeds/<type>.json` | The emulated device of a BEB type under `drp -d sim://` (§3e), and the emulated TDet timing receiver of every XpmDetector type (`seeds/xpmdet.json`, §3f). |
| `epixhremu_frame.py` | Writes the xtc2 file whose frame `drp -D epixhremu` replays (§3f). |
| `pattern.py` | The simulated BEB pixel values, the same function as `MemPoolSim::pattern` in C++. |
| `rogue_drive.py` | Debugging aid: runs a BEB type's config entry points against `rogue_dev`, without a DRP (§3e). |
| `../../drp/simFrame.cc` (`drp_sim_frame`) | Writes one simulated BEB DMA buffer to stdout, for the framer's tests. |
| `coverage.py`, `coverage_status.json` | `daq_sim coverage` and `daq_sim matrix` (§3d): which detector types and programs are proven to run without hardware, at HEAD. |
| `ami_check.py`, `gui_witness.py` | The checks `cycle` runs with `--ami` and `--gui`, and the witnesses of the run they write for coverage (§3d, §3h). |
| `ami_shot.py`, `qtgrab/` | `cycle --ami-shot PNG`: AMI's viewer of the camera image, offscreen, saved to PNG (§3h). |
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
- **Fields:** `{sha, dirty, rows, kind, run_id, job_id, host, files, content, started, ended,
  counts, data_dir}`; `data_dir` is the run's data dir (the drp's `-o`); `dirty` is true when tracked files differed from HEAD during the run; `content`
  holds, per listed file, its size and sha256 when the record was written (`{bytes, sha256}`).
- **Where:** `$DAQ_SIM_EVIDENCE`, else `<checkout>/.daq_sim/evidence` (gitignored).
- **From `daq_sim cycle`:** a passing recorded cycle writes one. It covers the programs in
  `daq_sim.cnf` (control, teb, drp), the drp's `-D` type (`fakecam`, or the `--det` type of
  §3e), and `prog:pyxpm`, because the status file names simxpm as its stand-in. It prints
  `evidence <id>: det:drp:fakecam prog:control prog:drp prog:pyxpm prog:teb`, then, for any row
  the check below would reject, `evidence <id>: coverage would reject it for <row>: <why>`.
- **Files:** the record lists the run's xtc2 files, `daq_sim.cnf`, `logs/cycle.jsonl`, each
  service's log (which `up` heads with its `# CMDLINE:`, as procmgr heads each process's log),
  the newest procmgr log of each process and the witnesses of the cycle's checks
  (`logs/ami_check.json` with `--ami`, `logs/gui_witness.json` with `--gui`, below). If you delete the work dir, the record no longer
  counts.

**Verdict.** The tool prints every row on its own line with its status and either its evidence id
or its reason. Then it prints `N rows, R run, S stand-in, K N/A, U unproven, X claimed without
valid evidence`: R and S count only rows whose evidence is valid at HEAD. The next line,
`status file claims ...`, gives what the status file says, counted apart. It ends with one of:
- **PASS (exit 0):** no row is UNPROVEN and every RUN and STAND-IN row has a valid record.
- **FAIL (exit 1):** the failing rows follow.

A record proves a row only if all of these hold, and the row's line names the first that does not:
- its `sha` is `git rev-parse HEAD` (`recorded at <sha>, not at HEAD <sha>`);
- `dirty` is false: the run used the commit's own code (`recorded with tracked files modified`);
- it has a `run_id` (`names no run (run_id)`);
- it has `content` (`holds no content hashes of its files`), and every file it lists exists, is
  non-empty and still starts with the bytes the record hashed: a log may have grown since, an
  `.xtc2` file not (`1 of 9 files changed, e.g. <file>: ...`; the kinds are `missing`, `empty`,
  `unhashed`, `changed` and `not xtc2`);
- every `.xtc2` file is a whole chain of xtc2 datagrams that starts with a Configure and ends at
  the end of the file, the Xtcs of its Configure, BeginRun and L1Accepts each inside its parent
  (`coverage.xtc2_content`; e.g. `not an xtc2 file (first datagram is transition 8, not a Configure)`);
- then, read from the files themselves (only the bytes the record hashed count):
  - for `det:<drp>:<type>`: a listed `.xtc2` file whose Configure has a detector of type `<type>`
    (its Names' detType or detName), whose BeginRun runinfo is the record's `run_id`, with at
    least 1000 L1Accepts holding that detector's data; and a listed log whose `# CMDLINE:` runs
    `<drp>` with `-D <type>` and names the run (`no listed xtc2 file has a detector of type
    wave8he in its Configure (they have: wave8)`, `... 3 of its 3 L1Accepts hold wave8he data,
    fewer than 1000`, `... its BeginRun is run tstx00001/r0002, the record says
    tstx00001/r0001`, `lists no xtc2 file`, `no listed log runs drp -D wave8he and names the
    run of ...`);
  - for `prog:<program>`: a listed log whose `# CMDLINE:` runs `<program>` (for a STAND-IN row,
    its `stand_in`, e.g. simxpm) and names the run (`lists no log of teb`, `its log of teb names
    neither the run's xtc2 file ... nor its BeginRun time ...`).

  A log names the run if it holds the path of a listed `.xtc2` file of the run (the DRP logs
  `Opening file <path>`, control the file reports), that path relative to the record's
  `data_dir` (control_gui logs control's `fileReport` as `/tst/<expt>/xtc/<file>`; it counts only
  if, joined to `data_dir`, it resolves to the very file the record hashed), or that file's
  BeginRun time as `sec.nsec` (the TEB logs `BeginRun @ <time>`, simxpm `BeginRun ... time
  <time>`). The tool reads the xtc2 files itself (datagram and Xtc headers, Names, the runinfo,
  each L1Accept's timestamp), as psana2's reader lays them out; it needs no psana.

  Programs whose own log can never name a run need a **witness**: a JSON log a check of the
  same cycle wrote, `{"witness": <kind>, "run_id", "xtc2": [...], ...}`, listed (and so hashed)
  by the record, with the record's `run_id` and one of its `.xtc2` files of that run
  (`names run ..., the record says ...`, `names no listed xtc2 file of run ...`):
  - `prog:ami-*` (R1), always: an `ami_check` witness (`logs/ami_check.json`) that passed
    (`says the check failed`), with `matches`, AMI's per-event agreement with psana2 as
    `[timestamp, seq, pixel]`, at least one, every timestamp an L1Accept of the run's file
    (`lists no per-event match`, `match timestamp ... is no L1Accept of the run's files`), and
    `served_by`, the processes (`pid`, `cmdline`, `ancestors`) that held a TCP socket on AMI's
    ports while the cycle fetched AMI's result, and, with `--ami-shot`, while the screenshot's
    ami-client showed the run: one of them, or one of their ancestors (AMI's GUI windows are
    processes it forks, renamed `ami editor`), must run the row's program with the pid its log
    gives (procmgr's `@@@ The PID of new child ... is: N`, or the `# PID: N` line ami_shot writes)
    (`its served_by lists no ami-client process`, `its log of ami-client gives pid N, not one of
    the ami-client processes that served the check`, `its log of ami-client gives no pid`). The
    program's own log is required too. The procmgr `ami-client` loads no graph, so it holds none
    of AMI's ports; the ami-client row is proven by the one `cycle --ami-shot` runs.
  - a GUI or monitor whose log does not name the run (R2; groupca, partca, pvant, procstat, epics_exporter): a
    `gui_witness` (`logs/gui_witness.json`) whose `programs` entry for it passed, whose `start`
    and `end` (EPICS-epoch seconds, the walk's process) lie between the run file's first and last
    L1Accept (`read from ... to ..., not within the run's L1Accepts`), and that shows at least one
    PV under the witness's `partition` prefix with 2 or more distinct numbers (a placeholder such
    as `-` is none) (`shows groupca read no live value under DAQ:SIM:XPM:0:PART:5`); plus the
    GUI's own log with its `# CMDLINE:`. procstat shows no PV but procmgr's table of the
    partition's processes (ID, status): its entry (`"kind": "procmgr"`) must show RUNNING every
    process whose procmgr log (`# ID:`) in the record names the run (`shows procstat did not list
    fakecam_0 RUNNING`).
  - a STAND-IN row whose stand-in's log does not name the run (R3, a PV server): the witness's
    `servers` entry for the stand-in (a client of the cycle read the stand-in's PVs while the run
    ran; a `programs` entry does not count): it passed, ran within the run's L1Accepts, read a
    PV under its own `prefix` with 2 or more distinct numbers, and its `interfaces` entry for the
    row's program gives `defined`, the PV names the program's source defines (more than 0), and
    `missing`, those the stand-in does not serve, empty (`simhsd does not serve 2 of the 40 PVs
    hsdpvs defines, e.g. ...`).
  `psdaq/psdaq/tests/test_sim_coverage.py` forges each of these and checks the row's line says why.

So commit first, build, then run: after every new commit, the runs must be repeated.

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

## 3e. BEB detector types: `daq_sim up --det <type>`

```bash
# step A, as in §2 but with the type (WD as in §2; take down any earlier 'up' first, §5)
nohup srun --jobid=$JOB --ntasks=1 --cpus-per-task=32 --mem=64G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim up -w $WD --det wave8" > $ROOT/daq_sim_up.log 2>&1 &
sleep 45; cat $ROOT/daq_sim_up.log
# step B, as in §3: a cycle; it records evidence for det:drp:wave8 and psana2 checks every sample
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=32 --mem=64G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim cycle -w $WD --events 1000"
```
`--det` is one of `daq_sim.SIM_TYPES`: `fakecam` (the default), the BEB types `epix100`, `wave8`,
`wave8he`, `hrencoder`, `epixm320`, `opal`, `piranha4`, `tb`, `epixquad` (§3g), and the XpmDetector
types `cspad`, `epixhremu`, `jungfrauemu`, `ts` (§3f).
The DRP is the real `drp -D <type> -d sim://...`, and its BEBDetector runs the type's own
`psdaq/psdaq/configdb/<type>_config.py`, unmodified, against an emulated device:

- **Control plane (`rogue_dev.py`).** With a `sim://` device only, BEBDetector calls
  `rogue_dev.install(device, type, epics_prefix)` before it imports the config module. It replaces
  rogue's `AxiMemMap` (the PCIe map) with an in-process register store, and `AxiStreamDma` with
  an SRPv3 responder, so the real pyrogue firmware trees run on top. A register reads back what
  was last written, except:
  - **seeds** in `seeds/<type>.json` preset what the script polls (firmware versions, lock bits,
    clocks). A seed path that is not a register of the tree raises; nothing is created on demand.
  - `_proc` in the seed file is what `open('/proc/<device>')` reads (PgpMonitor's board check).
  - `pv:` keys are the PVs of the front-end's IOC, for types configured over Channel Access
    (wave8, wave8he); `{prefix}` is the drp's `-k epics_prefix`. `epics.PV` is replaced in
    process; no CA leaves the process. A PV the table lacks reads `None` and is reported,
    as pyepics does when no IOC serves it.
  - **fault:** `PSDAQ_SIM_ROGUE_FAULT='<register path>[=<value>]'` (or `pv:<name>[=<value>]`)
    in the environment of `daq_sim up` makes that register read back wrong, so Configure fails
    and names it.
- **Data plane (`MemPoolSim.cc`).** A table keyed by type lays out each L1Accept as the
  AxiStreamBatcherEventBuilder would: the TimingHeader as subframe 0, then the type's
  subframes. Pixel (or sample) `i` of what the DRP builds is
  `pattern(seed, seq, i) = (mix(i) + seq*0x9e37 + seed)` masked to the type's bit depth
  (`pattern.py`), written where the firmware sends it (epix100: interleaved ASIC rows).
- **Check (`xtc2_check.py`).** psana2 reads the file through the type's own detector interface
  and compares every pixel, sample and fex value of every event with the pattern. So a pixel
  the DRP puts in the wrong place fails. `--self-test-offset 1` expects every value one place
  off and must FAIL.
- **Config DB.** `configdb_seed --det-type <type>` stores the type's own default:
  `<type>_config_store.<type>_cdict()`; or the config the store's `write_to_daq_config_db` would
  write, built against a configdb that contacts nothing; or (epix100) the firmware YAML.

What each type needs:

| type | config entry points run | emulated device (seeds) | DB config | DRP data (subframes) | psana check |
|---|---|---|---|---|---|
| epix100 | `epix100_init`, `_connectionInfo`, `_config`, `_enable`, `_disable`, `_unconfig` | lcls2_epix_hr_pcie DevRoot + ePix100a board over SRPv3: 9 seeds (KCU and camera FPGA versions, DMA size, clock and lock bits, RxId, BaseClock) | `ePix100a_asics_0123.yml` through `yaml_config_store_example` | 3: 1,087,532 B image, rows interleaved by ASIC | `epix100_raw_2_0_1` raw (704,768), every pixel, 14 bit |
| wave8 | `wave8_init`, `_connectionInfo`, `_config`, `_unconfig` (with PgpMonitor `init_lanes`/`check_lanes`, `config_timing`, `configure_trigger_delay`) | PgpMonitor KCU: board type and 2 link bits; driver text; 213 IOC PVs (29 the script writes or polls, 184 of the expert config it records); new IOC (no `EvrV2TriggerReg[0]:Delay`) | `wave8_config_store` through its `write_to_daq_config_db` | 1: aux timing; 2-9: 8 waveforms of 256 samples; 10: integrals (56 B); 11: processed (32 B) | `wave8_raw_0_0_1` raw_0..7, `wave8_fex_0_0_1` integrals, baselines, counts, intensity, position |
| wave8he | `wave8he_init`, `_connectionInfo`, `_config` (writes the HLS counts and scales), `_unconfig` | as wave8, with the HLS PVs: 228 keys | no wave8he store in the tree: the wave8 store's config plus the HLS region bounds | 2-9: 8 waveforms; 0x0C: peaks (64 B); 0x0D: integrals (32 B), 24-bit packed | `wave8he_raw_0_0_1`, `wave8he_fex_0_0_1`: every field |
| epixm320 | `epixm320_init` (PgpMonitor, `ePix320kM.Root` with `justCtrl`, `ConfigLclsTimingV2`, the RxId wait), `_connectionInfo`, `_config` (the firmware's own `fnInitAsicScript`: PLL, lane delays, waveforms, batchers, the ASIC YAMLs it writes to `/tmp`, then a 2500-trigger `hwTrigger` and `laneDiagnostics`), `_enable`, `_disable`, `_unconfig` | PgpMonitor KCU as hrencoder; camera over SRPv3: `RxId`, and `TriggerRegisters.AcqCount` and each `DigAsicStrmRegisters<i>.FrameCount` 2500, what the camera reports after the 2500-trigger train `hwTrigger` waits for | `epixm320_config_store.epixm320_cdict($SUBMODULEDIR/epix-hr-m-320k/software/config)`, as its `__main__` (`--dir`) | 1: timing copy; 2-5: ASICs 0-3, each a 48 B header (frameNo, asicNo), 192 x 384 in the ASIC's bank order (`EpixM320::_descramble`'s inverse), 48 B trailer | `epixm320_raw_0_1_0` raw (4, 192, 384), every pixel, 15 bit |
| hrencoder | `hrencoder_init` (PgpMonitor `init_lanes`, `high_rate_encoder_dev.Root` start: `ConfigLclsTimingV2`, Fmc write-and-verify, `StopRun`), `_connectionInfo`, `_config` (`StartRun`), `_unconfig` | PgpMonitor KCU: board type, DMA size, 2 link bits, driver text; encoder board over SRPv3: `FpgaVersion` 0x02040000 (the root's `FebVersionLock`), `RemRxLinkReady`, `RxId`. Its XVC server (`rogue.protocols.xilinx.Xvc(2542)`) is a null stream endpoint: no socket | `hrencoder_config_store` through its `write_to_daq_config_db` | 2: `Enc::Stream` (8 B: position, error, missed-trigger and latch counts) | `hrencoder_raw_0_1_0` `value()` (position) and the three counts |

Fault runs that fail Configure and name the register: epix100
`ePixBoard.ePix100aFPGA.EpixFpgaRegisters.DaqTriggerDelay` (rogue's write-verify),
wave8 and wave8he `pv:{prefix}:Top:TriggerEventManager:TriggerEventBuffer[0]:TriggerDelay=0`
(`ValueError: TriggerDelay(ns) too small`), hrencoder
`Root.App.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay` (rogue's write-verify in
`config_expert`), epixm320 `Root.App.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay`
(write-verify when `_config` applies the expert config).

**Debugging a type without a DRP.** `python -B -m psdaq.sim.rogue_drive --type <type>` runs the
entry points in the DRP's order against `rogue_dev` and a private config DB. It prints the first
failure with its traceback, which is how a type's seeds are found.

**Not running yet** (found with `rogue_drive`, and in a DRP where it gets that far):
- **epixquad1kfps:** `ePixQuad.Top.start` (its epix-quad-1kfps package) reads the camera's ADC
  calibration from its SPI PROM (`CypressS25Fl`: `resetFlash`, `readCmd`, `waitForFlashReady`), a
  command/response device behind registers; `rogue_dev`'s registers only keep what is written,
  so `epixquad1kfps_init` never returns (`seeds/` has none for it). Before that it needs the
  card's image name and `FpgaVersion` >= 0x04020000 on `Top.AxiPcieCore`; its config DB entry
  is `epixquad_config_store`'s (`configdb_seed.BORROWED_STORES`).
- **tt:** `tt_init` dies building `lcls2_timetool.TimeToolKcu1500Root`: that package's surf
  `AxiMicronN25Q` passes `size=` to pyrogue's `Device`, which this rogue (6.1.3) rejects
  (`TypeError: __init__() got an unexpected keyword argument 'size'`), before any register access,
  so on hardware too. `tt_config.py` also has no `tt_connectionInfo` (it has `tt_connect(cl)`),
  which `BEBDetector::connectionInfo` calls.
- **hsd:** its DRP class (`Digitizer`) is not a BEBDetector: `hsd_init` builds
  `l2si_drp.DrpPgpIlvRoot` on the device itself, with no `rogue_dev` under `sim://`, and the rest
  of its configuration goes through the hsdioc's PVA PVs (`<prefix>:CONFIG`, `:READY`, `:PADDR_U`,
  `:MONTIMING`, `:RESET`, ...), for
  which there is no stand-in yet; the hsd data format has no `MemPoolSim` framer.
- **jungfrau:** its DRP drives the modules through `sls::Detector` (the slsDetector control
  protocol to each module's server at `slsHosts`); there is no stand-in for that server, and the
  module data arrives over UDP (`jungfrauSim` generates such packets, not the control protocol).
- **epixuhr3x2:** `epixuhr3x2_config_store.beam_cdict()` (what its `__main__` writes) reads PLL
  tables and pixel bitmaps from `/cds/home/p/psrel/EpixUHR/{pll,pixelBitMaps_prod}/`, facility
  paths absent here (the PLL CSVs are also in `$SUBMODULEDIR/epix-uhr-gtreadout-dev`, the
  `pixelBitMaps_prod` maps nowhere), so `configdb_seed` cannot build its default config.
- **epixhr2x2:** `drp -D epixhr2x2 -d sim://` aborts at start: `epixhr2x2_config.py` imports
  `lcls2_epix_hr_pcie` and `epix_hr_single_10k` without the `psdaq.utils.enable_*` modules that
  put them on the path (`ModuleNotFoundError: No module named 'lcls2_epix_hr_pcie'`). With those
  imports added (not committed), `epix_hr_single_10k` imports `setupLibPaths`, which is in its
  `software/scripts`, not on the path; with that added too, `DevRoot` starts but the ePixHr10kT
  board's registers are answered by no simulated transport (rogue_dev cannot place its seeds).
  It also has no `epixhr2x2_connectionInfo`, which `BEBDetector::connectionInfo` requires (it has
  `epixhr2x2_connect(base)` instead); no run gets that far yet.
- **epixUHR:** `epixUHR_config_store.epixUHR_cdict()` reads its PLL tables from
  `/cds/home/p/psrel/EpixUHR/pll/`, a facility path (the same CSVs are in
  `$SUBMODULEDIR/epix-uhr-gtreadout-dev/software/config/pll/`), so `configdb_seed` cannot build its
  default config here; nothing past that was tried.

## 3f. XpmDetector types: fakecam, cspad, epixhremu, jungfrauemu, ts

These types have no EventBatcher: their DRP class derives from `XpmDetector`, and on hardware
`psdaq/psdaq/configdb/xpmdet_config.py` programs the KCU's TDet firmware (`l2si_drp.DrpTDetRoot`:
the timing receiver, the trigger event buffers and the `TDetSemi` payload generator). Under
`sim://` the DRP runs that same script, unmodified, at the same points as on hardware:

| DRP step | `xpmdet_config` entry point | what the emulated receiver does |
|---|---|---|
| start (constructor) | `xpmdet_init(dev, laneMask, timebase)`: `detect_C1100` reads `/proc/<dev>`, builds and starts `DrpTDetRoot` | `seeds/xpmdet.json`: the driver text (a KCU1500), `TxClkCount` as a free-running counter (below), `XpmMessageAligner.RxId` 0xff000000 |
| Alloc (`connectionInfo`) | `xpmdet_connectionInfo`: barrier, `refClockRate()` check (no Si570 reprogramming when it reads 180-190 MHz), `TxId`, the 8 trigger event buffers reset, `RxId` check | the link id the DRP reports is simxpm's (`MemPoolSim: simxpm registered ... link N`); the log line `XpmDetector: emulated RxId 0xff000000; link id 0x... from simxpm` gives both |
| Connect | `xpmdet_connect(group, length)`: `TriggerEventBuffer`, `TDetSemi.Length_<lane>`, `Enable_<lane>` | registers read back what was written; `MemPoolSim` then joins simxpm's readout group |
| Unconfigure, Dealloc | `xpmdet_unconfig`, `xpmdet_connectionShutdown` | |

A seed value `{"count_hz": f}` makes the register a counter that advances f per second, for a
script that measures a clock (`TDetTiming.refClockRate()`: 11,607,143 counts/s read as 185.71
MHz). The fault hook works as for the BEB types; on these types the first write it breaks is at
Connect (`xpmdet_connect`; there is no `xpmdet` step at Configure):
`PSDAQ_SIM_ROGUE_FAULT=DrpTDet.PcieControl.DevPcie.TDetSemi.Length_0` makes Connect fail, and the
DRP log names it: `Verify error for block DrpTDet.PcieControl.DevPcie.TDetSemi.Length_0 ... Got:
0xff, Exp: 0x40`, then `**** python error` and signal 6.

What each type needs and what psana2 checks (every L1Accept, `xtc2_check --det <type>`):

| type | own config code | DRP data | psana interface and check |
|---|---|---|---|
| fakecam | `xpmdet_config` only | `TDetSemi` words (§4) | `fakecam_raw_2_0_0` raw: w3 == seed, the w[k] pattern, w2 = 1..N, pulseId vs timestamp |
| cspad | `xpmdet_config` only (an `AreaDetector`, as fakecam) | as fakecam | `cspad_raw_2_0_0`, new in `psana/psana/detector/test_detectors.py` (the same reader as fakecam's): as fakecam |
| epixhremu | `xpmdet_config` only; `EpixHRemu` replays the first L1Accept's `raw` (uint16, rank 2) of the file its `xtcfile` kwarg names | `daq_sim up` writes that file (`epixhremu_frame.py`: an epixhr2x2 frame of 288 x 384, pixel i = `pattern(seed, 0, i, 16)`); every event records its first 192 columns of its first 144 rows in all 4 ASIC positions, 221,184 B, so its DMA buffers are 256 kB (`sim_dma_size=0x40000`) | `epixhremu_raw_0_0_1` raw (1, 144, 768): every pixel vs the frame |
| jungfrauemu | `xpmdet_config` only; `JungfrauEmulator` records each lane's DMA payload as one 512 x 1024 panel | `sim_length=262144` `TDetSemi` words (1 MiB, `sim_dma_size=0x101000`) | `jungfrauemu_raw_0_1_0`: its `raw()` adds random noise ("FOR DEBUGGING ONLY" in psana), so the words are checked through the `AreaDetectorRaw.raw` it overrides (seed, seq, pattern, pulseId), and `raw()` for its shape and a noise-sized difference |
| ts | `xpmdet_config`, and its own `ts_config.py`: `ts_connect` at Connect (`ts_connect.py`: `RemoteLinkId`, `LinkGroupMask`, `LinkRxReady`, `LinkRxErrI` of every port) and `ts_config` at Configure (the readout group's `L0Select*`, `DstSelect`, `L0RawUpdate`, `InhInterval/InhLimit/InhEnable0-3`, then `FwBuild`), all PVs simxpm serves (pyxpm's names and types); config from `ts_config_store.beam_cdict()` | the 153 B `TimingData` the timing system's TDet firmware sends (`MemPoolSim.cc` `timingMessage`): the frame's pulseId and time, every other element `pattern(seed, seq, element, bits)` with the field's width | `ts_raw_2_1_0`: every `TimingData` field, `eventcodes`, `inhibitCounts`, `destination`, `timestamp` == the event's, `pulseId` rising and matching the timestamp |

simxpm's `LinkRxReady<n>` and `LinkTxReady<n>` read 1 while a DRP holds link n; `RemoteLinkId<n>`
reads 0 (no XPM behind it, so `ts_connect` does not recurse), and the trigger and inhibit PVs only
keep what is written: simxpm's L1Accepts stay at `SIM:L1Rate`.

## 3g. Camera link cameras, the timing BEB and the ePixQuad: opal, piranha4, tb, epixquad

`daq_sim up --det opal|piranha4|tb|epixquad`, then `daq_sim cycle` as in §3e. Each is a
BEBDetector type, so its DRP runs the type's own `psdaq/psdaq/configdb/<type>_config.py` against
`rogue_dev` exactly as §3e describes. What is new for these types:

- **The camera's serial port (opal, piranha4).** `cameralink_gateway.ClinkDevRoot` talks to the
  camera through the FEB's UART, one character per 32-bit word on the lane's VC2 stream (surf
  `ClinkSerialTx`/`ClinkSerialRx`). With a `"_uart"` table in the seed file, `rogue_dev` answers
  each command on the streams it names with the table's reply (and `"default"` for the rest), as
  the camera would; the commands are logged with the register writes
  (`{"store": "uart", "cmd": ...}`).
  - Opal: `@ID?` answers `OPAL-1000m/Q S/N:00000001`, which `opal_connectionInfo` turns into
    model 1000 (1024 x 1024) and the serial number; `@BS?` the build string `opal_config` reads.
    Every reply ends with CR and the ACK the camera sends; other commands get the ACK only.
  - Piranha4: every command is answered with its lines and the `USER>` prompt the config script
    waits for. `gcp` is the configuration summary `piranha4_connectionInfo` parses (Model
    `P4_CM_02K10D_00_R`: 2048 pixels; `Serial #`; `BiST Good`; last the `CPA` line); `vt`/`vv` the
    temperature and voltage lines; everything else `OK`.
- **Seeds.** A seed may now be a string register's text (`{"string": "..."}`), may name a root
  whose class name starts with `_` (tb_config's `_DevRoot`; only keys with no `.` are comments),
  and may sit on a device that another seed enables: a FEB whose `enableDeps` is its PGP
  link-ready bit is reached once pyrogue's update thread has applied the link seed.
- **tb (TimingBEB).** `tb_init` reads the card's image name through its own `_DevRoot`
  (`seeds/tb.json`: a `BuildStamp` naming `Lcls2XilinxKcu1500Pgp4_6Gbps`), then builds
  `lcls2_pgp_pcie_apps.DevRoot`; `ts_connect` and `tb_config` program simxpm's PVs as ts does
  (§3f); the config is `ts_config_store.beam_cdict()`.
- **epixquad.** `epixquad_init` builds `lcls2_pgp_pcie_apps.DevRoot` and the camera
  (`ePixQuad.Top`, SRPv3); `seeds/epixquad.json` has the timing locks and `SystemRegs.AdcTestDone`,
  which `_checkADCs` polls at Configure. Its config DB entry is `epixquad_config_store`'s default
  plus `user.pixel_map` (zeros, 16 x 178 x 192, `configdb_seed.STORE_KEYS`): `epixquad_config`
  reads that key, which the store no longer writes (it writes `user.pixel_map_raw`, read by
  `epixquad1kfps_config`); with the store's all-zero map both views are zeros.

| type | config entry points run | emulated device (seeds) | DRP data (subframes) | psana check |
|---|---|---|---|---|
| opal | `opal_init` (ClinkDevRoot start: PCIe and FEB version checks), `_connectionInfo` (barrier, clock check, `TxId`, `RxId`, `@ID?`), `_config` (`@BS?`, `user_to_expert`, `config_expert` over registers and UART, `StartRun`), `_unconfig` | ClinkPcie: `RxRemLinkReady`, PCIe and FEB `FpgaVersion`, `DMA_SIZE_G`, `TxClkFreqRaw` 185.71 MHz, `RxId`; the Opal's UART | 1: timing copy; 2: 1024 x 1024 uint16 image in row order | `opal_raw_2_0_0` raw (1024, 1024), every pixel, 12 bit |
| piranha4 | `piranha4_init` (ClinkDevRoot start: `spf`, `gcp`), `_connectionInfo` (`gcp`, `vt`, `vv`), `_config` (the UART settings, `lpc`, `stm`), `_unconfig` | as opal; the Piranha4's console | 1: timing copy; 2: 2048 uint16 pixels | `piranha4_raw_2_1_0` raw (2048,), every pixel, 12 bit |
| tb | `tb_init` (`_DevRoot` image name, `DevRoot`), `ts_connect`, `tb_connectionInfo`, `tb_config` (trigger event buffer, `StartRun`, simxpm PVs) | `_DevRoot` `BuildStamp`; `DevRoot` timing locks, `RxId` | 2: the 48 B event timing message (rate markers, AC time slot, beam, 18 sequence values) | `ts_raw_2_1_0`: every field `TimingDef::createDataETM` records (the rest 0), event codes, destination, timestamp == the event's, pulseId rising with service L1Accept |
| epixquad | `epixquad_init`, `_connectionInfo`, `_config` (`_checkADCs`, the 16 ASICs' SACI settings and pixel maps, `startRun`, the 4 element configs), `_enable`, `_disable`, `_unconfig` | `DevRoot` timing locks, `RxId`; camera `SystemRegs.AdcTestDone` | 1, 3: timing copies; 2: 32 B header, 176 super rows of 8 element rows (columns reversed), 4 calibration rows per element | `epix10ka_raw_3_0_1` raw (4, 352, 384), every pixel, 14 bit |

Fault runs that fail Configure and name the register: opal and piranha4
`ClinkDevRoot.ClinkPcie.Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay`,
tb `DevRoot.DevPcie.Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[3].TriggerDelay` (all
rogue's write-verify), epixquad `Top.SystemRegs.TrigEn=0` (write-verify when `_checkADCs` switches
to external triggers).

## 3h. MEB, AMI and the system DRPs: `up --meb --ami --pva --epics --udp --gui`

Each option adds programs the procmgr configs start to the generated `.cnf`, on the same node and
on loopback, in the partition's readout group; `daq_sim cycle` then checks what each recorded and
its evidence record lists their logs.

| option | adds (procmgr id: program) | simulated source | what `cycle` checks |
|---|---|---|---|
| `--meb` | `meb0`: `monReqServer -d -n 8 -q 2 -t tstsim<p>`; `shmc0`: `shmemClient -p tstsim<p> -i 1 -v -R` | the TEB's events | `MEB_EvtCt` (events the MEB served), shmemClient's L1Accept lines |
| `--ami` (implies `--meb`) | `ami-manager`, `ami-global`, `ami-node_0`, `ami-worker_0` (`psana://shmem=tstsim<p>`), `ami-client` (offscreen) | the MEB | `psdaq.sim.ami_check`: a graph that keeps every event's timestamp, seq and one fakecam pixel, fetched from the manager and compared with psana2 event by event; it writes the `ami_check` witness (`logs/ami_check.json`: the run, the per-event matches, the AMI processes that held AMI's ports when the result was fetched) that proves the AMI rows |
| `--pva` | `pvcam_0`: `drp_pva -d sim://... pva/DAQ:SIM:CAM:IMAGE` | `simxpm --camera-pv`: an NTNDArray updated once per L1Accept with that L1Accept's time | `psdaq.sim.sysdrp_check --pva`: every recorded image is `camera_image(seed, seq)` with fakecam's seq of the same L1Accept, and drp_pva's `drp_match_count` equals the L1Accepts that have an image |
| `--epics` | `epics_0`: `epicsArch -d sim://... epicsArch.txt` | a stand-in IOC, EPICS base's `softIoc -S`, with `DAQ:SIM:EPICS:COUNT` (CA, +1 every 0.1 s) and `DAQ:SIM:EPICS:CONST` (CA, 1234.5); simxpm's `DAQ:SIM:XPM:0:PART:<p>:NumL0Acc` (PVA) | `sysdrp_check --epics`: `sim_const` is 1234.5, `sim_count` and `sim_l0acc` never decrease, `sim_l0acc` stays within the run's L1Accepts |
| `--udp` | `encoder_0`: `drp_udpencoder -d sim://... -L <udp port>`; `simenc`: `sim_udpencoder -T sim://... -p <p> -a 127.0.0.1 -d <udp port>` | `sim_udpencoder` sends one encoder frame per L1Accept, paced by simxpm's frames instead of `/dev/tpra` | `sysdrp_check --udp`: every recorded frame's count in step with fakecam's seq, the 100/200 test pattern, and drp_udpencoder's `drp_match_count` equals the L1Accepts that have a frame |
| `--pvservers` | services (not procmgr) `simhsd -P DAQ:SIM:HSD:1_DA:A DAQ:SIM:HSD:1_DA:B` and `simtpr -P DAQ:SIM:TPR`, each on PVA ports of its own (31300 + 10 p + 0..3: simxpm stays the only server on the node's search port) | the stand-ins of `hsdpvs` and `tprcas` (R3) | while the run is Running, `psdaq.sim.gui_witness` gets from each stand-in every PV name the program's own source defines (hsdpvs's `ChipServer`, the table `tprcas.main()` builds) and reads its monitoring counters (`MONTIMING`, `EVTCNT`) once a second; the `gui_witness`'s `servers` entry is what coverage counts the STAND-IN rows `prog:hsdpvs` and `prog:tprcas` from |
| `--gui` | `control_gui -H localhost -l DEBUG -u <config DB stand-in>`, `groupca DAQ:SIM 0 <p>`, `python -m psdaq.cas.partca DAQ:SIM:XPM:0:PART:<p>` (psdaq installs no `partca` command; lab3-cam.cnf runs it with `launch_py <bins>/partca.py`), `pvant --bases DAQ:SIM:XPM:0:PART:<p> --fields NumL0Acc NumL0Inp L0AccRate` and `procstat -p <p> -i 1 <WD>/daq_sim.cnf`, offscreen; and the PV monitor `pvrtmon_0`: `epics_exporter -H tst -I xpm-0 -M <WD>/prom -P DAQ:SIM:XPM:0 NumL0Acc NumL0Inp RunTime` | control's status messages; simxpm's PVs | control_gui logs the run's `fileReport` with its path relative to the data dir, which the record's `data_dir` resolves. groupca, partca, pvant and procstat never log a run: once the run is Running, `psdaq.sim.gui_witness` runs each GUI's own `main()` once more, offscreen, through the parity check's walk (`qt_walk --gui`, passive: event pumps only, nothing clicked or written), keeps every PV-bound widget's text after each pump, scrapes epics_exporter's Prometheus gauges (port from its log) once a second meanwhile, and writes the `gui_witness` witness (`logs/gui_witness.json`); `cycle` stays Running until the walks end and fails if a GUI showed no partition PV changing |

drp_pva, epicsArch and drp_udpencoder take their timing from simxpm with `-d sim://` as `drp`
does (MemPoolSim); without it they open the PGP card as before. The MEB does not unlink its
shared memory (`/dev/shm/PdsMonitorSharedMemory_tstsim<p>`, about 250 MB) or message queues;
`daq_sim down` removes this user's ones of the tag.

AMI is not part of the lcls2 tree. `--ami` runs the `ami-*` programs found on PATH, or, with
`--ami-src DIR` (or `$DAQ_SIM_AMI_SRC`), writes their console scripts into `<workdir>/bin` for an
AMI source tree such as a clone of github.com/slac-lcls/ami. The DAQ env must hold AMI's
dependencies (networkfox, amitypes, qasync, pyqtgraph). On S3DF the release tree
`/sdf/group/lcls/ds/ana/sw/conda2/rel/ami_091526` works with the `daq_20250402_r9` env.
AMI takes 10 TCP ports from 31100 + 10 p (31150-31159 for platform 5) on 127.0.0.1 and starts
Prometheus exporters from 31180 + 2 p. The UDP port is 31200 + p.

```bash
# step A (WD as in §2)
daq_sim up -w $WD --ami --ami-src /sdf/group/lcls/ds/ana/sw/conda2/rel/ami_091526 \
    --pva --epics --udp --gui --pvservers --rate 100 --detach
# step B: a cycle; besides the fakecam counts it prints the MEB, AMI and system DRP counts
daq_sim cycle -w $WD --events 1000
daq_sim down -w $WD
```

**A screenshot of AMI showing the camera.** With a DAQ up with `--ami`, `daq_sim cycle --ami-shot
PNG` (`psdaq.sim.ami_shot`) starts, once the run is Running, one more `ami-client` (AMI's own Qt
GUI) offscreen on the running manager, with a graph of its own (`-g ami_shot`, so the check's
graph is left alone) loaded from a flowchart that holds one viewed source node, `fakecam:raw:raw`;
loading it opens AMI's image viewer of the camera, as double-clicking the source does. The
directory `psdaq/psdaq/sim/qtgrab`, first on that client's `PYTHONPATH` only, makes each of its
windows save itself (`QWidget.grab`) to `<WD>/logs/ami-shot/<title>.<pid>.png` every 2 s, with no
change to AMI. Once the viewer's window shows data, the newest grab is copied to PNG and the
client stopped; the cycle prints `ami shot PASS <png>: window "fakecam:raw:raw" ...` and, after
Disable, the MEB's served-event count `MEB_EvtCt`. The client's PVA server takes 31230 + 2 p and
31231 + 2 p, its Prometheus port 31181 + 2 p.
```bash
daq_sim cycle -w $WD --events 1000 --ami-shot $WD/ami.png
```

## 3i. System features: `daq_sim feature a|b|c|d|e`

Each feature is one command, run inside a Slurm step on the node as in §2. It brings the DAQ up
(`up --detach` with the feature's options), drives one run, takes the DAQ down (always, unless
`--keep-up`) and prints a report: the Slurm job and step, the host, the checkout's HEAD SHA, each
transition with its time (each state as the client read it back, and each transition frame
simxpm sent the DRPs, from `logs/simxpm.log`), each DRP's L1Accepts as the DAQ counts them (the
L1Accepts simxpm sent its link, `SIM:LinkL1Acc`) against psana2's events in its stream, and
`FEATURE <x> PASS` (exit 0) or `FEATURE <x> FAIL` with the failing checks (exit 1).

```bash
# inside one srun step on the node (WD as in §2); each takes a few minutes
daq_sim feature a -w $WD       # readout groups at different rates
daq_sim feature b -w $WD       # a 3-step scan through generic_timing_scan.py
daq_sim feature e -w $WD       # drp_pva, drp_bld, drp_udpencoder, epicsArch with a PGP DRP
daq_sim feature c -w $WD       # the MEB serving AMI; AMI's GUI shows the camera ($DAQ_SIM_AMI_SRC or --ami-src)
daq_sim feature d --hosts nodeA,nodeB     # two nodes: NOT AVAILABLE unless both are hosts of this job
daq_sim feature a -w $WD --check-only --break drop-l1     # the checks can fail (no DAQ)
```

| feature | `up` options | the run | checks |
|---|---|---|---|
| a | `--det hrencoder --also epix100:<p+1> --also wave8:<p+1> --fixed-rate <p>:3 --fixed-rate <p+1>:4` | one cycle of `--events` (1000) L1Accepts of group p | hrencoder_0 (group p, 1.02 kHz marker), epix100_0 and wave8_0 (group p+1, 102 Hz): each DRP's DAQ count == psana2's events in its stream == events with its data, each passing the type's per-event check (`xtc2_check`); each group took its marker's share (group p+1 1/10 of group p's, within 10 %) |
| b | `--det tb --also epix100 --rate 100` | `python -m psdaq.cas.generic_timing_scan -p <p> -C localhost --detname epix100_0 --scantype timing --events <N> --record 1 --config BEAM --linear 700000 730000 10000`, from connected | psana2 reads 3 steps in tb's stream, `step_value` 700000, 710000, 720000 and a `step_docstring` naming each; each DRP has `--events` (200) L1Accepts in every step, all with data; each DRP's DAQ count == psana2's; every event passes its per-event check; `epix100_update` applied 700000, 710000, 720000 in order (its DRP's log) |
| e | `--pva --epics --udp --bld --rate 100` | one cycle | sysdrp_check reads drp_pva's, drp_udpencoder's, epicsArch's and drp_bld's data event by event; each system DRP's DAQ count == psana2's events in its stream; drp_bld's L1Accepts less its `bld_miss_count` == psana2's events with BLD data |
| c | `--ami --rate 100` (`--ami-src` passed on; §3h) | one cycle with `--ami-shot <WD>/ami-shot.png` | fakecam_0's DAQ count == psana2's events in its stream == events with its data, each passing the per-event check; the MEB served events (`MEB_EvtCt` > 0 and at least the events AMI kept); every event AMI computed from the MEB matches psana2's event with the same timestamp (`ami_check`: seq and pixel, at least 100 events, AMI's pixel sum == psana2's over them); a second `ami-client` showed the camera image while Running (the screenshot path is in the report) |
| d | `--det hrencoder --also epix100:<p>`, over `--hosts A,B` | none yet | NOT AVAILABLE unless `--hosts` names two different hosts of this Slurm job's allocation (`SLURM_JOB_NODELIST`, expanded by `scontrol show hostnames`); with two, it prints the plan (§3j) and fails: `up --hosts` runs a plan only |

The step values are recorded by the timing DRP, as at the hutches: `TimingBEB::scanEnabled()`
(tb) and `TimingSystem::scanEnabled()` (ts) are true, `Epix100::scanEnabled()` is false, so a scan
of epix100 alone records no `step_value` (the first feature-b run showed it: psana2 had no
`step_value` detector). tb rather than ts: ts is an XpmDetector and would wait for epix100 at
Connect (below). Until a8bda341f the step values were all 0.0: `ControlDef.MyFloatPv.update` dropped
the numpy values `generic_timing_scan.py` yields (fixed; CHANGELOG).

What each feature adds to `up` (usable on its own):

- **`--also TYPE[:GROUP]`** (repeatable): one more DRP `<TYPE>_0` of another simulated type, its
  own config in the config DB, in readout group GROUP (default: the platform's). The groups go to
  control through `activedet.json`, as the partition dialog's choice would. `cycle` then checks
  every PGP DRP's count, not only the `--det` one's.
  `up` refuses a mix that cannot connect on one node: `xpmdet_config` (fakecam, cspad, epixhremu,
  jungfrauemu, ts, and the system DRPs, which are XpmDetectors), `opal_config` and
  `piranha4_config` take every active DRP on the node for a segment on their board
  (`configdb/barrier.py` `supervisor_info`: "assume non-gpu hosts have only one board") and wait
  at Connect for all of them to join their barrier, which a DRP of the other BEB types never does.
  The first feature-a run, fakecam with epix100 and wave8, hung exactly so ("fakecam_0 did not
  respond to alloc"); hence hrencoder, a BEB type, in group p.
- **`--fixed-rate GROUP:INDEX`** (repeatable): simxpm runs with `--fixed-rates` and `up` puts
  `PART:<GROUP>:L0Select` = 0 (FixedRate) and `L0Select_FixedRate` = INDEX, the PVs an operator
  sets in the XPM GUI (pyxpm's markers: 3 is 1.02 kHz, 4 is 102 Hz, 5 is 10.2 Hz, 6 is 1.02 Hz;
  simxpm does not tick faster than 2 kHz, so markers 0-2 keep `--rate`). The markers are nested
  as on a real XPM: every L1Accept of the 102 Hz group is also one of the 1.02 kHz group's.
  Each DRP's seq (MemPoolSim's payload) is its own group's L1Accept count, so each stream
  checks on its own.
- **`--bld`**: `drp_bld -D simbld+scbld+DAQ:SIM:BLD -k interface=lo` (bld_0) records simxpm's
  BLD source (`simxpm --bld`): one LCLS-II style packet per L1Accept tick (time, pulseId, id,
  severity and three fields, `simxpm.bld_values(seed, seq)`) sent by multicast to
  `239.254.31.<p>`, UDP port 31220 + p, with TTL 1 on the 127.0.0.1 interface only. The group
  is outside 239.255.0.0/16, where LCLS's BLD lives, and simxpm refuses one inside it.
  drp_bld reads the group and port from the CA PVs `DAQ:SIM:BLD:BLD1_MULT_ADDR`/`PORT` of the
  stand-in IOC and the payload's layout from simxpm's PVA PV `DAQ:SIM:BLD:BLD_PAYLOAD`, as
  `BldPVA` does. psana2 reads it through `scbld_raw_1_0_0` (`energy`, `value`, `seq` and each
  field's 2-bit `<field>_sevr`).

Breaks (`--check-only --break KIND`, on a broken copy of the recorded run; the run's files stay
as they are): `a`: `drop-l1` cuts the last 10 L1Accepts off epix100_0's stream, `same-rate`
expects both groups at one rate; `b`: `expect-values` expects each step value + 1; `c`:
`ami-tamper` flips one bit of one event's pixel in a copy of the result fetched from AMI
(`logs/ami_check.rows.json`), which `ami_check` then finds against psana2; `e`: `bld-seed`
expects the BLD values of seq + 1. Each must print `FEATURE <x> FAIL` and exit 1.
`--check-only` without a break re-runs the checks on the recorded files (for c, `ami_check`
again on the fetched result).

## 3j. Two nodes (a plan): `daq_sim up --hosts A,B --dry-run`

`daq_sim up --hosts nodeA,nodeB --dry-run [--also TYPE:GROUP ...]` prints, and starts nothing:
the `.cnf` of one partition with control, the TEB, the `--det` DRP, simxpm and the stand-ins on
node A and the `--also` DRPs on node B (procmgr's `host:` field), every endpoint on one of the
two nodes (simxpm's frames, PVA and control `-X` socket, the config and run DB stand-ins,
control's ZMQ ports, libfabric over the nodes' NIC, `ep_domain=<nic>`), the EPICS environment
for both nodes (`EPICS_PVA_ADDR_LIST` and `EPICS_CA_ADDR_LIST` = the two nodes, auto address
lists off), and what is still needed to run it. `test_sim_features.py::test_two_node_plan`
checks the plan. It has not run on two nodes. To run it:

- procmgr starts node B's processes through procServ there: procServ and procmgrd must be
  reachable from node A (ssh between the nodes, or procServ started in a Slurm step on node B
  of the job that holds it);
- configdb_server and lgbk_server must bind the node's address instead of 127.0.0.1, and simxpm
  its `--bind`, `--frames` and `--pull` (with `--allow-remote`);
- preflight.sh must accept those two-node address lists (it now requires loopback only);
- the DRP on node B writes its file under the work dir, on a file system both nodes share.

## 4. Read the file back with psana2
```bash
F=$WD/data/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2      # run 1; see the fileReport line of cycle
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=4 --mem=8G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && source psdaq/psdaq/sim/sim_env.sh && \
              python -m psdaq.sim.xtc2_check $F --seed 0x1234 --expect <N>; echo EXIT=\$?"
```
`xtc2_check` reads with `DataSource(files=[F], skip_calib_load='all')`. `LCLS_CALIB_HTTP` defaults to a dead loopback URL, so no calibration DB is contacted. psana2's Prometheus push is off by default. For every L1Accept it checks:
- fakecam's raw data is present (cspad and jungfrauemu: the same words, §3f);
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
  - pvAccess UDP 15076;
  - with two or more XpmDetector DRPs on the node (`--segments 2`), `xpmdet_config`'s barrier
    (`psdaq/configdb/barrier.py`) binds ZMQ ports 5561 and 5562 on `*`, as it does on hardware.

  Isolation relies on every peer being on this node and on the non-default EPICS ports.
- **HTTP.** The node has an IP route to pswww. The dead proxy stops only HTTP clients that honour the proxy env.
- **Partition size.** One node. Up to three PGP DRPs of different types (`--also`, §3i) or four
  segments of one type, one lane each. Rates above about 1 kHz are untested; simxpm ticks at
  most at 2 kHz, so fixed-rate markers faster than 1.02 kHz keep `--rate`. Two nodes: a plan
  only (§3j).
- **BEB types.** `rogue_dev` serves the registers a config script touches, plus what the seeds
  preset. It runs no firmware logic: a register the firmware would change on its own (a counter,
  a status bit) keeps its seed. A BEB type's frame has the subframes its DRP reads, with the
  timing header copied where the firmware sends a detailed timing frame.
- **XpmDetector types.** `xpmdet_config` runs against registers that keep what is written; the
  timing link id the DRP reports comes from simxpm, not the emulated `RxId`. epixhremu records
  the same frame in every event, as the emulator does with its file. simxpm keeps the trigger and
  inhibit settings `ts_config` writes but does not act on them.
- **MEB and AMI.** One MEB with 8 buffers (its message queues may not exceed
  `fs.mqueue.msg_max`, 10 on milano nodes) and two queues: AMI's worker reads queue 0 and
  shmemClient queue 1, and each sees the events the MEB had a free buffer for, not every event.
  AMI's node and global collectors bind their upstream port on `*`, as they do in production;
  every other AMI port is on 127.0.0.1. The AMI programs never see the run's file or BeginRun
  time, so their logs cannot name the run: coverage counts their rows from the `ami_check`
  witness (§3d), which ties the check to the AMI processes by the sockets they held on AMI's
  ports, read from `/proc` while the result was fetched (another user's process would not be
  seen).
- **control_gui at DEBUG.** A control_gui that builds its window after the partition is selected
  exits at its default log level, DEBUG: `QWPopupTableCheck.update_partition_table` calls
  `logger.debug('list2d\n', list2d)`, whose formatting raises `TypeError` in `QWLoggerStd`'s
  filter. `up --gui` therefore waits until control_gui polls control (its log's first
  `CGWMain.on_zmq_poll`) before it returns, so the cycle selects the partition after.
- **Walk network guard.** The parity walk (`qt_walk`) refuses every connection to another host;
  a connect to this host's own name or addresses (`qt_walk.THIS_HOST`) is let through, since
  procstat's procmgr reaches the local procServ ports through the host's name (refused, every
  process showed `NO CONNECT`).
- **GUI witnesses.** The witness of groupca, partca, pvant and procstat is a second instance of each GUI,
  run by `cycle` through `qt_walk`; the procmgr instance's own log only shows it ran (its
  `# CMDLINE:`). The walk reads the same PVs with the same argv, while the run runs. xpmpva is
  not run: at startup it reads `<xpm>:Us:RxAlign` and `<xpm>:Cu:RxAlign`, which this simxpm does
  not serve, and exits on the timeout.
- **PVA servers.** A unicast PVA search reaches only one of the sockets bound to the node's
  search port (15076), so simxpm is the only PVA server on it: the stand-in IOC is CA only, and
  ami-client's own PVA server gets ports 31210 + 2 p and 31211 + 2 p. With two PVA servers on
  15076, drp_pva's PV once failed to connect within its 3 s at Configure.
- **System DRPs.** drp_pva records one camera PV that simxpm updates for every L1Accept; drp_bld
  records simxpm's BLD source (`--bld`, §3i), one packet per L1Accept tick on loopback
  multicast. drp_pva takes PV updates only once it has handled Enable, and at the default 1 kHz
  its PVA monitor fell behind for the first ~50 L1Accepts of a run (they were recorded without
  the image); run `--pva` at `--rate 100`, near a camera's rate, as §3h does. Even then an update
  can miss its L1Accept (2 of 1119 in one run); the check counts them and requires drp_pva's own
  count to agree. Those counters are per process, so compare them in the first cycle after `up`. epicsArch archives two CA PVs of a softIoc on loopback and one PVA PV of simxpm. sim_udpencoder sends the
  100/200 test pattern only (no `-f` playback in the run).
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
