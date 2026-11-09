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
| `simxpm.py` (`simxpm`) | Simulated XPM: serves the pyxpm PVs control.py writes (p4p, loopback), the `control -X` ZMQ PULL receiver, and an ordered, credit-flow-controlled timing frame stream (ZMQ ROUTER) to each simulated DRP. |
| `daq_sim.py` (`daq_sim`) | The one command: `up` starts the stand-ins, simxpm and, through procmgr, control (normal mode), the TEB and `drp -D fakecam -d sim://` (and with `--meb`, `--ami`, `--pva`, `--epics`, `--udp`, `--gui` the MEB, AMI, the system DRPs and PyQt GUIs, RUNBOOK §3g); `cycle` drives one run to Running and back and checks the counts; `status`; `down`. |
| `xtc2_check.py` | psana2 read-back of a run's xtc2 file with a per-event payload check. |
| `ami_check.py` | `daq_sim up --ami`: gives AMI a graph that keeps each event's timestamp, seq and one fakecam pixel, fetches it from AMI's manager and checks it against psana2 event by event. |
| `sysdrp_check.py` | psana2 read-back of every stream of a run with drp_pva (`--pva`), epicsArch (`--epics`) or drp_udpencoder (`--udp`), each event checked against what its simulated source sent. |
| `coverage.py`, `coverage_status.json` | `daq_sim coverage`: enumerates every detector type a DRP factory registers and every program a procmgr config under `psdaq/psdaq/cnf` starts, and checks that each is RUN, STAND-IN or N/A, with evidence recorded at HEAD. `daq_sim matrix` runs it (RUNBOOK §3d). |

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
