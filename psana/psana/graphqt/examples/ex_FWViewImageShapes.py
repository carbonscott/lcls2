
"""Example/test for ``FWViewImageShapes``: add, delete and switch editing of shapes with keyboard keys.

Running as a script shows a 1000x1000 random image.
"""
from psana.graphqt.FWViewImageShapes import *

class TestFWViewImageShapes(FWViewImageShapes):

      """``FWViewImageShapes`` subclass with keyboard control of shape creation and deletion."""
      def key_usage(self):
        """Return a help string listing the shape and control keys."""
        return 'Keys:'\
               '\n  ESC - exit'\
               '\n  M - add point'\
               '\n  A - add rect'\
               '\n  P - add polyline'\
               '\n  E - add ellipse'\
               '\n  L - add line'\
               '\n  C - add circle'\
               '\n  W - add wedge'\
               '\n  S - switch interactive session between scene and shapes'\
               '\n  D - delete selected item'\
               '\n'


      def keyPressEvent(self, e):
        #print('keyPressEvent, key=', e.key())
        # POINT,   LINE,   RECT,   CIRC,   POLY,   WEDG
        #FWViewImage.keyPressEvent(self, e) # uses Key_R and Key_N

        """Handle keys: M/A/L/C/P/W/E request a new shape, D deletes the selected one, S toggles scene versus shape editing.

        A shape request sets ``add_request`` and disables existing shapes; Escape closes; other keys log
        :meth:`key_usage`.
        """
        d = {Qt.Key_M: POINT, Qt.Key_A: RECT, Qt.Key_L: LINE,\
             Qt.Key_C: CIRC,  Qt.Key_P: POLY, Qt.Key_W: WEDG, Qt.Key_E: ELLIPSE}

        if   e.key() == Qt.Key_Escape:
            self.close()

        elif e.key() in d.keys():
            type = d[e.key()]
            self.add_request = type # e.g. RECT
            logger.info('click-drag-release mouse button on image to add %s' % dic_drag_type_to_name[type])
            self.setShapesEnabled(False)

        elif e.key() == Qt.Key_D:
            logger.info('delete selected item')
            self.delete_item(self.selected_item())

        elif e.key() == Qt.Key_S:
            logger.info('switch interactive session between scene and shapes')

            if self.scale_control():
                self.set_scale_control(scale_ctl='')
                self.setShapesEnabled()
            else:
                self.set_scale_control(scale_ctl='HV')
                self.setShapesEnabled(False)
        else:
            logger.info(self.key_usage())


if __name__ == "__main__":

    logging.basicConfig(format='%(asctime)s %(levelname)s L:%(lineno)03d %(message)s', datefmt='%H:%M:%S', level=logging.DEBUG)

    import os
    os.environ['LIBGL_ALWAYS_INDIRECT'] = '1'

    from PyQt5.QtWidgets import QApplication
    import sys
    import numpy as np
    arr = np.random.random((1000, 1000))
    app = QApplication(sys.argv)
    w = TestFWViewImageShapes(None, arr, origin='UL', scale_ctl='HV')
    w.show()
    app.exec_()
    del w
    del app

# EOF
