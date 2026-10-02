
"""
:py:class:`QWPopupFileName` - wrapper over QFileDialog to Open/Save file name
=============================================================================

Usage::

    # Import
    from psana.graphqt.QWPopupFileName import popup_file_name
    path = popup_file_name(parent=None, mode='r', path='', dirs=[], filter='*')

See:
    - :py:class:`QWPopupFileName`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Created on 2023-09-08 by Mikhail Dubrovin
"""
import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QApplication, QFileDialog
from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QCursor

def popup_file_name(parent=None, mode='w', path='', dirs=[], fltr='*'):
    """Open a file dialog and return the selected path.

    Parameters
    ----------
    parent : QWidget or None
        Dialog parent; if None the ``QFileDialog`` object is moved near the cursor.
    mode : str
        ``'w'`` calls ``getSaveFileName`` (caption ``'Output file'``), any other value ``getOpenFileName`` (caption ``'Input file'``).
    path : str
        Initial directory or file.
    dirs : list of str
        Set as the dialog history.
    fltr : str
        Name filter.

    Returns
    -------
    str
        First element of the dialog response (the chosen path; an empty string if cancelled).
    """
    qfdial = QFileDialog() #directory=path)
    qfdial.setHistory([]) # clear history
    rsp = qfdial.restoreState(qfdial.saveState())
    qfdial.setHistory(dirs)
    logger.debug('QFileDialog.history: %s' % str(qfdial.history()))
    if parent is None: qfdial.move(QCursor.pos() + QPoint(-10,-10))

    resp = qfdial.getSaveFileName(parent=parent, caption='Output file', directory=path, filter=fltr)\
           if mode == 'w' else \
           qfdial.getOpenFileName(parent=parent, caption='Input file', directory=path, filter=fltr)

    logger.debug('QFileDialog.get[Save/Open]FileName response: %s' % str(resp))
    path, filter = resp
    return path

if __name__ == "__main__":
    #import os
    import sys
    logging.basicConfig(format='[%(levelname).1s] L%(lineno)04d: %(message)s', level=logging.DEBUG)

    tname = sys.argv[1] if len(sys.argv) > 1 else '0'
    logger.debug('%s\nTest %s' % (50*'_', tname))

    app = QApplication(sys.argv)
    fltr = '*.py *.txt *.text *.dat *.data *.meta\n*'
    dirs = './ ../'
    if   tname == '0': path = popup_file_name(parent=None, mode='r', path='x.txt', dirs=[], fltr=fltr)
    elif tname == '1': path = popup_file_name(parent=None, mode='w', path='x.txt', dirs=[], fltr=fltr)
    else: sys.exit('Test %s is not implemented' % tname)
    #dname, fname = os.path.split(path)
    logger.debug('path = %s' % path)
    sys.exit('End of Test %s' % tname)

# EOF

