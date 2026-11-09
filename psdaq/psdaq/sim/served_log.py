"""served_log: what a PV-server stand-in served, for 'daq_sim coverage' to check a GUI witness's values against.

daq_sim up starts every service with DAQ_SIM_SERVED_LOG=<workdir>/logs/<service>.served.jsonl.  A stand-in that
finds it set (simxpm, simhsd, simtpr, simdti) writes there a first line {"served_log": "<program>", "pid": <pid>},
then one line {"t": <Unix seconds>, "pv": "<name>", "v": <value>} for each PV it creates (its initial value) and for
each post (or client put) whose value differs from the last one it logged for that PV.  A value is a number, a
string, a list, or for a structure {field: value}.  With the variable unset nothing is written.

psdaq.sim.coverage reads the log (served_log) and accepts a GUI's read of a PV only with values the PV's server
logged while the GUI read it.
"""

import json
import os
import threading
import time

ENV = 'DAQ_SIM_SERVED_LOG'


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
        if self.f:
            self.f.write(json.dumps({'served_log': program, 'pid': os.getpid()}) + '\n')

    def __call__(self, pv, value):
        if self.f is None:
            return
        v = plain(value)
        with self.lock:
            if pv in self.last and self.last[pv] == v:
                return
            self.last[pv] = v
            self.f.write(json.dumps({'t': round(time.time(), 3), 'pv': pv, 'v': v}, default=str) + '\n')
