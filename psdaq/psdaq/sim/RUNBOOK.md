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
| `../../drpGpu/MemPool.cc` (`drp_gpu -d sim://`) | The GPU DRP's simulated device: `MemPoolSim`'s frames copied into the GPU's DMA buffers (§3h). |
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
  counts}`; `dirty` is true when tracked files differed from HEAD during the run; `content`
  holds, per listed file, its size and sha256 when the record was written (`{bytes, sha256}`).
- **Where:** `$DAQ_SIM_EVIDENCE`, else `<checkout>/.daq_sim/evidence` (gitignored).
- **From `daq_sim cycle`:** a passing recorded cycle writes one. It covers the programs in
  `daq_sim.cnf` (control, teb, drp), the drp's `-D` type (`fakecam`, or the `--det` type of
  §3e), and `prog:pyxpm`, because the status file names simxpm as its stand-in. It prints
  `evidence <id>: det:drp:fakecam prog:control prog:drp prog:pyxpm prog:teb`, then, for any row
  the check below would reject, `evidence <id>: coverage would reject it for <row>: <why>`.
- **Files:** the record lists the run's xtc2 files, `daq_sim.cnf`, `logs/cycle.jsonl`, each
  service's log (which `up` heads with its `# CMDLINE:`, as procmgr heads each process's log)
  and the newest procmgr log of each process. If you delete the work dir, the record no longer
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
  `Opening file <path>`, control the file reports) or that file's BeginRun time as `sec.nsec`
  (the TEB logs `BeginRun @ <time>`, simxpm `BeginRun ... time <time>`). The tool reads the
  xtc2 files itself (datagram and Xtc headers, Names, the runinfo), as psana2's reader lays
  them out; it needs no psana.

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
`wave8he`, `hrencoder`, `epixm320`, `opal`, `piranha4`, `tb`, `epixquad` (§3g), `epixquad1kfps`,
`epixUHR` (§3i), `jungfrau` (§3j), `epixhr2x2` (§3k), `tt` (§3l), the XpmDetector types
`cspad`, `epixhremu`, `jungfrauemu`, `ts` (§3f), and the digitizer `hsd` (§3i).
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

**Firmware packages from elsewhere: `PSDAQ_SIM_PYTHONPATH`.** Two types cannot import or build
their firmware roots from what `$SUBMODULEDIR` puts on the path: `lcls2-timetool` bundles a surf
older than rogue 6 (`AxiMicronN25Q` passes `size=` to pyrogue's `Device`; `AxiVersion.parseUpTime`
calls `get(read)` positionally), and `epixhr2x2_config.py` imports `lcls2_epix_hr_pcie` and
`epix_hr_single_10k` with no `psdaq.utils.enable_*` module. Under `sim://` (in `rogue_dev.install`
and `configdb_seed`), every top-level package in the directories `PSDAQ_SIM_PYTHONPATH` names
(colon-separated, `$VARS` expanded) imports from there first (`psdaq/psdaq/sim/sim_path.py`);
unset, nothing changes. With it, `rogue_drive` returns from every entry point of both types:

```
# tt: a rogue-6 surf from another package of the same release
export PSDAQ_SIM_PYTHONPATH='$SUBMODULEDIR/lcls2-pgp-pcie-apps/firmware/submodules/surf/python'
python -B -m psdaq.sim.rogue_drive --type tt
# epixhr2x2: its two packages and their libraries
H='$SUBMODULEDIR/lcls2-epix-hr-pcie/firmware'; E='$SUBMODULEDIR/epix-hr-single-10k'
export PSDAQ_SIM_PYTHONPATH="$H/python:$H/submodules/surf/python:$H/submodules/axi-pcie-core/python:$H/submodules/lcls2-pgp-fw-lib/python:$H/submodules/lcls-timing-core/python:$H/submodules/l2si-core/python:$E/firmware/python:$E/software/scripts:$E/firmware/submodules/epix-hr-core/python"
QT_QPA_PLATFORM=offscreen python -B -m psdaq.sim.rogue_drive --type epixhr2x2
```

epixhr2x2 runs in a DAQ with it (§3k), and so does tt (§3l). On hardware the same surf error
stops `tt_init`, and before 99cc4db8d both types also lacked the `<type>_connectionInfo` that
`BEBDetector::connectionInfo` calls (d6b1e7552 merged `<det>_connect` into it; these two kept
`tt_connect` and `epixhr2x2_connect`).

**Not running yet** (found with `rogue_drive`, and in a DRP where it gets that far):
- **epixuhr3x2:** its config DB default now builds here (`EPIXUHR_CONFIG_DIR`, §3i), and
  `epixuhr3x2_init` returns with `seeds/epixuhr3x2.json`: its C1100 card's management (axipcie
  `CmsProxy`) sits behind a surf `AxiLiteMasterProxy`, a firmware AXI-Lite master the host drives
  through `Addr`/`Data`/`Rnw` and polls `Done` on, which `rogue_dev` emulates (any root with one:
  the access goes to a register store of its own and `Done` is set), and the seeds give the
  mailbox's ready and map id and make `CONTROL_REG[5]` answer at once. `epixuhr3x2_connectionInfo`
  then fails in `manager.ReadAll()`: the root reads every QSFP register of the card's two cages,
  each a mailbox request through the proxy, about 9500 in a row on one worker thread, and the
  last ones pass rogue's 1 s transaction timeout (`Timeout waiting for register transaction ...
  QsfpLowSpeedIo[0].QSFP_INT_L`). Its data framer and psana check are not written.

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

## 3h. The GPU DRP: `daq_sim up --drp drp_gpu`

`drp_gpu` (psdaq/drpGpu) registers five types: fakecam, epixuhremu, epixuhrsim, epixuhr3x2 and
jungfrau. With `-d sim://<simxpm>` it runs without the PGP card. It needs a GPU, so run step A
in a step that holds one, on a GPU allocation (`--gres=gpu:<type>:1`); step B needs none.

**Build.** meson builds drpGpu only when `nvcc` is on PATH, and takes the toolkit from
`CUDA_ROOT` (passed as `custom_cuda_path`), else `/usr/local/cuda`. The toolkit must be one the
node's driver runs: `nvidia-smi` prints the newest CUDA it supports. CUDA 13 gives the DRP's
stages their SMs through the runtime's green contexts, as in production; CUDA 12.5 to 12.9 does
the same through the driver API (`psdaq/drpGpu/GreenCtxCompat.hh`). A node whose driver predates
CUDA 13 (e.g. 575, which runs CUDA 12.9 and refuses CUDA 13's forward-compatibility library with
`system has unsupported display driver / cuda driver combination`) needs a 12.x toolkit. Where
the node has none, conda-forge's will do, in a directory of your own:
```bash
CUDA=<dir>/cuda-12.9
conda create -y -p $CUDA --override-channels -c conda-forge cuda-version=12.9 cuda-nvcc \
      cuda-cudart-dev cuda-cccl cuda-nvtx-dev libcufile-dev cuda-driver-dev cuda-profiler-api
# the layout meson expects of a toolkit: its version, lib64, and include/cccl (CUDA 13's place
# for the CCCL headers, which a 12.x toolkit keeps in include itself)
echo "{\"cuda\": {\"name\": \"CUDA SDK\", \"version\": \"12.9\"}}" > $CUDA/version.json
ln -s targets/x86_64-linux/lib $CUDA/lib64
ln -s . $CUDA/targets/x86_64-linux/include/cccl
# the GPU subprojects (lc, pfpl, sleek) are git wraps: fetch them where there is internet
(cd $ROOT/lcls2 && source ./setup_env_daq.sh && meson subprojects download lc pfpl sleek)
srun --jobid=$JOB --ntasks=1 --cpus-per-task=16 --mem=64G --gres=gpu:<type>:1 \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && export CUDA_ROOT=$CUDA PATH=\$PATH:$CUDA/bin && \
              ./build_all.sh -d -j 16; echo BUILD_EXIT=\$?"
```
It ends with `BUILD_EXIT=0`, and `install/bin/drp_gpu` and `install/lib/lib*_gpu.so` exist.

**Run.**
```bash
# step A, in a step that holds a GPU; --cuda-lib when the loader does not find libcudart itself
nohup srun --jobid=$JOB --ntasks=1 --cpus-per-task=16 --mem=64G --gres=gpu:<type>:1 \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && \
              daq_sim up -w $WD --drp drp_gpu --det epixuhremu --cuda-lib $CUDA/targets/x86_64-linux/lib" \
     > $ROOT/daq_sim_up.log 2>&1 &
# step B, as in §3: it records evidence for det:drp_gpu:epixuhremu and prog:drp_gpu
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=8 --mem=16G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim cycle -w $WD --events 1000"
```
procServ resets `LD_LIBRARY_PATH`, so `--cuda-lib` (or `$DAQ_SIM_CUDA_LIB`) becomes the
`env:` of the drp_gpu entry of `daq_sim.cnf`. The step's GPU is the one drp_gpu uses.

**What runs.** `drp_gpu -D <type> -d sim://...` (`psdaq/drpGpu/MemPool.cc`):
- `MemPoolGpu` takes the simulator mode's memory (registers in pinned host memory, DMA buffers
  on the GPU) and creates the drp's `MemPoolSim` on it, which receives simxpm's timing frames
  and lays each out as the type's firmware would (§3f). A thread does what GpuAsyncCore does:
  it waits until the GPU has re-armed the next DMA buffer in turn, copies the frame in after the
  32 B DMA frame, waits for the copy and only then writes the size word the Reader polls. The
  index restarts at each Configure frame, as the Reader's does.
- The type's configuration is the CPU class `Gpu::<type>` wraps, as under `drp -d sim://`: the
  XpmDetector and BEBDetector classes reach the same `MemPoolSim` (`MemPool::sim()`), so their
  config scripts run against `rogue_dev` and their link is simxpm's.
- The GPU's Reader, calibration, TrgInpGen, NoOpReducer and recorder run unchanged. The file
  holds each event's calibrated pixels as the NoOpReducer recorded them: psana reads them as
  `<type>_noOp_0_0_0.calib` (float32, `psana/psana/detector/drpgpu.py`).
- `xtc2_check --drp drp_gpu` compares every pixel of every event (the `--self-test-offset 1`
  run must FAIL).

| type | config code run | device payload | psana check |
|---|---|---|---|
| fakecam | `xpmdet_config` (as `drp -D fakecam`) | the TDetSemi words of `MemPoolSim::fill`, `sim_length` words = 2 x that many uint16 pixels | `fakecam_noOp_0_0_0.calib`: each pixel's low 14 bits (`Gpu::AreaDetector`, pedestals 0, gains 1) vs the words of seed, seq n and the event's pulseId |
| epixuhremu | `epixuhremu_configTiming` (link down: `ConfigLclsTimingV2()`), then `xpmdet_config` | TDetSemi words, 96768 = one 336 x 576 uint16 panel, as the emulator firmware (a TDet block) sends | `epixuhremu_noOp_0_0_0.calib` (336, 576): bits 1-11 of each pixel (gain in bit 0; no calibSerNo: pedestals 0, gains 1) vs the words |
| epixuhrsim | its `SimDetector` (no config script): 16 random frames and calibration constants on the GPU; simxpm's frames time them | frame n % 16 after the TimingHeader | `epixuhrsim_noOp_0_0_0.calib` vs frame (n - 1) % 16 calibrated with the constants it writes at BeginRun (`sim_ref` kwarg, `--ref`) |
| jungfrau | `Drp::Jungfrau`, as `drp -D jungfrau` (§3j): `jungfrau_config.py` against `rogue_dev`, `sls::Detector` against simsls | the module's frame n, its 128 UDP packets as `MemPoolSim` batches them (§3j), 1055848 B (`dmaBufSize` 0x120000) | `jungfrau_noOp_0_0_0.calib` (512, 1024): each pixel's low 14 bits (range in bits 14-15, pedestals 0, gains 1) vs `pattern(seed, n, i, 16)` |

The pulseId of each fakecam/epixuhremu event is the one, of the few ticks simxpm may add to its
timestamp's, whose first words match; it must rise.

Fault runs: fakecam and epixuhremu configure nothing at Configure (as the XpmDetector types of
§3f). `TDetSemi.Length_0` is written only at Connect (`xpmdet_connect`), so
`PSDAQ_SIM_ROGUE_FAULT=DrpTDet.PcieControl.DevPcie.TDetSemi.Length_0` makes Connect fail, and the
drp_gpu log names it (`rogue_dev: FAULT ...TDetSemi.Length_0`, then `Verify error for block
DrpTDet.PcieControl.DevPcie.TDetSemi.Length_0 ... Got: 0xff, Exp: 0x00` for epixuhremu, `Exp: 0x40`
for fakecam, `**** python error`). A register that `xpmdet_connectionInfo` writes fails earlier:
a fault on `TDetSemi.Enable_0` fails Allocate. rogue's verify error names the 32-bit block, which
`Enable_0` shares with `Length_0`. epixuhrsim has no registers.

**jungfrau** (`daq_sim up --drp drp_gpu --det jungfrau`) runs as `drp -D jungfrau` does (§3j),
with the same simsls, config DB entry and fault (`PSDAQ_SIM_SLS_FAULT`). Two drp_gpu defects
stopped it, and both are fixed:
- `Gpu::Jungfrau::configure` declared a second Names at `EventNamesIndex`, so psana could not
  read the file (`NamesIter.cc: Found duplicate namesId`).
- Every drp_gpu died at the Reset after a run: `PGPDrp::unconfigure` ran a second time and
  dereferenced the reader it had already reset.

drp_gpu accepts jungfrau's `segNums` and `slsHosts` kwargs only with a `sim://` device. A
hardware drp_gpu rejects them, as before, so `drp_gpu -D jungfrau` cannot be given the
`slsHosts` that `Drp::Jungfrau` requires. That defect is not fixed here.

**Not running yet:**
- **epixuhr3x2:** `Gpu::EpixUHR3x2` configures through `Drp::EpixUHR3x2`, whose constructor
  builds its rogue root itself (`_init_data_path_or_emu()`) instead of through
  `BEBDetector::_init()`, so `rogue_dev` is never installed and `epixuhr3x2_init` opens the device
  file: `rogue.GeneralError: AxiStreamDma::openShared: General Error: Failed to open device
  file: sim://127.0.0.1:31099` (drp_gpu started by hand on that device). Past that it needs
  what `drp -D epixuhr3x2` needs (§3e).

## 3i. The digitizer, the ePixQuad 1 kfps and the ePixUHR: hsd, epixquad1kfps, epixUHR

`daq_sim up --det hsd|epixquad1kfps|epixUHR`, then `daq_sim cycle` as in §3e.

- **hsd.** Its DRP class (`Digitizer`) is not a BEBDetector; with a `sim://` device it installs
  `rogue_dev` the same way before importing `hsd_config.py`, joins simxpm's readout group at
  Connect and takes its timing link from simxpm (`Digitizer: simulated device, PADDR_U 0xff000000;
  link id 0x... from simxpm`). `hsd_init` builds `l2si_drp.DrpPgpIlvRoot` on the emulated card
  (`seeds/hsd.json`: the 185.71 MHz `MonClkRate_3` `hsd_connect` checks, `PgpQPllLock`); everything
  else the config code does goes over PVA to the hsd's IOC. `up` starts `simhsdioc` for that,
  with channels `DAQ:SIM:HSD:1_SIM:A` and `:B` (the DRP's `-k hsd_epics_prefix` is A;
  `hsd_init` disables both): it serves hsdpvs's PVs (`psdaq/psdaq/cas/hsdpvs.py`'s `ChipServer`)
  and does what hsd134PVs, the IOC, does with them as far as `hsd_config` reads it back: a
  `CONFIG` put sets `READY`, and with `enable` sets `MONTIMING.group` and `l0delay` (81; the
  store's `user.raw.start_ns` of 93000 needs at most 86); `FEXOOR` is posted every second (Connect
  checks its age); `MONPGP.remlinkid` is the link id `hsd_connect` writes into the card's
  `TxLinkId` on this host; `PADDR_U`, `FWVERSION`, `FWBUILD`, free buffers. `logs/simhsdioc.log`
  lists every `CONFIG` it applied. The config DB entry is what `hsd_config_store.py`, a script,
  writes when run with `--name hsd --segm 0` (configdb_seed runs it against a configdb that
  contacts nothing), with `user.fex.prescale` 1 so the config asks for the fex stream the
  simulated digitizer sends.
- **epixquad1kfps.** The same EpixQuad DRP and data as epixquad (§3g), configured by
  `epixquad1kfps_config.py` and the epix-quad-1kfps package's `ePixQuad.Top`, whose `start` reads
  the ADC calibration from the camera's SPI PROM (surf `CypressS25Fl`). A seed
  `{"response": v, "bits": n}` makes a register's low n bits read v whatever is written:
  `Top.CypressS25Fl.CmdReg`'s low byte, the flash's status, reads 0 (idle; `waitForFlashReady`
  polls bit 0, active-low ready). The calibration data `Top.start` then reads (git hash, board
  ids) reads 0, as do the camera registers it compares them with. The package's `ePixViewer`
  constructs a `QApplication` when `ePixQuad` is imported (`ePixViewer/_ePixViewer.py` line 57),
  so a process that imports `epixquad1kfps_config` with no display aborts (`qt.qpa.xcb: could
  not connect to display`), a DRP on a node without one too; `daq_sim up` runs this type's
  config seeding and DRP with `QT_QPA_PLATFORM=offscreen`.
- **epixUHR.** `epixUHR_config_store.epixUHR_cdict()` reads its PLL tables and pixel maps from
  `EPIXUHR_CONFIG_DIR` (default the facility's `/cds/home/p/psrel/EpixUHR`); `up` writes
  simulated ones (`psdaq.sim.epixuhr_files`: Si5345 tables of a few registers, all-zero 168 x 192
  pixel maps) under the work dir and points it there. `seeds/epixUHR.json` is the PgpMonitor KCU
  (as epixm320's) and the camera's `RxId`, which `epixUHR_init` waits for.

| type | config entry points run | emulated device / stand-in | DRP data | psana check |
|---|---|---|---|---|
| hsd | `hsd_init` (`DrpPgpIlvRoot`, `hsd_unconfig` of A and B), `hsd_connect` (clock, QPLL, `TxLinkId`, `FEXOOR` age, `PADDR_U`, `MONPGP.remlinkid`), `hsd_config` (PGP resets, `READY`/`CONFIG` handshake twice, `MONTIMING`, buffers, `KEEPROWS`, `RESET.jesdclear`, `FWVERSION`), `hsd_unconfig` | `DrpPgpIlvRoot` seeds; `simhsdioc` | the TimingHeader's opaque words as the hsd event header (raw and fex streams, JESD ok), then a raw stream of 1160 12-bit samples and a fex stream of 44 words: 3 skip groups around 2 peaks | `hsd_raw_3_0_0` `waveforms()` every sample, `peaks()` every peak's start and samples |
| epixquad1kfps | `epixquad1kfps_init` (`DevRoot`, `ePixQuad.Top` with its PROM), `_connectionInfo`, `_config`, `_enable`, `_disable`, `_unconfig` | as epixquad, plus `Top.AxiPcieCore` image name and `FpgaVersion`, and the PROM's status byte | as epixquad | `epix10ka_raw_3_0_1` raw (4, 352, 384), every pixel, 14 bit |
| epixUHR | `epixUHR_init` (PgpMonitor, the camera `Root`, `ConfigLclsTimingV2`, the `RxId` wait), `_connectionInfo`, `_config` (PLL, ASIC gains, batchers), `_enable`, `_disable`, `_unconfig` | PgpMonitor KCU, `RxId` | 1: timing copy; 2-5: ASICs 0-3, each 168 x 192 12-bit pixels packed as the ASIC's 8 serial lanes send them (psana's descrambler run backwards) | `epixuhr_raw_*` raw (4, 168, 192) through its descrambler, every pixel, 12 bit |

Fault runs that fail Configure and name the register: hsd `DrpPgpIlv.PcieControl.DevPcie.PgpQPllReset`
(rogue's write-verify when `hsd_config` pulses the QPLL reset), epixquad1kfps
`DevRoot.DevPcie.Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay`, epixUHR
`Root.App.TimingRx.TriggerEventManager.TriggerEventBuffer[1].TriggerDelay`.

## 3j. Jungfrau: `daq_sim up --det jungfrau`

```bash
# as §3e, with --det jungfrau; each event is a 1 MiB frame, so 100 Hz is plenty
nohup srun --jobid=$JOB --ntasks=1 --cpus-per-task=32 --mem=64G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim up -w $WD --det jungfrau --rate 100" > $ROOT/daq_sim_up.log 2>&1 &
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=32 --mem=64G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim cycle -w $WD --events 1000"
```
`drp -D jungfrau -d sim://` configures two devices, each through its own code, unmodified:
- **the card:** `jungfrau_config.py` builds `lcls2_udp_pcie_apps.DevRoot` on `rogue_dev`, as in
  §3e. `seeds/jungfrau.json` gives the timing clock (`GtRxAlignCheck[1].TxClkFreqRaw`, 185.714
  MHz, so `check_i2c_clk` does not reprogram the Si570), lane 0's `EthPhy.phyReady`, `RxId`,
  `FpgaVersion` and `BuildStamp`.
- **the module:** `Drp::Jungfrau` drives it through `sls::Detector`, the env's slsDetectorPackage
  9.0.0 client, at `-k slsHosts`. `daq_sim up` starts **simsls** (`psdaq/psdaq/sim/simsls.py`) in
  its place, on loopback, before procmgr. simsls serves that client's protocol for the calls the
  DRP makes, and it reports the 9.0.0 Jungfrau server's version, so the client's version check
  passes. The env has only the package's client and receiver: its virtual server
  (`jungfrauDetectorServer_virtual`) is built only from source, with `SLS_USE_SIMULATOR`.

| DRP step | what `Drp::Jungfrau` asks the module (`sls::Detector`) | what simsls answers |
|---|---|---|
| start | `setHostname(127.0.0.1:<+4>)`: detector type, server version (control and stop servers), initial checks, interfaces, position | Jungfrau, `9.0.0 0x241121`, virtual (1) |
| Alloc | module id, serial number, firmware version, server version | 0x2a0, 0x1e3, 0x230920, 9.0.0: the segment's id is built from the board id, because simsls has no ARP entry or telnet server to read a MAC from |
| Configure | stop; trigger mode, 2^63-1 triggers, 1 frame; for the module: UDP destination port, IP and MAC, source IP and MAC, then validate; 8 DACs; chip power; readout speed; trigger delay, period, exposure time, high voltage, settings and gain mode, each set and read back | keeps each value. It refuses what the module refuses, with the 9.0.0 server's messages (DAC above 4095, high voltage not 0 or 60-200, settings other than gain0/highgain0). It also refuses a data destination outside 127.x |
| BeginRun | next frame number 1 | |
| Enable | start; status must be RUNNING or WAITING | WAITING: armed for triggers |
| Disable | stop; status must be IDLE or STOPPED | IDLE |

**The data, per L1Accept.**
1. MemPoolSim (the card's side, `UdpFront` in `MemPoolSim.cc`) sends a datagram to simsls's
   trigger input (UDP `127.0.0.1:<+4>`).
2. simsls sends frame n (n = 1, 2, ... from BeginRun) as 128 packets. Each packet is a 48 B
   `sls_detector_header` and 8192 B of pixels. It sends them to the destination the DRP
   programmed: the config's `user.kcu_ip:user.port`.
3. MemPoolSim takes the packets on `127.0.0.1:<sim_udp_port>`. It writes them as the card's
   UDP batcher does, as subframe 2: an EventBatcher of one subframe per packet.
4. `Jungfrau::_event` puts the frame together by packet number. It checks the frame number
   against its L1Accept count, and the module id.

Pixel i of the panel (psana2's raw, flattened) is `pattern(seed, n, i, 16)`: 14 data bits and 2
gain bits. `xtc2_check` checks, for every event:
- every pixel of `jungfrau_raw_0_2_0.raw`,
- `frame_cnt == n`,
- the module timestamp rises,
- `numHotPixels` equals the count recomputed from the pixels.

**Ports.**
- `+4`: simsls control (TCP) and its trigger input (UDP).
- `+5`: simsls stop server (TCP).
- `+6`: the module's data destination (UDP).

**Config DB.** The entry is `jungfrau_config_store`'s config with
`configdb_seed --set user.kcu_ip=127.0.0.1 --set user.jungfrau_ip=127.0.0.1 --set
user.port=<+6>`. The store's own values (10.0.0.10, port 8192) would send the module data off the
node, and simsls refuses them: `udp_dstip 10.0.0.10 refused`.

**Shared memory.** `SLSDETNAME=daq_sim_p<platform>` names the DRP's `sls::Detector` shared
memory (`/dev/shm/slsDetectorPackage_detector_1_daq_sim_p5...`). The DRP frees it when it exits,
and `daq_sim down` removes any that is left.

**Fault.** `PSDAQ_SIM_SLS_FAULT=<setting>[=<value>]` in `up`'s environment makes that setting read
back `<value>` (default: what was set, plus 1). `exptime=20000` makes Configure fail with
`<E> Failed readback check of exposure time for module 0: 0.000020 [0.000010]`. A DAC fault
(e.g. `vb_ds`) is only logged: `Drp::Jungfrau` ignores `_configueDAC`'s result.

## 3k. The ePixHR 2x2: `daq_sim up --det epixhr2x2`

```bash
# as §3e, with --det epixhr2x2 and, in up's environment, PSDAQ_SIM_PYTHONPATH (§3e) naming the
# two packages epixhr2x2_config.py imports; up reports it and never sets it
H='$SUBMODULEDIR/lcls2-epix-hr-pcie/firmware'; E='$SUBMODULEDIR/epix-hr-single-10k'
export PSDAQ_SIM_PYTHONPATH="$H/python:$H/submodules/surf/python:$H/submodules/axi-pcie-core/python:$H/submodules/lcls2-pgp-fw-lib/python:$H/submodules/lcls-timing-core/python:$H/submodules/l2si-core/python:$E/firmware/python:$E/software/scripts:$E/firmware/submodules/epix-hr-core/python"
nohup srun --jobid=$JOB --ntasks=1 --cpus-per-task=32 --mem=64G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim up -w $WD --det epixhr2x2" > $ROOT/daq_sim_up.log 2>&1 &
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=32 --mem=64G \
     bash -c "cd $ROOT/lcls2 && source ./setup_env_daq.sh && daq_sim cycle -w $WD --events 1000"
```
`drp -D epixhr2x2 -d sim://` runs `epixhr2x2_config.py`, unmodified, against `rogue_dev` (§3e).
`up` logs `epixhr2x2: PSDAQ_SIM_PYTHONPATH=...`, writes it as a comment into `daq_sim.cnf`, and
passes the drp `QT_QPA_PLATFORM=offscreen` (the camera's `ePixFpga` package imports PyQt5's
widgets), as for epixquad1kfps.

| DRP step | `epixhr2x2_config` entry point | the simulated device |
|---|---|---|
| start | `epixhr2x2_init`: `lcls2_epix_hr_pcie.DevRoot` on the PCIe map, the camera board `ePixHr10kT` (`epix_hr_core.SysReg`, `ePixFpga.EpixHR10kT`) over SRPv3, `ConfigLclsTimingV2`, `InitHSADC` | `seeds/epixhr2x2.json`: `FpgaVersion` 0x03040000 (`DevRoot.FwVersionLock`), `MmcmLocked` 3 and `RxLinkUp` 1 (what `LockProc` waits for) |
| Alloc | `epixhr2x2_connectionInfo` (99cc4db8d): `TxId`, the camera's `RxId` | `RxId` reads 0; the link id the DRP reports is simxpm's |
| Configure | `epixhr2x2_config`: the event builders' `Bypass`, `Timeout` and `Blowoff`; the camera's settings written as YAML files that `fnInitAsicScript` loads (MMCM, power, register control, the 4 ASICs, SSP, packet and trigger registers); gain mode 0's uniform pixel map into each ASIC; `_start` | registers keep what is written |
| Enable, Disable | `epixhr2x2_enable` (the camera's timing trigger, `SetTimingTrigger`), `epixhr2x2_disable` (its body is commented out) | |
| Unconfigure | `epixhr2x2_unconfig` (`StopRun` of the camera and the card) | |

**The YAML files.** `config_expert` writes them as `/tmp/epixhr<part>.yml` (`det_config.dictToYaml`)
and removes them after `fnInitAsicScript`. Under `daq_sim` they go under `$WD/tmp/` instead: the
seed file's `"_scratch": ["/tmp/epixhr"]` moves that prefix to `$PSDAQ_SIM_TMPDIR`, which `up` sets
to `$WD/tmp`, so two DAQs on one node do not share them. Not moved: the pixel-map CSVs gain mode 5 (Map) writes as
`/tmp/epixhrPixelMap<i>.csv`, and the `/tmp/Hr10kTAsic<i>.*` files of `readPixelMaps` (off). The
default config uses neither.

**Config DB.** `epixhr2x2_config_store`'s config, with the detType its `__main__` gives the entry,
`epixhr2x2hw` (`configdb_seed.STORE_DETTYPE`). The config script records that whole config as
detector `epixhr2x2hw`, segment 0 (psana: `epixhr2x2hw_config_2_0_0`), and its own segment
config (`asicPixelConfig`, `trbit`) as detector `epixhr2x2`, segment 0.

**The data, per L1Accept** (`MemPoolSim.cc`, `sim_dma_size=0x40000`). The card's event builder
nests the camera board's:

| subframe | what `EpixHR2x2` reads there |
|---|---|
| 0 | an EventBatcher whose first subframe is the TimingHeader: `getTimingHeader` steps into it |
| 3 | ASICs 0 and 1: an EventBatcher of {tdest 0: a copy of the TimingHeader, tdest 2: 146 rows of 384 uint16} |
| 4 | ASICs 2 and 3: the same |

`EpixHR2x2::_event` drops the first and the last row of each and records rows 1-144 of subframe
3's, then of subframe 4's, as `raw` (288, 384), the words as they come. Pixel i of `raw` is
`pattern(seed, n, i, 16)`. The dropped rows carry indices past the image, and the first starts
with the data header. `xtc2_check` checks every pixel of `epixhr2x2_raw_2_0_1`'s `raw` in every
event, and that the Configure has both detectors: `epixhr2x2hw` segment 0 (user, expert) through
`epixhr2x2hw_config_2_0_0`, and `epixhr2x2` segment 0's `asicPixelConfig`.

**Fault.** `PSDAQ_SIM_ROGUE_FAULT=DevRoot.DevPcie.Application.EventBuilder.Timeout` in `up`'s
environment fails Configure: rogue's write-verify names the register.

**Without `PSDAQ_SIM_PYTHONPATH`** `up` logs `epixhr2x2: PSDAQ_SIM_PYTHONPATH is not set (RUNBOOK
§3k)` and fails before it starts a DRP: `configdb_seed` imports `epixhr2x2_config` for the store's
config, and the import fails (`ModuleNotFoundError: No module named 'lcls2_epix_hr_pcie'`,
`logs/seed.log`). A `drp -D epixhr2x2 -d sim://` started without it stops at start with the same
error, as the base commit's drp does, under `sim://` and with `/dev/datadev_0`.

## 3l. The timetool: `daq_sim up --det tt`

```bash
# step A as in §3e, with the variable of §3e in the environment of 'up' (the drp inherits it)
export PSDAQ_SIM_PYTHONPATH='$SUBMODULEDIR/lcls2-pgp-pcie-apps/firmware/submodules/surf/python'
daq_sim up -w $WD --det tt            # prints: tt: PSDAQ_SIM_PYTHONPATH='$SUBMODULEDIR/...'
# step B as in §3e
daq_sim cycle -w $WD --events 1000
```
`drp -D tt` is a BEBDetector (`TimeTool.cc`): `tt_config.py` builds
`lcls2_timetool.TimeToolKcu1500Root` (the KCU's TimeToolKcu1500 and, behind the camera link FEB on
PGP lane 0, a Piranha4 line camera) on `rogue_dev`, with the surf the variable names
(`sim_path`). `up` never sets the variable: it reports it (`tt: PSDAQ_SIM_PYTHONPATH=...`, or
`... is not set`), stores it in `state.json` (`det_env`) and writes it as a comment at the top
of `daq_sim.cnf`. Unset, the drp stops in `tt_init` with the surf error of §3e (`TypeError:
__init__() got an unexpected keyword argument 'size'`, `**** python error`) a few seconds after
`up` has seen it RUNNING, and `cycle` fails at Alloc (`at least one DRP is required`).

| config entry points run | emulated device (`seeds/tt.json`) | DB config | DRP data (subframes) | psana check |
|---|---|---|---|---|
| `tt_init` (`TimeToolKcu1500Root` start, `ConfigureXpmMini`, `ConfigLclsTimingV2`), `tt_init_feb`, `tt_connectionInfo` (the PGP link check, `TxId`, `RxId`), `tt_config` (`user_to_expert`, `config_expert` over registers and the camera's UART, `gcp`, `MasterEnable`, the firmware version), `tt_unconfig` | `PgpMon[0].RxRemLinkReady`, `XpmMessageAligner.RxId`; the Piranha4's console (every command `OK` and the `USER>` prompt, `gcp` its summary) | `tt_config_store` through its `write_to_daq_config_db` | 2: the camera's region of interest, 2048 uint8 pixels (tdest 1, the firmware's FEX results, is not produced: `TimeTool::_event` does not read it) | `tt_raw_2_0_0` `image()` (2048,) uint8 and `_info().image`, every pixel, 8 bit |

`TimeTool::_configure` takes the region of interest's length from the config
(`UartPiranha4.ROI1 - ROI0 + 1`) and `TimeTool::_event` records subframe 2 only if it has that
length, else it marks the event damaged. Before this change the type could not configure on
hardware either: `tt_config_store` wrote `ROI[0]`, `ROI[1]` and `SAD[0..2]`, names an
`XtcData::Name` refuses since 2b0873c2c (`*** Error: illegal XtcData::Name:
expert.ClinkFeb.ClinkTop.ClinkCh.UartPiranha4.ROI[0]. Aborting.` at Configure), and
`TimeTool::_configure` read `expert.ClinkFeb[0].ClinkTop.Ch[0].UartPiranha4.ROI[1]`, a name that
cannot be in the xtc. The store now writes `ROI0`, `ROI1`, `SAD0`, `SAD1`, `SAD2`, `tt_config`
maps them to the camera's `ROI[i]` and `SAD[i]` (as it maps `PllConfig0` to `PllConfig[0]`), and
`TimeTool::_configure` reads `expert.ClinkFeb.ClinkTop.ClinkCh.UartPiranha4.ROI0` and `ROI1`.
Config DB entries written by the old store keep the old names and still abort at Configure;
they must be written again.

Not fixed: the store's `expert.TimeToolKcu1500.Application.AppLane.*` settings (prescalers, FIR
coefficients, IIR time constant, background subtraction) do not reach the firmware tree, which
names the lane `AppLane[0]` (lcls2_timetool `_Application.py`) and for which `tt_config`'s
translation has no `AppLane` entry: it prints `Lookup failed for node [AppLane] in path
[cl.TimeToolKcu1500.Application]` and skips them, on hardware as here.

Fault run that fails Configure and names the register:
`TimeToolKcu1500Root.TimeToolKcu1500.Kcu1500Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay`
(rogue's write-verify when `config_expert` applies the trigger delay `user_to_expert` computes:
`Verify error for block ...TriggerEventBuffer[0].TriggerDelay ... Got: 0xff, Exp: 0x17`, then
`**** python error` and signal 6 in the drp's log).

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
- **Partition size.** There is one detector DRP and one lane. Rates above about 1 kHz are untested.
- **BEB types.** `rogue_dev` serves the registers a config script touches, plus what the seeds
  preset. It runs no firmware logic: a register the firmware would change on its own (a counter,
  a status bit) keeps its seed. A BEB type's frame has the subframes its DRP reads, with the
  timing header copied where the firmware sends a detailed timing frame.
- **hsd.** The simulated digitizer sends the same streams whatever `CONFIG` asks for: 1160 raw
  samples (what `hsd_config_store`'s default gate gives) and a fex stream of 2 peaks. `simhsdioc`
  acts on a `CONFIG` put only as far as `hsd_config` reads it back (`READY`, the readout group
  and L0 delay in `MONTIMING`); it does not model buffers, prescales or deadtime.
- **jungfrau.** One module (lane mask 0x1). simsls answers the calls `Drp::Jungfrau` makes and a
  few getters (the table `simsls.F`). Any other call gets the 9.0.0 server's
  "Unrecognized Function enum" reply. simsls keeps values and refuses out-of-range ones, but runs
  no detector logic, and it sends frames only on a trigger. The card's `UdpFrameReorg` remap is
  not emulated: the packets arrive in order on loopback, and MemPoolSim places them by packet
  number. The hot pixel count is checked, but the detector protection trip is not (there is no
  IOC).
- **XpmDetector types.** `xpmdet_config` runs against registers that keep what is written; the
  timing link id the DRP reports comes from simxpm, not the emulated `RxId`. epixhremu records
  the same frame in every event, as the emulator does with its file. simxpm keeps the trigger and
  inhibit settings `ts_config` writes but does not act on them.
- **GPU DRP.** One GPU DRP, its own step's GPU, the NoOpReducer only; the payload is copied into
  the GPU's buffers by a host thread at the simxpm rate, not DMAed by a card, so the GPU DRP's
  rate limits (33 kHz on hardware) are not exercised. Built with CUDA 12 the stages get the
  same SMs as with CUDA 13, split by the driver API in groups of the Reader's size.
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
