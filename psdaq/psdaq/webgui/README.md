# DAQ control web GUI (v0)

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
(default: none; the alias list then falls back to NOBEAM/BEAM), `--events-url`.
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

Web elements carry `data-parity="<PyQt class>.<attr>[.<sub>]"`; the tests find them by that attribute.
