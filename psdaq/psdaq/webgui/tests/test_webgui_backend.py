"""In-process checks of the real-DAQ code path without a DAQ and without sockets.

RealBackend is given a fake psdaq.control.DaqControl module; the test checks that the
server's command handlers call the DaqControl methods the PyQt GUI calls, with the same
arguments, and that control-shaped status-stream messages update the cached status and log
the way CGWMain.process_zmq_message does.
"""

import sys
import types

import pytest

from webgui_harness import PKG_ROOT

sys.path.insert(0, str(PKG_ROOT))

from psdaq.webgui import server as srv            # noqa: E402
from psdaq.webgui.backend import RealBackend      # noqa: E402
from psdaq.webgui.events import NoEvents, parse_prometheus_text  # noqa: E402


class FakeDaqControl:
    calls = []

    def __init__(self, *, host, platform, timeout):
        FakeDaqControl.calls.append(('__init__', host, platform, timeout))
        self.front_sub = None

    def _rec(self, *a):
        FakeDaqControl.calls.append(a)

    def getStatus(self):
        self._rec('getStatus')
        return ('reset', 'reset', 'BEAM', False, {}, False, 'tst00000', 0, 7)

    def getInstrument(self):
        self._rec('getInstrument')
        return 'TST'

    def getPlatform(self):
        self._rec('getPlatform')
        return {}

    def setState(self, state, phase1Info={}):
        self._rec('setState', state)

    def setTransition(self, transition, phase1Info={}):
        self._rec('setTransition', transition)

    def setRecord(self, rec):
        self._rec('setRecord', rec)

    def setConfig(self, alias):
        self._rec('setConfig', alias)
        return 'cannot set config alias in state \'running\'' if alias == 'BAD' else None

    def selectPlatform(self, body):
        self._rec('selectPlatform', body)
        return {}


@pytest.fixture
def app(monkeypatch):
    mod = types.ModuleType('psdaq.control.DaqControl')
    mod.DaqControl = FakeDaqControl
    monkeypatch.setitem(sys.modules, 'psdaq.control.DaqControl', mod)
    FakeDaqControl.calls = []
    args = srv.build_parser().parse_args(['-p', '4', '-t', '1234'])
    be = RealBackend(host=args.host, platform=args.platform, timeout=args.timeout)
    monkeypatch.setattr(be, 'start', lambda on_message: None)   # no zmq monitor thread here
    a = srv.App(args, be, NoEvents())
    a.start()
    yield a
    a.stop()


def test_startup_calls(app):
    assert FakeDaqControl.calls[:3] == [('__init__', '127.0.0.1', 4, 1234), ('getStatus',), ('getInstrument',)]
    st = app.hub.snapshot()
    assert (st['state'], st['config_alias'], st['last_run_number'], st['instrument']) == ('reset', 'BEAM', 7, 'TST')
    assert app.aliases == ['NOBEAM', 'BEAM']   # CGWMainConfiguration.list_of_aliases fallback


def test_commands_call_daqcontrol_like_pyqt(app):
    FakeDaqControl.calls = []
    assert app.cmd_transition({'transition': 'rollcall'})[1]['ok']          # CGWMainPartition.roll_call
    plat = {'drp': {'1': {'active': 1, 'monitor': 0, 'proc_info': {'alias': 'cam_0'}, 'det_info': {'readout': 2}}}}
    assert app.cmd_platform({'platform': plat, 'allocate': True})[1]['ok']  # QWPopupTableCheck.onApply
    assert app.cmd_state({'state': 'configured'})[1]['ok']                  # CGWMainControl.on_box_state
    assert app.cmd_record({'record': True})[1]['ok']                        # CGWMainControl.on_but_record
    assert app.cmd_config({'alias': 'NOBEAM'})[1]['ok']                     # CGWMainConfiguration.on_but_type
    rep = app.cmd_config({'alias': 'BAD'})[1]
    assert rep == {'ok': False, 'err_info': "cannot set config alias in state 'running'"}
    assert FakeDaqControl.calls == [('setTransition', 'rollcall'), ('selectPlatform', plat),
                                    ('setState', 'allocated'), ('setState', 'configured'),
                                    ('setRecord', True), ('setConfig', 'NOBEAM'), ('setConfig', 'BAD')]
    assert app.cmd_state({'state': 'bogus'})[0] == 400
    assert app.cmd_record({'record': 'yes'})[0] == 400


def test_status_stream_messages(app):
    hub = app.hub
    hub.on_control_message({'header': {'key': 'status'}, 'body': {
        'state': 'running', 'transition': 'enable', 'platform': {'teb': {}}, 'config_alias': 'BEAM',
        'recording': True, 'bypass_activedet': False, 'experiment_name': 'tst00000', 'run_number': 8,
        'last_run_number': 7}})
    hub.on_control_message({'header': {'key': 'progress'}, 'body': {'transition': 'configure', 'elapsed': 1, 'total': 3}})
    assert hub.snapshot()['progress']['transition'] == 'configure'
    hub.on_control_message({'header': {'key': 'error'}, 'body': {'err_info': 'drp died'}})
    hub.on_control_message({'header': {'key': 'warning'}, 'body': {'err_info': 'slow'}})
    hub.on_control_message({'header': {'key': 'fileReport'}, 'body': {'path': '/x/r0008.xtc2'}})
    st = hub.snapshot()
    assert (st['state'], st['transition'], st['run_number'], st['platform']) == ('running', 'enable', 8, {'teb': {}})
    levels = [(r['level'], r['msg']) for r in hub.log]
    assert ('INFO', 'zmq msg transition:enable state:running config:BEAM recording:True') in levels
    assert ('ERROR', 'drp died') in levels and ('WARNING', 'slow') in levels
    assert ('INFO', 'fileReport: /x/r0008.xtc2') in levels


def test_prometheus_parser():
    text = ('# HELP TEB_EvtCt events\n# TYPE TEB_EvtCt counter\n'
            'TEB_EvtCt{alias="teb0",instrument="tst"} 1000\nTEB_EvtCt{alias="teb1",instrument="tst"} 24\n'
            'DRP_EvtCt{alias="cam_0"} 5\n')
    assert parse_prometheus_text(text, 'TEB_EvtCt') == 1024
    assert parse_prometheus_text(text, 'TEB_EvtCt', {'alias': 'teb1'}) == 24
    assert parse_prometheus_text(text, 'missing') is None
