
"""
:py:class:`Frame` - derived from QFrame
=======================================

Usage::

    # Import
    from psana.graphqt.Frame import Frame

    # Methods - see test

See:
    - :py:class:`QWPopupSelectItem`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Created on 2014-12-03 by Mikhail Dubrovin
Adopted for LCLS2 on 2018-02-15
"""

from PyQt5 import QtWidgets

class Frame(QtWidgets.QFrame):
    """ class Frame inherits from QFrame and sets its parameters.

    QFrame inherits from QWidget and hence Frame can be used in stead of QWidget
    """
    def __init__(self, parent=None, lw=0, mlw=1, vis=True, style=QtWidgets.QFrame.Box | QtWidgets.QFrame.Sunken):
        QtWidgets.QFrame.__init__(self, parent)
        self.parent = parent
        self.setFrame(lw, mlw, vis, style)


    def setFrame(self, lw=0, mlw=1, vis=False, style=QtWidgets.QFrame.Box | QtWidgets.QFrame.Sunken):
        """Set frame style, line width, mid-line width and border visibility.

        Parameters
        ----------
        lw : int
            Line width.
        mlw : int
            Mid-line width.
        vis : bool
            Passed to :meth:`setBoarderVisible`; default False here (the constructor passes True by default).
        style : int
            Frame style flags; default ``QFrame.Box | QFrame.Sunken``.
        """
        self.setFrameStyle(style)
        self.setLineWidth(lw)
        self.setMidLineWidth(mlw)
        self.setBoarderVisible(vis)


    def setBoarderVisible(self, vis=True):
        """Set the frame shape to ``QFrame.Box`` if ``vis`` is True, otherwise to ``QFrame.NoFrame``."""
        if vis: self.setFrameShape(QtWidgets.QFrame.Box)
        else  : self.setFrameShape(QtWidgets.QFrame.NoFrame)


class GUILabel(QtWidgets.QLabel, Frame):
    """Example ``QLabel``/``Frame`` combination initialized through ``Frame`` with mid-line width 5 and text ``'GUILabel set'``."""
    def __init__(self, parent=None):
        Frame       .__init__(self, parent, mlw=5)
        #QtWidgets.QLabel.__init__(self, QtCore.QString('label'), parent)
        self.setText('GUILabel set')


class GUIWidget(QtWidgets.QWidget):
    """Example ``QWidget`` containing one push button at (30, 20)."""
    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        #super(GUIWidget, self).__init__(parent)
        but = QtWidgets.QPushButton('Button', self)
        but.move(30,20)


class GUIWidgetFrame(Frame, QtWidgets.QWidget):
    """Example ``Frame``/``QWidget`` with mid-line width 5 containing one push button at (20, 10)."""
    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        Frame        .__init__(self, parent, mlw=5)
        but = QtWidgets.QPushButton('Button', self)
        but.move(20,10)


class GUIFrame(Frame):
    """Example ``Frame`` with mid-line width 30 containing one push button at (30, 20); shown when the module is run as a script."""
    def __init__(self, parent=None):
        #Frame.__init__(self, parent, mlw=5)
        Frame.__init__(self, mlw=30)
        but = QtWidgets.QPushButton('Button', self)
        but.move(30,20)


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)
    w = GUIFrame()
    w.setWindowTitle('GUIWidget')
    w.setGeometry(200, 500, 200, 100)
    w.show()
    app.exec_()

# EOF
