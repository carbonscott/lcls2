
"""
:py:class:`QWPopupCheckDict` - Popup GUI
========================================

Usage::

    # Test: python lcls2/psana/psana/graphqt/QWPopupCheckDict.py

    # Import
    from psana.graphqt.QWPopupCheckDict import QWPopupCheckDict

    # Methods - see test

See:
    - :py:class:`QWPopupCheckDict`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Adopted for LCLS2 on 2018-02-16 by Mikhail Dubrovin
"""

import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QPushButton, QCheckBox, QTextEdit, QFrame, QSizePolicy
from PyQt5.QtCore import Qt


class QWPopupCheckDict(QDialog):
    """Gets dict of item for checkbox GUI in format {name:(bool)status,},
    e.g.: {'name1':False, 'name2':True, ..., 'nameN':False},
    and modify this dict in popup dialog gui.
    """
    def __init__(self, parent=None, dict_in_out={}, win_title=None, msg=''):
        QDialog.__init__(self, parent)

        if win_title is not None: self.setWindowTitle(win_title)

        self.dict_in_out = dict_in_out

        self.vbox = QVBoxLayout()
        self.edi_msg = QTextEdit(msg)
        self.vbox.addWidget(self.edi_msg)

        self.make_gui_checkbox()

        self.but_cancel = QPushButton('&Cancel')
        self.but_apply  = QPushButton('&Apply')

        self.but_cancel.clicked.connect(self.onCancel)
        self.but_apply.clicked.connect(self.onApply)

        self.hbox = QHBoxLayout()
        self.hbox.addWidget(self.but_cancel)
        self.hbox.addWidget(self.but_apply)
        self.hbox.addStretch(1)

        self.vbox.addLayout(self.hbox)
        self.setLayout(self.vbox)

        self.but_cancel.setFocusPolicy(Qt.NoFocus)

        self.setStyle()
        self.setIcons()
        self.showToolTips()


    def make_gui_checkbox(self):
        """Add one check box per (name, state) of ``self.dict_in_out``, sorted by name, and record each in ``self.dict_of_items`` as ``[name, state]``.

        Each box's ``stateChanged`` signal is connected to ``onCBox``.
        """
        self.dict_of_items = {}
        for name,state in sorted(self.dict_in_out.items()):
            cbx = QCheckBox(name)
            if state: cbx.setCheckState(Qt.Checked)
            else    : cbx.setCheckState(Qt.Unchecked)
            #self.connect(cbx, QtCore.SIGNAL('stateChanged(int)'), self.onCBox)
            cbx.stateChanged[int].connect(self.onCBox)
            self.vbox.addWidget(cbx)

            self.dict_of_items[cbx] = [name,state]


    def showToolTips(self):
        """Set tool tips on the Apply and Cancel buttons."""
        self.but_apply.setToolTip('Apply changes to the dict')
        self.but_cancel.setToolTip('Use default dict')


    def setStyle(self):
        #self.setFixedWidth(200)
        #self.setMinimumWidth(200)
        """Clear the dialog style sheet, give both buttons a gray style and style the message box with ``set_style_msg``."""
        styleGray = "background-color: rgb(230, 240, 230); color: rgb(0, 0, 0);" # Gray
        styleDefault = ""

        self.setStyleSheet(styleDefault)
        self.but_cancel.setStyleSheet(styleGray)
        self.but_apply.setStyleSheet(styleGray)
        self.set_style_msg(styleGray)


    def set_style_msg(self, style_bkgd):
        """Make the message box read-only and frameless, apply ``style_bkgd`` and fix its size to 300x50."""
        self.edi_msg.setReadOnly(True)
        self.edi_msg.setStyleSheet(style_bkgd)
        self.edi_msg.setFrameStyle(QFrame.NoFrame)
        self.edi_msg.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        self.edi_msg.setFixedSize(300,50)

    def setIcons(self):
        """Load the shared icons and set the cancel and ok icons on the Cancel and Apply buttons."""
        from psana.graphqt.QWIcons import icon
        icon.set_icons()
        self.but_cancel.setIcon(icon.icon_button_cancel)
        self.but_apply .setIcon(icon.icon_button_ok)


    def onCBox(self, tristate):
        """Record the new checked state of the check box that has focus in ``self.dict_of_items``; ``tristate`` is not used."""
        for cbx in self.dict_of_items.keys():
            if cbx.hasFocus():
                name,state = self.dict_of_items[cbx]
                state_new = cbx.isChecked()
                msg = 'Checkbox "%s" set %s'%(name, state_new)#, tristate)
                logger.debug(msg)
                self.dict_of_items[cbx] = [name,state_new]


    def onCancel(self):
        """Log a debug message and reject the dialog; the input dict is not changed."""
        logger.debug('onCancel')
        self.reject()


    def onApply(self):
        """Copy the check box states into the input dict with ``fill_output_dict`` and accept the dialog."""
        logger.debug('onApply')
        self.fill_output_dict()
        self.accept()


    def fill_output_dict(self):
        """Fills output dict"""
        for cbx,[name,state] in self.dict_of_items.items():
            self.dict_in_out[name] = state


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication

    logging.basicConfig(format='%(message)s', level=logging.DEBUG)

    app = QApplication(sys.argv)
    dict_in = {'CSPAD1':True, 'CSPAD2x21':False, 'pNCCD1':True, 'Opal1':False, \
               'CSPAD2':True, 'CSPAD2x22':False, 'pNCCD2':True, 'Opal2':False}
    for name,state in dict_in.items(): logger.debug('%s checkbox is in state %s' % (name.ljust(10), state))
    w = QWPopupCheckDict(None, dict_in)
    #w.setGeometry(20, 40, 500, 200)
    w.setWindowTitle('Set check boxes')
    #w.show()
    resp=w.exec_()
    logger.debug('resp=%s' % resp)
    logger.debug('QtWidgets.QDialog.Rejected: %d' % QDialog.Rejected)
    logger.debug('QtWidgets.QDialog.Accepted: %d' % QDialog.Accepted)

    for name,state in dict_in.items(): logger.debug('%s checkbox is in state %s' % (name.ljust(10), state))

    del w
    del app

# EOF
