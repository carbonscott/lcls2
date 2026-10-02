
"""
:py:class:`QWPopupEditConfirm` - Popup GUI
============================================

Usage::

    # Test: python lcls2/psana/psana/graphqt/QWPopupEditConfirm.py

    # Import
    from psana.graphqt.QWPopupEditConfirm import popup_edit_and_confirm
    r, s = popup_edit_and_confirm(parent, dx=0, dy=0, height=60, width=150, is_frameless=False,\
                                  msg='text to edit',\
                                  win_title='Edit & confirm or cancel')

    # Methods - see test

See:
    - :py:class:`QWPopupEditConfirm`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Created on 2021-09-08 by Mikhail Dubrovin
"""

import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QPushButton, QTextEdit, QFrame, QSizePolicy, QApplication
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QCursor  # , QColor, QBrush


class QWPopupEditConfirm(QDialog):

    """QDialog with an editable text box and Cancel/Apply buttons.

    Keyword arguments 'parent', 'win_title', 'msg', 'but_title_apply' and 'but_title_cancel' set the parent, title, initial text and button labels; Apply accepts and Cancel rejects the dialog.
    """
    def __init__(self, **kwa):
        QDialog.__init__(self, kwa.get('parent', None))
        win_title = kwa.get('win_title', 'Edit and confirm or cancel')
        if win_title: self.setWindowTitle(win_title)
        self.edi_msg = QTextEdit(kwa.get('msg', 'text to edit and confirm'))
        self.but_apply = QPushButton(kwa.get('but_title_apply', 'Apply'))
        self.but_cancel = QPushButton(kwa.get('but_title_cancel', 'Cancel'))
        self.but_cancel.clicked.connect(self.on_cancel)
        self.but_apply.clicked.connect(self.on_apply)

        self.hbox = QHBoxLayout()
        self.hbox.addWidget(self.but_cancel)
        self.hbox.addWidget(self.but_apply)
        self.hbox.addStretch(1)

        self.vbox = QVBoxLayout()
        self.vbox.addWidget(self.edi_msg)
        self.vbox.addLayout(self.hbox)
        self.setLayout(self.vbox)

        self.but_cancel.setFocusPolicy(Qt.NoFocus)
        self.set_style()

    def set_style(self):
        """Set small layout margins and a gray style sheet on both buttons."""
        self.layout().setContentsMargins(2,2,2,2)
        styleGray = "background-color: rgb(230, 240, 230); color: rgb(0, 0, 0);"
        self.but_cancel.setStyleSheet(styleGray)
        self.but_apply.setStyleSheet(styleGray)
        #self.edi_msg.setMinimumSize(500,60)
        #self.setFixedHeight(30)
        #self.setMinimumHeight(30)

    def on_cancel(self):
        """Log a debug message and reject the dialog."""
        logger.debug('on_cancel')
        self.reject()

    def on_apply(self):
        """Log a debug message and accept the dialog."""
        logger.debug('on_apply')
        self.accept()

    def message(self):
        """Return the current plain text of the edit box as str."""
        return str(self.edi_msg.toPlainText())

def popup_edit_and_confirm(parent, dx=0, dy=0, height=60, width=150, is_frameless=False,\
                           msg='text to edit',\
                           win_title='Edit & confirm or cancel'):
    """Show a modal ``QWPopupEditConfirm`` at the cursor position plus (``dx``, ``dy``) and return the result.

    ``width`` and ``height`` fix the dialog size when not None; ``is_frameless`` adds the frameless window flag.

    Returns
    -------
    tuple
        ``(resp, s)``: the ``exec_()`` result (QDialog.Accepted or Rejected) and the edited text.
    """
    w = QWPopupEditConfirm(parent=parent, msg=msg, win_title=win_title)
    if width  is not None: w.setFixedWidth(width)
    if height is not None: w.setFixedHeight(height)
    if is_frameless: w.setWindowFlags(w.windowFlags() | Qt.FramelessWindowHint)
    w.move(QCursor.pos().__add__(QPoint(dx,dy)))
    resp = w.exec_()
    s = w.message()
    del w
    return resp, s

if __name__ == "__main__":
    import os
    import sys
    logging.getLogger('psana.pscalib.geometry').setLevel(logging.WARNING)
    logging.basicConfig(format='[%(levelname).1s] L:%(lineno)03d %(name)s %(message)s', level=logging.DEBUG)

    app = QApplication(sys.argv)
    parent = None
    r, s = popup_edit_and_confirm(parent, dx=0, dy=0, height=60, width=150, is_frameless=False,\
                                  msg='my text', win_title='Edit & confirm or cancel')

    logger.debug('QtWidgets.QDialog.Rejected: %d' % QDialog.Rejected)
    logger.debug('QtWidgets.QDialog.Accepted: %d' % QDialog.Accepted)
    logger.debug('resp=%s output: %s' % (r,s))

    #del w
    del app

# EOF
