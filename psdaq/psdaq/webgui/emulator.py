"""In-process emulator of the DAQ control level, for web GUI tests without a DAQ.

`DaqControlEmulator` has the method names and return shapes of
`psdaq.control.DaqControl.DaqControl` that the GUI uses, and publishes the
messages control publishes on its front_pub socket (status, progress, error,
warning, fileReport), in control's own shapes (psdaq/control/ControlDef.py
create_msg & co., control.py status_msg).  Like control, setState and
setTransition reply at once and run the transitions in a worker thread
(control.py handle_setstate / service_requests), so errors arrive on the
status stream, not in the reply.

Nothing here opens a socket.
"""

import copy
import logging
import queue
import threading
import time

from psdaq.control.ControlDef import (ControlDef, create_msg, error_msg, warning_msg,
                                      fileReport_msg, progress_msg)

logger = logging.getLogger(__name__)

# copied from psdaq/control/control.py next_dict: next transition from state to target
NEXT = {
    'unallocated': {'reset': 'reset', 'allocated': 'alloc', 'connected': 'alloc', 'configured': 'alloc',
                    'starting': 'alloc', 'paused': 'alloc', 'running': 'alloc'},
    'allocated': {'reset': 'reset', 'unallocated': 'dealloc', 'connected': 'connect', 'configured': 'connect',
                  'starting': 'connect', 'paused': 'connect', 'running': 'connect'},
    'connected': {'reset': 'reset', 'unallocated': 'disconnect', 'allocated': 'disconnect',
                  'configured': 'configure', 'starting': 'configure', 'paused': 'configure', 'running': 'configure'},
    'configured': {'reset': 'reset', 'unallocated': 'unconfigure', 'allocated': 'unconfigure',
                   'connected': 'unconfigure', 'starting': 'beginrun', 'paused': 'beginrun', 'running': 'beginrun'},
    'starting': {'reset': 'reset', 'unallocated': 'endrun', 'allocated': 'endrun', 'connected': 'endrun',
                 'configured': 'endrun', 'paused': 'beginstep', 'running': 'beginstep'},
    'paused': {'reset': 'reset', 'unallocated': 'endstep', 'allocated': 'endstep', 'connected': 'endstep',
               'configured': 'endstep', 'starting': 'endstep', 'running': 'enable'},
    'running': {'reset': 'reset', 'unallocated': 'disable', 'allocated': 'disable', 'connected': 'disable',
                'configured': 'disable', 'starting': 'disable', 'paused': 'disable'},
    'reset': {s: 'rollcall' for s in ('unallocated', 'allocated', 'connected', 'configured',
                                      'starting', 'paused', 'running')},
}

# control.py collectMachine.add_transition(name, source(s), dest); None = no state change
TRANSITIONS = {
    'reset': ('*', 'reset'),
    'rollcall': (('reset', 'unallocated'), 'unallocated'),
    'alloc': (('unallocated',), 'allocated'),
    'dealloc': (('allocated',), 'unallocated'),
    'connect': (('allocated',), 'connected'),
    'disconnect': (('connected',), 'allocated'),
    'configure': (('connected',), 'configured'),
    'unconfigure': (('configured',), 'connected'),
    'beginrun': (('configured',), 'starting'),
    'endrun': (('starting',), 'configured'),
    'beginstep': (('starting',), 'paused'),
    'endstep': (('paused',), 'starting'),
    'enable': (('paused',), 'running'),
    'disable': (('running',), 'paused'),
    'slowupdate': (('running',), None),
}

DEFAULT_ALIASES = ['BEAM', 'NOBEAM']


def _default_platform():
    def proc(alias, pid, readout=None):
        d = {'proc_info': {'alias': alias, 'host': 'localhost', 'pid': pid}, 'active': 1, 'monitor': 0}
        if readout is not None:
            d['det_info'] = {'readout': readout}
        return d
    return {
        'control': {'0': proc('control', 41000)},
        'drp': {'1': proc('timing_0', 41001, 0), '2': proc('fakecam_0', 41002, 0), '3': proc('fakecam_1', 41003, 0)},
        'teb': {'4': proc('teb0', 41004)},
        'meb': {'5': proc('meb0', 41005)},
    }


class DaqControlEmulator:
    """DaqControl look-alike. `publish(msg)` receives every front_pub message."""

    def __init__(self, publish, *, instrument='TST', experiment='tst00000', last_run_number=0,
                 fail_transition=None, step_delay=0.05, slow_transition_time=0.6, l1_rate=500.0,
                 aliases=None):
        self._publish = publish
        self._lock = threading.RLock()
        self.instrument = instrument
        self.state = 'reset'
        self.last_transition = 'reset'
        self.config_alias = 'BEAM'
        self.recording = False
        self.bypass_activedet = False
        self.experiment_name = experiment
        self.run_number = 0
        self.last_run_number = last_run_number
        self.fail_transition = fail_transition
        self.step_delay = step_delay
        self.slow_transition_time = slow_transition_time
        self.l1_rate = l1_rate
        self.aliases = list(aliases or DEFAULT_ALIASES)
        self._history = _default_platform()   # what rollcall finds (selection is remembered, as control's history)
        self.cmstate = {}                       # platform; empty in reset (control.py on_enter_reset)
        self._events = 0.0
        self._running_since = None
        self._jobs = queue.Queue()
        self._worker = threading.Thread(target=self._work, name='emulator-control', daemon=True)
        self._worker.start()

    # ---- messages, in control.py shapes ----
    def _status_body(self):
        return {'state': self.state, 'transition': self.last_transition,
                'platform': copy.deepcopy(self.cmstate),
                'config_alias': str(self.config_alias), 'recording': self.recording,
                'bypass_activedet': self.bypass_activedet,
                'experiment_name': self.experiment_name or 'None',
                'run_number': self.run_number, 'last_run_number': self.last_run_number}

    def _report_status(self):
        self._publish(create_msg('status', body=self._status_body()))

    def _report_error(self, msg):
        logger.error(msg)
        self._publish(error_msg(msg))

    # ---- worker: control's request loop is single threaded ----
    def _work(self):
        while True:
            job = self._jobs.get()
            try:
                job()
            except Exception as ex:  # keep the worker alive
                logger.exception('emulator job failed')
                self._report_error('emulator internal error: %s' % ex)

    def _sync(self, fn):
        """Run fn on the worker thread after queued jobs (like control's serial REQ handling)."""
        done = threading.Event()
        box = {}

        def job():
            box['v'] = fn()
            done.set()
        self._jobs.put(job)
        done.wait()
        return box.get('v')

    # ---- transitions ----
    def _count_events(self):
        if self._running_since is not None:
            now = time.monotonic()
            self._events += (now - self._running_since) * self.l1_rate
            self._running_since = now

    def _trigger(self, name, state_change=True):
        """Run one transition; return err_info or None."""
        if name not in TRANSITIONS:
            return 'transition \'%s\' not recognized' % name
        sources, dest = TRANSITIONS[name]
        with self._lock:
            if sources != '*' and self.state not in sources:
                return 'transition \'%s\' not permitted in state \'%s\'' % (name, self.state)
        if name == self.fail_transition:
            return 'emulated failure of transition \'%s\' (--emulate-fail)' % name
        if name == 'alloc':
            active = [v for v in self.cmstate.get('drp', {}).values() if v['active']]
            if not active:
                return 'alloc: no active drp process selected'
        slow = name in ('configure', 'beginrun')
        if slow and self.slow_transition_time > 0:
            t0 = time.monotonic()
            total = self.slow_transition_time
            while True:
                elapsed = time.monotonic() - t0
                if elapsed >= total:
                    break
                # control.py progressReport sends elapsed/total (it rounds to int seconds; ms here)
                self._publish(progress_msg(name, elapsed * 1000, total * 1000))
                time.sleep(min(0.1, total - elapsed))
        else:
            time.sleep(self.step_delay)
        with self._lock:
            self._count_events()
            if name == 'reset':
                self.cmstate = {}
                self.run_number = 0
            elif name == 'rollcall':
                self.cmstate = copy.deepcopy(self._history)
            elif name == 'beginrun':
                self._events = 0.0
                if self.recording:
                    self.run_number = self.last_run_number + 1
                    self._publish(fileReport_msg('/emulated/xtc/%s-r%04d-s000-c000.xtc2'
                                                 % (self.experiment_name, self.run_number)))
                else:
                    self.run_number = 0
            elif name == 'endrun':
                if self.run_number:
                    self.last_run_number = self.run_number
                self.run_number = 0
            if dest is not None:
                self.state = dest
            if name != 'slowupdate':
                self.last_transition = name
            self._running_since = time.monotonic() if self.state == 'running' else None
            self._report_status()
        return None

    def _set_state_job(self, target):
        while self.state != target:
            nxt = NEXT.get(self.state, {}).get(target, 'error')
            if nxt == 'error':
                self._report_error('next_transition() error')
                return
            err = self._trigger(nxt)
            if err:
                self._report_error(err)
                return

    # ---- DaqControl API ----
    def getState(self):
        with self._lock:
            return self.state

    def getPlatform(self):
        with self._lock:
            return copy.deepcopy(self.cmstate)

    def getInstrument(self):
        return self.instrument

    def getStatus(self):
        with self._lock:
            b = self._status_body()
        return (b['transition'], b['state'], b['config_alias'], b['recording'], b['platform'],
                b['bypass_activedet'], b['experiment_name'], b['run_number'], b['last_run_number'])

    def setState(self, state, phase1Info={}):
        if state not in ControlDef.states:
            return 'state \'%s\' not recognized' % state
        self._jobs.put(lambda: self._set_state_job(state))
        return None

    def setTransition(self, transition, phase1Info={}):
        if transition not in ControlDef.transitions:
            return 'transition \'%s\' not recognized' % transition

        def job():
            err = self._trigger(transition, state_change=False)
            if err:
                self._report_error(err)
        self._jobs.put(job)
        return None

    def setConfig(self, config):
        def job():
            with self._lock:
                if self.state in ('running', 'paused'):
                    msg = 'cannot set config alias in state \'%s\'' % self.state
                    logger.error(msg)
                    return msg
                if config != self.config_alias:
                    self.config_alias = config
                    self._report_status()
            return None
        return self._sync(job)

    def setRecord(self, recordIn):
        if not isinstance(recordIn, bool):
            return 'setRecord() requires True or False'

        def job():
            with self._lock:
                if self.state in ('running', 'paused', 'starting'):
                    return 'cannot change recording setting in state \'%s\' -- end run first' % self.state
                if recordIn != self.recording:
                    self.recording = recordIn
                    self._report_status()
            return None
        return self._sync(job)

    def selectPlatform(self, body):
        def job():
            with self._lock:
                if self.state != 'unallocated':
                    msg = 'selectPlatform only permitted in unallocated state'
                    self._report_error(msg)
                    return error_msg(msg)['body']
                try:
                    for level, val1 in body.items():
                        for key2, val2 in val1.items():
                            key2 = str(key2)
                            if level == 'control' and val2['active'] == 0:
                                self._publish(warning_msg('ignoring attempt to clear the control level active flag'))
                                val2['active'] = 1
                            self.cmstate[level][key2]['active'] = val2['active']
                            self.cmstate[level][key2]['monitor'] = val2.get('monitor', 0)
                            if val2.get('monitor'):
                                alias = val2['proc_info']['alias']
                                self._publish(warning_msg('%s/%s set to MONITOR ONLY.' % (level, alias)))
                            if level in ('drp', 'tpr'):
                                self.cmstate[level][key2]['det_info']['readout'] = val2['det_info']['readout']
                except Exception as ex:
                    msg = 'handle_selectplatform(): %s' % ex
                    logger.error(msg)
                    return error_msg(msg)['body']
                self._history = copy.deepcopy(self.cmstate)
                return {}   # control.py handle_selectplatform replies 'ok' and publishes no status
        return self._sync(job)

    # ---- extras used by the server ----
    def get_aliases(self):
        return list(self.aliases)

    def l1_counts(self):
        """(events, drops) of the current/last run, like a DAQ L1Accept counter."""
        with self._lock:
            self._count_events()
            return int(self._events), 0
