# psdaq.sim — pieces for running the DAQ with no hardware

This package holds what a hardware-free lcls2 DAQ needs on a single compute
node. This first part provides the campaign-local stand-ins and the isolation
checks. Later parts add the simulated timing source and the simulated
detector.

| File | What it is |
|---|---|
| `configdb_server.py` | Config DB stand-in: serves the HTTP commands `psdaq.configdb.configdb` sends, from a JSON file, with `mongoconfigdb` semantics (versioned keys, aliases, history). Binds 127.0.0.1. |
| `configdb_seed.py` | Seeds the stand-in with what Configure needs: `<inst>/BEAM/tmoteb_0` (the trigger config control.py fetches; `persistValue` 0xdeadbeef, the value libtmoTeb writes for an event to be recorded) and `<inst>/BEAM/fakecam_0` (`user.sim_seed`, `expert.sim_length`). Refuses non-local URLs. |
| `lgbk_server.py` | Run DB / eLog stub: answers the 7 calls control.py makes in normal mode (active experiment, current run, start/end run, run parameters, parameter descriptions, register file) and logs each call to a JSONL file. Binds 127.0.0.1. |
| `sim_env.sh` | Isolation environment. Source it after `setup_env_daq.sh`: it drops production credentials, keeps EPICS CA and PVA on loopback with non-default ports, sends HTTP(S) through a dead proxy so a stray facility URL fails, and pins libfabric to `tcp`. |
| `preflight.sh` | Fail-closed check, run on the compute node: no DAQ devices present, HTTPS to pswww fails, production-looking PVs time out, and a loopback PV works. Exit 0 = isolated. |
| `procmgrd.s3df.conf` | procServ rcfile for `procmgr -r` on S3DF Rocky 9 nodes, where procServ is not on PATH. |

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

Tests: `pytest psdaq/psdaq/tests/test_sim_configdb.py psdaq/psdaq/tests/test_sim_lgbk.py`.
