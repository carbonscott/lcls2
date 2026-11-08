"""Pluggable sources for the web GUI's "events" counter.

A source has `name` and `poll()` -> dict(events=int|None, drops=int|None, ok=bool, error=str|None)
and optionally `ts` (epoch s, when the value was read) and `final` (bool).  A source may also define
`bind(hub)`; the server calls it once with its Hub, whose `status` dict holds control's state.
The server polls the selected source about once a second and pushes changes to the browser.

- NoEvents: always None (the GUI shows N/A).
- EmulatorEvents: the emulator's L1Accept counter.
- PrometheusTextEvents: reads a Prometheus text exposition from a loopback URL
  (e.g. a DAQ process' metrics endpoint) and sums one metric over the series
  that match optional label filters. Proxies are bypassed; the URL must be loopback.
- PvaCountEvents: the timing source's accepted-L1 counter, an XPM partition PV
  <pvbase>:XPM:<xpm>:PART:<group>:NumL0Acc (drops: NumL0Inp - NumL0Acc), read over PV Access
  with p4p.  The client gets its EPICS_PVA_* settings explicitly (no environment lookup), and
  only after netguard.require_loopback_pva_env accepted them.  RunLatch marks the count final
  once the run has been disabled and holds it through EndRun/Unconfigure/Reset.
"""

import re
import time
import urllib.request

from psdaq.webgui.netguard import require_loopback_url


class NoEvents:
    name = 'none'

    def poll(self):
        return {'events': None, 'drops': None, 'ok': True, 'error': None}


class EmulatorEvents:
    name = 'emulator'

    def __init__(self, emulator):
        self.emu = emulator

    def poll(self):
        events, drops = self.emu.l1_counts()
        return {'events': events, 'drops': drops, 'ok': True, 'error': None}


_LINE = re.compile(r'^([A-Za-z_:][A-Za-z0-9_:]*)(\{[^}]*\})?\s+(\S+)')
_LABEL = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:[^"\\]|\\.)*)"')


def parse_prometheus_text(text, metric, labels=None):
    """Sum of `metric` samples whose labels include all of `labels` (dict). None if no sample."""
    labels = labels or {}
    total, found = 0.0, False
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        m = _LINE.match(line)
        if not m or m.group(1) != metric:
            continue
        have = dict(_LABEL.findall(m.group(2) or ''))
        if any(have.get(k) != v for k, v in labels.items()):
            continue
        try:
            total += float(m.group(3))
        except ValueError:
            continue
        found = True
    return total if found else None


class PrometheusTextEvents:
    name = 'prometheus'

    def __init__(self, url, metric, labels=None, drops_metric=None, timeout=2.0):
        self.url = require_loopback_url(url, '--events-url')
        self.metric = metric
        self.labels = labels or {}
        self.drops_metric = drops_metric
        self.timeout = timeout
        # empty ProxyHandler: never route through HTTP(S)_PROXY
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def poll(self):
        try:
            with self._opener.open(self.url, timeout=self.timeout) as r:
                text = r.read().decode('utf-8', 'replace')
        except Exception as ex:
            return {'events': None, 'drops': None, 'ok': False, 'error': '%s: %s' % (self.url, ex)}
        ev = parse_prometheus_text(text, self.metric, self.labels)
        dr = parse_prometheus_text(text, self.drops_metric, self.labels) if self.drops_metric else None
        return {'events': None if ev is None else int(ev), 'drops': None if dr is None else int(dr),
                'ok': ev is not None, 'error': None if ev is not None else 'metric %s not found' % self.metric}


def parse_labels(s):
    """'k=v,k2=v2' -> dict"""
    out = {}
    for part in (s or '').split(','):
        if part.strip():
            k, _, v = part.partition('=')
            out[k.strip()] = v.strip()
    return out


def xpm_count_pv(pvbase, xpm, group, label='NumL0Acc'):
    """The XPM partition counter PV, as pyxpm and psdaq.sim.simxpm name it."""
    return '%s:XPM:%s:PART:%s:%s' % (pvbase, xpm, group, label)


class RunLatch:
    """Decide when the displayed count is final for a run, and hold it.

    feed(state, transition, events, drops, ts) -> (events, drops, ts, final)

    - While control is in 'running' (or before any run was seen): the live value, final False.
    - After a run (state left 'running' with a Disable): control reports Disable only after the
      XPM stopped L0 triggers and posted its counters (control.py condition_disable, simxpm
      l0disable), so every read made after the server saw the non-running state is the
      count posted at Disable.  The count becomes final at the second consecutive equal read
      after that (so its ts is at least one poll period after control reported the state),
      and is latched: the same value, drops and ts with final True, through EndStep, EndRun,
      Unconfigure, Disconnect and Reset, until a transition up starts the next cycle
      (Configure or BeginRun clear the XPM counters, control.py clear_readout; BeginStep and
      Enable lead to running).  The server polls about once a second, so a quick
      configured -> starting -> paused -> running may show only some of these transitions:
      any one of them, or state running, releases the latch.
    """

    RELEASE = ('configure', 'beginrun', 'beginstep', 'enable')

    def __init__(self):
        self.armed = False      # a run was seen in 'running'
        self.after = None       # (events, drops, ts) of the first read after the run stopped
        self.latched = None     # (events, drops, ts)

    def feed(self, state, transition, events, drops, ts):
        if state == 'running':
            self.armed, self.after, self.latched = True, None, None
            return events, drops, ts, False
        if transition in self.RELEASE or state is None:
            self.armed, self.after, self.latched = False, None, None
            return events, drops, ts, False
        if self.latched is not None:
            return self.latched + (True,)
        if not self.armed or events is None:
            return events, drops, ts, False
        if self.after is not None and self.after[0] == events:
            self.latched = (events, drops, ts)
            return self.latched + (True,)
        self.after = (events, drops, ts)
        return events, drops, ts, False


class PvaCountEvents:
    name = 'pva'

    def __init__(self, pv, conf, drops_pv=None, timeout=2.0):
        """pv: the NumL0Acc PV; conf: EPICS_PVA_* dict from netguard.require_loopback_pva_env."""
        from p4p.client.thread import Context     # DAQ env
        self.pv = pv
        self.drops_pv = drops_pv
        self.timeout = timeout
        self.conf = dict(conf)
        self.ctx = Context('pva', conf=self.conf, useenv=False)
        self.latch = RunLatch()
        self._hub = None

    def bind(self, hub):
        self._hub = hub

    def _get(self, name):
        v = self.ctx.get(name, timeout=self.timeout)
        return int(round(float(v)))

    def _control(self):
        if self._hub is None:
            return None, None
        with self._hub.lock:
            return self._hub.status.get('state'), self._hub.status.get('transition')

    def poll(self):
        state, transition = self._control()      # before the read: the read is the later one
        ts = time.time()
        try:
            ev = self._get(self.pv)
            ts = time.time()
            dr = None
            if self.drops_pv:
                dr = max(0, self._get(self.drops_pv) - ev)
            err = None
        except Exception as ex:
            ev = dr = None
            err = '%s: %s' % (self.pv, ex)
        events, drops, ts, final = self.latch.feed(state, transition, ev, dr, ts)
        return {'events': events, 'drops': drops, 'ts': ts, 'final': final,
                'ok': events is not None, 'error': err if events is None else None, 'pv': self.pv}

    def close(self):
        self.ctx.close()
