# psdaq.sim — pieces for running the DAQ with no hardware

This package holds what a hardware-free lcls2 DAQ needs on a single compute
node: a simulated timing source in place of the XPM, a simulated detector
DRP, local stand-ins for the config DB and the run DB, and isolation checks.
**To run it, follow [RUNBOOK.md](RUNBOOK.md).**

| File | What it is |
|---|---|
| `configdb_server.py` | Config DB stand-in: serves the HTTP commands `psdaq.configdb.configdb` sends, from a JSON file, with `mongoconfigdb` semantics (versioned keys, aliases, history). Binds 127.0.0.1. |
| `configdb_seed.py` | Seeds the stand-in with what Configure needs: `<inst>/BEAM/tmoteb_0` (the trigger config control.py fetches; `persistValue` 0xdeadbeef, the value libtmoTeb writes for an event to be recorded) and `<inst>/BEAM/fakecam_0` (`user.sim_seed`, `expert.sim_length`). Refuses non-local URLs. |
| `lgbk_server.py` | Run DB / eLog stub: answers the 7 calls control.py makes in normal mode (active experiment, current run, start/end run, run parameters, parameter descriptions, register file) and logs each call to a JSONL file. Binds 127.0.0.1. |
| `sim_env.sh` | Isolation environment. Source it after `setup_env_daq.sh`: it drops production credentials, keeps EPICS CA and PVA on loopback with non-default ports, sends HTTP(S) through a dead proxy so a stray facility URL fails, and pins libfabric to `tcp`. |
| `preflight.sh` | Fail-closed check, run on the compute node: no DAQ devices present, HTTPS to pswww fails, production-looking PVs time out, and a loopback PV works. Exit 0 = isolated. |
| `procmgrd.s3df.conf` | procServ rcfile for `procmgr -r` on S3DF Rocky 9 nodes, where procServ is not on PATH. |
| `simxpm.py` (`simxpm`) | Simulated XPM: serves the pyxpm PVs control.py writes (p4p, loopback), the `control -X` ZMQ PULL receiver, and an ordered, credit-flow-controlled timing frame stream (ZMQ ROUTER) to each simulated DRP; with `--fixed-rates` each readout group on its fixed-rate marker, with `--bld` an LCLS-II style BLD source on loopback multicast (RUNBOOK §3i). |
| `daq_sim.py` (`daq_sim`) | The one command: `up` starts the stand-ins, simxpm and, through procmgr, control (normal mode), the TEB and `drp -D fakecam -d sim://` (and with `--meb`, `--ami`, `--pva`, `--epics`, `--udp`, `--gui` the MEB, AMI, the system DRPs and PyQt GUIs, RUNBOOK §3h; with `--also`, `--fixed-rate`, `--bld` DRPs of other types in other readout groups and drp_bld, §3i); `up --hosts A,B --dry-run` prints a two-node plan (§3j); `cycle` drives one run to Running and back and checks the counts; `status`; `down`. |
| `xtc2_check.py` | psana2 read-back of a run's xtc2 file with a per-event payload check. |
| `ami_check.py` | `daq_sim up --ami`: gives AMI a graph that keeps each event's timestamp, seq and one fakecam pixel, fetches it from AMI's manager and checks it against psana2 event by event. |
| `gui_witness.py` | `daq_sim up --gui` + `cycle`: runs groupca and pvant once more offscreen (through `qt_walk`) while the run is Running and writes the witness of the partition PVs they showed changing, which `daq_sim coverage` reads for their rows. |
| `ami_shot.py`, `qtgrab/sitecustomize.py` | `daq_sim cycle --ami-shot PNG`: a second `ami-client`, offscreen, loads a viewer of the camera image while the run is Running; `qtgrab` (on that client's `PYTHONPATH` only) saves its windows to PNG. |
| `sysdrp_check.py` | psana2 read-back of every stream of a run with drp_pva (`--pva`), epicsArch (`--epics`), drp_udpencoder (`--udp`) or drp_bld (`--bld`), each event checked against what its simulated source sent. |
| `feature.py` | `daq_sim feature a\|b\|c\|d\|e`: one run per system feature, end to end, with its checks and report: readout groups at different rates (a), a scan through `psdaq/psdaq/cas/generic_timing_scan.py` (b), the MEB serving events to AMI with AMI's own GUI showing the camera (c), two nodes (d: NOT AVAILABLE unless `--hosts` names two hosts of the Slurm job; then the plan, and FAIL: a plan only), drp_pva, drp_bld, drp_udpencoder and epicsArch with a PGP DRP (e); `--check-only --break` shows each check can fail (RUNBOOK §3i). |
| `simhsdioc.py` (`python -m psdaq.sim.simhsdioc`) | The PVs and IOC of a simulated hsd: hsdpvs's PVs, and what hsd134PVs does with them as far as `hsd_config.py` reads it back (`READY` after a `CONFIG` put, `MONTIMING`, `FEXOOR` every second, the card's link id in `MONPGP`); `daq_sim up --det hsd` starts it. Binds 127.0.0.1. |
| `epixuhr_files.py` | Simulated PLL tables and pixel maps for the ePixUHR config stores (`EPIXUHR_CONFIG_DIR`); `daq_sim up --det epixUHR` writes them. |
| `simsls.py` | Stand-in for a Jungfrau module's slsDetector servers: serves the slsDetectorPackage 9.0.0 protocol `Drp::Jungfrau` drives its modules with (`sls::Detector` at `slsHosts`), on loopback, and sends each frame as the module's 128 UDP packets on a trigger from `MemPoolSim` (`daq_sim up --det jungfrau`, RUNBOOK §3j). |
| `coverage.py`, `coverage_status.json` | `daq_sim coverage`: enumerates every detector type a DRP factory registers and every program a procmgr config under `psdaq/psdaq/cnf` starts, and checks that each is RUN, STAND-IN or N/A, with evidence recorded at HEAD whose files show the row ran: the xtc2 file of the record's run has the type's detector in its Configure and its data in at least 1000 L1Accepts, and the program's log names the run (RUNBOOK §3d). |
| `matrix.py` | `daq_sim matrix`: the whole matrix in one command, unattended: one DAQ per detector type (up, a recorded cycle of 1000 L1Accepts, down) with named assertions on its transitions, its DRP, its counts against psana2's, the per-event check and its evidence; one run of the programs (`up --ami --pva --epics --udp --gui`, its checks and the AMI screenshot); `daq_sim feature a`..`e`; then coverage; exit 0 only if every assertion passes, and a JSON summary. `--break register\|kill-drp\|corrupt` shows it failing (RUNBOOK §3k). |

The DRP side is `psdaq/drp/MemPoolSim.{hh,cc}`: started with `-d sim://<host>:<port>`, the DRP takes its DMA buffers from simxpm's frame stream instead of a PGP card. The fakecam payload of each L1Accept carries the pulse ID, simxpm's L1 sequence number and `sim_seed` read from the config DB at Configure, so a reader can check every event.

## Use

On a compute node (S3DF: inside a milano allocation, `srun --jobid=<id> --ntasks=1 --cpus-per-task=<n> --mem=<m>G ...`):

```bash
source ./setup_env_daq.sh
source psdaq/psdaq/sim/sim_env.sh
bash psdaq/psdaq/sim/preflight.sh            # expect: PREFLIGHT PASS, exit 0

python -m psdaq.sim.configdb_server --store /tmp/$USER-configdb.json --port 0 &   # prints CONFIGDB_URL=...
python -m psdaq.sim.configdb_seed --url http://127.0.0.1:<port>/ws/
python -m psdaq.sim.lgbk_server --state /tmp/$USER-lgbk.json --log /tmp/$USER-lgbk.jsonl &  # prints LGBK_URL=...
```

Then point the DAQ at them: `control -d http://127.0.0.1:<port>/ws/configDB --url http://127.0.0.1:<port>/ ...`
(`--url` must end in `/`). Use plain `http://` URLs: `configdb.py` adds credentials only to `ws-auth`/`ws-kerb` URLs.

## Known limits

- The isolation relies on the dead proxy and on every URL being local. The node may still have a network route to facility hosts.
- pvAccess may bind its UDP search port on the node's NIC despite `EPICS_PVAS_INTF_ADDR_LIST`. The non-default ports keep production clients and servers from meeting it.
- ZMQ (control.py) and Prometheus exporters listen on all interfaces. Every peer must be started on the same node with local addresses.

Tests: `pytest psdaq/psdaq/tests/test_sim_configdb.py psdaq/psdaq/tests/test_sim_lgbk.py psdaq/psdaq/tests/test_simxpm.py psdaq/psdaq/tests/test_sim_coverage.py`.
