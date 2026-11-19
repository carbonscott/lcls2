"""Which of upstream dtica's PV monitors stay alive, and which widgets keep updating.

Instrumentation only: upstream dtica and pvedit are imported unchanged.  Every pvedit.Pv is counted (weak
references, so the count does not keep anything alive) together with the class of the object whose update()
it calls, and each update is timed.  dtica's main() body (dtica.py:234-241) runs for SECS seconds, then the
window is saved as PNG.  With --keep, every monitor owner is also kept in a list (what a fix would do).

usage: python stalecheck.py BASE SECS PNG [--keep]
"""
import collections, gc, sys, time, weakref
from PyQt5 import QtCore, QtWidgets

from psdaq.cas import dtica
import psdaq.cas.pvedit as pvedit

base, secs, png, keep = sys.argv[1], float(sys.argv[2]), sys.argv[3], '--keep' in sys.argv
made, alive, upd, kept = collections.Counter(), collections.defaultdict(weakref.WeakSet), [], []
_init = pvedit.Pv.__init__


def counted_init(self, *a, **k):
    cb = a[1] if len(a) > 1 else k.get('callback')
    owner = getattr(cb, '__self__', None)
    cls = type(owner).__name__ if cb is not None else '(no callback)'
    made[cls] += 1
    alive[cls].add(self)
    if keep and owner is not None:
        kept.append(owner)
    if cb is not None:
        def timed(*x, **y):
            upd.append((cls, time.monotonic()))
            return cb(*x, **y)
        a = (a[0], timed) + a[2:] if len(a) > 1 else a
        if 'callback' in k:
            k['callback'] = timed
    _init(self, *a, **k)


pvedit.Pv.__init__ = counted_init
app = QtWidgets.QApplication([])
win = QtWidgets.QMainWindow()
ui = dtica.Ui_MainWindow()
ui.setupUi(win, base)
win.updateGeometry()
win.show()
t0 = time.monotonic()
QtCore.QTimer.singleShot(int(secs * 1000), app.quit)
app.exec_()
win.grab().save(png)
t1 = time.monotonic()
print(f'{base}  {secs:.0f} s  keep={keep}  platform={app.platformName()}  window saved to {png}')
print(f"{'monitor owner':18s} {'created':>8s} {'alive at end':>13s} {'updates 0-5 s':>14s} {'updates, last 5 s':>18s}")
for cls in sorted(made):
    first = sum(1 for c, t in upd if c == cls and t - t0 < 5)
    last = sum(1 for c, t in upd if c == cls and t > t1 - 5)
    print(f'{cls:18s} {made[cls]:8d} {len(alive[cls]):13d} {first:14d} {last:18d}')
print(f"{'total':18s} {sum(made.values()):8d} {sum(len(v) for v in alive.values()):13d}")
