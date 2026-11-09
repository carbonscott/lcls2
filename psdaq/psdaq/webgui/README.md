# DAQ control web GUI

A browser front end for the DAQ control level, beside the PyQt `control_gui` (which is unchanged).
Server: `server.py`, Python standard library only (`http.server` + Server-Sent Events), runs in the DAQ env.
Front end: `static/` (vanilla HTML/JS/CSS, no build step, no CDN).

## Run

```bash
source setup_env_daq.sh
daq_webgui -p <platform> -H 127.0.0.1            # talk to a running control (psdaq.control.DaqControl)
daq_webgui --emulate                             # built-in emulator, no DAQ needed
python -m psdaq.webgui.server --emulate --port 0 # same; port 0 picks a free port (printed on stdout)
```

Open `http://127.0.0.1:8650/` on the same node, or tunnel: `ssh -L 8650:127.0.0.1:8650 <node>`.

The server binds loopback only (no override). Every endpoint it may contact must be loopback or it
exits 2 before opening anything: the control host (`-H`, ZMQ ports from `ControlDef`), `--configdb-url`
(default: none; the alias list then falls back to NOBEAM/BEAM), `--events-url`, and the host of every process
in `--procstat-cnf` (read with ProcMgr in a dry run; a process with no host is localhost).  `/gui/procstat` then
opens every procServ port at 127.0.0.1 (::1 for a process at ::1), also where ProcMgr would use the machine's name.
`--print-config` prints every endpoint as JSON.

Events counter: `--events-source none|emulator|prometheus`; for prometheus give
`--events-url http://127.0.0.1:<port>/metrics --events-metric <name> [--events-labels k=v,...] [--events-drops-metric <name>]`.

## HTTP API

| method, path | body | DaqControl call | reply |
|---|---|---|---|
| GET `/api/meta` | | | states, transitions, aliases, backend, endpoints |
| GET `/api/status` | | cached status (getStatus at start, then the SUB stream) | status body + instrument + progress |
| GET `/api/platform` | | cached platform, else getPlatform | platform dict |
| GET `/api/aliases` | | configdb get_aliases | `{aliases, source}` |
| GET `/api/events` | | events source | `{events, drops, source, ok, error, ts}` |
| GET `/api/log?since=N` | | | `{records: [{seq, ts, level, msg}]}` |
| GET `/api/stream` | | | SSE: `hello`, `status`, `progress`, `log`, `events` |
| POST `/api/state` | `{"state": "configured"}` | setState | `{ok, err_info}` |
| POST `/api/transition` | `{"transition": "rollcall"}` | setTransition | `{ok, err_info}` |
| POST `/api/record` | `{"record": true}` | setRecord | `{ok, err_info}` |
| POST `/api/config` | `{"alias": "BEAM"}` | setConfig | `{ok, err_info}` |
| POST `/api/platform` | `{"platform": {...}, "allocate": true}` | selectPlatform, then setState('allocated') | `{ok, err_info}` |

POST bodies must be `application/json`; requests with a non-loopback `Host` header or a cross-origin
`Origin` header are refused.

## Tests

```bash
psdaq/psdaq/webgui/tests/run_webgui_tests.sh -v       # Playwright (headless chromium) + safety + backend tests
WEBGUI_SERVER_ARGS='--emulate-fail enable' psdaq/psdaq/webgui/tests/run_webgui_tests.sh -k full_cycle   # must fail
```

Against the simulated DAQ (what the parity check requires), on a compute node with the DAQ up
(`daq_sim up -w $WD --segments 2`: control, teb0 and two segments fakecam_0 / fakecam_1, see
`psdaq/psdaq/sim/RUNBOOK.md`):

```bash
source setup_env_daq.sh && source psdaq/psdaq/sim/sim_env.sh
WEBGUI_SIM_DAQ=$WD psdaq/psdaq/webgui/tests/run_webgui_tests.sh --junitxml=/tmp/webgui-sim.xml
```

The parity tests' server (`webgui_harness.daq_server`) then runs with the real DaqControl backend on that
DAQ (its control, its config DB stand-in, simxpm's counter over PVA, as `daq_sim up --webgui` starts it).
Before and after each test it puts control back in reset with recording off, alias BEAM and the partition
selection daq_sim set up, and after it writes back every config the test changed.  Each test records, as
junit `backend` properties, the backend of every server it drove, detected from the server (`/api/meta`)
and the daq_sim state file: `sim-daq`, `emulator` or `daqcontrol` (another DAQ).

Web elements carry `data-parity="<PyQt class>.<attr>[.<sub>]"`; the tests find them by that attribute.

## Parity with the PyQt control GUI

`parity/enumerate_pyqt.py` lists the user-facing controls of `psdaq/psdaq/control_gui` from its source
(Python `ast`), one row per affordance, with a stable id `<Class>.<attr>[.<sub>]`. `parity/check_parity.py`
compares them with `parity/mapping.json` plus `parity/mapping.d/*.json`:

- a row is **mapped** (M) only if its test is a headless-browser test (`[chromium]`), it passed in the
  given junit file, that testcase records the row id with `record_property('parity', id)` and records
  `backend` = `sim-daq` and nothing else (a row whose passing test ran only against the emulator fails,
  named), and the offscreen PyQt walk shows the running GUI builds the row (`qt_walk.built`: module
  imported, source line run outside the standalone probe phase, widget instantiated); a mapped row the
  walk does not show built fails the check, named (CGWMainTabs / CGWMainTabUser are N/A for that
  reason: `control_gui/CGWMain.py:43` and `:78` are commented out);
- a row is **not applicable** (K) only if the enumerator flags it (test-harness code under
  `if __name__ == "__main__":`, an unimported module, a method never called, a hidden or inert widget),
  its reason cites the guard line, and the offscreen PyQt walk of the same source agrees
  (`parity/qt_walk.json`, sha256 of the source; `--run-walk` runs a fresh walk, PyQt5 offscreen, about 16 s).

```bash
WEBGUI_SIM_DAQ=$WD psdaq/psdaq/webgui/tests/run_webgui_tests.sh --junitxml=/tmp/webgui-sim.xml   # see Tests
python -m psdaq.webgui.parity.check_parity --junit /tmp/webgui-sim.xml [--run-walk]  # exit 0 only if M + K = N
```
It prints `N controls found, M mapped ..., K marked not applicable`, every not-applicable row with its
reason, and names every row that is unmapped, untagged, failing or stale.

## Parity with the other PyQt GUIs

`parity/qapps.py` lists, from the syntax tree (not grep), every psdaq file outside `control_gui` that constructs
a `QApplication` (a file whose text has `QApplication(` only inside a string, like the enumerator test's fixture,
is reported as not listed).  `parity/check_gui_parity.py` checks each one with the control GUI's method
(`check_parity.check`): rows from the source (`parity/gui_rows.py`: every call that builds a counted Qt or pvedit
widget in the GUI's own files) and from the offscreen walk of the running program (`qt_walk --gui`: the program's
own `main()` with a spec's arguments against the simulated DAQ, every counted widget class replaced by a recording
subclass), M = rows whose headless-browser test passed tagged with the row and with backend `sim-daq`, K = rows
the source flags (main block, a def nothing calls, a slot whose object the ui never creates, a display nothing
writes) and the walk agrees with.  A file is either a GUI program with a spec `parity/guis/<name>.json` (web path,
walk arguments, mapping) or not a GUI program (`"na"` with a rule the check verifies: `walk-tool`, `library-demo`
with a run-time import probe); a file with no spec fails.

| PyQt program | web page | data source in the tests | server arguments |
|---|---|---|---|
| `procmgr/procstat` | `/gui/procstat` | the daq_sim .cnf, its procServ ports and logs | `--procstat-cnf F [--procstat-platform P --procstat-interval S --procstat-logdir D]` |
| `cas/groupca.py` | `/gui/groupca` | simxpm `PART:<group>` and XPM PVs (PV Access, loopback only) | `--pvgui 'groupca:<pvbase> <xpm> <groups>'` |
| `cas/pvant.py` | `/gui/pvant` | simxpm PVs | `--pvgui 'pvant:--bases B... --fields F...'` |

The pvedit pages are built by `pvgui/<name>.py` (no Qt) and rendered by `static/gui/pvgui.js`; each widget carries
`data-parity="<row id>"`.  simxpm serves stand-ins for the pyxpm PVs groupca reads (FwBuild, RemoteLinkId<n>,
LinkGroupMask<n>, L0Select*, L0RawUpdate, Inh*, RunTime, DeadFrac, DeadTime).

Each page is served at `/gui/<name>` (`/gui/procstat`, `/gui/groupca`, `/gui/pvant`) by any `daq_webgui` started
with that page's arguments from the table, beside the control GUI at `/`.  On a node with the DAQ up (`$WD`, platform
5), for example:

```bash
daq_webgui -p 5 -H 127.0.0.1 --port 31063 --configdb-url http://127.0.0.1:31050/ws/ --procstat-cnf $WD/daq_sim.cnf \
    --procstat-logdir $WD/pmlogs --pvgui 'groupca:DAQ:SIM 0 5' \
    --pvgui 'pvant:--bases DAQ:SIM:XPM:0:PART:5 DAQ:SIM:XPM:0:PART:0 --fields NumL0Acc NumL0Inp L0AccRate'
# then http://127.0.0.1:31063/gui/procstat, /gui/groupca, /gui/pvant (from your machine: ssh -L, via the login host)
```

The check runs the offscreen walks now, every time, as `check_parity --run-walk` does: `--run-walks` writes them to
`--walks DIR` (default a temporary dir) and checks with them, so no walk is kept in the tree and none can be stale.

```bash
WEBGUI_SIM_DAQ=$WD psdaq/psdaq/webgui/tests/run_webgui_tests.sh -k 'test_gui_ or check_gui' --junitxml=/tmp/gui.xml
python -m psdaq.webgui.parity.check_gui_parity --run-walks --sim-daq $WD --junit /tmp/gui.xml [--details]
# DAQ env (PyQt5): one line per file `file | web path or N/A reason | N/M/K | PASS|FAIL`; exit 0 only if all pass
```
