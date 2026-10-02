"""
Class :py:class:`CGWMainTabExpert` is a QWidget for interactive image
=======================================================================

Usage ::

    import sys
    from PyQt5.QtWidgets import QApplication
    from psdaq.control_gui.CGWMainTabExpert import CGWMainTabExpert
    app = QApplication(sys.argv)
    w = CGWMainTabExpert(None, app)
    w.show()
    app.exec_()

See:
    - :class:`CGWMainTabExpert`
    - :class:`CGWMainPartition`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2/psdaq/psdaq/control_gui>`_.

Created on 2019-05-07 by Mikhail Dubrovin
"""
#------------------------------

import logging
logger = logging.getLogger(__name__)

#------------------------------

from time import time

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QTextEdit, QSizePolicy
from PyQt5.QtCore import Qt, QSize

from psdaq.control_gui.CGWMainPartition import CGWMainPartition
from psdaq.control_gui.CGWMainControl   import CGWMainControl

#------------------------------

class CGWMainTabExpert(QWidget) :

    """Expert tab widget: a vertical splitter with a `CGWMainPartition` above a `CGWMainControl`.

    The 'parent' keyword is passed to `CGWMainControl` only; the widget itself is created without a parent.
    """
    _name = 'CGWMainTabExpert'

    def __init__(self, **kwargs) :

        parent      = kwargs.get('parent', None)

        QWidget.__init__(self, parent=None)

        logger.debug('In %s' % self._name)

        self.wpart = CGWMainPartition()
        self.wctrl = CGWMainControl(parent)

        #self.wpart = QTextEdit('Txt 1')
        #self.wctrl = QTextEdit('Txt 2')

        self.vspl = QSplitter(Qt.Vertical)
        self.vspl.addWidget(self.wpart) 
        self.vspl.addWidget(self.wctrl) 

        self.mbox = QHBoxLayout() 
        self.mbox.addWidget(self.vspl)
        self.setLayout(self.mbox)

        self.set_style()

#------------------------------

    def set_tool_tips(self) :
        """Do nothing; body is `pass`."""
        pass
        #self.butStop.setToolTip('Not implemented yet...')

#--------------------

    def sizeHint(self):
        """Return QSize(300, 280)."""
        return QSize(300, 280)

#--------------------

    def set_style(self) :
        """Set minimum size 280x260, zero margins and a MinimumExpanding/Preferred size policy."""
        self.setMinimumSize(280, 260)
        self.layout().setContentsMargins(0,0,0,0)
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)

#--------------------

    def closeEvent(self, e) :
        """Log a debug message; the try block contains only `pass`, so nothing else happens.

        `QWidget.closeEvent` is not called.
        """
        logger.debug('%s.closeEvent' % self._name)

        try :
            pass
            #self.wpart.close()
            #self.wctrl.close()
        except Exception as ex:
            print('Exception: %s' % ex)

#--------------------

    if __name__ == "__main__" :
 
      def resizeEvent(self, e):
        #logger.debug('resizeEvent', self._name) 
        """Print the widget size.

        Defined only when the module is run as a script.
        """
        print('CGWMainTabExpert.resizeEvent: %s' % str(self.size()))


     #def moveEvent(self, e) :
        #logger.debug('moveEvent', self._name) 
        #self.position = self.mapToGlobal(self.pos())
        #self.position = self.pos()
        #logger.debug('moveEvent - pos:' + str(self.position), __name__)       
        #logger.info('CGWMainTabExpert.moveEvent - move window to x,y: ', str(self.mapToGlobal(QPoint(0,0))))
        #self.wimg.move(self.pos() + QPoint(self.width()+5, 0))
        #pass

#--------------------

if __name__ == "__main__" :

    from psdaq.control_gui.CGDaqControl import daq_control, DaqControlEmulator, Emulator
    daq_control.set_daq_control(DaqControlEmulator())

    import sys
    logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s: %(message)s', datefmt='%H:%M:%S', level=logging.DEBUG)

    from psdaq.control_gui.CGConfigParameters import cp
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    kwargs = {'parent':None}
    cp.test_cpinit()
    w = CGWMainTabExpert(**kwargs)
    w.show()
    app.exec_()
    del w
    del app

#------------------------------
