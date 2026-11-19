"""Count the Qt widget calls upstream dtica makes from threads other than the GUI thread.

Instrumentation only: upstream code is imported unchanged.  QLabel.setText and QAbstractButton.setChecked are
wrapped to record the calling thread, then dtica's main() body (psdaq/psdaq/cas/dtica.py:234-241) runs for SECS
seconds.  usage: python threadcheck.py BASE SECS
"""
import collections, gc, sys, threading, weakref
from PyQt5 import QtCore, QtWidgets, sip

calls = collections.Counter()


def wrap(cls, name):
    orig = getattr(cls, name)

    def w(self, *a, **k):
        py_gui = threading.current_thread() is threading.main_thread()                     # Python's view
        qt_gui = (sip.unwrapinstance(QtCore.QThread.currentThread()) ==                       # Qt's own view
                  sip.unwrapinstance(QtCore.QCoreApplication.instance().thread()))
        calls[(f'{cls.__name__}.{name}', 'GUI thread' if py_gui else 'other thread',
               'GUI thread' if qt_gui else 'other thread')] += 1
        return orig(self, *a, **k)
    setattr(cls, name, w)


wrap(QtWidgets.QLabel, 'setText')
wrap(QtWidgets.QAbstractButton, 'setChecked')

from psdaq.cas import dtica                       # noqa: E402  (after wrapping, as dtica imports pvedit)
import psdaq.cas.pvedit as pvedit                 # noqa: E402

pvs, made = weakref.WeakSet(), [0]                # how many pvedit.Pv monitors exist, and how many survive
_init = pvedit.Pv.__init__


def counted_init(self, *a, **k):
    made[0] += 1
    pvs.add(self)
    _init(self, *a, **k)


pvedit.Pv.__init__ = counted_init

app = QtWidgets.QApplication([])
win = QtWidgets.QMainWindow()
ui = dtica.Ui_MainWindow()
ui.setupUi(win, sys.argv[1])
win.updateGeometry()
win.show()
QtCore.QTimer.singleShot(int(float(sys.argv[2]) * 1000), app.quit)
app.exec_()
print('platform', app.platformName(), ' pvedit', pvedit.__file__)
print(f'pvedit.Pv objects: {made[0]} created, {len(pvs)} still alive at exit; gc collections {[g["collections"] for g in gc.get_stats()]}')
print(f"{'widget method':32s} {'thread (Python)':16s} {'thread (Qt)':13s} calls")
for (fn, py, qt), n in sorted(calls.items()):
    print(f'{fn:32s} {py:16s} {qt:13s} {n:5d}')
off = sum(n for (fn, py, qt), n in calls.items() if py != 'GUI thread')
qoff = sum(n for (fn, py, qt), n in calls.items() if qt != 'GUI thread')
print(f'widget calls off the GUI thread in {sys.argv[2]} s: {off} (Python), {qoff} (Qt)')
