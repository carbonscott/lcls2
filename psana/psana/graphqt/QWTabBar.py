
"""
:py:class:`QWTabBar` - Re-implementation of QWTabBar
========================================

Usage::

    # Import
    from psana.graphqt.QWTabBar import QWTabBar

    # Methods - see test

See:
    - :py:class:`QWTabBar`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Created on 2017-02-08 by Mikhail Dubrovin
Adopted for LCLS2 on 2018-02-16
"""

import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QTabBar#, QWidget
from PyQt5.QtCore import QPoint, QSize # Qt, QEvent
from psana.graphqt.QWIcons import icon


class QWTabBar(QTabBar):
    """Re-implementation of QTabBar - add "+" tab
    """
    def __init__ (self, parent=None, width=80):
        QTabBar.__init__(self, parent)
        #self._name = self.__class__.__name__
        icon.set_icons()

        self.tab_width = width
        self.tabi_add = None
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setExpanding(False) # need it to lock tab width

        self.make_tab_bar()

        self.set_style()
        self.set_tool_tips()


    def make_tab_bar(self):

        """Add six demo tabs 'Tab0'-'Tab5' and connect the tab-bar signals.

        Tab 0 gets a folder icon and a zero-size close button, tab 1 gets a custom 'x' QPushButton connected to ``on_tab_close``, and tab 2's close button is hidden. ``QPushButton`` is imported only in the ``__main__`` block, so this method raises NameError when the module is imported.
        """
        w = self

        it0 = w.addTab('Tab0')
        it1 = w.addTab('Tab1')
        it2 = w.addTab('Tab2')
        it3 = w.addTab('Tab3')
        it4 = w.addTab('Tab4')
        it5 = w.addTab('Tab5')

        itab = 0
        w.setTabIcon(itab, icon.icon_folder_closed)
        w.tabButton(itab, QTabBar.RightSide).resize(0, 0) # hide closing button
        ##w.tabButton(itab, QTabBar.RightSide).hide() # hide closing button

        itab = 1
        but_close = QPushButton('x')
        but_close.setFixedWidth(30)
        but_close.clicked.connect(self.on_tab_close)
        but_close.setIcon(icon.icon_table)
        w.setTabButton(itab, QTabBar.RightSide, but_close)

        itab = 2
        w.tabButton(itab, QTabBar.RightSide).hide() # hide closing button

        #itab = 2
        #w.setTabIcon(itab, icon.icon_table)
        #but_tab2_close = w.tabButton(itab, QTabBar.RightSide)
        #but_tab2_close.clicked.connect(self.on_tab_close)

        #itab = 3
        #but_tab3_close = w.tabButton(itab, QTabBar.RightSide)
        #but_tab3_close.clicked.connect(self.on_tab_close)

        self.currentChanged[int].connect(self.on_current_changed)
        self.tabCloseRequested[int].connect(self.on_tab_close_request)
        self.tabMoved[int,int].connect(self.on_tab_moved)

      #but_close.setVisible(True)
        #logger.debug(str(but_close))


    def on_current_changed(self, itab):
        """Log at debug level the new current tab index ``itab``."""
        logger.debug('on_current_changed tab index:%d' % (itab))


    def current_tab_index_and_name(self):
        """Return a tuple (index, text) of the current tab."""
        tab_ind  = self.currentIndex()
        tab_name = str(self.tabText(tab_ind))
        return tab_ind, tab_name


    def on_tab_close(self):
        """Log at debug level the index and text of the current tab; no tab is removed."""
        tab_ind, tab_name = self.current_tab_index_and_name()
        logger.debug('on_tab_close tab index:%d name:%s' % (tab_ind, tab_name))


    def on_tab_close_request(self, itab):
        """Log at debug level the index of the tab whose close was requested; no tab is removed."""
        logger.debug('on_tab_close_request tab index:%d' % itab)


    def on_tab_moved(self, inew, iold):
        """Log at debug level the old and new index of a moved tab."""
        logger.debug('on_tab_close_request tab index begin:%d -> end:%d' % (iold, inew))


    def set_tool_tips(self):
        """Set the tab bar tool tip to 'This is a tabbar'."""
        self.setToolTip('This is a tabbar')


    def set_style(self):
        """Set a minimum width of 600 and a style sheet for the tab close buttons."""
        self.setMinimumWidth(600)
        #self.setGeometry(10, 25, 500, 50)
        ss = "QTabBar::close-button { image: url(close.png) subcontrol-position: left; }"\
             "QTabBar::close-button:hover { image: url(close-hover.png) }"
        self.setStyleSheet(ss)


    def enterEvent(self, e):
        """Append a '+' tab with a zero-size close button when the mouse enters the tab bar, storing its index in ``self.tabi_add``."""
        logger.debug('enterEvent %s' % e.type())
        #if e.type() == QEvent.Enter:
        #self.setTabEnabled(self.tabi_add, True)
        #self.setTabsClosable(True)
        self.tabi_add = self.addTab('+')
        self.tabButton(self.tabi_add, QTabBar.RightSide).resize(0, 0) # hide closing button

        #self.tabButton(self.tabi_add, QTabBar.RightSide).hide() # hide closing button


    def leaveEvent(self, e):
        """Remove the '+' tab added by ``enterEvent`` (if any) when the mouse leaves, and reset ``self.tabi_add`` to None."""
        logger.debug('leaveEvent %s' % e.type())
        #if e.type() == QtCore.QEvent.Leave:
        #self.setTabEnabled(self.tabi_add, False)
        #self.setTabsClosable(False)
        if self.tabi_add is not None: self.removeTab(self.tabi_add)
        self.tabi_add = None


    def tabSizeHint(self, index):
        """Return the size hint for tab ``index``: width ``self.tab_width`` (30 for the '+' tab or text starting with '+') and the base-class height."""
        w = self.tab_width
        if index==self.tabi_add or (self.tabText(index)[0] == '+'): w = 30
        h = QTabBar.tabSizeHint(self, index).height()
        return QSize(w, h)


    #def event(self, e):
    #    QTabBar.event(self, e)
    #    logger.debug('event %s' % e.type())


    #def mouseMoveEvent(self, e):
    #    logger.debug('mouseMoveEvent x,y=%.3f,%.3f' % (e.x(), e.y()))


    def mouseHoverEvent(self, e):
        """Log a debug message; this name is not a Qt event handler and is not called in this module."""
        logger.debug('mouseHoverEvent')


    def closeEvent(self, event):
        """Log a debug message; the event is not passed to the base class."""
        logger.debug('closeEvent')

        #try   : self.gui_win.close()
        #except: pass


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication, QPushButton
    app = QApplication(sys.argv)
    w  = QWTabBar()
    w.setWindowTitle('Widget with tabs')
    w.move(QPoint(50,50))
    w.show()
    app.exec_()
    del w
    del app

# EOF
