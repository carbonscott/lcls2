
"""
Class :py:class:`DragPoint` - for draggable shape item
========================================================

Created on 2016-10-11 by Mikhail Dubrovin
"""
import logging
logger = logging.getLogger(__name__)

from PyQt5.QtGui import QBrush, QPen, QPainterPath#, QCursor
from PyQt5.QtCore import Qt, QPointF, QPoint, QRectF #, QPoint, QRect, QRectF
from PyQt5.QtWidgets import QGraphicsPathItem # QApplication

from psana.graphqt.DragBase import DragBase, FROZEN, ADD, MOVE, EDIT, DELETE, POINT #, dic_mode_type_to_name


class DragPoint(QGraphicsPathItem, DragBase):
                # QPointF, QGraphicsItem, QGraphicsScene
    """QGraphicsPathItem plus DragBase that draws a small selectable, movable marker at ``point``.

    ``pshape`` selects the marker path: 'v' rhombus, 'h' rectangle, 'w', 'z', 'x', 'c' other outlines, anything else an ellipse; its size ``rsize`` is in view pixels converted to scene units. The item adds itself to ``scene`` when it has no parent and starts in ADD drag mode.
    """
    def __init__(self, point=QPointF(0,0), parent=None, scene=None,\
                 brush=QBrush(Qt.white, Qt.SolidPattern),\
                 pen=QPen(Qt.black, 2, Qt.SolidLine),\
                 pshape='v', rsize=7):
        """pshape (char) point shape: h-horizontal rectangular, v-rombic, r-radial (ellyptical)
        """

        self._lst_circle = None

        self._dragtype = POINT

        self.rsize = rsize
        self.point_center = point

        path = self.pathForPointV(point, scene, rsize) if pshape=='v' else\
               self.pathForPointH(point, scene, rsize) if pshape=='h' else\
               self.pathForPointW(point, scene, rsize) if pshape=='w' else\
               self.pathForPointZ(point, scene, rsize) if pshape=='z' else\
               self.pathForPointX(point, scene, rsize) if pshape=='x' else\
               self.pathForPointC(point, scene, rsize) if pshape=='c' else\
               self.pathForPointR(point, scene, rsize)

        QGraphicsPathItem.__init__(self, path, parent)
        if (parent is None) and (scene is not None): scene.addItem(self)
        DragBase.__init__(self, parent, brush, pen)

        self.setTransformOriginPoint(point)

        self.setAcceptHoverEvents(True)
        self.setAcceptTouchEvents(True)
        #self.setAcceptedMouseButtons(Qt.LeftButton)

        self.setPen(self._pen_pos)
        self.setBrush(self._brush)
        self.setFlags(self.ItemIsSelectable | self.ItemIsMovable)

        #self.setBoundingRegionGranularity(0.95)
        self._drag_mode = ADD
        #self.grabMouse() # makes available mouseMoveEvent


#    def boundingRect(self):
#        """Re-implements superclass method.
#        """
#        r = self.rsize
#        c = self.point_center
#        return QRectF(c.x()-r, c.x()+r, c.y()-r, c.y()+r)


    def size_on_scene(self, scene, rsize):
        """Return ``rsize`` converted to scene units in x and y using the scale of the first view of ``scene``.

        Also stores the view scales in ``self.scx0`` and ``self.scy0``.

        Returns
        -------
        tuple of float
            ``(rsize/m11, rsize/m22)`` of the view transform.
        """
        t = scene.views()[0].transform()
        self.scx0, self.scy0 = t.m11(), t.m22()
        return rsize/self.scx0, rsize/self.scy0


    def size_points_on_scene(self, scene, rsize):
        """Return the scene-unit sizes from ``size_on_scene`` as two offset points ``(QPointF(rx, 0), QPointF(0, ry))``."""
        rx, ry = self.size_on_scene(scene, rsize)
        return QPointF(rx,0), QPointF(0,ry)


    def pathForPointH(self, p, scene, rsize=7):
        """ point shape - horizantal rectangular
        """
        dx, dy = self.size_points_on_scene(scene, rsize)
        path = QPainterPath(p+dx+dy)
        path.lineTo(p-dx+dy)
        path.lineTo(p-dx-dy)
        path.lineTo(p+dx-dy)
        path.closeSubpath()
        return path


    def pathForPointV(self, p, scene, rsize=7):
        """ rombic - shaped point
        """
        dx, dy = self.size_points_on_scene(scene, rsize)
        path = QPainterPath(p+dx)
        path.lineTo(p+dy)
        path.lineTo(p-dx)
        path.lineTo(p-dy)
        path.closeSubpath()
        return path


    def pathForPointW(self, p, scene, rsize=7):
        """ W-shaped point
        """
        dx, dy = self.size_points_on_scene(scene, rsize)
        path = QPainterPath(p+dx+dy)
        path.lineTo(p-dx-dy)
        path.lineTo(p-dx+dy)
        path.lineTo(p+dx-dy)
        path.closeSubpath()
        return path


    def pathForPointZ(self, p, scene, rsize=7):
        """ Z-shaped point
        """
        dx, dy = self.size_points_on_scene(scene, rsize)
        path = QPainterPath(p+dx)
        path.lineTo(p-dx)
        path.lineTo(p+dy)
        path.lineTo(p-dy)
        path.closeSubpath()
        return path


    def pathForPointX(self, p, scene, rsize=7):
        """ X-shaped point
        """
        dx, dy = self.size_points_on_scene(scene, rsize)
        path = QPainterPath(p+dx)
        path.lineTo(p+dy)
        path.lineTo(p-dy)
        path.lineTo(p-dx)
        path.closeSubpath()
        return path


    def pathForPointC(self, p, scene, rsize=7):
        """ C-center point
        """
        dx, dy = self.size_points_on_scene(scene, rsize)
        path = QPainterPath(p-dy)
        path.lineTo(p+dy)
        path.lineTo(p-dx/5+dy/5)
        path.lineTo(p-dx)
        path.lineTo(p+dx)
        path.lineTo(p)
        path.closeSubpath()
        return path


    def pathForPointR(self, p, scene, rsize=5):
        """ point shape - Ellipse
        """
        rx, ry = self.size_on_scene(scene, rsize)
        path = QPainterPath()
        path.addEllipse(p, rx, ry)
        return path


    def listOfCirclePoints(self, p, rx=5, ry=5, np=12):
        """Return a cached list of ``np`` integer QPoints at angles i*pi/np (i = 0..np-1) on an ellipse of radii ``rx``, ``ry`` around ``p``.

        The angles cover half a turn. The list is built on the first call only; later calls return it unchanged regardless of the arguments.
        """
        if self._lst_circle is None:
            from math import cos, sin, pi, ceil
            dphi = pi/np
            lst_sc = [(sin(i*dphi),cos(i*dphi)) for i in range(np)]
            self._lst_circle = [QPoint(ceil(p.x()+rx*c), ceil(p.y()+ry*s)) for s,c in lst_sc]
        return self._lst_circle


    def mousePressEvent(self, e):
        """Log the press position, select the item, forward the event to the base class and then to the parent item, if any."""
        pe = e.pos()
        ps = e.scenePos()
        pc = self.path().currentPosition()
        logger.debug('DragPoint.mousePressEvent at point (%6.1f, %6.1f) on scene (%6.1f, %6.1f) currentPosition (%6.1f, %6.1f)'%
                      (pe.x(), pe.y(), ps.x(), ps.y(), pc.x(), pc.y()))
        self.setSelected(True)
        #print("DragPoint is selected: ", self.isSelected())
        QGraphicsPathItem.mousePressEvent(self, e)
        parent = self.parentItem()
        if parent is not None: parent.mousePressEvent(e)


    def mouseMoveEvent(self, e):
        #logger.debug('DragPoint:mouseMoveEvent at point: (%.1f, %.1f)' % (e.pos().x(),  e.pos().y()))
                     #(str(e.pos()), str(e.scenePos()))) # self.__class__.__name__
        """Forward the event to the base class and then to the parent item, if any."""
        QGraphicsPathItem.mouseMoveEvent(self, e)
        if self.parentItem() is not None: self.parentItem().mouseMoveEvent(e)


    def mouseReleaseEvent(self, e):
        """Log the release position, deselect the item and forward the event; if the drag mode was ADD, call ``set_drag_mode()``; then forward the event to the parent item, if any."""
        pe = e.pos()
        ps = e.scenePos()
        logger.debug('DragPoint.mouseReleaseEvent at point (%6.1f, %6.1f) on scene (%6.1f, %6.1f)'%
                      (pe.x(), pe.y(), ps.x(), ps.y()))
        self.setSelected(False)
        QGraphicsPathItem.mouseReleaseEvent(self, e)
        if self._drag_mode == ADD:
            self.set_drag_mode()
        if self.parentItem() is not None: self.parentItem().mouseReleaseEvent(e)


#    def wheelEvent(self, e):
#        QGraphicsPathItem.wheelEvent(self, e)
#        print('%s.wheelEvent, at point: ' % self.__class__.__name__, e.pos()) #e.globalX(), e.globalY())

#        print('%s.mouseReleaseEvent isSelected():' % self.__class__.__name__, self.isSelected())
#            self.ungrabMouse()
#        if self.parentItem() is not None: self.parentItem().setEnabled(True)
#        self.setSelected(False)
#        print('mouseReleaseEvent')
#        QGraphicsPathItem.mouseReleaseEvent(self, e)
#        QApplication.setOverrideCursor(QCursor(self.hover_cursor))
#        QApplication.restoreOverrideCursor()

#    def hoverEnterEvent(self, e):
#        print('%s.hoverEnterEvent' % self.__class__.__name__)
#        QGraphicsPathItem.hoverEnterEvent(self, e)
#        #QApplication.setOverrideCursor(QCursor(self.hover_cursor))

#    def hoverLeaveEvent(self, e):
#        print('%s.hoverLeaveEvent' % self.__class__.__name__)
#        QGraphicsPathItem.hoverLeaveEvent(self, e)
#        #QApplication.setOverrideCursor(QCursor(self.hover_cursor))
#        #QApplication.restoreOverrideCursor()

#    def hoverMoveEvent(self, e):
#        #print('%s.hoverMoveEvent' % self.__class__.__name__)
#        QGraphicsPathItem.hoverMoveEvent(self, e)


#    def mouseDoubleClickEvent(self, e):
#        QGraphicsPathItem.hoverLeaveEvent(self, e)
#        print('%s.mouseDoubleClickEvent, at point: ' % self.__class__.__name__, e.pos() #e.globalX(), e.globalY())

#    def focusInEvent(self, e):
#        """for keyboard events"""
#        print('DragPoint.focusInEvent, at point: ', e.pos())

#    def focusOutEvent(self, e):
#        """for keyboard events"""
#        print('DragPoint.focusOutEvent, at point: ', e.pos())

#    def emit_signal(self, msg='click'):
#        self.emit(QtCore.SIGNAL('event_on_rect(QString)'), msg)
#        #print(msg)


if __name__ == "__main__":
    print('Self test is not implemented...')
    print('use > python FWViewImageShapes.py')

# EOF
