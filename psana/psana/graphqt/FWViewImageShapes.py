
"""
Class :py:class:`FWViewImageShapes` is a QWidget for interactive image
==========================================================================

Usage ::

    import sys
    import numpy as np
    from psana.graphqt.FWViewImageShapes import *
    arr = np.random.random((1000, 1000))
    app = QApplication(sys.argv)
    w = FWViewImageShapes(None, arr, origin='UL', scale_ctl='HV', rulers='UDLR')
    w.show()
    app.exec_()

Created on 2016-10-10 by Mikhail Dubrovin
"""

import logging
logger = logging.getLogger(__name__)

from PyQt5.QtCore import Qt #, QPointF#, QRect, QRectF

import psana.graphqt.ColorTable as ct
from psana.graphqt.FWViewImage import FWViewImage
from psana.graphqt.DragTypes import POINT, LINE, RECT, CIRC, POLY, WEDG, ELLIPSE,\
                      dic_drag_type_to_name, dic_drag_name_to_type
from psana.graphqt.DragFactory import add_item, DragPoint
from psana.graphqt.DragBase import FROZEN, ADD, MOVE, EDIT, DELETE

class FWViewImageShapes(FWViewImage):

    """``FWViewImage`` that lets the user add, select and delete draggable shapes (from ``DragFactory``) on the image.

    Set ``add_request`` to a drag type (POINT, LINE, RECT, ...) to add that shape at the next mouse press.
    """
    def __init__(self, parent=None, arr=None,\
                 coltab=ct.color_table_rainbow(ncolors=1000, hang1=250, hang2=-20),\
                 origin='UL', scale_ctl='HV'):

        FWViewImage.__init__(self, parent, arr, coltab, origin, scale_ctl)

        self.add_request=None
        self.lst_drag_items = []
        self.scale_ctl_normal = scale_ctl

        self.connect_scene_rect_changed(self.on_scene_rect_changed)


    def on_scene_rect_changed(self):
        """Re-scale scene items on zoom-in/out
        """
        scx, scy = self.transform().m11(), self.transform().m22()
        print('on_scene_rect_changed: scalex=%.3f, scaley=%.3f' %(scx, scy))

        for item in self.scene().items():
            if isinstance(item, DragPoint):
                 item.setScale(item.scx0/scx)


    def setShapesEnabled(self, is_enabled=True):
        """Enable or disable all items in ``lst_drag_items``."""
        for item in self.lst_drag_items: item.setEnabled(is_enabled)


    def selected_item(self):
        """Return the first item in ``lst_drag_items`` that is selected, or None."""
        for item in self.lst_drag_items:
            if item.isSelected(): return item
        return None


    def item_marked_to_delete(self):
        """Return the first item in ``lst_drag_items`` whose mode is ``DELETE``, or None."""
        for item in self.lst_drag_items:
            if item.mode() == DELETE: return item
        return None


    def mousePressEvent(self, e):
        """Handle a mouse press: add a requested shape, delete a marked shape, or set the scale control.

        After the base-class handling, if ``add_request`` is set a new item is created with ``add_item``
        at the scene point, selected and appended to ``lst_drag_items``. Otherwise a DELETE-marked item is
        deleted, or scale control is disabled while an item is selected and restored when none is.
        """
        scpoint = self.mapToScene(e.pos())
        print('==== click')
        logger.debug('FWViewImageShapes.mousePressEvent but=%d %s scene x=%.1f y=%.1f'%\
                     (e.button(), str(e.pos()), scpoint.x(), scpoint.y())) # self.__class__.__name__

        #print('XXX DragPoly.mousePressEvent button L/R/M = 1/2/4: ', e.button())
        #print('XXX DragPoly.mousePressEvent Left: ', e.button()==Qt.LeftButton)

        FWViewImage.mousePressEvent(self, e) # to select/deselect items

        if self.add_request is not None:
            self.set_scale_control('')

            logger.debug('process request to add %s' % dic_drag_type_to_name[self.add_request])
            parent = None if self.add_request in (POINT,LINE,CIRC,WEDG,POLY) else self
            #parent = None if self.add_request == RECT else self
            item = add_item(self.add_request, scpoint, parent, scene=self.scene())
            item.setZValue(100 if self.add_request == POINT else 30)
            item.setSelected(True)
            self.lst_drag_items.append(item)
            return

        item_del = self.item_marked_to_delete()
        #print('item_marked_to_delete', item_del)
        if item_del is not None:
            self.delete_item(item_del)
            return

        if self.selected_item() is None:
            self.set_scale_control(scale_ctl=self.scale_ctl_normal)
            #FWViewImage.mousePressEvent(self, e) # to move pixmap on click
        else:
            self.set_scale_control(scale_ctl='')


    def mouseReleaseEvent(self, e):
        #logger.debug('%s.mouseReleaseEvent pos: %s' % (self.__class__.__name__, str(e.pos())))
        """Pass the event to the base class; if a shape was being added, re-enable all shapes and clear ``add_request``."""
        FWViewImage.mouseReleaseEvent(self, e)

        if self.add_request is not None:
            self.setShapesEnabled()
            self.add_request = None


    def closeEvent(self, e):
        """Pass the event to ``FWViewImage.closeEvent``."""
        FWViewImage.closeEvent(self, e)
        #print('FWViewImage.closeEvent' # % self._name)


    def delete_item(self, item):
        """Remove ``item`` from the scene and from ``lst_drag_items``, disable scale control and re-enable shapes.

        Does nothing if ``item`` is None.
        """
        if item is None: return

        self.set_scale_control('')
        self.scene().removeItem(item)
        self.lst_drag_items.remove(item)
        self.setShapesEnabled()


if __name__ == "__main__":
    import sys
    import psana.graphqt.QWUtils as qu
    sys.exit(qu.msg_on_exit())

# EOF
