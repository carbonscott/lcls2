
"""
:py:class:`QWPopupSelectItem` - Popup GUI for (str) item selection from the list of items
=========================================================================================

Usage::

    # Import
    from psdaq.control_gui.QWPopupSelectItem import QWPopupSelectItem

    # Methods - see test
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    selected = popup_select_item_from_list(None, lst)

See:
    - :py:class:`QWPopupSelectItem`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2/psdaq/psdaq/control_gui>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Copied from graphqt on 2018-03-26 by Mikhail Dubrovin
Adopted for LCLS2 on 2018-02-15
"""

from PyQt5.QtWidgets import QDialog, QListWidget, QVBoxLayout, QListWidgetItem, QSizePolicy# QPushButton
from PyQt5.QtCore import Qt, QPoint, QEvent, QMargins, QSize
from PyQt5.QtGui import QCursor

class QWPopupSelectItem(QDialog) :

    """Frameless popup QDialog listing strings; clicking one stores it and accepts the dialog.

    The list is sorted unless `do_sort` is False. Losing window focus or closing rejects
    the dialog.
    """
    def __init__(self, parent=None, lst=[], do_sort=True):

        QDialog.__init__(self, parent)

        self.name_sel = None
        self.do_sort = do_sort
        self._list = QListWidget(parent)
        self.fill_list(lst)

        vbox = QVBoxLayout()
        vbox.addWidget(self._list)
        self.setLayout(vbox)

        self.show_tool_tips()
        self.set_style()
        self._list.itemClicked.connect(self.on_item_click)


    def fill_list(self, lst) :
        """Fill the list widget from `lst` (sorted if `do_sort`), recording the longest length and row count.

        Does nothing if `lst` is empty, in which case `nchars`/`nrows` stay undefined and
        `set_style` would raise AttributeError.
        """
        if not lst : return
        self.nchars = max([len(s) for s in lst])
        self.nrows  = len(lst)
        self._list.clear()

        list_to_show = sorted(lst) if self.do_sort else lst
        for txt in list_to_show  :
            item = QListWidgetItem(txt, self._list)
            item.setSizeHint(QSize(50,20))
        #self._list.sortItems(Qt.AscendingOrder)


    def set_style(self):
        """Set title 'Select', make the window frameless, zero margins and fix the size from `nchars` and `nrows`."""
        self.setWindowTitle('Select')
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.layout().setContentsMargins(0,0,0,0)

        width  = min(self.nchars*12, 300) + (40 if self.nchars==1 else 22)
        height = min(self.nrows *20, 500) + 2
        self.setFixedSize(width,height)

        #self.but_cancel.setStyleSheet(style.styleButton)
        #self.move(QCursor.pos().__add__(QPoint(-110,-50)))


    def show_tool_tips(self):
        """Set the tool tip to 'Select item from the list.'."""
        self.setToolTip('Select item from the list.')


    def on_item_click(self, item):
        #widg = self._list.itemWidget(item)
        #item.checkState()
        """Store the clicked item's text in `name_sel` and accept the dialog."""
        self.name_sel = item.text()
        #logger.debug('on_item_click: selected %s' % self.name_sel)
        self.accept()


    #def mousePressEvent(self, e):
    #    logger.debug('mousePressEvent')


    def event(self, e):
        #logger.debug('event.type', e.type())
        """Reject the dialog on QEvent.WindowDeactivate, then return `QDialog.event(self, e)`."""
        if e.type() == QEvent.WindowDeactivate :
            self.reject()
        return QDialog.event(self, e)


    def closeEvent(self, e) :
        """Reject the dialog."""
        self.reject()


    def selectedName(self):
        """Return the selected item text, or None if nothing was clicked."""
        return self.name_sel


    def onCancel(self):
        """Reject the dialog."""
        self.reject()


    def onApply(self):
        """Accept the dialog."""
        self.accept()


def popup_select_item_from_list(parent, lst, dx=-46, dy=-33, use_cursor_pos=False, do_sort=True) :
    """Show a `QWPopupSelectItem` modally and return the selected string.

    The popup is moved to the cursor position plus (dx, dy) if `use_cursor_pos`, else to
    the parent's global position plus (dx, dy) when a parent is given.

    Returns
    -------
    str or None
        Selected item text, or None if the dialog was dismissed without a click.
    """
    w = QWPopupSelectItem(parent, lst, do_sort)
    if use_cursor_pos: w.move(QCursor.pos().__add__(QPoint(dx,dy)))
    elif parent is not None: w.move(parent.mapToGlobal(parent.pos()) + QPoint(dx, dy))
    else: pass

    resp=w.exec_()
    #if   resp == QDialog.Accepted : return w.selectedName()
    #elif resp == QDialog.Rejected : return None
    #else : return None
    return w.selectedName()


#----------- TESTS ------------

if __name__ == "__main__" :
  import logging
  logger = logging.getLogger(__name__)
  logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s: %(message)s', datefmt='%H:%M:%S', level=logging.DEBUG)

  import os

  from PyQt5.QtWidgets import QApplication

  def test_select_exp(tname) :
    """Test: pop up a selection list of the entries in '/reg/d/psdm/CXI/' and log the choice."""
    lst = sorted(os.listdir('/reg/d/psdm/CXI/'))
    logger.debug('lst:', lst)
    app = QApplication(sys.argv)
    exp_name = popup_select_item_from_list(None, lst)
    logger.debug('exp_name = %s' % exp_name)


if __name__ == "__main__" :
    import sys; global sys

    tname = sys.argv[1] if len(sys.argv) > 1 else '0'
    logger.debug(50*'_', '\nTest %s' % tname)
    if   tname == '0': test_select_exp(tname)
    #elif tname == '1': test_select_icon(tname)
    else : sys.exit('Test %s is not implemented' % tname)
    sys.exit('End of Test %s' % tname)

# EOF
