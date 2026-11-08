# Hardware-free lcls2 DAQ on one S3DF milano node: runbook

This runbook takes a fresh checkout to one recorded run with no hardware. The run uses a
simulated timing source (`simxpm`, which stands in for the XPM), one simulated detector DRP
(`drp -D fakecam -d sim://`), the TEB and the DRP's file writer. procmgr and control.py
(normal mode) run it, as they do in a hutch. The config DB and the run DB (eLog) are
campaign-local stand-ins on 127.0.0.1. Then it reads the xtc2 file back with psana2 and
takes everything down.

Everything in `psdaq/psdaq/sim/`:

| file | role |
|---|---|
| `daq_sim.py` (console script `daq_sim`) | `up` / `status` / `cycle` / `down`: the one command |
| `sim_env.sh` | Isolation env. EPICS CA and PVA stay on loopback, on ports 15064/15065/15075/15076. HTTP(S) goes to a dead proxy at `http://127.0.0.1:9`. Production credentials are emptied. `FI_PROVIDER=tcp`. `daq_sim` sources it itself. |
| `preflight.sh` | Fail-closed check that `daq_sim up` runs first. It must print `PREFLIGHT PASS`. |
| `configdb_server.py`, `configdb_seed.py` | Config DB stand-in, seeded with `tst/BEAM/tmoteb_0` (persistValue 0xdeadbeef) and `tst/BEAM/fakecam_0` (`user.sim_seed`). |
| `lgbk_server.py` | Run DB / eLog stand-in. Experiment `tstx00001`; runs are numbered from 1. |
| `simxpm.py` | Software XPM: the pyxpm PVs over PVA, timing frames to `sim://` DRPs, and the `control -X` PULL receiver. |
| `xtc2_check.py` | psana2 read-back with a per-event payload check. |
| `procmgrd.s3df.conf` | procmgr rcfile for S3DF: the rhel9 procServ. |

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

Set the cache variables if uv or pip hangs on /sdf/data.

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
| `-S <Hz>` | control's SlowUpdate rate; default 1. |
| `-v` | Run teb and drp with -v. |

If anything fails, `up` prints the reason, takes down what it started, and exits 1.

Ports for platform p; p = 5 gives the values in brackets:

| port | what |
|---|---|
| 31000+10p (31050) | config DB stand-in |
| +1 (31051) | run DB stand-in |
| +2 (31052) | simxpm frames |
| +3 (31053) | reserved for the web GUI |
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

It prints the transitions with their timestamps, then a count table. Expected end:
```
  simxpm NumL0Acc        <N>
  TEB_WrtCt              <N>
  psana2 events          <N>
  psana2 with data       <N>
  psana2 checks          PASS
  equal (simxpm NumL0Acc == TEB_WrtCt == psana2 events) >= 1000: True
... cycle PASS
CYCLE_EXIT=0
```
`cycle` exits 1 on any of these:
- a state that does not read back,
- an `error` message on control's status stream,
- counts that are not equal,
- a failed psana2 check,
- not ending in the start state.

`daq_sim status -w $WD` shows the processes, control's state, simxpm's counts and the Prometheus counters.

To drive by hand, use `daqstate -p 5 -P tst -C localhost --state <state>` (`--record 1` before beginrun). **daqstate exits 0 even when a transition fails**, because control answers setstate before it runs the transition. Always read the state back (`daqstate -p 5 -P tst -C localhost`) and check `$WD/pmlogs/*/*/*control.log`.

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
1. `procmgr stop` for control, teb0 and fakecam_0.
2. The PIDs that `up` recorded: simxpm, the run DB and the config DB.
3. Any process of yours whose environment carries `DAQ_SIM_WORKDIR=$WD`, such as the caRepeater that libca spawns.

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
- `$WD/pmlogs/<yyyy>/<mm>/<dd_HH:MM:SS>_<host>:<id>.log`: the control, teb0 and fakecam_0 logs. Expected lines:
  - drp: `Simulated PGP device 'sim://127.0.0.1:31052'`
  - drp: `MemPoolSim: simxpm registered fakecam_0 as XPM 0 link 0`
  - drp: `EbLfClient: libfabric 2.1.0, provider 'tcp' ..., domain 'lo'`
  - drp, at Configure: `Sim payload seed 4660 (0x00001234) from configdb BEAM/fakecam_0`
  - drp: `Opening file '.../xtc/tstx00001-r0001-s000-c000.xtc2'`
  - teb: `EbLfServer: libfabric 2.1.0, provider 'tcp'`
- Harmless lines:
  - drp/teb: `<C> Inadequate RTPRIO limit: got 0, require 99`, at critical level but non-fatal.
  - control: `<W> ami NOT supported in absence of MEB`.
- SlowUpdates exist only in state running, by control.py's design. At `-S 1` the xtc2 holds about one per second of running.
- `$WD/data/tst/tstx00001/xtc/` holds the xtc2 files, with `smalldata/` beside them.

## 7. Known limits
- **Network listeners.** Every connection is between 127.0.0.1 peers (checked with `ss -tnp` during a run). But some processes listen on all interfaces:
  - control's ZMQ on `*`;
  - the Prometheus exporters on `0.0.0.0:92xx`;
  - procServ `--allow`;
  - pvAccess UDP 15076.

  Isolation relies on every peer being on this node and on the non-default EPICS ports.
- **HTTP.** The node has an IP route to pswww. The dead proxy stops only HTTP clients that honour the proxy env.
- **Partition size.** There is one detector DRP and one lane. Rates above about 1 kHz are untested.
- **Web GUI.** The web GUI is not part of this runbook yet; port +3 is reserved for it.
