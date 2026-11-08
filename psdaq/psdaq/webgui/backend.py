"""Backends for the DAQ web GUI server.

Both expose `ctl` (an object with the psdaq.control.DaqControl method names the
PyQt GUI uses), `start(on_message)`, `stop()`, `aliases()` and `endpoints()`.

- RealBackend: psdaq.control.DaqControl (the same client the PyQt GUI's
  CGDaqControl uses) for requests; its front_sub SUB socket (front_pub and
  step_pub ports) read in a monitor thread, the way CGWMain/QWZMQListener read
  the status stream.  Config aliases come from psdaq.configdb when a (loopback)
  --configdb-url is given.
- EmulatorBackend: psdaq.webgui.emulator.DaqControlEmulator, no sockets.
"""

import logging
import threading

from psdaq.control.ControlDef import front_pub_port, front_rep_port, fast_rep_port, step_pub_port
from psdaq.webgui.netguard import require_loopback_host, require_loopback_url

logger = logging.getLogger(__name__)

# CGWMainConfiguration.list_of_aliases, used when the config DB gives none
FALLBACK_ALIASES = ['NOBEAM', 'BEAM']


class LockedControl:
    """Serialise calls into one DaqControl: its REQ sockets are not thread safe."""

    def __init__(self, ctl):
        self._ctl = ctl
        self._lock = threading.Lock()

    def __getattr__(self, name):
        fn = getattr(self._ctl, name)
        if not callable(fn):
            return fn

        def call(*a, **k):
            with self._lock:
                return fn(*a, **k)
        return call


class RealBackend:
    name = 'daqcontrol'

    def __init__(self, *, host, platform, timeout, configdb_url=None, configdb_root='configDB',
                 user='tstopr', password=None):
        self.host = require_loopback_host(host, '--host (control)')
        self.platform = platform
        self.timeout = timeout
        self.configdb_url = require_loopback_url(configdb_url, '--configdb-url') if configdb_url else None
        self.configdb_root = configdb_root
        self.user = user
        self.password = password
        self._stop = threading.Event()
        self._thread = None
        self._raw = None
        self.ctl = None

    def endpoints(self):
        p = self.platform
        eps = {'front_rep': 'tcp://%s:%d' % (self.host, front_rep_port(p)),
               'fast_rep': 'tcp://%s:%d' % (self.host, fast_rep_port(p)),
               'front_pub': 'tcp://%s:%d' % (self.host, front_pub_port(p)),
               'step_pub': 'tcp://%s:%d' % (self.host, step_pub_port(p))}
        if self.configdb_url:
            eps['configdb'] = self.configdb_url
        return eps

    def connect(self):
        from psdaq.control.DaqControl import DaqControl   # needs zmq: DAQ env
        self._raw = DaqControl(host=self.host, platform=self.platform, timeout=self.timeout)
        self.ctl = LockedControl(self._raw)

    def start(self, on_message):
        import zmq
        sub = self._raw.front_sub   # used only by the monitor thread

        def run():
            poller = zmq.Poller()
            poller.register(sub, zmq.POLLIN)
            while not self._stop.is_set():
                try:
                    if not dict(poller.poll(500)):
                        continue
                    while True:
                        try:
                            msg = sub.recv_json(flags=zmq.NOBLOCK)
                        except zmq.Again:
                            break
                        on_message(msg)
                except Exception as ex:
                    logger.warning('monitor: %s' % ex)
        self._thread = threading.Thread(target=run, name='control-monitor', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def aliases(self, instrument):
        if not self.configdb_url:
            return FALLBACK_ALIASES, 'default (no --configdb-url)'
        try:
            from psdaq.configdb.configdb import configdb
            cdb = configdb(self.configdb_url, instrument, create=False, root=self.configdb_root,
                           user=self.user, password=self.password)
            lst = cdb.get_aliases(hutch=instrument)
        except Exception as ex:
            logger.error('configdb get_aliases: %s' % ex)
            lst = []
        if not lst:
            return FALLBACK_ALIASES, 'default (configdb returned none)'
        return list(lst), 'configdb %s' % self.configdb_url


class EmulatorBackend:
    name = 'emulator'

    def __init__(self, *, fail_transition=None, l1_rate=500.0, slow_transition_time=0.6, step_delay=0.05):
        self.kw = dict(fail_transition=fail_transition, l1_rate=l1_rate,
                       slow_transition_time=slow_transition_time, step_delay=step_delay)
        self.ctl = None
        self._on_message = None

    def endpoints(self):
        return {}

    def connect(self):
        from psdaq.webgui.emulator import DaqControlEmulator
        self.ctl = DaqControlEmulator(self._publish, **self.kw)

    def _publish(self, msg):
        if self._on_message is not None:
            self._on_message(msg)

    def start(self, on_message):
        self._on_message = on_message

    def stop(self):
        pass

    def aliases(self, instrument):
        return self.ctl.get_aliases(), 'emulator'
