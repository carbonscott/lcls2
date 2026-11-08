"""Shared pytest hooks of the web GUI tests."""

import pytest

import webgui_harness
from parity_rows import ROWS


@pytest.fixture(autouse=True)
def _parity_rows(request, record_property):
    """Record the parity rows parity_rows.ROWS assigns to this test as junit `parity` properties, and the backend
    of every web GUI server the test drove as junit `backend` properties (sim-daq, emulator, ...: what
    webgui_harness.detect_backend found when the server started), which check_parity reads."""
    mod = getattr(request.node, 'module', None)
    name = mod.__name__.rsplit('.', 1)[-1] if mod is not None else ''
    for rid in ROWS.get(name, {}).get(getattr(request.node, 'originalname', request.node.name), []):
        record_property('parity', rid)
    n0 = len(webgui_harness.STARTED)
    yield
    drove = list(webgui_harness.STARTED[n0:])      # servers started during the test (function-scoped fixtures)
    for v in (getattr(request.node, 'funcargs', None) or {}).values():     # and a longer-lived server it took
        e = getattr(v, 'started_entry', None)
        if e is not None and e not in drove:
            drove.append(e)
    for b in sorted(set(x['backend'] for x in drove)):
        record_property('backend', b)
    for x in drove:
        record_property('backend_detail', '%s %s: %s' % (x['backend'], x['url'], x['why']))
