
"""
Class :py:class:`CMWDBMain` is a QWidget for calibman
===========================================================

Usage ::
    See test_CMWDBMain() at the end

See:
    - :class:`CMWDBMain`
    - :class:`CMWMainTabs`
    - :class:`CMConfigParameters`
    - `graphqt documentation <https://lcls-psana.github.io/graphqt/py-modindex.html>`_.

Created on 2017-02-01 by Mikhail Dubrovin
Adopted for LCLS2 on 2018-02-26 by Mikhail Dubrovin
"""

import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QApplication, QWidget, QSplitter, QVBoxLayout, QTextEdit
from PyQt5.QtCore import Qt

from psana.graphqt.CMConfigParameters import cp
from psana.graphqt.CMWDBDocs import CMWDBDocs
from psana.graphqt.CMWDBDocEditor import CMWDBDocEditor
from psana.graphqt.CMWDBTree import CMWDBTree
from psana.graphqt.CMWDBControl import CMWDBControl


class CMWDBMain(QWidget):

    """Calibman DB-tab widget: a control panel (``CMWDBControl``) above a horizontal splitter.

    The splitter holds ``CMWDBTree``, ``CMWDBDocs`` and ``CMWDBDocEditor``. The constructor
    registers the instance as ``cp.cmwdbmain``.
    """
    _name = 'CMWDBMain'

    def __init__(self, parent=None):
        QWidget.__init__(self, parent=parent)
        cp.cmwdbmain = self

        self.wbuts = CMWDBControl(parent=self)
        self.wtree = CMWDBTree()
        self.wdocs = CMWDBDocs()
        self.wdoce = CMWDBDocEditor()

        # Horizontal splitter widget
        self.hspl = QSplitter(Qt.Horizontal)
        self.hspl.addWidget(self.wtree)
        self.hspl.addWidget(self.wdocs)
        self.hspl.addWidget(self.wdoce)

        # Vertical splitter widget
        self.vspl = QSplitter(Qt.Vertical)
        self.vspl.addWidget(self.wbuts)
        self.vspl.addWidget(self.hspl)

        # Main box layout
        self.mbox = QVBoxLayout()
        self.mbox.addWidget(self.vspl)
        self.setLayout(self.mbox)

        self.set_style()
        self.set_tool_tips()
        self.connect_signals_to_slots()


    def connect_signals_to_slots(self):
        """Does nothing; body is ``pass``."""
        pass


    def on_but_tabs_clicked_test(self):
        """Log ``'on_but_tabs_clicked'`` at debug level."""
        logger.debug('on_but_tabs_clicked')


    def proc_parser(self, parser=None):
        """Store ``parser`` in ``self.parser`` and return None."""
        self.parser=parser
        if parser is None:
            return
        return


    def set_tool_tips(self):
        """Does nothing; body is ``pass``."""
        pass
        #self.butStop.setToolTip('Not implemented yet...')


    def set_hsplitter_sizes(self, s0=None, s1=None, s2=None):
        """Set the three horizontal splitter sizes.

        Parameters
        ----------
        s0, s1, s2 : int or None
            Sizes of the tree, docs and editor panes; None takes the value of
            ``cp.cdb_hsplitter0``, ``cp.cdb_hsplitter1`` or ``cp.cdb_hsplitter2``.
        """
        _s0 = cp.cdb_hsplitter0.value() if s0 is None else s0
        _s1 = cp.cdb_hsplitter1.value() if s1 is None else s1
        _s2 = cp.cdb_hsplitter2.value() if s2 is None else s2
        self.hspl.setSizes((_s0, _s1, _s2))


    def set_hsplitter_size2(self, s2=0):
        """Set the third splitter pane to ``s2`` and give the freed or taken space to the second pane."""
        _s0, _s1, _s2 = self.hsplitter_sizes()
        self.set_hsplitter_sizes(_s0, _s1+_s2-s2, s2 )


    def hsplitter_sizes(self):
        """Return ``self.hspl.sizes()``, the list of horizontal splitter pane sizes."""
        return self.hspl.sizes() #[0]


    def save_hsplitter_sizes(self):
        """Save hsplitter sizes in configuration parameters.
        """
        s0, s1, s2 = self.hsplitter_sizes()
        msg = 'Save h-splitter sizes %d %d %d' % (s0, s1, s2)
        logger.debug(msg)

        cp.cdb_hsplitter0.setValue(s0)
        cp.cdb_hsplitter1.setValue(s1)
        cp.cdb_hsplitter2.setValue(s2)


    def set_style(self):
        """Set zero layout margins, limit the tree width to 100-600 pixels and apply :meth:`set_hsplitter_sizes` with config defaults."""
        self.layout().setContentsMargins(0,0,0,0)
        self.wtree.setMinimumWidth(100)
        self.wtree.setMaximumWidth(600)
        self.set_hsplitter_sizes()


    def closeEvent(self, e):
        """Log the event, call :meth:`on_save` and pass the event to ``QWidget.closeEvent``."""
        logger.debug('%s.closeEvent' % self._name)
        self.on_save()
        QWidget.closeEvent(self, e)


    def view_hide_tabs(self):
        #self.set_tabs_visible(not self.tab_bar.isVisible())
        #self.wbuts.tab_bar.setVisible(not self.tab_bar.isVisible())
        """Call ``self.wbuts.view_hide_tabs()``."""
        self.wbuts.view_hide_tabs()


    def key_usage(self):
        """Return a help string listing the V key (view/hide tabs)."""
        return 'Keys:'\
               '\n  V - view/hide tabs'\
               '\n'

    if __name__ == "__main__":
      def keyPressEvent(self, e):
        #logger.debug('keyPressEvent, key=', e.key())
        """Handle keys: Escape closes the widget, V calls :meth:`view_hide_tabs`, others log :meth:`key_usage`.

        This method is defined only when the module is run as ``__main__``.
        """
        logger.info('%s.keyPressEvent, key=%d' % (self._name, e.key()))
        if   e.key() == Qt.Key_Escape:
            self.close()

        elif e.key() == Qt.Key_V:
            self.view_hide_tabs()

        else:
            logger.debug(self.key_usage())


    def on_save(self):
        """Call :meth:`save_hsplitter_sizes` to store the splitter sizes in the config parameters."""
        self.save_hsplitter_sizes()


if __name__ == "__main__":
  def test_CMWDBMain():
    """Create a ``QApplication``, show a ``CMWDBMain`` widget with minimum size 600x300 and run the event loop.

    Defined only when the module is run as ``__main__``.
    """
    import sys
    logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s: %(message)s', level=logging.DEBUG)
    app = QApplication(sys.argv)
    w = CMWDBMain()
    w.setMinimumSize(600, 300)
    w.show()
    app.exec_()
    del w
    del app


if __name__ == "__main__":
    test_CMWDBMain()

# EOF
