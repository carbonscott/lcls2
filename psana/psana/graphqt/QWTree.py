
"""Class :py:class:`QWTree` is a QTreeView->QWidget for tree model
===================================================================

Usage ::

    # Run test: python lcls2/psana/psana/graphqt/QWTree.py

    from psana.graphqt.QWTree import QWTree
    w = QWTree()

Created on 2017-03-23 by Mikhail Dubrovin
"""

import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QApplication, QTreeView, QVBoxLayout, QAbstractItemView
from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtCore import Qt, QModelIndex

from psana.graphqt.QWIcons import icon


class QWTree(QTreeView):
    """Widget for tree
    """
    dic_smodes = {'single'      : QAbstractItemView.SingleSelection,
                  'contiguous'  : QAbstractItemView.ContiguousSelection,
                  'extended'    : QAbstractItemView.ExtendedSelection,
                  'multi'       : QAbstractItemView.MultiSelection,
                  'no selection': QAbstractItemView.NoSelection}

    def __init__(self, parent=None, tname='1'):

        QTreeView.__init__(self, parent)

        icon.set_icons()

        self.tname = tname
        self.model = QStandardItemModel()
        self.set_selection_mode()

        self.fill_tree_model() # defines self.model

        self.setModel(self.model)
        self.setAnimated(True)

        self.set_style()
        self.show_tool_tips()

        self.expanded.connect(self.on_item_expanded)
        self.collapsed.connect(self.on_item_collapsed)
        #self.model.itemChanged.connect(self.on_item_changed)
        self.connect_item_selected(self.on_item_selected)
        self.clicked[QModelIndex].connect(self.on_click)
        #self.doubleClicked[QModelIndex].connect(self.on_double_click)


    def set_selection_mode(self, smode='extended'):
        """Set the view selection mode from a name.

        ``smode`` is a key of ``dic_smodes`` ('single', 'contiguous', 'extended', 'multi', 'no selection'); any other value raises KeyError.
        """
        logger.debug('Set selection mode: %s'%smode)
        mode = self.dic_smodes[smode]
        self.setSelectionMode(mode)


    def connect_item_selected(self, recipient):
        """Connect ``recipient`` to the selection model's ``currentChanged[QModelIndex, QModelIndex]`` signal."""
        self.selectionModel().currentChanged[QModelIndex, QModelIndex].connect(recipient)


    def disconnect_item_selected(self, recipient):
        """Disconnect ``recipient`` from the selection model's ``currentChanged[QModelIndex, QModelIndex]`` signal."""
        self.selectionModel().currentChanged[QModelIndex, QModelIndex].disconnect(recipient)


    def selected_indexes(self):
        """Return ``self.selectedIndexes()``."""
        return self.selectedIndexes()


    def selected_items(self):
        """Return the list of model items for the currently selected indexes."""
        indexes =  self.selectedIndexes()
        return [self.model.itemFromIndex(i) for i in self.selectedIndexes()]


    def clear_model(self):
        """Remove all top-level rows from ``self.model``."""
        rows = self.model.rowCount()
        self.model.removeRows(0, rows)


    def fill_tree_model(self):
        """Fill the model with ``fill_tree_model_v2`` if ``self.tname == '2'``, otherwise with ``fill_tree_model_v1``.

        ``fill_tree_model_v2`` is defined only when the module runs as a script, so ``tname='2'`` fails with AttributeError when the class is imported.
        """
        if self.tname=='2': self.fill_tree_model_v2()
        else:               self.fill_tree_model_v1()


    def fill_tree_model_v1(self):
        """Clear the model and fill it with nested demo items.

        For k in 0..4 it starts at the invisible root (setting its icon to the open folder) and, k times, appends a checkable 'itemA k i' item and an 'itemB k i' folder item, then descends into the 'itemB' item.
        """
        self.clear_model()
        for k in range(0, 5):
            parentItem = self.model.invisibleRootItem()
            parentItem.setIcon(icon.icon_folder_open)
            for i in range(0, k):
                item = QStandardItem('itemA %s %s'%(k,i))
                item.setIcon(icon.icon_table)
                item.setCheckable(True)
                parentItem.appendRow(item)
                item = QStandardItem('itemB %s %s'%(k,i))
                item.setIcon(icon.icon_folder_closed)
                parentItem.appendRow(item)
                parentItem = item
                logger.debug('append item %s' % (item.text()))


    def on_item_expanded(self, ind):
        """Set the open-folder icon on the expanded item if it has children.

        Connected to the ``expanded`` signal in ``__init__``.
        """
        item = self.model.itemFromIndex(ind)
        if item.hasChildren():
           item.setIcon(icon.icon_folder_open)


    def on_item_collapsed(self, ind):
        """Set the closed-folder icon on the collapsed item if it has children.

        Connected to the ``collapsed`` signal in ``__init__``.
        """
        item = self.model.itemFromIndex(ind)
        if item.hasChildren():
           item.setIcon(icon.icon_folder_closed)


    def on_item_selected(self, selected, deselected):
        """Log at debug level the text, row and parent text of the newly current item, if it exists.

        Connected to the selection model's currentChanged signal; ``deselected`` is unused.
        """
        itemsel = self.model.itemFromIndex(selected)
        if itemsel is not None:
            parent = itemsel.parent()
            parname = parent.text() if parent is not None else None
            msg = 'selected item: %s row: %d parent: %s' % (itemsel.text(), selected.row(), str(parname))
            logger.debug(str(msg))


    def on_item_changed(self, item):
        """Log at debug level the text and check state of a changed item.

        Not connected in ``__init__`` (the connection is commented out).
        """
        state = ['UNCHECKED', 'TRISTATE', 'CHECKED'][item.checkState()]
        msg = 'on_item_changed: item "%s", is at state %s' % (item.text(), state)
        logger.debug(msg)


    def on_click(self, index):
        """Log the clicked item and its parent text; if ``self.tname == '2'`` also call ``fill_item_test_v2(item)``."""
        item = self.model.itemFromIndex(index)
        parent = item.parent()
        spar = parent.text() if parent is not None else None
        msg = 'clicked item: %s parent: %s' % (item.text(), spar) # index.row()
        logger.debug(msg)
        if self.tname=='2': self.fill_item_test_v2(item)


    def on_double_click(self, index):
        """Log at debug level the row and text of the double-clicked item.

        Not connected in ``__init__`` (the connection is commented out).
        """
        item = self.model.itemFromIndex(index)
        msg = 'on_double_click item in row:%02d text: %s' % (index.row(), item.text())
        logger.debug(msg)


    def process_expand(self):
        """Log a debug message and expand all tree items."""
        logger.debug('process_expand')
        #self.model.set_all_group_icons(self.icon_expand)
        self.expandAll()
        #self.tree_view_is_expanded = True


    def process_collapse(self):
        """Log a debug message and collapse all tree items."""
        logger.debug('process_collapse')
        #self.model.set_all_group_icons(self.icon_collapse)
        self.collapseAll()
        #self.tree_view_is_expanded = False


    def show_tool_tips(self):
        """Set the widget tool tip to 'Tree model'."""
        self.setToolTip('Tree model')


    def set_style(self):
        """Hide the header, set the window icon and zero contents margins, and apply a style sheet that colors hovered items."""
        self.header().hide()
        #from psana.graphqt.Styles import style
        self.setWindowIcon(icon.icon_monitor)
        self.setContentsMargins(0,0,0,0)
        self.setStyleSheet("QTreeView::item:hover{background-color:#00FFAA;}")


    def closeEvent(self, e):
        """Log a debug message and forward the close event to ``QTreeView.closeEvent``."""
        logger.debug('closeEvent')
        QTreeView.closeEvent(self, e)


    def on_exit(self):
        """Log a debug message and close the widget."""
        logger.debug('on_exit')
        self.close()


    if __name__ == "__main__":

      def fill_tree_model_v2(self):
        """Clear the model and append 1000 top-level folder items 'itemTop %04d', logging the elapsed time.

        Defined only when the module runs as a script.
        """
        from time import time
        t0_sec = time()

        self.clear_model()
        parentItem = self.model.invisibleRootItem()
        #parentItem.setIcon(icon.icon_folder_open)

        for k in range(0, 1000):
            item = QStandardItem('itemTop %04d'%(k))
            item.setIcon(icon.icon_folder_closed)
            parentItem.appendRow(item)

        logger.info('model is completed %.3f sec' % (time()-t0_sec))


      def fill_item_test_v2(self, parent_item):
        """Replace the children of ``parent_item`` with five new folder items.

        Existing child rows are removed first; each new item text includes the next column number. Defined only when the module runs as a script.
        """
        m = self.model
        pindex = m.indexFromItem(parent_item)
        if m.hasChildren(pindex):
            logger.info('item already has children - update')
            #print('XXX rowCount %d' % m.rowCount(pindex))
            m.removeRows(0, m.rowCount(pindex), pindex)
            #print('XXX removeRows rowCount %d' % m.rowCount(pindex))

        nextcol = pindex.column() + 1
        for k in range(0, 5):
           item = QStandardItem('itemA %02d col:%d' % (k,nextcol))
           item.setIcon(icon.icon_folder_closed)
           parent_item.appendRow(item)


      def keyPressEvent(self, e):
        """Handle key presses: Esc closes, E expands all, C collapses all, any other key logs a key help message.

        Defined only when the module runs as a script.
        """
        logger.debug('keyPressEvent, key = %s'%e.key())
        if   e.key() == Qt.Key_Escape:
            self.close()

        elif e.key() == Qt.Key_E:
            self.process_expand()

        elif e.key() == Qt.Key_C:
            self.process_collapse()

        else:
            logger.debug('Keys:'\
              '\n  ESC - exit'\
              '\n  E - expand'\
              '\n  C - collapse'\
              '\n')


if __name__ == "__main__":

    import os
    os.environ['LIBGL_ALWAYS_INDIRECT'] = '1'

    import sys
    tname = sys.argv[1] if len(sys.argv) > 1 else '1'
    scrname = sys.argv[0].split('/')[-1]
    print('%s\nUSAGE:' % (60*'_')\
      +'\n  python %s 1 - (default) - pyramide item model ' % (scrname)\
      +'\n  python %s 2 - dynamically added item model ' % (scrname)\
    )

    logging.basicConfig(format='[%(levelname).1s] L:%(lineno)03d %(name)s %(message)s', level=logging.DEBUG)
    app = QApplication(sys.argv)
    w = QWTree(tname=tname)
    w.setGeometry(10, 25, 400, 600)
    w.setWindowTitle('QWTree')
    w.move(100,50)
    w.show()
    app.exec_()
    del w
    del app

# EOF
