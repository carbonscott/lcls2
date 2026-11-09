"""served_log: what a PV-server stand-in served, for 'daq_sim coverage' to check a GUI witness's values against.

daq_sim up starts every service with DAQ_SIM_SERVED_LOG=<workdir>/logs/<service>.served.jsonl.  A stand-in that
finds it set (simxpm, simhsd, simtpr, simdti) writes there a first line {"served_log": "<program>", "pid": <pid>},
then one line {"t": <Unix seconds>, "pv": "<name>", "v": <value>} for each PV it creates (its initial value) and for
each post (or client put) whose value differs from the last one it logged for that PV.  A value is a number, a
string, a list, or for a structure {field: value}.  With the variable unset nothing is written.

A log stops at DAQ_SIM_SERVED_LOG_MAX bytes (default 64 MiB; simdti's grows about 46 MB an hour of 'up') with a last
line {"t": <Unix seconds>, "capped": <bytes>}: a read after that time cannot be checked, and coverage says so.

psdaq.sim.coverage reads the log (served_log) and accepts a GUI's read of a PV only with values the PV's server
logged while the GUI read it, and the log only at <service>.served.jsonl next to the service's log, whose '# PID:'
line (daq_sim writes it) must be the pid this log's first line gives.
"""

import json
import os
import threading
import time

ENV = 'DAQ_SIM_SERVED_LOG'
MAX_ENV = 'DAQ_SIM_SERVED_LOG_MAX'
MAX_BYTES = 64 << 20


def plain(v):
    """A posted value as JSON can hold it: a p4p Value's 'value' field (an NT scalar) or its fields (a structure),
    numpy arrays and scalars as lists and numbers."""
    if hasattr(v, 'todict'):
        v = v.todict()
        if isinstance(v, dict) and 'value' in v:
            v = v['value']
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items() if not str(k).startswith(('timeStamp', 'alarm', 'display', 'control', 'valueAlarm'))}
    if hasattr(v, 'tolist'):
        return v.tolist()
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, bytes):
        return v.decode('utf-8', 'replace')
    return v


class ServedLog:
    """log(pv, value): one line per new value of a PV (see the module doc); does nothing without a path."""

    def __init__(self, program, path=None):
        path = os.environ.get(ENV) if path is None else path
        self.f = open(path, 'a', buffering=1) if path else None
        self.last, self.lock = {}, threading.Lock()
        try:
            self.max = int(os.environ.get(MAX_ENV, MAX_BYTES))
        except ValueError:
            self.max = MAX_BYTES
        self.size = 0
        if self.f:
            self._write(json.dumps({'served_log': program, 'pid': os.getpid()}) + '\n')

    def _write(self, line):
        self.f.write(line)
        self.size += len(line)

    def __call__(self, pv, value):
        if self.f is None:
            return
        v = plain(value)
        with self.lock:
            if self.f is None or pv in self.last and self.last[pv] == v:
                return
            self.last[pv] = v
            line = json.dumps({'t': round(time.time(), 3), 'pv': pv, 'v': v}, default=str) + '\n'
            if self.size + len(line) > self.max:      # the size cap: say so once and stop
                self._write(json.dumps({'t': round(time.time(), 3), 'capped': self.size}) + '\n')
                self.f.close()
                self.f = None
                return
            self._write(line)
