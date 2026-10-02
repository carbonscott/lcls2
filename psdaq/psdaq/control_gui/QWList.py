#------------------------------
"""Class :py:class:`QWList` is a QListView->QWidget for list model
===================================================================

Usage ::

    # Run test: python lcls2/psdaq/psdaq/control_gui/QWList.py

    from psdaq.control_gui.QWList import QWList
    w = QWList()

Copy psana.graphqt.QWList on 2019-03-11
"""
#------------------------------
import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QListView, QVBoxLayout, QAbstractItemView
from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtCore import Qt, QModelIndex

#from psdaq.control_gui.QWIcons import icon

#------------------------------

class QWList(QListView) :
    """Widget for List
    """
    def __init__(self, **kwargs) :

        QListView.__init__(self, kwargs.get('parent', None))
        #self._name = self.__class__.__name__

        #icon.set_icons()

        self.model = QStandardItemModel()
        self.set_selection_mode()
        self.fill_list_model(**kwargs) # defines self.model
        self.setModel(self.model)

        self.set_style()
        self.show_tool_tips()

        self.connect_signals()
        #self.disconnect_signals()


    def connect_signals(self) :
        """Connect model itemChanged, current-changed, clicked and doubleClicked signals to the `on_*` handlers."""
        self.model.itemChanged.connect(self.on_item_changed)
        self.connect_item_selected_to(self.on_item_selected)
        self.clicked[QModelIndex].connect(self.on_click)
        self.doubleClicked[QModelIndex].connect(self.on_double_click)


    def disconnect_signals(self) :
        """Disconnect the signals connected by `connect_signals`."""
        self.model.itemChanged.disconnect(self.on_item_changed)
        self.disconnect_item_selected_from(self.on_item_selected)
        self.clicked[QModelIndex].disconnect(self.on_click)
        self.doubleClicked[QModelIndex].disconnect(self.on_double_click)
 

    def set_selection_mode(self, smode='extended') :
        """Set the selection mode by name.

        Parameters
        ----------
        smode : str, optional
            One of 'single', 'contiguous', 'extended' (default), 'multi', 'no selection';
            other values raise KeyError.
        """
        logger.debug('Set selection mode: %s'%smode)
        mode = {'single'      : QAbstractItemView.SingleSelection,
                'contiguous'  : QAbstractItemView.ContiguousSelection,
                'extended'    : QAbstractItemView.ExtendedSelection,
                'multi'       : QAbstractItemView.MultiSelection,
                'no selection': QAbstractItemView.NoSelection}[smode]
        self.setSelectionMode(mode)


    def connect_item_selected_to(self, recipient) :
        """Connect the selection model's currentChanged signal to `recipient`."""
        self.selectionModel().currentChanged[QModelIndex, QModelIndex].connect(recipient)


    def disconnect_item_selected_from(self, recipient) :
        """Disconnect `recipient` from the selection model's currentChanged signal."""
        self.selectionModel().currentChanged[QModelIndex, QModelIndex].disconnect(recipient)


    def selected_indexes(self):
        """Return ``self.selectedIndexes()``."""
        return self.selectedIndexes()


    def selected_items(self):
        """Return the model items for the selected indexes."""
        indexes =  self.selectedIndexes()
        return [self.model.itemFromIndex(i) for i in self.selectedIndexes()]


    def clear_model(self):
        """Remove all rows from the model."""
        rows = self.model.rowCount()
        self.model.removeRows(0, rows)


    def fill_list_model(self, **kwargs):
        """Clear the model and append 20 checkable demo items ('00 item text' ... '19 item text'); kwargs are unused."""
        self.clear_model()
        for i in range(20):
            item = QStandardItem('%02d item text'%(i))
            #item.setIcon(icon.icon_table)
            item.setCheckable(True) 
            self.model.appendRow(item)


    def on_item_selected(self, selected, deselected):
        """Log the row and text of the newly current item at info level, if there is one."""
        itemsel = self.model.itemFromIndex(selected)
        if itemsel is not None :
            msg = 'on_item_selected row:%02d selected: %s' % (selected.row(), itemsel.text()) 
            logger.info(msg)

        #itemdes = self.model.itemFromIndex(deselected)
        #if itemdes is not None :
        #    msg = 'on_item_selected row: %d deselected %s' % (deselected.row(), itemdes.text())
        #    logger.info(msg)


    def on_item_changed(self, item):
        """Log the item's text and check state at info level."""
        state = ['UNCHECKED', 'TRISTATE', 'CHECKED'][item.checkState()]
        msg = 'on_item_changed: item "%s", is at state %s' % (item.text(), state)
        logger.info(msg)


    def on_click(self, index):
        """Log the clicked row and its text (truncated to 50 characters) at info level."""
        item = self.model.itemFromIndex(index)
        txt = item.text()
        txtshow = txt if len(txt)<50 else '%s...'%txt[:50]
        msg = 'doc clicked in row%02d: %s' % (index.row(), txtshow) 
        logger.info(msg)


    def on_double_click(self, index):
        """Log the double-clicked row and text at debug level."""
        item = self.model.itemFromIndex(index)
        msg = 'on_double_click item in row:%02d text: %s' % (index.row(), item.text())
        logger.debug(msg)

    #--------------------------
    #--------------------------
    #--------------------------

    def show_tool_tips(self):
        """Set the tool tip to 'List model'."""
        self.setToolTip('List model') 


    def set_style(self):
        #from psana.graphqt.Styles import style
        #self.setWindowIcon(icon.icon_monitor)
        #self.layout().setContentsMargins(0,0,0,0)

        """Set an item-hover style sheet and a minimum size of 50x100."""
        self.setStyleSheet("QListView::item:hover{background-color:#00FFAA;}")

        #self.palette = QPalette()
        #self.resetColorIsSet = False
        #self.butELog    .setIcon(icon.icon_mail_forward)
        #self.butFile    .setIcon(icon.icon_save)  
        self.setMinimumHeight(100)
        self.setMinimumWidth(50)
        #self.adjustSize()
        #self.        setStyleSheet(style.styleBkgd)
        #self.butSave.setStyleSheet(style.styleButton)
        #self.butFBrowser.setVisible(False)
        #self.butExit.setText('')
        #self.butExit.setFlat(True)
 

    #def resizeEvent(self, e):
        #pass
        #self.frame.setGeometry(self.rect())
        #logger.debug('resizeEvent') 


    #def moveEvent(self, e):
        #logger.debug('moveEvent') 
        #self.position = self.mapToGlobal(self.pos())
        #self.position = self.pos()
        #logger.debug('moveEvent - pos:' + str(self.position), __name__)       
        #pass


    def closeEvent(self, e):
        """Log a debug message and call `QListView.closeEvent`."""
        logger.debug('closeEvent')
        QListView.closeEvent(self, e)

        #try    : self.gui_win.close()
        #except : pass

        #try    : del self.gui_win
        #except : pass


    def on_exit(self):
        """Log a debug message and close the widget."""
        logger.debug('on_exit')
        self.close()


    def process_selected_items(self) :
        """Log the number and texts of the selected items at info level."""
        selitems = self.selected_items()
        msg = '%d Selected items:' % len(selitems)
        for i in selitems :
            msg += '\n  %s' % i.text()
        logger.info(msg)

    if __name__ == "__main__" :

      def key_usage(self) :
        """Return the key help text (ESC exits, S shows selected items).

        Defined only when the module is run as a script.
        """
        return 'Keys:'\
               '\n  ESC - exit'\
               '\n  S - show selected items'\
               '\n'


      def keyPressEvent(self, e) :
        #logger.info('keyPressEvent, key=', e.key())       
        """Handle keys in the test window: Esc closes, S logs selected items, others log `key_usage()`.

        Defined only when the module is run as a script.
        """
        if   e.key() == Qt.Key_Escape :
            self.close()

        elif e.key() == Qt.Key_S : 
            self.process_selected_items()

        else :
            logger.info(self.key_usage())

#------------------------------
#------------------------------
#------------------------------

if __name__ == "__main__" :
    import sys
    from PyQt5.QtWidgets import QApplication
    logging.basicConfig(format='%(message)s', level=logging.DEBUG)
    #logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s: %(message)s', datefmt='%H:%M:%S', level=logging.DEBUG)

    app = QApplication(sys.argv)
    w = QWList()
    w.setGeometry(10, 25, 400, 600)
    w.setWindowTitle('QWList')
    w.move(100,50)
    w.show()
    app.exec_()
    del w
    del app

#------------------------------
