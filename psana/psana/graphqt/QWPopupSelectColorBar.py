
"""
:py:class:`QWPopupSelectColorBar` - Popup GUI for selection color table
=======================================================================

Usage::

    # Import
    from psana.graphqt.QWPopupSelectColorBar import QWPopupSelectColorBar

    # Methods - see test

See:
    - :py:class:`QWPopupSelectColorBar`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Created on 2017-01-31 by Mikhail Dubrovin
Adopted for LCLS2 on 2018-02-16 by Mikhail Dubrovin
"""

import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QDialog, QPushButton, QListWidget, QVBoxLayout,\
                            QListWidgetItem, QLabel
from PyQt5.QtCore import Qt, QPoint, QEvent, QSize
from PyQt5.QtGui import QCursor

import psana.graphqt.ColorTable as ct
from psana.graphqt.Styles import style


class QWPopupSelectColorBar(QDialog):

    """Frameless popup dialog listing color tables 1-8 as pixmaps, plus a Cancel button.

    Clicking a list item stores its color table index in ``ctab_selected`` and accepts the dialog; Cancel, closing or window deactivation rejects it.
    """
    def __init__(self, parent=None):

        QDialog.__init__(self, parent)

        self.but_cancel = QPushButton('&Cancel')

        self.ctab_selected = None
        self.list = QListWidget(parent)

        self.fill_list()

        vbox = QVBoxLayout()
        vbox.addWidget(self.list)
        self.setLayout(vbox)

        self.but_cancel.clicked.connect(self.onCancel)
        self.list.itemClicked.connect(self.onItemClick)

        self.set_tool_tips()
        self.set_style()


    def fill_list(self):
        """Fill the list widget with items for color tables 1-8 and a final 'cancel' item.

        Each color item gets ``_coltab_index`` set to its index and a QLabel showing ``ct.get_pixmap(i, size=(200,30))``; the last item holds the Cancel button.
        """
        for i in range(1,9):
           item = QListWidgetItem('%02d'%i, self.list)
           item.setSizeHint(QSize(200,30))
           item._coltab_index = i
           #item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
           lab = QLabel(parent=None)
           lab.setPixmap(ct.get_pixmap(i, size=(200,30)))
           self.list.setItemWidget(item, lab)

        item = QListWidgetItem('cancel', self.list)
        self.list.setItemWidget(item, self.but_cancel)


    def onItemClick(self, item):
        """Store ``item._coltab_index`` in ``self.ctab_selected`` and accept the dialog.

        Connected to ``self.list.itemClicked``.
        """
        self.ctab_selected = item._coltab_index
        logger.debug('onItemClick ctab_selected: %s' % str(self.ctab_selected))
        self.accept()


    def set_style(self):
        """Set the title, fixed width 215, minimum height from the number of list items, frameless window flag, zero margins and Cancel button style, and move the dialog near the cursor."""
        self.setWindowTitle('Select')
        self.setFixedWidth(215)
        lst_len = self.list.__len__()
        self.setMinimumHeight(30*lst_len+10)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.layout().setContentsMargins(0,0,0,0)
        self.but_cancel.setStyleSheet(style.styleButton)
        self.but_cancel.setFixedSize(200,30)
        self.move(QCursor.pos().__add__(QPoint(-110,-50)))


    def set_tool_tips(self):
        """Set the dialog tool tip to 'Select color table'."""
        self.setToolTip('Select color table')


    def mousePressEvent(self, e):
        """If the child widget under the click is a QLabel, store its ``_coltab_index`` in ``ctab_selected`` and accept the dialog.

        The labels created in ``fill_list`` do not set ``_coltab_index`` (it is set on the list items), so this path would raise AttributeError.
        """
        logger.debug('mousePressEvent')
        child = self.childAt(e.pos())
        if isinstance(child, QLabel):
            logger.debug('Selected color table index: %d' % child._coltab_index)
            self.ctab_selected = child._coltab_index
            self.accept()


    def event(self, e):
        #logger.debug('event.type %s' % e.type())
        """Reject the dialog on a ``QEvent.WindowDeactivate`` event, then return ``QDialog.event(self, e)``."""
        if e.type() == QEvent.WindowDeactivate:
            self.reject()
        return QDialog.event(self, e)


    def closeEvent(self, e):
        """Log a debug message and reject the dialog."""
        logger.debug('closeEvent')
        self.reject()


    def selectedColorTable(self):
        """Return the selected color table index stored in ``ctab_selected`` (None if nothing was selected)."""
        return self.ctab_selected


    def onCancel(self):
        """Log a debug message and reject the dialog.

        Connected to the Cancel button.
        """
        logger.debug('onCancel')
        self.reject()


def popup_select_color_table(parent):
    """Show a modal ``QWPopupSelectColorBar`` and return its selected color table index.

    The ``exec_()`` result is ignored; the return value is ``selectedColorTable()``, which is None if nothing was clicked.
    """
    w = QWPopupSelectColorBar(parent)
    resp=w.exec_()
    return w.selectedColorTable()
    #if   resp == QDialog.Accepted: return w.selectedColorTable()
    #elif resp == QDialog.Rejected: return None
    #else: return None

#----------- TESTS ------------

def test_select_color_table(tname):
    """Create a QApplication, open the color table popup and log the selected index.

    ``tname`` is unused. Uses ``sys``, which is imported only in the ``__main__`` block.
    """
    from PyQt5.QtWidgets import QApplication
    logging.basicConfig(format='%(message)s', level=logging.DEBUG)
    app = QApplication(sys.argv)
    ctab_ind = popup_select_color_table(None)
    logger.debug('Selected color table index = %s' % ctab_ind)


if __name__ == "__main__":
    import sys; global sys
    logging.basicConfig(format='[%(levelname).1s] L%(lineno)04d %(name)s : %(message)s', level=logging.DEBUG)
    tname = sys.argv[1] if len(sys.argv) > 1 else '0'
    logger.debug('%s\nTest %s' % (50*'_', tname))
    if   tname == '0': test_select_color_table(tname)
    #elif tname == '1': test_select_icon(tname)
    else: sys.exit('Test %s is not implemented' % tname)
    sys.exit('End of Test %s' % tname)

# EOF
