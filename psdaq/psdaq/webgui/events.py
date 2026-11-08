"""Pluggable sources for the web GUI's "events" counter.

A source has `name` and `poll()` -> dict(events=int|None, drops=int|None, ok=bool, error=str|None).
The server polls the selected source about once a second and pushes changes to the browser.

- NoEvents: always None (the GUI shows N/A).
- EmulatorEvents: the emulator's L1Accept counter.
- PrometheusTextEvents: reads a Prometheus text exposition from a loopback URL
  (e.g. a DAQ process' metrics endpoint) and sums one metric over the series
  that match optional label filters. Proxies are bypassed; the URL must be loopback.
"""

import re
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
