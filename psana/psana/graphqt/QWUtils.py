
"""
:py:class:`QWUtils` - Popup GUIs
================================

Usage::
    # Test: python lcls2/psana/psana/graphqt/QWUtils.py 0

    # Import
    from psana.graphqt.QWUtils import *

    # Methods - see test

See:
    - :py:class:`QWUtils`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Created on 2017-02-08 by Mikhail Dubrovin
Adopted for LCLS2 on 2018-02-15
"""

import os
import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QMenu, QDialog, QFileDialog, QMessageBox, QColorDialog, QWidget, QVBoxLayout, QApplication
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QCursor


def msg_on_exit():
    """Return a hint string 'run test > python <dir>/examples/ex_<script> <test-number>' built from ``sys.argv[0]``."""
    import sys
    lst = sys.argv[0].rsplit('/',1)
    path = '%s/examples/ex_%s' % tuple(lst) if len(lst) == 2 else 'examples/ex_%s' % lst[0]
    return 'run test > python %s <test-number>' % path


def select_item_from_popup_menu(lst, title=None, default=None, parent=None):
    """Shows the list as a pop-up menu and returns the selected item as a string or None"""
    w = QMenu(parent)
    _title = title if title is not None else 'Select'
    #w.setTitle(_title)
    atitle = w.addAction(_title)
    atitle.setDisabled(True)
    asep = w.addSeparator()
    for name in lst:
       action = w.addAction(name)
       if name == default:
           #w.setDefaultAction(action)
           w.setActiveAction(action)
    item = w.exec_(QCursor.pos())
    return None if item is None else str(item.text()) # str(QString)


def select_color(colini=Qt.blue, parent=None):
    """Select color using QColorDialog"""
    qcd = QColorDialog
    w = qcd(colini, parent)
    w.setOptions(qcd.ShowAlphaChannel)# | qcd.DontUseNativeDialog | qcd.NoButtons
    res = w.exec_()
    color=w.selectedColor()
    #color = QColorDialog.getColor()
    return None if color is None else color # QColor or None


def change_check_box_list_in_popup_menu(list, win_title='Set check boxes', parent=None):
    """Shows the list of check-boxes as a dialog pop-up menu and returns the (un)changed list"""
    if list is None: return 0

    from psana.graphqt.QWPopupCheckList import QWPopupCheckList

    popupMenu = QWPopupCheckList(parent, list, win_title)
    popupMenu.move(QCursor.pos())
    response = popupMenu.exec_()

    if   response == QDialog.Accepted:
        #logger.debug('New checkbox list is accepted')
        return 1
    elif response == QDialog.Rejected:
        #logger.debug('Will use old checkbox list')
        return 0
    else:
        #logger.error('Unknown response...')
        return 2


def change_check_box_dict_in_popup_menu(dict, win_title='Set check boxes', parent=None, msg=''):
    """Shows the dict of check-boxes as a dialog pop-up menu and returns the (un)changed dict"""
    if dict is None: return 0

    from psana.graphqt.QWPopupCheckDict import QWPopupCheckDict

    popupMenu = QWPopupCheckDict(parent, dict, win_title, msg)
    popupMenu.move(QCursor.pos())
    response = popupMenu.exec_()

    if   response == QDialog.Accepted:
        #logger.debug('New checkbox dict is accepted',)
        return 1
    elif response == QDialog.Rejected:
        #logger.debug('Will use old checkbox dict')
        return 0
    else:
        #logger.error('Unknown response...')
        return 2


def select_radio_button_in_popup_menu(dict_of_pars, win_title='Select option', do_confirm=False, parent=None):
    """Popup GUI to select radio button from the list:  dict_of_pars = {'checked':'radio1', 'list':['radio0', 'radio1', 'radio2']}
    """
    from psana.graphqt.QWPopupRadioList import QWPopupRadioList

    popupMenu = QWPopupRadioList(parent, dict_of_pars, win_title, do_confirm)
    popupMenu.move(QCursor.pos()-QPoint(100,100))
    return popupMenu.exec_() # QDialog.Accepted or QDialog.Rejected


def info_rect_xywh(r, cmt='', fmt='%sx=%8.2f  y=%8.2f  w=%8.2f  h=%8.2f'):
    """Return a string with ``cmt`` and the x, y, width and height of rect ``r`` formatted by ``fmt``."""
    return fmt % (cmt, r.x(), r.y(), r.width(), r.height())


def info_rect_lbrt(r, cmt='', fmt='%sL=%8.2f  B=%8.2f  R=%8.2f  T=%8.2f'):
    """Return a string with the left, right, top and bottom of rect ``r`` formatted by ``fmt``.

    ``cmt`` is replaced by the same number of spaces. The values are passed in the order left, right, top, bottom while the default labels read L, B, R, T, so the B, R and T labels do not match their values.
    """
    return fmt % (len(cmt)*' ', r.left(), r.right(), r.top(), r.bottom())


def print_rect(r, cmt=''):
    """Log at debug level ``cmt`` followed by ``info_rect_xywh(r)`` and ``info_rect_lbrt(r)``."""
    logger.debug('%s %s %s'% (cmt, info_rect_xywh(r), info_rect_lbrt(r)))


def info_point(p, cmt='', fmt='%sx=%.2f y=%.2f'):
    """Return a string with ``cmt`` and the x and y of point ``p`` formatted by ``fmt``."""
    return fmt % (cmt, p.x(), p.y())


def get_save_fname_through_dialog_box(parent, path0, title, filter='*.txt'):

    """Open a save-file dialog with caption ``title`` starting at ``path0`` and return the chosen path, or None if cancelled."""
    path, fext = QFileDialog.getSaveFileName(parent,
                                             caption   = title,
                                             directory = path0,
                                             filter    = filter
                                             )
    if path == '':
        #logger.debug('Saving is cancelled. get_save_fname_through_dialog_box')
        return None
    return path


def get_open_fname_through_dialog_box(parent, path0, title, filter='*.txt'):

    """Open an open-file dialog with caption ``title`` starting at ``path0`` and return the chosen path.

    Returns None if the directory or file part of the result is empty (for example when cancelled).
    """
    path, fext = QFileDialog.getOpenFileName(parent, title, path0, filter=filter)

    dname, fname = os.path.split(path)
    if dname == '' or fname == '':
        #logger.debug('Input directiry name or file name is empty... keep file path unchanged...'
        return None
    #logger.info('Input file: ' + path + 'get_open_fname_through_dialog_box')
    return path


def get_existing_directory_through_dialog_box(parent, path0, title, options = QFileDialog.ShowDirsOnly):

    """Open a directory dialog and return the chosen directory (also logged), or None if cancelled."""
    path = QFileDialog.getExistingDirectory(parent, title, path0, options)

    dname = path #, fname = os.path.split(path)
    if dname == '':
        # logger.debug('Input directiry name or file name is empty... keep file path unchanged...'
        return None
    logger.info('Selected directory: %s' % path)
    return path


def confirm_dialog_box(parent=None, text='Please confirm that you aware!', title='Please acknowledge'):
        """Pop-up MODAL box for confirmation"""

        mesbox = QMessageBox(parent, windowTitle=title,
                                           text=text,
                                           standardButtons=QMessageBox.Ok)

        clicked = mesbox.exec_() # DISPLAYS THE QMessageBox HERE
        mesbox.setDefaultButton(QMessageBox.Ok)

        return True if clicked == QMessageBox.Ok else False


def edit_and_confirm_or_cancel_dialog_box(parent=None, text='Text confirm or cancel', title='Edit and confirm or cancel'):
    """Show a ``QWPopupEditConfirm`` dialog with editable ``text`` and Confirm/Cancel buttons.

    Returns
    -------
    str or None
        The edited text if confirmed, otherwise None.
    """
    from psana.graphqt.QWPopupEditConfirm import QWPopupEditConfirm
    w = QWPopupEditConfirm(parent=parent, msg=text, win_title=title, but_title_apply='Confirm', but_title_cancel='Cancel')
    #w.setGeometry(20, 40, 500, 200)
    resp=w.exec_()
    return w.message() if resp == QDialog.Accepted else None


def confirm_or_cancel_dialog_box(parent=None, text='Please confirm or cancel', title='Confirm or cancel'):
        """Pop-up MODAL box for confirmation"""

        mesbox = QMessageBox(parent, windowTitle=title,
                                           text=text,
                                           standardButtons=QMessageBox.Ok | QMessageBox.Cancel)
               #standardButtons=QtGui.QMessageBox.Save | QtGui.QMessageBox.Discard | QtGui.QMessageBox.Cancel)
        mesbox.setDefaultButton(QMessageBox.Ok)

        clicked = mesbox.exec_() # DISPLAYS THE QMessageBox HERE

        if   clicked == QMessageBox.Ok    : return True
        elif clicked == QMessageBox.Cancel: return False
        else: return False


def help_dialog_box(parent=None, text='Help message goes here', title='Help'):
        """Pop-up NON-MODAL box for help etc."""
        mesbox = QMessageBox(parent, windowTitle=title,
                                      text=text,
                                      standardButtons=QMessageBox.Ok)
                                      #standardButtons=QMessageBox.Close)

        mesbox.setDefaultButton(QMessageBox.Ok)
        mesbox.setModal(False)
        mesbox.update()
        clicked = mesbox.exec_() # For MODAL dialog
        return mesbox


def widget_from_layout(l):
    """Create a QWidget, set layout ``l`` on it and return it.

    The code calls ``QWigget`` (a misspelling that is not defined), so it raises NameError.
    """
    w = QWigget()
    w.setLayout(l)
    return w


def layout_from_widget(w, layout=QVBoxLayout):
    """Create a layout of class ``layout`` (default QVBoxLayout), add widget ``w`` to it and return the layout."""
    l = layout()
    l.addWidget(w)
    return l


if __name__ == "__main__":
    import sys
    sys.exit(msg_on_exit())

#EOF
