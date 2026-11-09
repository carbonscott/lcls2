"""Window grabs for an offscreen PyQt program (psdaq.sim.ami_shot), with no change to the program.

This directory goes first on PYTHONPATH of that one program only, with DAQ_SIM_GRAB_DIR set; Python
then imports this module at startup (the site module's sitecustomize hook), in the program and in
every Python process it starts.  Every QApplication made from then on saves each visible top-level
window to <DAQ_SIM_GRAB_DIR>/<window title>.<pid>.png every DAQ_SIM_GRAB_MS ms (default 2000), with
QWidget.grab(), which renders the window offscreen, and appends one line per grab to index.jsonl
there.  Without DAQ_SIM_GRAB_DIR it does nothing.
"""

import os


def _install(outdir):
    import json
    import re
    import time
    from PyQt5 import QtCore, QtWidgets
    base = QtWidgets.QApplication
    if getattr(base, '_daq_sim_grab', False):
        return
    period = int(os.environ.get('DAQ_SIM_GRAB_MS', '2000'))

    class GrabApplication(base):
        _daq_sim_grab = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._daq_sim_timer = QtCore.QTimer()
            self._daq_sim_timer.timeout.connect(self._daq_sim_grab_windows)
            self._daq_sim_timer.start(period)

        def _daq_sim_grab_windows(self):
            for w in self.topLevelWidgets():
                try:
                    if not w.isVisible() or w.width() < 32 or w.height() < 32:
                        continue
                    title = w.windowTitle() or type(w).__name__
                    name = re.sub(r'[^A-Za-z0-9_.:-]+', '_', title)[:80]
                    path = os.path.join(outdir, f'{name}.{os.getpid()}.png')
                    if w.grab().save(path + '.tmp.png'):
                        os.replace(path + '.tmp.png', path)
                        with open(os.path.join(outdir, 'index.jsonl'), 'a') as f:
                            f.write(json.dumps({'time': time.time(), 'pid': os.getpid(), 'title': title,
                                                'class': type(w).__name__, 'size': [w.width(), w.height()],
                                                'png': path}) + '\n')
                except Exception:
                    pass

    QtWidgets.QApplication = GrabApplication


if os.environ.get('DAQ_SIM_GRAB_DIR'):
    try:
        os.makedirs(os.environ['DAQ_SIM_GRAB_DIR'], exist_ok=True)
        _install(os.environ['DAQ_SIM_GRAB_DIR'])
    except Exception as e:                  # never stop the program
        print(f'psdaq.sim qtgrab: not installed: {type(e).__name__}: {e}', flush=True)
