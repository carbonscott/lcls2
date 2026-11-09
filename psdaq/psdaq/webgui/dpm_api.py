"""Web copy of trigger/detector_protection_monitor.py (the hot-pixel detector protection monitor): an extension of
psdaq.webgui.server, started with  --dpm '<the PyQt program's arguments>'  (-b BASE_PV -d DETECTOR).

The Channel Access client (pyepics, as the PyQt program) starts only after netguard.require_loopback_ca_env accepted
the environment (EPICS_CA_AUTO_ADDR_LIST=NO, loopback EPICS_CA_ADDR_LIST).  A thread does what BlockerPVMonitor.run
does, reading <base>:BLOCKED (its timestamp), :NPIX_OT, :NPIX and :ADU: a changed NPIX / ADU / NPIX_OT updates the
window's copy (MonitorProgressBar.update_npix_over_threshold / update_adu_threshold / update_progress_bar: the bar
shows int(npix_ot / npix * 100) %, a value outside 0-100 or a zero threshold leaves it as it was), and a BLOCKED
timestamp other than the first one seen, while reports are on, opens the dialog '<detector> Tripped' / '<npix_ot>
pixels over threshold <adu>' with its button 'Dismiss.' and turns reports off (MonitorMW.detector_protection_activated).
Dismiss turns reports back on, as the PyQt program does after msg_box.exec_(); since BlockerPVMonitor never updates
its last timestamp, the dialog then opens again at once, as in the PyQt program.  The thread sleeps 50 ms between
reads (the PyQt thread loops with no sleep).

Routes
  GET  /api/dpm/status       title, info text, progress (null: never set), the values, dialog (null or
                             {title, text, button, n}), reports, connected, sim_pid (<base>:SIM:PID, simdetprot only)
  POST /api/dpm/dismiss      the dialog's 'Dismiss.' button
"""

import argparse
import os
import shlex
import threading
import time

INFO = ('Progress bar of number of pixels over ADU threshold as percentage of the maximum number of hot pixels.')


def parse(argv):
    p = argparse.ArgumentParser(prog='detector_protection_monitor', description='Monitor DAQ hot-pixel detector protection.')
    p.add_argument('-b', '--base_pv', type=str, default='MFX:JF16M:BLOCKER')
    p.add_argument('-d', '--detector', type=str, default='Jungfrau')
    return p.parse_args(argv)


class DpmApi:
    def __init__(self, app):
        self.spec = getattr(app.args, 'dpm', None)
        self.lock = threading.Lock()
        if not self.spec:
            return
        from psdaq.webgui.netguard import require_loopback_ca_env
        self.ca_conf = require_loopback_ca_env(os.environ, '--dpm')
        a = parse(shlex.split(self.spec))
        self.base, self.detname = a.base_pv, a.detector
        self.npix_ot = self.npix_ot_thresh = self.adu_thresh = 0      # MonitorProgressBar's copies
        self.progress = None
        self.dialog, self.dialogs, self.should_report = None, 0, True
        self.connected, self.sim_pid, self.reads = False, None, 0
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        import epics                                  # after the env check: libca reads EPICS_CA_* from os.environ
        blocked = epics.PV(self.base + ':BLOCKED')
        thresh_pv = epics.PV(self.base + ':NPIX')
        ot_pv = epics.PV(self.base + ':NPIX_OT')
        adu_pv = epics.PV(self.base + ':ADU')
        t_npix_ot_thresh = t_npix_ot = t_adu = 0     # BlockerPVMonitor's copies
        last_ts = -1
        while self.running:
            if blocked.connected:
                ts = blocked.get_timevars()['timestamp']
                npix_ot, thresh, adu = ot_pv.get(), thresh_pv.get(), adu_pv.get()
                with self.lock:
                    self.connected = True
                    self.reads += 1
                    if thresh != t_npix_ot_thresh:
                        t_npix_ot_thresh = self.npix_ot_thresh = thresh
                    if adu != t_adu:
                        t_adu = self.adu_thresh = adu
                    if npix_ot != t_npix_ot:
                        t_npix_ot = npix_ot
                        self._update_progress_bar(npix_ot)
                    if last_ts == -1:
                        last_ts = ts
                    elif last_ts != ts and self.should_report:
                        self.dialogs += 1
                        self.dialog = {'title': '%s Tripped' % self.detname,
                                       'text': '%s pixels over threshold %s' % (npix_ot, adu), 'button': 'Dismiss.',
                                       'n': self.dialogs}
                        self.should_report = False
                if self.sim_pid is None:
                    v = epics.caget(self.base + ':SIM:PID', timeout=1.0)
                    self.sim_pid = int(v) if v is not None else 'none'
            time.sleep(0.05)

    def _update_progress_bar(self, npix_ot):
        self.npix_ot = npix_ot
        try:
            pct = int((self.npix_ot / self.npix_ot_thresh) * 100)
        except (ZeroDivisionError, TypeError):
            return                                    # the PyQt slot raises: the bar keeps its value
        if 0 <= pct <= 100:                           # QProgressBar.setValue ignores a value outside its range
            self.progress = pct

    def status(self, q):
        if not self.spec:
            return 404, {'ok': False, 'err_info': 'no --dpm'}
        with self.lock:
            return 200, {'ok': True, 'title': '%s Detector Protection Monitor' % self.detname, 'info': INFO,
                         'base_pv': self.base, 'detector': self.detname, 'progress': self.progress,
                         'npix_ot': self.npix_ot, 'npix_ot_thresh': self.npix_ot_thresh, 'adu_thresh': self.adu_thresh,
                         'dialog': self.dialog, 'reports': self.should_report, 'connected': self.connected,
                         'reads': self.reads, 'sim_pid': self.sim_pid, 'ca_conf': self.ca_conf}

    def dismiss(self, body):
        if not self.spec:
            return 404, {'ok': False, 'err_info': 'no --dpm'}
        with self.lock:
            if self.dialog is None:
                return 409, {'ok': False, 'err_info': 'no dialog'}
            n = self.dialog['n']
            self.dialog = None
            self.should_report = True                 # reportSignal.emit(True) after msg_box.exec_()
        return 200, {'ok': True, 'dismissed': n}


def register(app, get_routes, post_routes):
    api = DpmApi(app)
    app.dpm_api = api
    get_routes['/api/dpm/status'] = api.status
    post_routes['/api/dpm/dismiss'] = api.dismiss
    return api
