#!/usr/bin/env python

"""Example/test for ``GWViewExt``: views with different origins and scale controls and keyboard control of the scene rect.

Run as a script with test name ``'0'``-``'8'``. Configures root logging at DEBUG level at import time.
"""
from psana.graphqt.GWViewExt import *

logging.basicConfig(format='[%(levelname).1s] %(filename)s L:%(lineno)03d %(message)s', level=logging.DEBUG)

import sys
import inspect
import psana.pyalgos.generic.NDArrGenerators as ag
import numpy as np


class TestGWViewExt(GWViewExt):

    """``GWViewExt`` subclass with key handling for resetting and changing the scene rect."""
    KEY_USAGE = 'Keys:'\
            '\n  ESC - exit'\
            '\n  R - reset original size'\
            '\n  U - update default rect scene to QRectF(-10, -10, 30, 30)'\
            '\n  W - change scene rect, do not change default'\
            '\n  D - change scene rect and its default'\
            '\n'

    def keyPressEvent(self, e):
        #logger.debug('keyPressEvent, key=', e.key())
        """Handle keys: Escape closes, R calls ``reset_scene_rect()``, U resets to rect (-10, -10, 30, 30), W/D set a random rect.

        W and D both call ``reset_scene_rect(rs)``, which also replaces the default rect; the W/D
        difference only changes the printed message. Other keys print ``KEY_USAGE``.
        """
        if   e.key() == Qt.Key_Escape:
            self.close()

        elif e.key() == Qt.Key_R:
            print('Reset original size')
            #self.reset_original_size()
            self.reset_scene_rect()

        elif e.key() == Qt.Key_U:
            print('Update default rect scene')
            #self.reset_original_size()
            self.reset_scene_rect(rs=QRectF(-10, -10, 30, 30))

        elif e.key() in (Qt.Key_W, Qt.Key_D):
            change_def = e.key()==Qt.Key_D
            print('change scene rect %s' % ('set new default' if change_def else ''))
            v = ag.random_standard((4,), mu=0, sigma=3, dtype=np.int32)
            rs = QRectF(v[0]-5, v[1]-5, v[2]+20, v[3]+20)
            print('Set scene rect: %s' % str(rs))
            self.reset_scene_rect(rs)

        else:
            print(self.KEY_USAGE)


def test_fwviewext(tname):
    """Create a ``QApplication`` and show a ``TestGWViewExt`` over scene rect (-10, -10, 30, 30) configured by ``tname``.

    Tests ``'0'``-``'8'`` vary origin (DL, UL, UR, DR), ``scale_ctl`` and ``show_mode``; other names print a
    message and return. Mouse-move, scene-rect and mouse-press signals are connected to the test slots.
    """
    print('%s:' % sys._getframe().f_code.co_name)
    b="background-color:yellow; border: 0px solid green"
    app = QApplication(sys.argv)
    w = None
    if   tname == '0': w=TestGWViewExt(None, rscene=QRectF(-10, -10, 30, 30), origin='DL', show_mode=3, scale_ctl='HV')
    elif tname == '1': w=TestGWViewExt(None, rscene=QRectF(-10, -10, 30, 30), origin='UL', show_mode=3, scale_ctl='HV')
    elif tname == '2': w=TestGWViewExt(None, rscene=QRectF(-10, -10, 30, 30), origin='UR', show_mode=3, scale_ctl='HV')
    elif tname == '3': w=TestGWViewExt(None, rscene=QRectF(-10, -10, 30, 30), origin='DR', show_mode=3, scale_ctl='HV')
    elif tname == '4': w=TestGWViewExt(None, rscene=QRectF(-10, -10, 30, 30), origin='DL', show_mode=3, scale_ctl='')
    elif tname == '5': w=TestGWViewExt(None, rscene=QRectF(-10, -10, 30, 30), origin='DL', show_mode=3, scale_ctl='H')
    elif tname == '6': w=TestGWViewExt(None, rscene=QRectF(-10, -10, 30, 30), origin='DL', show_mode=3, scale_ctl='V')
    elif tname == '7': w=TestGWViewExt(None, rscene=QRectF(-10, -10, 30, 30), origin='DL', show_mode=1, scale_ctl='HV')
    elif tname == '8': w=TestGWViewExt(None, rscene=QRectF(-10, -10, 30, 30), origin='DL', show_mode=3, scale_ctl='HV')
    else:
        print('test %s is not implemented' % tname)
        return

    w.connect_mouse_move_event(w.test_mouse_move_event_reception)
    w.connect_scene_rect_changed(w.test_scene_rect_changed_reception)
    w.connect_mouse_press_event(w.test_mouse_press_event_reception)

    w.setWindowTitle('ex_GWViewExt')
    w.setGeometry(20, 20, 600, 600)
    w.show()

    #w.disconnect_mouse_move_event(w.test_mouse_move_event_reception)
    #w.disconnect_scene_rect_changed(w.test_scene_rect_changed_reception)
    #w.disconnect_mouse_press_event(w.test_mouse_press_event_reception)
    #w.close()

    app.exec_()
    app.quit()

    del w
    del app

SCRNAME = sys.argv[0].split('/')[-1]

USAGE = '\nUsage: python %s <tname [0-8]>' % SCRNAME\
      + '\n'.join([s for s in inspect.getsource(test_fwviewext).split('\n') if "tname ==" in s]) \
      + '\n then activate graphics window and use keyboad keys R/W/D/<Esc>'

if __name__ == "__main__":
    import os
    os.environ['LIBGL_ALWAYS_INDIRECT'] = '1'
    tname = sys.argv[1] if len(sys.argv) > 1 else '0'
    print(50*'_', '\nTest %s' % tname)
    test_fwviewext(tname)
    print(USAGE)
    sys.exit('End of Test %s' % tname)

# EOF
