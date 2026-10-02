
"""
:py:class:`QWGraphicsRectItem` - derived from QWGraphicsRectItem to intercept events
=========================================================================================

Usage::

    # Import
    from psana.graphqt.QWGraphicsRectItem import WGraphicsRectItem

    # Methods - see test

See:
    - :py:class:`QWGraphicsRectItem`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Created on 2016-06-12 by Mikhail Dubrovin
Adopted for LCLS2 on 2018-02-16
"""

import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QGraphicsRectItem, QApplication
from PyQt5.QtCore import Qt, pyqtSignal # , QPoint, QEvent, QMargins
from PyQt5.QtGui import QCursor


class QWGraphicsRectItem(QGraphicsRectItem):
    #                  QRectF, QGraphicsItem, QGraphicsScene

    """QGraphicsRectItem that accepts hover and touch events and changes the application override cursor on hover and mouse press.

    If ``scene`` is given the item adds itself to it. The class declares ``event_on_rect = pyqtSignal('QString')`` although it does not derive from QObject.
    """
    event_on_rect = pyqtSignal('QString')

    def __init__(self, rect, parent=None, scene=None):
        #QGraphicsRectItem.__init__(self, rect, parent, scene)
        QGraphicsRectItem.__init__(self, rect, parent)
        if scene is not None: scene.addItem(self)

        self.setAcceptHoverEvents(True)
        self.setAcceptTouchEvents(True)
        #self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursorHover()
        self.setCursorGrab()


    def setCursorHover(self, cursor=Qt.CrossCursor):
        #QGraphicsRectItem.setCursor(self, cursor)
        """Store ``cursor`` in ``self.hover_cursor``; it is used as override cursor on hover enter."""
        self.hover_cursor = cursor


    def setCursorGrab(self, cursor=Qt.SizeAllCursor): # Qt.ClosedHandCursor):
        """Store ``cursor`` in ``self.grub_cursor``; it is used as override cursor on mouse press."""
        self.grub_cursor = cursor


    def hoverEnterEvent(self, e):
        #logger.debug('hoverEnterEvent')
        """Forward the event to the base class and set the application override cursor to ``self.hover_cursor``."""
        QGraphicsRectItem.hoverEnterEvent(self, e)
        QApplication.setOverrideCursor(QCursor(self.hover_cursor))


    def hoverLeaveEvent(self, e):
        #logger.debug('hoverLeaveEvent')
        """Forward the event to the base class and restore the application override cursor."""
        QGraphicsRectItem.hoverLeaveEvent(self, e)
        #QtWidgets.QApplication.setOverrideCursor(QCursor(self.hover_cursor))
        QApplication.restoreOverrideCursor()


    def hoverMoveEvent(self, e):
        #logger.debug('hoverMoveEvent')
        """Forward the event to ``QGraphicsRectItem.hoverMoveEvent``."""
        QGraphicsRectItem.hoverMoveEvent(self, e)


    def mouseMoveEvent(self, e):
        """Log a debug message and forward the event to the base class."""
        logger.debug('QWGraphicsRectItem: mouseMoveEvent')
        QGraphicsRectItem.mouseMoveEvent(self, e)


    def mousePressEvent(self, e):
        #logger.debug('mousePressEvent, at point: ', e.pos() #e.globalX(), e.globalY())
        """Forward the event to the base class and set the application override cursor to ``self.grub_cursor``."""
        QGraphicsRectItem.mousePressEvent(self, e)
        QApplication.setOverrideCursor(QCursor(self.grub_cursor))


    def mouseReleaseEvent(self, e):
        """ !!! This method does not receive control because module is distracted before...
        """
        #logger.debug('mouseReleaseEvent')
        QGraphicsRectItem.mouseReleaseEvent(self, e)
        #QApplication.setOverrideCursor(QCursor(self.hover_cursor))
        QApplication.restoreOverrideCursor()


    def emit_signal(self, msg='click'):
        #self.emit(QtCore.SIGNAL('event_on_rect(QString)'), msg)
        """Call ``self.event_on_rect.emit(msg)``.

        The class is not a QObject subclass, so the class-level pyqtSignal is not bound to instances; not verified at runtime.
        """
        self.event_on_rect.emit(msg)
        #logger.debug(msg)

# EOF
