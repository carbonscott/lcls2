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
| `calibws_server.py` | Calibration constants stand-in (the `calib_ws` that `psalg.calibdb` reads), for `drp_gpu -D epixuhr3x2` (§3h). |
| `simxpm.py` | Software XPM: the pyxpm PVs over PVA, timing frames to `sim://` DRPs, and the `control -X` PULL receiver. |
| `xtc2_check.py` | psana2 read-back with a per-event payload check (every pixel or sample for BEB types, §3e). |
| `rogue_dev.py`, `seeds/<type>.json` | The emulated device of a BEB type under `drp -d sim://` (§3e), and the emulated TDet timing receiver of every XpmDetector type (`seeds/xpmdet.json`, §3f). |
| `epixhremu_frame.py` | Writes the xtc2 file whose frame `drp -D epixhremu` replays (§3f). |
| `pattern.py` | The simulated BEB pixel values, the same function as `MemPoolSim::pattern` in C++. |
| `rogue_drive.py` | Debugging aid: runs a BEB type's config entry points against `rogue_dev`, without a DRP (§3e). |
| `../../drp/simFrame.cc` (`drp_sim_frame`) | Writes one simulated BEB DMA buffer to stdout, for the framer's tests. |
| `coverage.py`, `coverage_status.json` | `daq_sim coverage` (§3d): which detector types and programs are proven to run without hardware, at HEAD. |
| `matrix.py` | `daq_sim matrix` (§3p): the whole matrix in one command, every detector type, the system features and coverage, with an exit code that is the verdict. |
| `MAINTAINING.md`, `FLAKES.md` | How to bring upstream in and re-prove the sim, start to end (allocations, the sync merge, the build, the cheap tier, the full check, what to rerun when); the register of known intermittent failures with each one's verdict. |
| `ami_check.py`, `gui_witness.py` | The checks `cycle` runs with `--ami` and `--gui`, and the witnesses of the run they write for coverage (§3d, §3m). |
| `ami_shot.py`, `qtgrab/` | `cycle --ami-shot PNG`: AMI's viewer of the camera image, offscreen, saved to PNG (§3m). |
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

# fresh checkout of the branch that holds psdaq/psdaq/sim (sim-main, the fork's default branch)
ROOT=/sdf/data/lcls/ds/prj/<your project>/scratch/<you>     # any directory on a shared filesystem
cd $ROOT && git clone https://github.com/carbonscott/lcls2.git && cd lcls2 && git checkout sim-main
# or a pull request's head before it is merged (here #42): fetch it into a branch of your own
#   git fetch origin pull/42/head:pr-42 && git checkout pr-42 && git log -1 --format=%h   # the PR's head commit

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
... evidence <id>: det:drp:fakecam prog:control prog:drp prog:pykcuxpm prog:pyxpm prog:teb
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
(`psdaq/psdaq/webgui/README.md`, "Parity with the other PyQt GUIs": its environment, its value API
`/api/pvgui/values?gui=<name>`, and how `daq_sim down` stops it).

It listens on 127.0.0.1 of the node only. To open it from your own machine, tunnel to the node
that holds the job (S3DF lets you ssh to a compute node only while you have a job on it). This
`-J` form was not tested; a two-hop tunnel through sdfiana025 was (recorded at 7695dfdae, the page
driven Configure to Running to Reset): `ssh -L 31053:<dir>/webgui.sock sdfiana025 'ssh -N -o
StreamLocalBindUnlink=yes -L <dir>/webgui.sock:127.0.0.1:31053 <node>'`, `<dir>` a `mkdir -m 700`
directory of yours on sdfiana025. If ssh says the node's host key changed, it turns port forwarding
off: check the key the node itself has (`/etc/ssh/ssh_host_*_key.pub`, read in a step on it)
before you trust it.
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
sdfiana025's `python3` is 3.6 and fails (`TypeError: __init__() got an unexpected keyword argument
'capture_output'`); there, use the DAQ env's own interpreter without sourcing the env:
`PYTHONPATH=psdaq /sdf/group/lcls/ds/ana/sw/conda2/inst/envs/daq_20250402_r9/bin/python -m psdaq.sim.coverage`
(Python 3.9; about 2 minutes over a full matrix's evidence there).

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
- `N/A`: a hardware diagnostic or firmware tool with no role in a run, or (R7) a program the tree itself cannot
  build or import (its build commented out in meson, or classes it needs absent from the tree: `xpmPVs`,
  `hsd64PVs`). The entry gives a one-line `reason`, for R7 with the file and line and the failing command.

A row with no entry is UNPROVEN. An entry for a row that the enumeration does not find is an error.

**Evidence.** Each passing run writes one JSON record with
`psdaq.sim.coverage.record_evidence(rows, kind, files, ...)`:
- **Fields:** `{sha, dirty, rows, kind, run_id, job_id, host, files, content, started, ended,
  counts, data_dir}`; `data_dir` is the run's data dir (the drp's `-o`); `dirty` is true when tracked files differed from HEAD during the run; `content`
  holds, per listed file, its size and sha256 when the record was written (`{bytes, sha256}`).
- **Where:** `$DAQ_SIM_EVIDENCE`, else `<checkout>/.daq_sim/evidence` (gitignored).
- **From `daq_sim cycle`:** a passing recorded cycle writes one. It covers the programs in
  `daq_sim.cnf` (control, teb, drp), the drp's `-D` type (`fakecam`, or the `--det` type of
  §3e), and `prog:pyxpm` and `prog:pykcuxpm`, because the status file names simxpm as the stand-in
  of both. It prints
  `evidence <id>: det:drp:fakecam prog:control prog:drp prog:pykcuxpm prog:pyxpm prog:teb`, then, for any row
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
    (`lists no per-event match`, `match timestamp ... is no L1Accept of the run's files`) whose
    seq and pixel are what that file holds there: the tool reads the detector's (`det`, default
    fakecam) raw array itself, words 4 and 5 of its first row (seq) and word 8 (pixel), as
    `ami_check` reads them with psana2 (`match 0x... gives seq 7 pixel 248, the run's xtc2 file
    holds seq 0 pixel 7 there`), and
    `served_by`, the processes (`pid`, `cmdline`, `ancestors`) that held a TCP socket on AMI's
    ports while the cycle fetched AMI's result, and, with `--ami-shot`, while the screenshot's
    ami-client showed the run: one of them, or one of their ancestors (AMI's GUI windows are
    processes it forks, renamed `ami editor`), must run the row's program with the pid its log
    gives (procmgr's `@@@ The PID of new child ... is: N`, or the `# PID: N` line ami_shot writes)
    (`its served_by lists no ami-client process`, `its log of ami-client gives pid N, not one of
    the ami-client processes that served the check`, `its log of ami-client gives no pid`). The
    program's own log is required too. The procmgr `ami-client` loads no graph, so it holds none
    of AMI's ports; the ami-client row is proven by the one `cycle --ami-shot` runs.
  - a GUI whose log does not name the run (R2; groupca, partca, pvant): a `gui_witness`
    (`logs/gui_witness.json`) whose `programs` entry for it passed, whose `start` and `end`
    (EPICS-epoch seconds, the walk's process) lie between the run file's first and last L1Accept
    (`read from ... to ..., not within the run's L1Accepts`), and that shows at least one PV under
    the witness's `partition` prefix with 2 or more distinct numbers (a placeholder such as `-` is
    none) (`shows groupca read no live value under DAQ:SIM:XPM:0:PART:5`); plus the GUI's own log
    with its `# CMDLINE:`. Every rule below also needs the program's own log and the passing entry
    read within the run's L1Accepts.
  - procstat (R2b) shows no PV but procmgr's table of the partition's processes (ID, status): its
    entry (`"kind": "procmgr"`) must show RUNNING every process whose procmgr log (`# ID:`) in the
    record names the run (`shows procstat did not list fakecam_0 RUNNING`).
  - a PV monitor that is not a GUI (R2c; epics_exporter, procmgr id `pvrtmon_0`): its entry holds
    the Prometheus gauges cycle scraped from it once a second, each named by the partition PV it
    exports (`DAQ:SIM:XPM:0:PART:5:RunTime`); one gauge under the partition must take 2 or more
    distinct values (`shows epics_exporter read no live value under DAQ:SIM:XPM:0:PART:5`).
  - a GUI on a device stand-in (R4; hsdpva and pvatable on simhsd, tprca on simtpr, dtica on simdti,
    with `up --gui --pvservers`; xpmpva on simxpm, the XPM stand-in on the node's own PVA ports,
    which serves the `PAddr`, `Us:RxAlign` and `SFPSTATUS` it reads at start and pulse IDs in
    `PATT:GROUPS`; deadca on simxpm, below): its `programs` entry names the stand-in (`stand_in`) and holds one
    read per widget; one widget must show, after its first text (which may be the text the widget
    was built with: tprca's fields show `0` before their PV's value), 2 or more distinct values
    (texts with a digit: dtica shows `928.6154kHz`) of a PV under a prefix the stand-in serves,
    which is the `-P` of the stand-in's own log, listed by the same record
    (`its hsdpva entry reads the PVs of simhsd, but the record lists no log of simhsd`, `shows
    hsdpva read no live value of a PV simhsd serves (under ...)`). The partition prefix plays no
    part. The walk names a widget's PV by a `pv` on it or its parents, or (the witness's walks
    only, `bind_holders`: the parity check's rows stay as they were) by the object that holds the
    widget in its `fields` or `widgets` list and has a `pv` (pvatable's `PvBase`, which calls its
    `PvField` labels back; `PvDblArray`, which sets its labels). deadca's only values are the
    partition's `DeadFLnk`, one per link: the share of each second a real XPM held the group's
    L0s back because that link asserted full (its DRP past its pause threshold; pyxpm
    `pvstats.py` `GroupStats`). A healthy run has none, so while the walks run the cycle has
    fakecam_0's link assert full for 0.3 of every 1.3 s (`gui_witness.LINK_FULL`; simxpm's
    `SIM:LinkFull`, a sim-only PV, 0 by default), as a DRP whose readout stalls would, and puts it
    back to 0 after them. simxpm then holds the group's L0s back as an XPM does (they count in
    `NumL0Inp`, not `NumL0Acc`; fewer L1Accepts are recorded; transitions go through) and posts
    each second's held share in `DeadFLnk`, which differs from second to second because 1.3 s is
    not a whole second. The entry's `stimulus` says which link, its share and when.
  - a GUI that reads no PV (R5; daqstat, the Slurm job of each process of a daqmgr config): `up
    --gui` has simslurm hold a job for each process of `daq_sim.cnf` and answer daqstat's Slurm
    commands (shims first on the procmgr daqstat's PATH; in the walk, `psdaq.slurm.utils`'s
    `subprocess`); no Slurm controller is asked. Its `programs` entry (`"kind": "slurm"`) holds
    `refreshes`, the walk's record of each call of daqstat's table refresh slot with its time and
    rows (`[ID, Status]`), and `squeue`, the cycle's own squeue reads of simslurm every 0.5 s
    while the walk ran (`{t, jobs: {comment: state}}`), with `comment_prefix` (daqmgr's
    `x<xpm>_p<platform>_s<station>`). 2 or more refreshes within the run's L1Accepts must each
    show, for every row, the state the squeue read nearest in time (within 1.5 s) gave that
    process's job (`<comment_prefix>_<ID>`; COMPLETED when squeue lists none, as daqstat shows a
    job that ended), and at least one job squeue listed; and the rows of those refreshes must
    list every process whose procmgr log in the record names the run (`shows daqstat refreshed 1
    time(s) during the run with what an independent squeue read gave (2 or more needed): the
    refresh at ... shows control PENDING, squeue said RUNNING`, `shows daqstat listed no job of
    fakecam_0`).
  - a STAND-IN row whose stand-in's log does not name the run (R3, a PV server): the witness's
    `servers` entry for the stand-in (a client of the cycle read the stand-in's PVs while the run
    ran; a `programs` entry does not count): it passed, ran within the run's L1Accepts, read a
    PV under its own `prefix` with 2 or more distinct numbers, and its `interfaces` entry for the
    row's program gives `defined`, the PV names the program's source defines (more than 0), and
    `missing`, those the stand-in does not serve, empty (`simhsd does not serve 2 of the 40 PVs
    hsdpvs defines, e.g. ...`). For a C++ program the names are read from its sources:
    hsd134PVs's 44 (`gui_witness.hsd134pvs_names`: the files `meson.build` builds it from, its
    `PV_ADD`, `NPV`, `pvbase + "..."` and `sprefix` names for its 2 chips), all of which simhsd
    serves on the chips' prefixes; tprioc's 237 (`gui_witness.tprioc_names`: tprca.cc's
    `to_name(name, "...")`, the channels' for `TprBase::NCHANNELS`), which simtpr serves: tprcas's
    table and the 10 names tprioc adds to it.
  - a RUN row whose program is itself a PV server of the tree (R3b; bldcas and hpsdbuscas, which
    `up --pvservers` runs under procmgr as lab3-bld.cnf does, each on PVA ports of its own): a
    `servers` entry keyed by the program and marked `"program": true` (and no `programs` entry
    for it), judged as R3 with the program's own interface (`interfaces.<program>`: every name
    its source defines, from `bldcas.main()`'s table and hpsdbuscas's `PVAServer`, served), a
    `prefix` under the `-P` of the program's own log in the record (`its bldcas entry reads under
    DAQ:LAB2:HPSEX, which no listed log of bldcas serves (its -P: DAQ:SIM)`), and a PV under it
    with 2 or more distinct numbers: these servers hold set values, so the cycle's client puts the
    entry's PV to a new value and back while the run runs and reads it back each time (bldcas
    `HPSEX:PORT` 11001, 11002, 11001; hpsdbuscas `HPS:FIELDMASK`, with `PAYLOAD`'s type ID, which
    hpsdbuscas rebuilds for each mask, in `type_ids`).
  - a TPR program (R8, proposed; tprtrig and tpr_trigger, which `up --tpr` runs as srcf-rix.cnf and
    rix.py do, `tprtrig -t a -c 0 -o 1 -d 2 -w 10 -z` with procmgr's `-p <platform>` and
    `tpr_trigger -H tst -C localhost -t a -c 0 -o 1 -d 2 -w 10` as a `tpr` level process of the
    partition): each runs on a simulated TPR card of its own. With `PSDAQ_SIM_TPR=<dir>`,
    `tpr::Client` (`psdaq/psdaq/tpr/Client.cc`) maps the regular files `<dir>/tpra` (the
    card's register map, `TprReg`) and `<dir>/tpra<channel>` (its message queues) instead of the
    device files, and logs `Tpr::Client: simulated TPR (PSDAQ_SIM_TPR): /dev/tpra is <file>`; the
    registers keep what the program writes. Without the variable it opens `/dev/tpra` as
    before. Neither program logs a run, so while the run is Running the cycle reads each card's
    channel and trigger registers once a second (`gui_witness.tpr_reads`); the `programs` entry
    (`"kind": "tpr"`) holds the reads and the card. Coverage reads the card from the program's
    own log (`no listed log of tprtrig says tpr::Client mapped it`), computes what the program's
    `# CMDLINE:` programs from its source (`coverage.tpr_expected`: `TprBase::setupChannel` and
    `setupTrigger` as tprtrig.cc and TprTrigger.cc call them through `tpr::Client`; tpr_trigger's
    channel on the readout group control gives it at Connect, the partition's), and needs 2 or
    more reads within the run's L1Accepts, each with exactly those values (`shows tprtrig's card
    at ... with trigger0.delay 0x2, not the 0x3 its command line programs`).
  - every GUI or monitor row above (R2, R2b, R2c, R4, R5; not R8's TPR programs, lclsBldServer,
    the HPS chain or wave8pvs, which their own checks below cover) also needs
    procmgr's own instance of the
    program to have run through the run, not only cycle's offscreen copy of it. The record lists
    every procmgr log of the id since `up` (`# ID:`; a procmgr or procstat restart starts a new
    log), and between them they must name one child pid (`The PID of new child`) and no
    `Received a sigChild` (procServ saw the child end). procstat's entry holds two more tables
    that `cycle` reads with procstat in Configured, `before` (its walk ends before the run's
    BeginRun) and `after` (its walk starts after the EndRun), each with the pids `procmgr status`
    gave right after the walk (`procmgr_pids`). The id must be RUNNING in both and in the table
    read while Running, and its pid in `before` and `after` must be that one child pid
    (`procstat's table before the run shows procmgr's groupca SHUTDOWN, not RUNNING`, `procstat's
    table "after" was read from ... not after the run's EndRun`, `its procmgr logs of partca
    (partca, 2 listed) name 2 child pids`, `says procServ received a sigChild for process ...`,
    `procmgr status, read with procstat's table after the run, gives dtica pid ..., not the child
    pid ... its procmgr log names`). So a GUI killed, or restarted by `procmgr restart` or
    procstat's Restart button, at any time between `up` and the record does not count.
  - the values a GUI, monitor or client read must be ones their PVs' servers served while it
    read. Each stand-in (simxpm, simhsd, simtpr, simdti) logs every value it serves to
    `logs/<service>.served.jsonl` (`psdaq.sim.served_log`), which the record lists. A live read
    counts only if its PV is in such a log and every number it shows was served from the last
    post before the read's `start` to its `end` (2 s either side), to the precision the text
    shows (rounded or cut at its last digit, scaled by a `k`, `M` or `G` unit at its end) (`its groupca
    entry shows '1' for DAQ:SIM:XPM:0:PART:5:NumL0Acc, a value simxpm did not serve while groupca
    read`, `shows groupca read no live value of a PV a served-value log holds`, `the record lists
    no served-value log`). simhsd, simtpr and simdti start their counts at a random second, so
    another run's values do not fit this one's log. procstat's statuses, daqstat's Slurm states
    (R5), a TPR card's registers (R8), an R3b program's own PVs, lclsBldServer's packets, the HPS
    chain's packets and PVs (R9) and wave8pvs's own PVs (R6b) are not values a stand-in serves, so
    this rule does not apply to them (each has its own check, below). A served-value log counts only at
    `logs/<service>.served.jsonl` next to `logs/<service>.log`, a log the record lists, which runs
    the program the served log's first line names and whose `# PID:` line (`daq_sim up` writes it
    when it starts the service, and removes an older served log first) is the pid that first line
    gives (`served-value logs not counted: extra.served.jsonl: the record lists no log extra.log of
    the service that wrote it`). A served-value log stops at 64 MiB (`DAQ_SIM_SERVED_LOG_MAX`
    bytes; simdti's grows about 46 MB an hour) with a last line `{"t": ..., "capped": ...}`; a
    read after that time fails and says the log stopped at its cap.
  - what these rules catch: a forged witness or log that the record's hashes still match, as
    long as the forger did not also fit the run's other files to it: AMI matches whose seq or pixel
    the xtc2 file does not hold, GUI values no stand-in served while the GUI read, another run's
    witness or served-value log (alone it names no listed xtc2 file of the run, or its values were
    not served in this run), another run's files added to a record with that run's witness and logs,
    unchanged (every daq_sim run is tstx00001/r0001, so a record is one run by its BeginRun: its xtc2
    files of the run must all have the same BeginRun time, `its xtc2 files of run tstx00001/r0001
    have 2 different BeginRuns (...): a record is one run, so it cannot list another run's files`),
    a served-value log added beside the stand-ins' own, and a GUI killed or restarted between `up`
    and the record. The record is not signed, and what ties it to a commit is only its own `sha`
    field: a record written at another commit with only that field changed passes for every row it
    proved there, with no file touched. Nor do the rules catch a forger who also edits or adds a
    served-value log, takes AMI matches from the xtc2 file itself, or edits procstat's tables. Nor does it catch pids swapped consistently between two AMI
    processes in the witness and in their procmgr logs, or a GUI's reads moved or widened, within
    the run, to other values its server served.
  - the BLD server lclsBldServer (R8 and its packets): lab3-bld.cnf:52 starts it as
    `lclsBldServer -i enp1s0f1 -r 4`, a line from 572812c2d, when `-b` was ignored and `-a` gave
    the group; 27c997fae then made `-b` required (with no `-b` it prints its usage and exits 1,
    at HEAD too), fixed each type's group to the production 239.255.25.0-3 on port 12148 and
    dropped `-a`, and the cnf line was never updated. So `up --tpr` runs the cnf's command plus
    `-b ebeam` (the type its usage still names the default), with `-i lo` for the loopback
    interface and `-a 239.254.33.0 -p 31240+<p>`: options this branch adds to choose the group
    base (the type adds 0-3) and port, off the production network (without them the groups and
    port are as before: with no TPR, `strace` shows the same socket calls at base and head).
    Its card (`<workdir>/tpr/lclsbldsvc/tpra`) gets timing frames: `up` starts
    `psdaq.sim.tprframes`, which, for each channel a program enabled on a fixed rate, writes
    every pulse of that rate's marker into the channel's queue file as the driver would (the
    frame in `allq[gwp]`, its index in `allrp[ch]`, then `allwp[ch]`), at 1300/1.4 MHz / the
    marker's divisor (fixed rate 4: 102 Hz), each frame timed at its pulse and carrying the
    pulse ID simxpm gives that instant; `tpr::Client` polls a simulated card's queue file every
    1 ms (reading a file does not block as the device does). While the run is Running the cycle
    reads the card (as for tprtrig) and `gui_witness.bld_receive` joins 239.254.33.0 on
    127.0.0.1 (it refuses any group in 239.255.0.0/16) and keeps every packet; the `programs`
    entry (`"kind": "bld"`) holds the reads, the group and port, each packet's time, pulse ID
    and size, and the words after them. Coverage checks the card as R8 (channel 1 on the fixed
    rate `-r` selects, trigger 0 from channel 1) and then (`coverage.bld_problem`) that 10 or
    more packets came on the group and port the program's own `# CMDLINE:` sends to
    (`bld_expected`), each timed within the run's L1Accepts and after the one before, on the
    marker of its `-r` and at half its rate or more, with simxpm's pulse ID for that time, of
    the size and with the words lclsBldServer sends for its `-b` type, the pid in them the one
    its procmgr log gives (`its packets carry pid ..., but its log of lclsBldServer gives pid
    ...`).
  - the HPS BLD chain (R9: a stand-in for the HPS crate): lab3-bld.cnf starts `bldcas -P DAQ:LAB2
    <services>` (the BLD registry: each service's `:ADDR` and `:PORT`), `hpsBldServer -i eno2 -n
    DAQ:LAB2:HPSEX -p 0x1e0 -a 10.0.3.105` and `hpsBldCopy -i eno2 -I DAQ:LAB2:HPSEX -O
    DAQ:LAB2:<cp> -o 0`. `up --hps` runs the three under procmgr as `bldcas -P DAQ:SIM -A
    239.254.34.0 --port 31402+10<p> HPSEX HPSCPA`, `hpsBldServer -i lo -n DAQ:SIM:HPSEX -p 0x1e0
    -a 127.0.0.1 -r 31400+10<p> -d 31401+10<p>` and `hpsBldCopy -i lo -I DAQ:SIM:HPSEX -O
    DAQ:SIM:HPSCPA -o 0`: on the loopback interface, groups off the production network, and
    options this branch adds, each with the old value as its default (bldcas `--port`, 11001;
    hpsBldServer `-r`, the crate's register port, 8193, and `-d`, its diagnostic-bus port,
    8198). bldcas and hpsBldServer's own PVA server share a search port of their own (31404+10<p>;
    pvxs answers a search on a shared port from every server), which every client of the chain
    searches. hpsBldServer's crate is `psdaq.sim.simhps`, a service `up` starts: pyrogue's own
    RSSI server (`UdpRssiPack(server=True)`, `rogue.protocols.udp.Server` on every interface of
    the node, as R9 allows; the program addresses it by 127.0.0.1) with an SRPv3 responder on
    tDest 0 over a `rogue_dev` register store (seeds `seeds/hps.json` by register path, each
    write logged by path to `logs/simhps-writes.jsonl`; the paths come from HpsRoot's own tree,
    built in the stand-in on the same store), and a diagnostic bus on 127.0.0.1: once the
    program has sent its 4 bytes and while `BldControl.Enable` is 1 with a `channelMask` (what
    PVCtrls.update writes), it sends one BLD packet per pulse of fixed rate 4, 4 events 91
    pulses apart, each at the pulse ID simxpm gives its time. Running it at all needed
    production fixes, each for hardware too (base `b6f370d9f` against this branch, no simulated
    device: lab3-bld.cnf's command with `-i lo`, in a network namespace with no route, fails to
    connect to 10.0.3.105:8198 at both; on loopback, `-a 127.0.0.1`, both connect to port 8198,
    then base aborts and this branch sends RSSI to port 8193): pyhpsbld imported `psdaq.pyxpm.surf` and
    `psdaq.pyxpm.LclsTimingCore`, copies the tree dropped in d2d58210a and 04ac138c5, so at base
    `hpsBldServer` aborts at `hps_init`'s import in any env (`ModuleNotFoundError: No module
    named 'psdaq.pyxpm.surf'`); it now imports them from the cameralink-gateway submodules as
    pyxpm has since 04ac138c5; `hps_init` passed `serverPort`, which pyrogue 6's `Root` no longer
    takes; and that LclsTimingCore names the top 2 bits of the old 19-bit `DestSel` `DestType`,
    so `destSel()` writes the same register bits through either. hpsBldCopy dropped every packet
    of hpsBldServer (`id changed 0x8000 -> 0x0`): c41b8a44b made `HpsEventIterator` leave the
    packets' ID 0; it is the channel mask again (PAYLOAD's type ID, as hpsBldCopy compares).
    Not fixed, as they are: each event's payload after its `valid` word is its severity word,
    not its channel data (`HpsEvent::sevr` sits between `channels` and the data since
    c41b8a44b, and `publish` copies from `&ev.channels`), and `Pds::Bld::Server` writes the
    pulse ID before the time stamp, the other way round from drp_bld's LCLS-II layout
    (`BldDetector.hh`: `TimestampPos 0`, `PulseIdPos 8`), so hpsBldCopy's Client takes the time
    stamp for the pulse ID. While the run is Running the cycle (`gui_witness.hps_receive`)
    joins each program's output group on 127.0.0.1 (it refuses 239.255.0.0/16), keeps every
    packet with its source and the pids holding that source's socket (`udp_owner`,
    `/proc/net/udp`), and gets every PV name hpsBldServer's source defines under its `-n`
    (`hpsbld_names`: PVCtrls.run on a provider that keeps names); the `programs` entries
    (`"kind": "hps"`) hold them. Coverage (`coverage.hps_problem`) needs 10 or more packets on
    the group and port a bldcas of the record serves for the program's output service (its
    `-n`, or hpsBldCopy's `-O`), each from a socket held by the pid its procmgr log gives,
    every event's `valid` word the FIELDMASK hpsBldServer served; for hpsBldServer each
    packet's first event timed within the run's L1Accepts at the pulse ID simxpm gives that
    time, its ID the mask, its events within 4095 pulses and after the packet before, and
    its four PVs served with PAYLOAD's type ID the mask; for hpsBldCopy most of its events
    carrying the time of an hpsBldServer event (plus the pulse delta, as its Client gives it),
    within the run. As everywhere (the record is not signed: "what these rules catch", above), a
    witness rewritten and re-hashed would pass.
  - wave8pvs (R6b: another site env, its board simulated): lab3-wave8.cnf starts `wave8pvs --l 0`,
    which imports `rogue.hardware.pgp` (the DAQ env's rogue, 6.1.3, has none) and the wave8 package
    (in no env; the site keeps its source tarballs). `up --wave8pvs` runs it under procmgr as
    `<env>/bin/python -m psdaq.cas.wave8pvs --l 0 --dev sim://wave8pvs --base DAQ:SIM:WAVE8`, the
    env the one `$PSDAQ_SIM_WAVE8PVS_ENV` names (the entry's `env:` gives its `PATH`,
    `LD_LIBRARY_PATH` and a `PYTHONPATH` of the wave8 package's python and its submodules', which
    `up` unpacks from the tarball `$PSDAQ_SIM_WAVE8PVS_SRC` under `<workdir>/wave8pvs`, and this
    psdaq). Without both variables `up --wave8pvs` refuses, and `daq_sim matrix` leaves it out.
    On S3DF:
    `PSDAQ_SIM_WAVE8PVS_ENV=/sdf/group/lcls/ds/ana/sw/conda2/inst/envs/ps-4.5.16` (rogue 5.9.3) and
    `PSDAQ_SIM_WAVE8PVS_SRC=/sdf/group/lcls/ds/ana/sw/source_files/wave8-1.0.1.tar.gz`. No other
    pair runs: wave8-1.0.0's `RawBuffers.py` declares `OvflCntBuff[i]` a 32-bit `pr.Bool`, which
    pyrogue rejects (`The bitSize param of Model Bool must be 1`) in every site env whose rogue
    has `rogue.hardware.pgp` (5.9.3 in ps-4.5.16, 5.14.0 in ps-4.5.17 to 4.5.24, 5.16.0 in
    ps-4.5.26), and wave8-1.0.1's surf calls `get(read)` positionally, which 5.14.0 and 5.16.0
    reject (their `get` takes keywords only), so it needs 5.9.3. Its board is
    `psdaq.sim.rogue_dev`, installed in its process by `--dev sim://` (seeds `seeds/wave8pvs.json`:
    1.0.1's `Top.start` raises unless `AxiVersion.FpgaVersion` is its `FwVersionLock`); rogue_dev
    now writes its replies as a bytearray (rogue 5.9.3 takes no bytes there) and replaces Xilinx's
    Xvc only where rogue has one (5.9.3 has none). wave8pvs itself needed production fixes, each for
    hardware too (base `b6f370d9f` against this branch, no simulated device; `wave8pvs --l 0` in the
    DAQ env fails importing `rogue.hardware.pgp` at both): it called `Top.start(pollEn=..., initRead=..., timeout=...)`,
    which no rogue since 5 takes (a Root takes them when it is made; `start()` takes nothing), so
    with any site rogue it could not start once its board answered; and it passed `dataCapture`,
    which wave8 1.0.1's `Top` does not take (`TypeError` at `wave8pvs.py:66` at base with 1.0.1;
    with 1.0.0 both fail opening `/dev/datadev_0`, as before). `up` waits for its PV list. While
    the run is Running the cycle (`gui_witness.wave8pvs_entry`) gets every PV its log lists
    (pyrogue's `EpicsPvServer.dump()`, `<pv> -> <register path>`; 972 at 1.0.1) from it on its own
    PVA ports, finds the pids holding its PVA TCP port, and puts `Top:AxiVersion:ScratchPad` to
    0x5a5a and back, reading it back; its board logs each register write by path
    (`logs/wave8pvs-writes.jsonl`). Coverage (`coverage.pvs_problem`) needs a simulated device in
    its command line, every PV its own log lists under its `--base` served, its PVA port held by
    the pid its procmgr log gives, the put PV one its log lists with that register path, read
    back as 2 or more distinct numbers, each after the first one its board logged written to the
    register.
  `psdaq/psdaq/tests/test_sim_coverage.py` forges each of these (R1, R2, R2b, R2c, R3, R3b, R4,
  R5, R8, the procmgr instance, the served values, the BLD server, the HPS chain, wave8pvs) and
  checks the row's line says why.

So commit first, build, then run: after every new commit, the runs must be repeated.

Options:

| option | effect |
|---|---|
| `--repo DIR` | Checkout to check. Default: the checkout that holds the module, else the one that holds the current directory. |
| `--status FILE` | Another status file. |
| `--evidence DIR` | Another evidence dir. |
| `-v` | Show where each row comes from (`file:line`, or the configs that start it). |
| `--json` | Print the result as JSON. |

`daq_sim matrix` (§3p) is the one command for the whole hardware-free matrix: it runs every
detector type and the system features, which write the evidence, and then this check. Until every
row has a run, both commands end in FAIL.

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
`epixUHR`, `epixuhr3x2` (§3i), `jungfrau` (§3j), `epixhr2x2` (§3k), `tt` (§3l), the XpmDetector types
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

epixhr2x2 runs in a DAQ with it (§3k), and so does tt (§3l). The two need different values (with
both in one, tt's `tt_init` fails: `No module named 'lcls2_pgp_fw_lib.hardware'`), so `up --det <type>`
takes `PSDAQ_SIM_PYTHONPATH_<type>`, when set, as its `PSDAQ_SIM_PYTHONPATH` (`daq_sim.inherit_env`):
one environment then serves both, as `daq_sim matrix` needs (§3p). On hardware the same surf error
stops `tt_init`. Before 99cc4db8d neither type had the `<type>_connectionInfo(root, alloc_json)`
that `BEBDetector::connectionInfo` calls at Alloc. For tt, the one-argument `tt_connect(cl)`
has not matched the DRP's two-argument call since 3b829abf4, and d6b1e7552 renamed that call
to `<det>_connectionInfo`. For epixhr2x2, d6b1e7552 did add `epixhr2x2_connectionInfo`, and
668cb79e1 renamed it back to a one-argument `epixhr2x2_connect(base)`.

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

drp_gpu says `Ready for transitions` only after its CUDA start (cuInit, the GPU's context and
DMA buffers) and its detector's init, and control's rollcall finds only a DRP that has. So `up`
waits for that line in the DRP's newest procmgr log for every GPU type (`ready_s`, 300 s; it
prints `<type>_0 ready for transitions after <n> s`). On a GPU shared with another user's jobs
(persistence mode off) cuInit alone took 28 to 37 s in fresh processes, and before this wait three
GPU types missed rollcall (`drp/<type>_0 did not respond to rollcall`). If it never comes, `up`
fails with `<type>_0 not ready for transitions after 300 s: drp_gpu says it only after its CUDA
start ...`; time cuInit on the node in a fresh process to see whether the GPU is the cause:
`python -c "import ctypes,time; t=time.time(); ctypes.CDLL('libcuda.so.1').cuInit(0); print(time.time()-t)"`.

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
| epixuhr3x2 | `Drp::EpixUHR3x2`, as `drp -D epixuhr3x2` (§3i): `epixuhr3x2_config.py` against `rogue_dev`; at BeginRun `psdaq.configdb.epixuhr_calib` against `calibws_server` | the panel n, 336 x 576 uint16 as `MemPoolSim` frames it (tdest 3, §3i), 387168 B (`dmaBufSize` 0x70000) | `epixuhr3x2_noOp_0_0_0.calib` (336, 576): (bits 1-11 - pedestal) x 1/gain of the plane bit 0 selects, 0 for a bad pixel, with the stand-in's constants, vs `pattern(seed, n, i, 12)` |

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

**epixuhr3x2** (`daq_sim up --drp drp_gpu --det epixuhr3x2`) runs as `drp -D epixuhr3x2` does
(§3i): `Gpu::EpixUHR3x2` builds `Drp::EpixUHR3x2` on `MemPoolGpu`, whose `sim()` is the
`MemPoolSim`, and `EpixUHR3x2`'s own init installs `rogue_dev` (`BEBDetector::_simInstall`), so
the same seeds, config DB entry, store files, wait for its init (`ready_s`) and fault apply.
The GPU class adds a calibration the CPU one does not have: at BeginRun (u16 data, any alias but
CALIB) it fetches the panel's pedestals and gains for the serial number read at Connect through
`psdaq.configdb.epixuhr_calib`, which asks the calibration DB (`psalg.calibdb`, the web service at
`$LCLS_CALIB_HTTP/calib_ws`), and fails BeginRun without them. `up` starts
`calibws_server` for it on port `+7` and points the DRP's `LCLS_CALIB_HTTP` there (the
isolation's dead HTTP proxy would otherwise refuse the facility's service):
- for any `epixuhr3x2_<serial>` (here `epixuhr3x2_0000000000-0000000000-0000000000`, from the
  emulated board) it names the detector `epixuhr3x2_000001`;
- an experiment's database is empty; the detector's holds `pedestals`, `pixel_gain` and
  `pixel_status`, each (8, 1, 336, 576), valid for runs 0..end, functions of the seed, gain mode
  and pixel (`calibws_server.constants`): pedestals 25 to 124.75, gains 0.125 to 2, one pixel in
  1013 bad in gain mode 2;
- every request is a line of `logs/calibws.jsonl`; the DRP log says `Gpu::EpixUHR: loaded
  pedestals of <serial> for tstx00001 run <n>` (and `gain_factors`).

`xtc2_check` recomputes what the GPU must have applied: psana gain modes 0 and 1 for gain bit 0
and 1, 1/gain, and 0 for a pixel whose status is bad in any of modes 0-4 (as `epixuhr_calib` and
psana's default mask). Every pixel of every event must match, so constants that did not reach
the GPU, or a wrong plane, fail it. psana reads the recorded pixels as `epixuhr3x2_noOp_0_0_0`
(`psana/psana/detector/drpgpu.py`), a class this adds: without it psana had no class for what
`drp_gpu -D epixuhr3x2` records with the NoOpReducer (`'Container' object has no attribute
'noOp'`). The framer sends tdests 0, 2 and 3, which is all either DRP reads; `Gpu::EpixUHR3x2`
declares five sub-frames (tdest 1, the event, and 4, the ASICs' header, are not sent), so its
Reader warns `found 4 AxiStream Batcher sub-frames in 387168 bytes, expected 5`, which it treats
as not fatal (`Reader::checkBatcher`). Fault run:
`PSDAQ_SIM_ROGUE_FAULT=Root.ROS[0].FebFpga.App.TimingRx.TriggerEventManager.TriggerEventBuffer[1].TriggerDelay`,
as for drp (§3i).

## 3i. The digitizer, the ePixQuad 1 kfps and the ePixUHRs: hsd, epixquad1kfps, epixUHR, epixuhr3x2

`daq_sim up --det hsd|epixquad1kfps|epixUHR|epixuhr3x2`, then `daq_sim cycle` as in §3e.

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
- **epixuhr3x2.** Its DRP class (`EpixUHR3x2`) runs its own init instead of BEBDetector's; with a
  `sim://` device it installs `rogue_dev` the same way before importing `epixuhr3x2_config.py`, and
  takes its timing link from simxpm (`EpixUHR3x2: simulated device, link id 0x... from simxpm`).
  `epixuhr3x2_init` builds `epixuhr_3x2_readout_testing.Root`: the data C1100 card on the PCIe map
  and the front-end board behind SRPv3 (`seeds/epixuhr3x2.json`: the card's hardware type, the
  board's `RxId`). The card's management (axipcie `CmsSubsystem`, which `connectionInfo`'s `ReadAll`
  reaches) sits behind a surf `AxiLiteMasterProxy`, a firmware AXI-Lite master the host drives
  through `Addr`/`Data`/`Rnw` and polls `Done` on; `rogue_dev` emulates any such proxy (the access
  goes to a register store of its own and `Done` is set) and, behind it, the CMS firmware
  (`CmsFirmware`): a request the host writes into the mailbox and flags with `CONTROL_REG[5]` is
  answered in the mailbox with `HOST_MSG_ERR_REG` 0, and the bit clears at the host's second read
  after the request (the first is pyrogue's write-verify of the bit, which the card's MicroBlaze,
  slower than one register access, has not cleared yet); each QSFP cage's low-speed IO and I2C
  bytes keep what is written. The seeds give the mailbox's ready bit and map id. The config DB
  entry is `epixuhr3x2_config_store.beam_cdict()` (files from `psdaq.sim.epixuhr_files`, as
  epixUHR's) with `user.asic_enable` 0x3f: the panel's six ASICs. The store's own default, 0xf
  (its `numAsics` 4), fails at Configure with this firmware tree: `setup_bypasses_for_disabled_asics`
  writes 24 into `EventSeqMux[1].Bypass`, a 4-bit register (`EventFrameSequencerMux` with 4
  slaves), and rogue raises `Value range error for Bypass`.

| type | config entry points run | emulated device / stand-in | DRP data | psana check |
|---|---|---|---|---|
| hsd | `hsd_init` (`DrpPgpIlvRoot`, `hsd_unconfig` of A and B), `hsd_connect` (clock, QPLL, `TxLinkId`, `FEXOOR` age, `PADDR_U`, `MONPGP.remlinkid`), `hsd_config` (PGP resets, `READY`/`CONFIG` handshake twice, `MONTIMING`, buffers, `KEEPROWS`, `RESET.jesdclear`, `FWVERSION`), `hsd_unconfig` | `DrpPgpIlvRoot` seeds; `simhsdioc` | the TimingHeader's opaque words as the hsd event header (raw and fex streams, JESD ok), then a raw stream of 1160 12-bit samples and a fex stream of 44 words: 3 skip groups around 2 peaks | `hsd_raw_3_0_0` `waveforms()` every sample, `peaks()` every peak's start and samples |
| epixquad1kfps | `epixquad1kfps_init` (`DevRoot`, `ePixQuad.Top` with its PROM), `_connectionInfo`, `_config`, `_enable`, `_disable`, `_unconfig` | as epixquad, plus `Top.AxiPcieCore` image name and `FpgaVersion`, and the PROM's status byte | as epixquad | `epix10ka_raw_3_0_1` raw (4, 352, 384), every pixel, 14 bit |
| epixUHR | `epixUHR_init` (PgpMonitor, the camera `Root`, `ConfigLclsTimingV2`, the `RxId` wait), `_connectionInfo`, `_config` (PLL, ASIC gains, batchers), `_enable`, `_disable`, `_unconfig` | PgpMonitor KCU, `RxId` | 1: timing copy; 2-5: ASICs 0-3, each 168 x 192 12-bit pixels packed as the ASIC's 8 serial lanes send them (psana's descrambler run backwards) | `epixuhr_raw_*` raw (4, 168, 192) through its descrambler, every pixel, 12 bit |
| epixuhr3x2 | `epixuhr3x2_init` (the readout system's `Root`: PLL check, `ConfigLclsTimingV2`, power-up), `_connectionInfo` (`TxId`/`RxId`, `Stop`, `ReadAll` through the CMS mailbox, serial number), `_config` (power, bypasses, waveforms, ASICs, descramblers, gains, charge injection, trigger registers), `_enable`, `_disable`, `_unconfig` | C1100 hardware type, the AXI-Lite proxy and the CMS firmware, `RxId` | 2: timing copy; 3: the panel, 336 x 576 uint16 in row order | `epixuhr3x2_raw_1_0_0` raw (1, 336, 576), every pixel, 12 bit |

Fault runs that fail Configure and name the register: hsd `DrpPgpIlv.PcieControl.DevPcie.PgpQPllReset`
(rogue's write-verify when `hsd_config` pulses the QPLL reset), epixquad1kfps
`DevRoot.DevPcie.Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay`, epixUHR
`Root.App.TimingRx.TriggerEventManager.TriggerEventBuffer[1].TriggerDelay`, epixuhr3x2
`Root.ROS[0].FebFpga.App.TimingRx.TriggerEventManager.TriggerEventBuffer[1].TriggerDelay`.

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
| `tt_init` (`TimeToolKcu1500Root` start, `ConfigureXpmMini`, `ConfigLclsTimingV2`), `tt_init_feb`, `tt_connectionInfo` (99cc4db8d: the PGP link check, `TxId`, `RxId`), `tt_config` (`user_to_expert`, `config_expert` over registers and the camera's UART, `gcp`, `MasterEnable`, the firmware version), `tt_unconfig` | `PgpMon[0].RxRemLinkReady`, `XpmMessageAligner.RxId`; the Piranha4's console (every command `OK` and the `USER>` prompt, `gcp` its summary) | `tt_config_store` through its `write_to_daq_config_db` | 2: the camera's region of interest, 2048 uint8 pixels (tdest 1, the firmware's FEX results, is not produced: `TimeTool::_event` does not read it) | `tt_raw_2_0_0` `image()` (2048,) uint8 and `_info().image`, every pixel, 8 bit |

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
Config DB entries written by the old store keep the old names and must be written again
(`tt_config_store.py`). With 149eb4dee alone such an entry hung Configure instead of aborting:
`config_expert` set the camera's `ROI[0]` under rogue's own name, which sends no serial
command, and waited for a reply (`sleeping for cl.ClinkFeb.ClinkTop.ClinkCh.UartPiranha4.ROI[0]`
in the drp's log; control's `tt_0 did not respond to configure`, then to disconnect).
690b84618 makes `config_expert` refuse such an entry before it sets anything: the drp's log has
`ValueError: tt_config: the config DB entry has
expert.ClinkFeb.ClinkTop.ClinkCh.UartPiranha4.ROI[0], ROI[1], SAD[0], SAD[1], SAD[2], which
tt_config_store now writes as ROI0, ROI1, SAD0, SAD1, SAD2 (...): write the entry again with
tt_config_store.py, or rename those keys`, then `**** python error` and signal 6, as soon as
Configure reaches the DRP. Control still reports `tt_0 did not respond to configure` when its
60 s wait ends, as for any DRP that stops at Configure.

**Not fixed: the timetool's processing settings are skipped, on hardware as here.** The store
writes them under `expert.TimeToolKcu1500.Application.AppLane`: the raw-data and background
prescalers (`Prescale`, `Fex.background_prescaler`), the 8 FIR coefficient sets and
`LoadCoefficients`, the IIR time constant (`Fex.FrameIIR`) and background subtraction
(`Fex.FrameSubtractor`). lcls2_timetool names the lane `AppLane[%i]` (`_Application.py`), and
`tt_config`'s `rogue_translate` has no `AppLane` entry, so `config_expert` prints `Lookup failed
for node [AppLane] in path [cl.TimeToolKcu1500.Application]` at every Configure (the drp's log)
and writes none of them. The firmware keeps whatever those registers held. The one-line entry
(`'AppLane': 'AppLane[%d]' % lane`, as for `ClinkFeb`) is not added here. It would make
`tt_config` write these values to deployed timetools, which, with this release's
lcls2_timetool, it does not write today. Among them are a raw-data prescaler of 2 and
`LoadCoefficients` 1, which the store's own comment says crashes `pgpread_timetool.cc`. That
change needs the timetool's owners.

Fault run that fails Configure and names the register:
`TimeToolKcu1500Root.TimeToolKcu1500.Kcu1500Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay`
(rogue's write-verify when `config_expert` applies the trigger delay `user_to_expert` computes:
`Verify error for block ...TriggerEventBuffer[0].TriggerDelay ... Got: 0xff, Exp: 0x17`, then
`**** python error` and signal 6 in the drp's log).

## 3m. MEB, AMI and the system DRPs: `up --meb --ami --pva --epics --udp --gui`

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
| `--pvservers` | services (not procmgr) `simhsd -P DAQ:SIM:HSD:1_DA:A DAQ:SIM:HSD:1_DA:B`, `simtpr -P DAQ:SIM:TPR` and `simdti -P DAQ:SIM:DTI`, each on PVA ports of its own (31300 + 10 p + 0..5: simxpm stays the only server on the node's search port); under procmgr the tree's own PV servers `bldcas -P DAQ:SIM -A 239.254.32.1 HPSEX` and `hpsdbuscas -P DAQ:SIM:HPSCPA` (lab3-bld.cnf), on ports 31300 + 10 p + 6..9 (it serves the address, it sends nothing); with `--gui` also the GUIs on them (R4): `hsdpva DAQ:SIM:HSD:1_DA:A DAQ:SIM:HSD:1_DA:B`, `tprca DAQ:SIM:TPR` and `python -m psdaq.cas.dtica DAQ:SIM:DTI` (no `dtica` command; lab3-cam.cnf runs `launch_py <bins>/dtica.py`), offscreen, each with `EPICS_PVA_ADDR_LIST=127.0.0.1 EPICS_PVA_AUTO_ADDR_LIST=NO EPICS_PVA_BROADCAST_PORT=<its stand-in's search port>`, and `pvatable --bases DAQ:SIM:HSD:1_DA:A DAQ:SIM:HSD:1_DA:B --fields MONTIMING.trigcntsum ... MONRAWBUF.freeevt` (test-hsd.cnf) on simhsd the same way and `xpmpva DAQ:SIM:XPM:0` on simxpm | the stand-ins of `hsdpvs`, `hsd134PVs`, `tprcas`, `tprioc` and `dticas` (R3); bldcas and hpsdbuscas themselves (R3b) | while the run is Running, `psdaq.sim.gui_witness` gets from each stand-in every PV name the program's own source defines (hsdpvs's `ChipServer`, the tables `tprcas.main()` and `dticas.main()` build) and reads its monitoring counters (`MONTIMING`, `EVTCNT`, `3:TimFrRate`) once a second; the `gui_witness`'s `servers` entry is what coverage counts the STAND-IN rows `prog:hsdpvs`, `prog:hsd134PVs` and `prog:tprioc` (their names read from their C++ sources) and `prog:tprcas` from (no config starts `dticas`, so it has no row). From bldcas and hpsdbuscas it gets every name their source defines and puts one PV to a new value and back, reading it back (R3b). It walks hsdpva, pvatable, tprca, dtica and xpmpva offscreen once more, each searching only its stand-in (xpmpva: simxpm's own ports), and keeps each PV-bound widget's texts (one read per widget): their `programs` entries name the stand-in (R4) |
| `--tpr` | `tprtrig`: `tprtrig -t a -c 0 -o 1 -d 2 -w 10 -z -p <p>` (srcf-rix.cnf, flags `sp`); `enc_trig`: `tpr_trigger -H tst -C localhost -t a -c 0 -o 1 -d 2 -w 10 -p <p> -u enc_trig` (rix.py's `mono_enc_trig`, a `tpr` level process of the partition); `lclsbldsvc`: `lclsBldServer -i lo -r 4 -b ebeam -a 239.254.33.0 -p <31240 + p>` (lab3-bld.cnf:52 with the `-b` its source requires, on loopback, off the production network), each with `PSDAQ_SIM_TPR=<workdir>/tpr/<id>`; and the service `tprframes` (`python -m psdaq.sim.tprframes <workdir>/tpr/lclsbldsvc/tpra`) | a simulated TPR card each: `tpr::Client` maps `<workdir>/tpr/<id>/tpra`, a file, instead of `/dev/tpra` (§3d, R8); tprframes delivers the timing frames of lclsBldServer's card at the fixed rate its channel selects | while the run is Running, `psdaq.sim.gui_witness` reads each card's channel and trigger registers once a second and receives lclsBldServer's packets on 239.254.33.0 (loopback); coverage checks the registers against what each program's command line programs, and lclsBldServer's packets against its command line and the run |
| `--hps` | `hpsbldcas`: `bldcas -P DAQ:SIM -A 239.254.34.0 --port <31402 + 10 p> HPSEX HPSCPA`; `hpsbldsvc`: `hpsBldServer -i lo -n DAQ:SIM:HPSEX -p 0x1e0 -a 127.0.0.1 -r <31400 + 10 p> -d <31401 + 10 p>`; `hpsbldcpa`: `hpsBldCopy -i lo -I DAQ:SIM:HPSEX -O DAQ:SIM:HPSCPA -o 0` (lab3-bld.cnf, on loopback, off the production network); and the service `simhps` | hpsBldServer's crate, `psdaq.sim.simhps` (§3d, R9): an RSSI/SRPv3 register server and a diagnostic bus timed by simxpm's pulses | while the run is Running, `psdaq.sim.gui_witness` receives both programs' packets on 239.254.34.0 and .1 (loopback) with the pids that sent them and reads hpsBldServer's PVs; coverage checks them against the programs' command lines and the run |
| `--wave8pvs` | `wave8pvs`: `<$PSDAQ_SIM_WAVE8PVS_ENV>/bin/python -m psdaq.cas.wave8pvs --l 0 --dev sim://wave8pvs --base DAQ:SIM:WAVE8` (lab3-wave8.cnf, in a site conda env of its own, R6b), the wave8 package from `$PSDAQ_SIM_WAVE8PVS_SRC` unpacked under `<workdir>/wave8pvs`; PVA ports 31406 + 10 p and 31407 + 10 p | its board, `psdaq.sim.rogue_dev` in its process (§3d) | while the run is Running, `psdaq.sim.gui_witness` gets every PV its log lists and puts `Top:AxiVersion:ScratchPad` and back; coverage checks them against its log and its board's writes |
| `--gui` | `control_gui -H localhost -l DEBUG -u <config DB stand-in>`, `groupca DAQ:SIM 0 <p>`, `python -m psdaq.cas.partca DAQ:SIM:XPM:0:PART:<p>` (psdaq installs no `partca` command; lab3-cam.cnf runs it with `launch_py <bins>/partca.py`), `pvant --bases DAQ:SIM:XPM:0:PART:<p> --fields NumL0Acc NumL0Inp L0AccRate` and `procstat -p <p> -i 1 <WD>/daq_sim.cnf`, offscreen; `daqstat -i 1 <WD>/slurm/daqstat.py` (mfx.py: `daqstat -i 5`), offscreen, with `<WD>/slurm/bin` (simslurm's shims for squeue, sacct, scontrol, sinfo, sbatch, scancel) first on its PATH and `HOME=<WD>/slurm/home`; and the PV monitor `pvrtmon_0`: `epics_exporter -H tst -I xpm-0 -M <WD>/prom -P DAQ:SIM:XPM:0 NumL0Acc NumL0Inp RunTime`; and the service `simslurm`, a Slurm job for each process of `daq_sim.cnf` (`<WD>/slurm/daqstat.py`, daqmgr's config of them; state in `<WD>/slurm/state.json`) | control's status messages; simxpm's PVs; simslurm's jobs | control_gui logs the run's `fileReport` with its path relative to the data dir, which the record's `data_dir` resolves. groupca, partca, pvant and procstat never log a run: once the run is Running, `psdaq.sim.gui_witness` runs each GUI's own `main()` once more, offscreen, through the parity check's walk (`qt_walk --gui`, passive: event pumps only, nothing clicked or written), keeps every PV-bound widget's text after each pump, scrapes epics_exporter's Prometheus gauges (port from its log) once a second meanwhile, and writes the `gui_witness` witness (`logs/gui_witness.json`); `cycle` stays Running until the walks end and fails if a GUI showed no partition PV changing. daqstat's walk has its Slurm commands answered by simslurm and records each refresh of its table, while the cycle reads squeue from simslurm itself every 0.5 s (R5, §3d) |

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
    --pva --epics --udp --gui --pvservers --tpr --rate 100 --detach
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

## 3n. System features: `daq_sim feature a|b|c|d|e`

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
daq_sim feature d --hosts nodeA,nodeB     # two nodes of this job, run on nodeA (§3o); NOT AVAILABLE otherwise
daq_sim feature d --hosts nodeA,nodeB --break kill-remote-drp   # the DRP on nodeB killed while Running: FAIL
daq_sim feature a -w $WD --check-only --break drop-l1     # the checks can fail (no DAQ)
```

| feature | `up` options | the run | checks |
|---|---|---|---|
| a | `--det hrencoder --also epix100:<p+1> --also wave8:<p+1> --fixed-rate <p>:3 --fixed-rate <p+1>:4` | one cycle of `--events` (1000) L1Accepts of group p | hrencoder_0 (group p, 1.02 kHz marker), epix100_0 and wave8_0 (group p+1, 102 Hz): each DRP's DAQ count == psana2's events in its stream == events with its data, each passing the type's per-event check (`xtc2_check`); each group took its marker's share (group p+1 1/10 of group p's, within 10 %) |
| b | `--det tb --also epix100 --rate 100` | `python -m psdaq.cas.generic_timing_scan -p <p> -C localhost --detname epix100_0 --scantype timing --events <N> --record 1 --config BEAM --linear 700000 730000 10000`, from connected | psana2 reads 3 steps in tb's stream, `step_value` 700000, 710000, 720000 and a `step_docstring` naming each; each DRP has `--events` (200) L1Accepts in every step, all with data; each DRP's DAQ count == psana2's; every event passes its per-event check; `epix100_update` applied 700000, 710000, 720000 in order (its DRP's log) |
| e | `--pva --epics --udp --bld --rate 100` | one cycle | sysdrp_check reads drp_pva's, drp_udpencoder's, epicsArch's and drp_bld's data event by event; each system DRP's DAQ count == psana2's events in its stream; drp_bld's L1Accepts less its `bld_miss_count` == psana2's events with BLD data |
| c | `--ami --rate 100` (`--ami-src` passed on; §3m) | one cycle with `--ami-shot <WD>/ami-shot.png` | fakecam_0's DAQ count == psana2's events in its stream == events with its data, each passing the per-event check; the MEB served events (`MEB_EvtCt` > 0 and at least the events AMI kept); every event AMI computed from the MEB matches psana2's event with the same timestamp (`ami_check`: seq and pixel, at least 100 events, AMI's pixel sum == psana2's over them); a second `ami-client` showed the camera image while Running (the screenshot path is in the report) |
| d | `--hosts A,B --segments 2 --rate 100` (§3o): control, the TEB, simxpm and fakecam_0 on A, fakecam_1 on B | one cycle of `--events` (1000) L1Accepts | the cycle passed; each DRP's DAQ count (the L1Accepts simxpm sent its link) == psana2's events in its own stream (fakecam_1's: the stream whose Configure has segment 1, read through that segment) == events with its data, each passing the per-event check; while Running, `ss -tnp` on each host (on B in a step of the job there) shows established TCP connections to the other host owned by DAQ processes (`drp`, `teb`, `control`, `python3`). The report also gives each host's address, interface and processes, the step that ran procmgrd on B, and both hosts' EPICS lists. NOT AVAILABLE unless `--hosts` names two different hosts of this Slurm job's allocation (squeue's node list of `SLURM_JOB_ID`, expanded by `scontrol show hostnames`). `--break kill-remote-drp` (a live run, no `--check-only`) SIGKILLs fakecam_1 on B once Running (`cycle --kill-drp fakecam_1`, through a step on B) and must FAIL |

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

## 3o. Two nodes: `daq_sim up --hosts A,B`

`daq_sim up --hosts nodeA,nodeB [--segments N] [--also TYPE[:GROUP] ...]`, run in a Slurm step on
nodeA, brings up one partition over two hosts of the same Slurm job (`psdaq.sim.twonode`). Both
hosts must be in the job's allocation (squeue's node list of `SLURM_JOB_ID`), and neither may look
like a hutch or DAQ host. The hosts come from the command line and their addresses from the
resolver; no host name or address is written in the code.

- **Where things run.** nodeA runs control, the TEB, simxpm, the config DB and run DB stand-ins
  and `<det>_0`. nodeB runs `<det>_1` .. `<det>_<N-1>` (`--segments`, at least 2 when there is no
  `--also`) and the `--also` DRPs. The `.cnf` gives nodeB's entries procmgr's `host:` field, as a
  config over several DAQ hosts does (`<workdir>/daq_sim.cnf`).
- **How nodeB's processes start.** procmgr starts a remote host's processes through the procmgrd
  of the platform there (`procServ --allow ... 29000+100p /bin/tcsh -f`, as `procmgrd.init`
  starts it on a DAQ host). `up` starts it in a Slurm step of the same job on nodeB
  (`srun --jobid=$SLURM_JOB_ID --overlap -w nodeB python -m psdaq.sim.twonode hostd ...`). hostd
  writes `<workdir>/hosts/nodeB.json` (its address, interface, job and step), links procmgr's
  short log path on nodeB, starts procmgrd and waits. procmgr then starts, checks and stops
  nodeB's processes through procServ, as on a DAQ host.
- **Addresses and ports.** Every EPICS address list names nodeA's address only, since the PV
  servers (simxpm and control's) run there; nodeB's processes serve on nodeB's own address
  (`env:` in the `.cnf`). The auto address lists are off and the ports are sim_env.sh's
  (PVA 15075/15076, CA 15064/15065). procmgr sends the lists to nodeB (`PROCMGR_EXPORT`), each
  a single address, since it sends them as `setenv` lines to tcsh. simxpm's frames
  (`--frames`, `--bind`, with `--allow-remote`) and the config DB stand-in (`--host`) listen on
  nodeA's address. The run DB stand-in and control's `-X` socket stay on loopback, since only
  nodeA uses them. libfabric runs over tcp on each host's interface that holds its address
  (`ep_domain=<nic>`). `NO_PROXY` names both hosts. The DRPs on nodeB read simxpm's frames and
  the config DB on nodeA's address, and write their files under the work dir, which both hosts
  must share (S3DF: `/sdf/data`).
- **Down.** `daq_sim down` (or a failed `up`) runs procmgr stop. It then touches
  `<workdir>/hosts/nodeB.stop`, and hostd kills every process left in its step (its cgroup).
  hostd records what it killed and what was left, and the step ends. A step that does not end
  within 60 s is cancelled (`scancel <job>.<step>`), and `down` is then not clean. `down`
  prints `hostd on nodeB: step J.S ended; killed 2 process(es) of the step (... procServ, ...
  tcsh), left 0`.
- **Not yet.** `--meb`, `--ami`, `--pva`, `--epics`, `--udp`, `--bld`, `--gui`, `--pvservers`,
  `--tpr`, `--webgui` and `--fixed-rate` are refused with `--hosts`. preflight.sh runs on nodeA
  with sim_env.sh's loopback lists; it does not check the two-host lists.

`daq_sim feature d --hosts nodeA,nodeB` (§3n) runs it with `--segments 2` and checks it.
`daq_sim up --hosts A,B --dry-run` still prints the earlier plan (`multi_host_plan`: both
addresses in the lists, the `--also` DRPs on B). What `up --hosts` runs is the `.cnf` and
environment above. `test_sim_features.py` checks the host checks, the `.cnf` and the address
lists without a DAQ.

## 3p. The whole matrix, one command: `daq_sim matrix`

`daq_sim matrix` runs, unattended, a cycle of every detector type, one run of the programs (§3m),
the system features and the coverage check, and exits 0 only if every assertion passes. Run it in
one `srun` step on the node (a shell that cuts commands off needs `nohup` and a log, §1; AMI as
in §3m, from `--ami-src DIR` or `$DAQ_SIM_AMI_SRC`). Over two milano nodes and a GPU node
("Everything", below) it takes 24-33 min: 24.3-33.1 min in the six full checks of PR #42 and
26.7 min in the full check s1 at def58eaf8; on one node, that node runs every type itself:

```bash
# one srun step on the node (JOB, ROOT and WD as in §1 and §2)
srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=16 --mem=32G bash -c "
  cd $ROOT/lcls2 && source ./setup_env_daq.sh && source psdaq/psdaq/sim/sim_env.sh &&
  daq_sim matrix -w $WD/matrix --ami-src <AMI source tree>; echo MATRIX_EXIT=\$?"
```

It brings up one DAQ at a time, each in its own work dir under `-w`, and always takes it down:

| section | what runs, in `<WD>/...` | assertions (each named, each PASS or FAIL) |
|---|---|---|
| `types` | for each detector type: `daq_sim up --det <T> --detach` (`--rate 100` for jungfrau, its table's `rate`), one recorded `daq_sim cycle --events 1000`, `daq_sim down`, in `types/<T>` | `types/<T>/up`; `.../transitions` (every state read back as requested, no error message, back to the start state); `.../drp-alive` (the DRP `up` started is still alive after the run); `.../counts` (simxpm's L1Accepts == `TEB_WrtCt` == psana2's events == psana2's events with `<T>`'s data, all >= 1000); `.../per-event` (`xtc2_check` compared every event's data, through the type's own psana interface, with what the simulated device was set to send); `.../evidence` (the cycle wrote a record for `det:drp:<T>` that coverage accepts); `.../down` (`down: clean`) |
| `programs` | `daq_sim up --ami --pva --epics --udp --gui --pvservers --tpr --rate 100 --detach` (the MEB, AMI, drp_pva, epicsArch, drp_udpencoder with sim_udpencoder, control_gui, groupca, pvant, procstat, epics_exporter, daqstat on simslurm, and the PV-server stand-ins simhsd, simtpr and simdti with hsdpva, pvatable, tprca and dtica on them, xpmpva and deadca on simxpm, bldcas and hpsdbuscas, tprtrig and tpr_trigger on simulated TPR cards: §3m), one recorded `cycle --ami-shot programs/ami-shot.png`, `down`, in `programs` | as a type's, for fakecam_0, and `programs/checks`: the cycle's checks of the system DRPs, AMI against psana2, the GUIs' witness and the AMI screenshot all PASS; its `evidence` needs every row of the record accepted (these runs are the programs' evidence for coverage) |
| `features` | `daq_sim feature <x>` (§3n), x = a .. e, in `features/<x>` (c with `--ami-src`, d with `--hosts`) | `features/<x>` (`FEATURE <x> PASS`, exit 0), `features/<x>/down`. A feature `psdaq.sim.feature` cannot run here is `NOT AVAILABLE`, a failed assertion, and starts nothing: d (two nodes, §3o) unless `--hosts` names two hosts of this Slurm job |
| `coverage` | `daq_sim coverage` (§3d), after the runs above wrote their evidence | `coverage` (PASS: every row RUN, STAND-IN or N/A with valid evidence at HEAD) |

The types are every `det:drp` row that `coverage_status.json` marks RUN, in the order
`PGPDetectorApp.cc` registers them, then any other type `up --det` runs. A RUN row that `up --det`
cannot run fails as `types/<row>/runnable`: a `det:drp_gpu` row, unless `--gpu-host` runs the GPU DRP's
types (below). For each type the matrix
prints the line the coverage goal asks for:

```
TYPE epix100      node sdfmilan048 job 43839059 run <WD>/matrix/types/epix100/data/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2 DAQ 1018 psana2 1018 with-data 1018 per-event PASS PASS
```

The programs run prints the same line, `PROGRAMS fakecam ...`. The end is a summary: the type
lines, the programs line, one line per feature, coverage's counts, every assertion with
its detail, the failed ones again as `FAILED <name>: <why>`, and `MATRIX PASS` (exit 0) or
`MATRIX FAIL (k of n assertions failed)` (exit 1). The same is written as JSON to
`<WD>/matrix/matrix-summary.json` (`--summary FILE`): the per-type and per-feature results,
coverage's counts, every assertion and the runs.

| option | effect |
|---|---|
| `-w DIR` | Work dir of the whole matrix (each type's and feature's DAQ in a subdirectory, replaced by its next run). |
| `--only types\|programs\|features\|coverage` | Run only these sections (repeatable, or comma-separated). |
| `--ami-src DIR` | The AMI source tree of the programs run and of feature c (default: `daq_sim up`'s, `$DAQ_SIM_AMI_SRC`, else `ami-*` on PATH). |
| `--hosts A,B` | Feature d's two nodes; without two hosts of this Slurm job's allocation, d is `NOT AVAILABLE`. With `--locks`, the matrix runs over both (below). |
| `--locks LOCK_A,LOCK_B` | With `--hosts`: each host's lock file, a file on that host. LOCK_A takes `--lock`'s place on A; B's type runs take LOCK_B; feature d holds LOCK_A, then LOCK_B (`flock(1)` in a step on B), from its `up` to its `down`. |
| `--gpu-host G` | Run the GPU DRP's types (`daq_sim.GPU_SIM_TYPES`, the `det:drp_gpu` rows) on G, meanwhile: one more `daq_sim matrix --only types --drp drp_gpu` in a step on G of the Slurm job that holds G, in `<WD>/matrix/gpu/G`. Their lines are `TYPE drp_gpu:<T> node G ...`. drp_gpu finds the CUDA runtime through `$DAQ_SIM_CUDA_LIB` (§3h), which the step inherits. |
| `--gpu-job J`, `--gpu-gres R`, `--gpu-lock FILE` | With `--gpu-host`: G's Slurm job (default: the one `squeue` shows running there), the step's `--gres` (default `gpu:1`), and the lock file on G that each GPU DAQ holds from `up` to `down`. |
| `--types T,T` | Only these detector types (any of `up --det`). |
| `--features x,x` | Only these features. |
| `--events N` | L1Accepts of each type's cycle; default 1000. |
| `--lock FILE` | Take an exclusive `flock(2)` on FILE around each DAQ, from `up` to `down` of one type or one feature, and release it in between; for a node where several people's DAQs take turns (`flock(1)` takes the same lock). Default `$DAQ_SIM_MATRIX_LOCK`, else none. `--lock-timeout S` (default 3600). |
| `--repo`, `--status`, `--evidence`, `-v` | As for `daq_sim coverage`. |
| `-p P` | Platform; default 5. |

**Over two hosts.** `daq_sim matrix -w $WD/matrix --hosts nodeA,nodeB --locks LOCK_A,LOCK_B`,
run in a step on nodeA, shares the types between the hosts. Every other type goes to nodeB, where
one more `daq_sim matrix --only types --types ...` runs in a step of the job (`srun --overlap -w
nodeB`), in `<WD>/matrix/hosts/nodeB`, under LOCK_B. nodeA runs its own types meanwhile, under
LOCK_A. Their results join this run's, and each type line names its node. The programs run and
features a, b, c and e run on nodeA. Feature d runs over both hosts and holds both locks. Coverage
then reads the evidence of all of them; both hosts write to the same evidence dir
(`$DAQ_SIM_EVIDENCE`: `--evidence` alone does not reach the cycles), which they must share. The three deliberate breaks stay
separate commands (below).

```bash
# one srun step on nodeA (JOB, ROOT and WD as in §1 and §2); the lock files are each host's own
srun --jobid=$JOB --overlap -w nodeA --ntasks=1 --cpus-per-task=16 --mem=32G bash -c "
  cd $ROOT/lcls2 && source ./setup_env_daq.sh && source psdaq/psdaq/sim/sim_env.sh &&
  daq_sim matrix -w $WD/matrix --hosts nodeA,nodeB --locks /tmp/daq-a.lock,/tmp/daq-b.lock \
    --ami-src <AMI source tree>; echo MATRIX_EXIT=\$?"
```

**Everything, over every node of the campaign.** The one command, run in a step on nodeA: the types
shared between nodeA and nodeB, the GPU DRP's types on a GPU node G, the programs run and features a,
b, c and e on nodeA, d over both, then coverage over all their evidence. The programs run adds
wave8pvs with `$PSDAQ_SIM_WAVE8PVS_ENV` and `$PSDAQ_SIM_WAVE8PVS_SRC` set (§3m). tt and epixhr2x2 each need
their own `PSDAQ_SIM_PYTHONPATH` (§3e), given as `PSDAQ_SIM_PYTHONPATH_tt` and
`PSDAQ_SIM_PYTHONPATH_epixhr2x2`, which `up --det <type>` takes as its `PSDAQ_SIM_PYTHONPATH`; set no
plain `PSDAQ_SIM_PYTHONPATH`, which every type's `rogue_dev` would read:

```bash
# one srun step on nodeA; G is in a job of its own (GJOB), with a GPU (§3h); the lock files are each host's own
H='$SUBMODULEDIR/lcls2-epix-hr-pcie/firmware'; E='$SUBMODULEDIR/epix-hr-single-10k'
srun --jobid=$JOB --overlap -w nodeA --ntasks=1 --cpus-per-task=16 --mem=32G bash -c "
  cd $ROOT/lcls2 && source ./setup_env_daq.sh && source psdaq/psdaq/sim/sim_env.sh &&
  export DAQ_SIM_CUDA_LIB=$CUDA/targets/x86_64-linux/lib &&
  export PSDAQ_SIM_WAVE8PVS_ENV=<site conda env> PSDAQ_SIM_WAVE8PVS_SRC=<wave8 source tarball> &&
  export PSDAQ_SIM_PYTHONPATH_tt='\$SUBMODULEDIR/lcls2-pgp-pcie-apps/firmware/submodules/surf/python' &&
  export PSDAQ_SIM_PYTHONPATH_epixhr2x2=\"$H/python:$H/submodules/surf/python:$H/submodules/axi-pcie-core/python:$H/submodules/lcls2-pgp-fw-lib/python:$H/submodules/lcls-timing-core/python:$H/submodules/l2si-core/python:$E/firmware/python:$E/software/scripts:$E/firmware/submodules/epix-hr-core/python\" &&
  daq_sim matrix -w $WD/matrix --hosts nodeA,nodeB --locks /tmp/daq-a.lock,/tmp/daq-b.lock \
    --gpu-host G --gpu-job $GJOB --gpu-gres gpu:<type>:1 --gpu-lock /tmp/daq-g.lock \
    --ami-src <AMI source tree>; echo MATRIX_EXIT=\$?"
```

**Restart.** A section, a type or a feature can be re-run alone, e.g. after fixing one type:
`daq_sim matrix -w $WD/matrix --types epix100`, then `--only coverage`. The exit code is the
verdict of what ran. The JSON keeps, for what did not run, the last result at the same HEAD
(`"carried": true`, with its time); its `whole` entry is the verdict over all of it (`not run`
lists what has no result at this HEAD; `stale` says coverage ran before a later run).

**Deliberate breaks.** `--break KIND` runs one type in `<WD>/break-<KIND>` (its own summary, no
feature, no coverage, no evidence) with a fault that must make the matrix fail, and the summary
names the failed assertions:

| `--break` | type (`--types` to change) | the fault | fails |
|---|---|---|---|
| `register` | epix100 | `PSDAQ_SIM_ROGUE_FAULT=ePixBoard.ePix100aFPGA.EpixFpgaRegisters.DaqTriggerDelay` in the DAQ's environment: `rogue_dev` reads that register back wrong, so `epix100_config` fails Configure (`--fault` for another register; the types with a known register are in `matrix.FAULTS`, from §3e and §3g) | `transitions` (`epix100_0 did not respond to configure`, and the DRP log's `FAULT ... DaqTriggerDelay ... reads back` and rogue's `Verify error for block ...DaqTriggerDelay`), `drp-alive` (the DRP exits after the failed Configure, as on hardware), so no run: `counts`, `per-event`, `evidence`; `up` and `down` pass |
| `kill-drp` | fakecam | `daq_sim cycle --kill-drp`: SIGKILL the DRP once Running, after its first L1Accepts | `drp-alive` (gone), `transitions` (`fakecam_0 did not respond to disable`; the run stays Running), `counts` (simxpm's L1Accepts against the TEB's and an empty file: the DRP never wrote it), `per-event` (no event), `evidence`; `down` still passes (`down: clean`) |
| `corrupt` | fakecam | `PSDAQ_SIM_CORRUPT_SEQ=500` (`--events` / 2): `MemPoolSim` inverts one byte of that L1Accept's payload (the middle byte of its largest data subframe for a BEB type, of its TDet words or message otherwise; `drp_sim_frame` makes the same buffer; the DRP logs `byte 160 of 288 inverted`) | `per-event` only, and so `evidence`: every count agrees, and `xtc2_check` names the event and the word (`event 500: payload pattern broken: 1 of 60 payload words differ, first lane 0 w32 ...`) |

```bash
daq_sim matrix -w $WD/matrix --break register; echo MATRIX_EXIT=$?    # 1
daq_sim matrix -w $WD/matrix --break kill-drp; echo MATRIX_EXIT=$?    # 1
daq_sim matrix -w $WD/matrix --break corrupt; echo MATRIX_EXIT=$?     # 1
```
`PSDAQ_SIM_ROGUE_FAULT` and `PSDAQ_SIM_CORRUPT_SEQ` act only on a `sim://` device; a run without
`--break` removes them from the DAQ's environment.

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
4. Any process of yours whose environment carries `DAQ_SIM_WORKDIR=$WD`, such as the caRepeater that libca spawns, or
   a second `daq_webgui` started with that tag (`psdaq/psdaq/webgui/README.md`, "Parity with the other PyQt GUIs";
   one started without it keeps running: stop it yourself).

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
  - psana2 (`xtc2_check`, §4) on a GPU node (seen on sdfada011): Open MPI's `shmem: mmap: an error
    occurred ... /lscratch/.../shared_mem_cuda_pool...` and `create_and_attach: unable to create
    shared memory BTL coordinating structure`. psana2 runs as one process and does not use them;
    the check's result line is what counts.
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
- **Partition size.** One node. Up to three PGP DRPs of different types (`--also`, §3n) or four
  segments of one type, one lane each. Rates above about 1 kHz are untested; simxpm ticks at
  most at 2 kHz, so fixed-rate markers faster than 1.02 kHz keep `--rate`. Two nodes (§3o):
  control, the TEB and PGP DRPs only (no MEB, AMI, system DRPs or GUIs yet), one host's address in
  the EPICS lists.
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
  `# CMDLINE:`). The walk reads the same PVs with the same argv, while the run runs. The
  deadtime deadca shows is deadtime the cycle causes on purpose (simxpm `SIM:LinkFull`, §3d): no
  DRP of these runs stalls by itself. xpmpva runs too (`up --gui --pvservers`, R4): at startup it
  reads `<xpm>:Us:RxAlign` and `<xpm>:Cu:RxAlign` (and exits on the timeout without them), which
  simxpm now serves.
- **PVA servers.** A unicast PVA search reaches only one of the sockets bound to the node's
  search port (15076), so simxpm is the only PVA server on it: the stand-in IOC is CA only, and
  ami-client's own PVA server gets ports 31210 + 2 p and 31211 + 2 p. With two PVA servers on
  15076, drp_pva's PV once failed to connect within its 3 s at Configure.
- **System DRPs.** drp_pva records one camera PV that simxpm updates for every L1Accept; drp_bld
  records simxpm's BLD source (`--bld`, §3n), one packet per L1Accept tick on loopback
  multicast. drp_pva takes PV updates only once it has handled Enable, and at the default 1 kHz
  its PVA monitor fell behind for the first ~50 L1Accepts of a run (they were recorded without
  the image); run `--pva` at `--rate 100`, near a camera's rate, as §3m does. Even then an update
  can miss its L1Accept (2 of 1119 in one run); the check counts them and requires drp_pva's own
  count to agree. drp_pva's monitor (`MonTracker`) drops an update that arrives while its
  constructor still runs (`shared_from_this()` throws `bad_weak_ptr`), and pvAccessCPP then
  signals no later update, since the monitor's queue never empties; on loopback, with drp_pva's
  TCP link to simxpm already up, the camera PV's first update came within 1 ms, so drp_pva
  sometimes waited out its 3 s at Configure ("PV DAQ:SIM:CAM:IMAGE hasn't connected"). simxpm's
  camera PV therefore opens 0.25 s after a client's first channel and closes after its last. Those counters are per process, so compare them in the first cycle after `up`. epicsArch archives two CA PVs of a softIoc on loopback and one PVA PV of simxpm. sim_udpencoder sends the
  100/200 test pattern only (no `-f` playback in the run).
- **Web GUI.** It listens on 127.0.0.1 only and refuses non-loopback endpoints. Its events number
  comes from simxpm's counter, not from the recorded file; `daq_sim e2e` checks the two against
  each other. A tunnel to it through sdfiana025 was tested (§3b), not the `-J` form. The e2e covers one run of one detector
  at 1 kHz, platform 5.
- **Web GUI requests.** It answers 403 to any request whose Host header is not loopback, and to a
  POST whose Origin is another host:port (`webgui/tests/test_webgui_hostorigin.py`). It does not
  refuse `Origin: null`; a browser page with that origin still cannot send it a command, because
  the server takes only `Content-Type: application/json` (other types: 415) and answers no CORS
  preflight (OPTIONS: 501). It has no authentication: any process on the node that can reach
  127.0.0.1 can drive the DAQ through it.
