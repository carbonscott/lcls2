
"""Class :py:class:`CMWDBDocs` is a QWidget for configuration parameters
========================================================================

Usage ::
    # Test: python lcls2/psana/psana/graphqt/CMWDBDocs.py

    # Import
    from psana.graphqt.CMWDBDocs import CMWDBDocs

    # See test at the EOF

See:
  - :class:`CMWMain`
  - :class:`CMWDBDocs`
  - `on github <https://github.com/slac-lcls/lcls2>`_.

Created on 2017-04-05 by Mikhail Dubrovin
"""

import logging
logger = logging.getLogger(__name__)

from psana.graphqt.CMConfigParameters import cp
from psana.graphqt.Styles import style

from psana.graphqt.CMDBUtils import dbu
from psana.graphqt.CMWDBDocsText  import CMWDBDocsText
from psana.graphqt.CMWDBDocsList  import CMWDBDocsList
from psana.graphqt.CMWDBDocsTable import CMWDBDocsTable
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QTextEdit

def docs_widget_selector(dwtype):
    """Factory method for selection of the document widget.
    """
    dwtypes = cp.list_of_doc_widgets

    logger.info('Set document browser in mode %s' % dwtype)

    if   dwtype == dwtypes[0]: return CMWDBDocsText()
    elif dwtype == dwtypes[1]: return CMWDBDocsList()
    elif dwtype == dwtypes[2]: return CMWDBDocsTable()
    else:
        logger.warning('Unknown doc widget type "%s"' % dwtype)
        return QTextEdit(dwtype)


class CMWDBDocs(QWidget):
    """CMWDBDocs is a QWidget with tabs for configuration management"""

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self._name = 'CMWDBDocs'

        cp.cmwdbdocs = self

        self.dbname  = None
        self.colname = None

        self.list_of_doc_widgets = cp.list_of_doc_widgets

        self.hboxw = QHBoxLayout()
        self.gui_win = None
        self.set_docs_widget(cp.cdb_docw.value())

        self.vbox = QVBoxLayout()
        self.vbox.addLayout(self.hboxw)
        self.setLayout(self.vbox)

        self.set_tool_tips()
        self.set_style()


    def set_tool_tips(self):
        """Do nothing; the body is ``pass``."""
        pass


    def set_style(self):
        """Apply the background style sheet and zero the layout margins."""
        self.setStyleSheet(style.styleBkgd)
        self.layout().setContentsMargins(0,0,0,0)


    def set_docs_widget(self, docw=None):

        """Replace the document widget with one made by ``docs_widget_selector`` for ``docw`` (default ``cp.cdb_docw.value()``), then call ``show_documents`` for the stored DB and collection."""
        if self.gui_win is not None:
            self.gui_win.close()
            del self.gui_win

        docw_type = docw if docw is not None else cp.cdb_docw.value()
        self.gui_win = docs_widget_selector(docw_type)
        self.hboxw.addWidget(self.gui_win)
        self.gui_win.setVisible(True)

        self.show_documents(self.dbname, self.colname)


    def show_documents(self, dbname, colname, force_update=False):

        """Show the documents of collection ``colname`` in DB ``dbname`` in the current document widget.

        Returns if either name is None. The document list is fetched with ``dbu.list_of_documents`` only when the names differ from the stored ones or ``force_update`` is true; otherwise the cached ``self.current_docs`` is reused.
        """
        if None in (dbname, colname): return

        if ((dbname, colname) != (self.dbname, self.colname))\
        or force_update:
            self.current_docs = dbu.list_of_documents(dbname, colname)
            self.dbname, self.colname = dbname, colname

        self.gui_win.show_documents(dbname, colname, self.current_docs)


    def closeEvent(self, e):
        """Close the document widget, then call ``QWidget.close(self)``."""
        logger.debug('closeEvent')
        if self.gui_win is not None: self.gui_win.close()
        QWidget.close(self)

    if __name__ == "__main__":

      def key_usage(self):
        """Return the key help text (Esc, 0, 1, 2).

        Defined only when the module runs as a script.
        """
        return 'Keys:'\
               '\n  ESC - exit'\
               '\n  0 - set widget'\
               '\n  1 - set another widget'\
               '\n  2 - set another widget'\
               '\n'


      def keyPressEvent(self, e):
        """Handle key presses: Esc closes; keys 0-2 select a document widget type and rebuild the widget; others log the key help.

        Defined only when the module runs as a script. It uses ``Qt``, which this module does not import, and indexes ``list_of_doc_widgets`` with the raw key code.
        """
        logger.info('keyPressEvent, key=', e.key())

        if   e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() in (Qt.Key_0, Qt.Key_1, Qt.Key_2):
            docw_type = self.list_of_doc_widgets[int(e.key())]
            cp.cdb_docw.setValue(docw_type)
            self.set_docs_widget()
        else:
            logger.info(self.key_usage())


if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys
    logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s: %(message)s', datefmt='%H:%M:%S', level=logging.DEBUG)
    app = QApplication(sys.argv)
    w = CMWDBDocs()
    #w.setGeometry(1, 1, 600, 200)
    w.setWindowTitle('Document widge selector')
    w.show()
    app.exec_()
    del w
    del app

# EOF
