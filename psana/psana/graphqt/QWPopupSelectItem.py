
"""
:py:class:`QWPopupSelectItem` - Popup GUI for (str) item selection from the list of items
=========================================================================================

Usage::

    # Import
    from psana.graphqt.QWPopupSelectItem import QWPopupSelectItem

    # Methods - see test
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    exp_name = popup_select_item_from_list(None, lst)

See:
    - :py:class:`QWPopupSelectItem`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Created on 2017-01-26 by Mikhail Dubrovin
Adopted for LCLS2 on 2018-02-15
"""

import os
import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QApplication, QDialog, QListWidget, QVBoxLayout, QListWidgetItem# QPushButton
from PyQt5.QtCore import Qt, QPoint, QEvent, QMargins, QSize, QTimer
from PyQt5.QtGui import QCursor, QColor, QBrush


class QWPopupSelectItem(QDialog):

    """Stay-on-top popup dialog that shows a list of strings and returns the clicked one.

    Items ending with ':' are shown as non-selectable yellow titles. A timer re-activates the window every second, and window deactivation rejects the dialog.
    """
    def __init__(self, parent=None, lst=[], show_frame=False, do_sorted=True):

        QDialog.__init__(self, parent, flags=Qt.WindowStaysOnTopHint)

        self.name_sel = None
        self.list = QListWidget(parent=self)
        self.show_frame = show_frame

        self.fill_list(lst, do_sorted)

        vbox = QVBoxLayout()
        vbox.addWidget(self.list)
        self.setLayout(vbox)

        self.list.itemClicked.connect(self.on_item_click)

        self.show_tool_tips()
        self.set_style()

        self.dt_msec=1000
        QTimer().singleShot(self.dt_msec, self.on_timeout)

    def on_timeout(self):
        """Give the dialog focus, raise and activate it, and schedule itself again after ``self.dt_msec`` ms."""
        logger.debug('on_timeout - activate popup window, isActive: %s' % self.isActiveWindow())
        self.setFocus(True)
        self.raise_()
        self.activateWindow()
        QTimer().singleShot(self.dt_msec, self.on_timeout)

    def fill_list(self, lst, do_sorted=True):
        """Clear the list widget and add one item per string of ``lst`` (sorted if ``do_sorted``).

        Strings ending with ':' get black text on yellow background and no item flags; each item gets a size hint of width ``4*len(s)`` and height 15.
        """
        self.list.clear()
        names = sorted(lst) if do_sorted else lst
        for s in names:
            item = QListWidgetItem(s, self.list)
            if s[-1]==':':
                item.setForeground(QBrush(Qt.black))
                item.setBackground(QBrush(Qt.yellow))
                item.setFlags(Qt.NoItemFlags)
            item.setSizeHint(QSize(4*len(s), 15))
        #self.list.sortItems(Qt.AscendingOrder)

    def set_style(self):
        """Set the title, focus policy, zero margins and, unless ``show_frame``, the frameless window flag.

        If the dialog has no parent widget it is moved near the cursor.
        """
        self.setWindowTitle('Select')
        if not self.show_frame:
          self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setEnabled(True)
        self.layout().setContentsMargins(0,0,0,0)
        #self.setMinimumHeight(400)
        parent = self.parentWidget()
        if parent is None:
           self.move(QCursor.pos().__add__(QPoint(-110,-50)))
        logger.debug('use %s position for popup findow' % ('CURSOR' if parent is None else 'BUTTON'))

    def show_tool_tips(self):
        """Set the dialog tool tip to 'Select item from the list'."""
        self.setToolTip('Select item from the list')

    def on_item_click(self, item):
        """Store the clicked item text in ``name_sel`` and accept the dialog.

        For a title item (text ending with ':') it logs a warning and rejects first, but execution continues to ``accept()`` and ``done(QDialog.Accepted)``.
        """
        self.name_sel = item.text()
        logger.debug('on_item_click %s' % self.name_sel)
        if self.name_sel[-1] == ':':
            logger.warning('Clicked on tytle, select other item')
            self.reject()
            self.done(QDialog.Rejected)
        self.accept()
        self.done(QDialog.Accepted)

    def event(self, e):
        #logger.debug('event.type %s' % str(e.type()))
        """Reject the dialog on ``QEvent.WindowDeactivate``, then return ``QDialog.event(self, e)``."""
        if e.type() == QEvent.WindowDeactivate:
            logger.debug('intercepted mouse click outside popup window')
            self.reject()
            self.done(QDialog.Rejected)
        return QDialog.event(self, e)

    def closeEvent(self, e):
        """Log a debug message and reject the dialog."""
        logger.debug('closeEvent')
        self.reject()
        self.done(QDialog.Rejected)

    def selectedName(self):
        """Return the text of the clicked item, or None if nothing was clicked."""
        return self.name_sel

def popup_select_item_from_list(parent, lst, min_height=200, dx=0, dy=0, show_frame=False, do_sorted=True):
    """Show a modal ``QWPopupSelectItem`` for ``lst`` and return the selected string.

    The dialog width is 10 times the longest string length and its height is ``min(min_height, 16*len(lst))``; if ``dx`` or ``dy`` is non-zero it is moved to the cursor position plus that offset.

    Returns
    -------
    str or None
        The selected string, or None if nothing was selected or a title item (ending with ':') was clicked.
    """
    w = QWPopupSelectItem(parent, lst, show_frame, do_sorted)
    #w.setMinimumHeight(min_height)
    size = len(lst)
    nchars = max([len(s) for s in lst])
    height = min(min_height, size*16)
    w.setFixedWidth(10*nchars)
    w.setFixedHeight(height)
    if dx or dy: w.move(QCursor.pos().__add__(QPoint(dx,dy)))
    resp=w.exec_()
    r = w.selectedName()
    return None if r is None or r[-1]==':' else r

if __name__ == "__main__":
  logging.basicConfig(format='[%(levelname).1s] L%(lineno)04d: %(message)s', level=logging.DEBUG)

  def test_select_item_from_list(tname):
    #lst = sorted(os.listdir('/sdf/data/lcls/ds/'))
    """Open the popup for a fixed list of instrument names with a title item and log the result.

    Defined only when the module runs as a script; ``tname`` is unused.
    """
    lst = ('Title:', 'CXI', 'DET', 'MEC', 'MFX', 'XCS', 'XPP')
    logger.debug('lst: %s' % str(lst))
    app = QApplication(sys.argv)
    exp_name = popup_select_item_from_list(None, lst, do_sorted=False)
    logger.debug('exp_name = %s' % exp_name)

if __name__ == "__main__":
    import sys; global sys
    os.environ['LIBGL_ALWAYS_INDIRECT'] = '1'

    tname = sys.argv[1] if len(sys.argv) > 1 else '0'
    logger.debug('%s\nTest %s' % (50*'_', tname))
    if   tname == '0': test_select_item_from_list(tname)
    else: sys.exit('Test %s is not implemented' % tname)
    sys.exit('End of Test %s' % tname)

# EOF
