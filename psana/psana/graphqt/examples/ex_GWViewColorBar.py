#!/usr/bin/env python

"""Example/test for ``GWViewColorBar``: a subclass with keyboard control of the color table.

Run as a script with test name ``'0'`` (horizontal bar) or ``'1'`` (vertical bar). The module-level
``USAGE`` refers to ``test_gfviewcolorbar``, which is defined only under ``__main__``, so importing the
module raises NameError.
"""
import inspect
from psana.graphqt.GWViewColorBar import *

SCRNAME = sys.argv[0].split('/')[-1]

class TestGWViewColorBar(GWViewColorBar):

    """``GWViewColorBar`` subclass with key handling for resetting and cycling the color table."""
    KEY_USAGE = 'Keys:'\
            '\n  ESC - exit'\
            '\n  R - reset color table 0'\
            '\n  N - set next color table'\
            '\n'

    def keyPressEvent(self, e):
        #print('keyPressEvent, key=', e.key())

        """Handle keys if bit 0 of ``change_mode`` is set: Escape closes, R selects table 0, N the next table, others print ``KEY_USAGE``."""
        if not (self.change_mode & 1): return

        if   e.key() == Qt.Key_Escape:
            self.close()

        elif e.key() == Qt.Key_R:
            print('Reset original size')
            self.set_colorbar_table_ind(ctab_ind=0)

        elif e.key() == Qt.Key_N:
            print('Set next color table')
            self.set_colorbar_table_ind(ctab_ind=None)

        else:
            print(self.KEY_USAGE)


if __name__ == "__main__":

  import os
  import sys
  logging.basicConfig(format='[%(levelname).1s] %(filename)s L:%(lineno)03d %(message)s', level=logging.DEBUG)
  os.environ['LIBGL_ALWAYS_INDIRECT'] = '1' #export LIBGL_ALWAYS_INDIRECT=1

  def test_gfviewcolorbar(tname):
    """Create a ``QApplication`` and show a ``TestGWViewColorBar`` with a 1000-color rainbow table.

    Test ``'0'`` makes a horizontal bar with ``change_mode=1`` and ``scale_ctl='H'``, ``'1'`` a vertical
    bar; other names print a message and return. Test slots are connected to the mouse-move,
    index-selected, new-color-table and scene-rect signals.
    """
    print('%s:' % sys._getframe().f_code.co_name)
    arr = np.random.random((1000, 100))
    #arr = image_with_random_peaks((1000, 1000))
    ctab = ct.color_table_rainbow(ncolors=1000, hang1=250, hang2=-20)
    #ctab = ct.color_table_monochr256()
    #ctab = ct.color_table_interpolated()

    app = QApplication(sys.argv)
    w = None
    if   tname == '0': w = TestGWViewColorBar(None, coltab=ctab, orient='H', change_mode=1, scale_ctl='H')
    elif tname == '1': w = TestGWViewColorBar(None, coltab=ctab, orient='V')
    else:
        print('test %s is not implemented' % tname)
        return

    #w.setWindowTitle(w._name)
    w.setWindowTitle(SCRNAME)
    w.setGeometry(100, 20, 600, 600)

    w.connect_mouse_move_event(w.test_mouse_move_event_reception)
    w.connect_new_color_table_index_is_selected(w.test_new_color_table_index_is_selected_reception)
    w.connect_new_color_table(w.test_new_color_table_reception)
    w.connect_scene_rect_changed(w.test_scene_rect_changed_reception)

    w.show()
    app.exec_()

    del w
    del app

USAGE = '\nUsage: %s <tname>\n' % SCRNAME\
      + '\n'.join([s for s in inspect.getsource(test_gfviewcolorbar).split('\n') if "tname ==" in s])


if __name__ == "__main__":
    tname = sys.argv[1] if len(sys.argv) > 1 else '0'
    print(50*'_', '\nTest %s' % tname)
    test_gfviewcolorbar(tname)
    print(USAGE)
    sys.exit('End of Test %s' % tname)

# EOF
