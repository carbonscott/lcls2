
"""
2018-02-20
"""

from time import time

from PyQt5.QtWidgets import QGroupBox, QTextEdit, QVBoxLayout
from PyQt5.QtCore import QTimer #QMargins
from psana.graphqt.Styles import style
from psana.graphqt.QWIcons import icon


#class QWStatus(QWidget):
class QWStatus(QGroupBox):
    """GUI State"""

    def __init__(self, parent=None, msg='No message in QWStatus...'):

        QGroupBox.__init__(self, 'State', parent)
        #QWidget.__init__(self, parent)

        icon.set_icons()
        try: self.setWindowIcon(icon.icon_logviewer)
        except: pass

        self.box_txt        = QTextEdit(self)
        #self.tit_status     = QLabel(' State ', self)

        #self.setTitle('My status')

        self.vbox = QVBoxLayout()
        self.vbox.addWidget(self.box_txt)
        self.setLayout(self.vbox)

        #self.connect( self.but_close, QtCore.SIGNAL('clicked()'), self.onClose )

        self.setStatusMessage(msg)

        self.showToolTips()
        self.setStyle()

        #cp.guistatus = self
        self.timer = QTimer()
        self.timer.timeout.connect(self.on_timeout)
        self.timer.start(1000)


    def showToolTips(self):
        #self           .setToolTip('This GUI is intended for run control and monitoring.')
        #self.but_close .setToolTip('Close this window.')
        """Does nothing; body is ``pass``."""
        pass


    def setStyle(self):
        """Apply background and text style sheets, make the text box read-only, zero the margins and set minimum size 300x60.

        This overrides ``QWidget.setStyle`` with a method that takes no style argument.
        """
        self.           setStyleSheet (style.styleBkgd)
        self.box_txt   .setReadOnly   (True)
        self.box_txt   .setStyleSheet (style.styleWhiteFixed)
        self.layout().setContentsMargins(0,0,0,0)
        self.setMinimumSize(300,60)


    def setParent(self,parent):
        """Store ``parent`` in the attribute ``self.parent``; this overrides ``QWidget.setParent`` and does not reparent the widget."""
        self.parent = parent


    def on_timeout(self):
        """Restart the 1-second timer and show the current ``time()`` in seconds as the status message."""
        self.timer.start(1000)
        self.setStatusMessage(msg='Time %.3f sec' % time())


    def closeEvent(self, event):
        """Close the text box ``box_txt``; the event is not passed to the base class."""
        self.box_txt.close()


    def onClose(self):
        #logger.debug('onClose', __name__)
        """Close the widget."""
        self.close()


    def setStatusMessage(self, msg='msg is empty...'):
        #logger.debug('Set status message',__name__)
        """Set the text of the status text box to ``msg``."""
        self.box_txt.setText(msg)
        #self.setStatus(0, 'Status: unknown')


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = QWStatus()
    w.setGeometry(100, 100, 300, 60)
    w.setWindowTitle('GUI Status')
    w.setStatusMessage('Test of QWStatus...')

    w.show()
    app.exec_()

    del w
    del app

# EOF
