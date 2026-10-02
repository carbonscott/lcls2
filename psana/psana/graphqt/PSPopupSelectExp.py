
"""
:py:class:`PSPopupSelectExp` - Popup GUI for (str) experiment selection from the list of experiments
====================================================================================================

Usage::

    # Import
    from psana.graphqt.PSPopupSelectExp import PSPopupSelectExp

    # Methods - see test

See:
    - :py:class:`PSPopupSelectExp`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Created on 2014? by Mikhail Dubrovin
Adopted for LCLS2 on 2021-07-21
 - latest version of CalibManager/src/GUIPopupSelectExp.py
"""

import os

import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QApplication, QDialog, QListWidget, QPushButton, QListWidgetItem,\
                            QVBoxLayout, QHBoxLayout, QTabBar
from PyQt5.QtCore import Qt, QPoint, QMargins, QEvent, QTimer
from PyQt5.QtGui import QFont, QColor, QCursor


def years(lst_exp):
    """Return sorted year strings '20YY' built from the distinct two-digit endings of the names in ``lst_exp``.

    Names whose last two characters are not digits are ignored.
    """
    years = []
    for exp in lst_exp:
        year = exp[-2:]
        if year in years: continue
        if not year.isdigit(): continue
        years.append(year)
    return ['20%s'%y for y in sorted(years)]


def years_and_runs(lst_exp):
    """Return two sorted lists derived from the last two characters of the names in ``lst_exp``.

    The first list is '20YY' for distinct digit endings of 8-character names; the second is 'Run:NN' for distinct digit endings of 9-character names.

    Returns
    -------
    tuple of (list of str, list of str)
    """
    years = []
    runs  = []
    for exp in lst_exp:
        if len(exp) != 8: continue
        year = exp[-2:]
        if year in years: continue
        if not year.isdigit(): continue
        years.append(year)

    for exp in lst_exp:
        if len(exp) != 9: continue
        run = exp[-2:]
        if run in runs: continue
        if not run.isdigit(): continue
        runs.append(run)

    return ['20%s'%y for y in sorted(years)], ['Run:%s'%r for r in sorted(runs)]


def lst_exp_for_year(lst_exp, year):
    """Return the names in ``lst_exp`` whose last two characters equal the last two characters of ``year``.

    ``year`` may be a str or an int (formatted with '%4d').
    """
    str_year = year if isinstance(year,str) else '%4d'%year
    pattern = str_year[-2:] # two last digits if the year
    return [exp for exp in lst_exp if exp[-2:]==pattern]


class PSPopupSelectExp(QDialog):
    """Stay-on-top popup dialog listing experiment names grouped under non-selectable year and 'Run:' headers.

    Clicking an experiment stores its name and accepts the dialog; window deactivation or closing rejects it. A timer re-activates the window every second.
    """
    def __init__(self, parent=None, lst_exp=[], show_frame=False):

        QDialog.__init__(self, parent, flags=Qt.WindowStaysOnTopHint)

        self.name_sel = None
        self.list = QListWidget(parent)
        self.show_frame = show_frame

        self.fill_list(lst_exp)

        vbox = QVBoxLayout()
        vbox.addWidget(self.list)
        self.setLayout(vbox)

        self.list.itemClicked.connect(self.on_item_click)

        self.show_tool_tips()
        self.set_style()

        self.dt_msec=1000
        QTimer().singleShot(self.dt_msec, self.on_timeout)


    def on_timeout(self):
        """Raise, activate and focus the dialog, and schedule itself again after ``self.dt_msec`` ms."""
        self.raise_()
        self.activateWindow()
        self.setFocus(True)
        QTimer().singleShot(self.dt_msec, self.on_timeout)


    def fill_list(self, lst_exp):
        """Fill the list widget from ``lst_exp`` using ``years_and_runs``.

        Each '20YY' header (bold, no item flags) is followed by the sorted 8-character names with that ending; each 'Run:NN' header is followed by the sorted 9-character names with that ending. Sets ``self.years`` and ``self.runs``.
        """
        self.years, self.runs = years_and_runs(lst_exp)

        for year in self.years:
            item = QListWidgetItem(year, self.list)
            item.setFont(QFont('Courier', 14, QFont.Bold))
            item.setFlags(Qt.NoItemFlags)
            #item.setFlags(Qt.NoItemFlags ^ Qt.ItemIsEnabled ^ Qt.ItemIsSelectable)
            for exp in sorted(lst_exp_for_year(lst_exp, year)):
                if len(exp) != 8: continue
                item = QListWidgetItem(exp, self.list)
                item.setFont(QFont('Monospace', 11, QFont.Normal)) # Bold))

        for run in self.runs:
            item = QListWidgetItem(run, self.list)
            item.setFont(QFont('Courier', 14, QFont.Bold))
            item.setFlags(Qt.NoItemFlags)
            #item.setFlags(Qt.NoItemFlags ^ Qt.ItemIsEnabled ^ Qt.ItemIsSelectable)
            for exp in sorted(lst_exp_for_year(lst_exp, run)):
                if len(exp) != 9: continue
                item = QListWidgetItem(exp, self.list)
                item.setFont(QFont('Monospace', 11, QFont.Normal)) # Bold))


    def set_style(self):
        """Set the title, fixed width 120, minimum height 600, small margins, focus policy and, unless ``show_frame``, the frameless flag.

        If the dialog has no parent widget it is moved near the cursor.
        """
        self.setWindowTitle('Select experiment')
        self.setFixedWidth(120)
        self.setMinimumHeight(600)
        if not self.show_frame:
          self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setFocusPolicy(Qt.StrongFocus)
        self.layout().setContentsMargins(2,2,2,2)
        parent = self.parentWidget()
        if parent is None:
           self.move(QCursor.pos().__add__(QPoint(0,-50)))
        logger.debug('use %s position for popup findow' % ('CURSOR' if parent is None else 'BUTTON'))


    def show_tool_tips(self):
        """Set the dialog tool tip to 'Select experiment'."""
        self.setToolTip('Select experiment')


    def on_item_click(self, item):
        """Store the clicked item text in ``name_sel`` and accept the dialog, unless the text is a year or run header."""
        self.name_sel = item.text()
        if self.name_sel in self.years: return # ignore selection of year
        if self.name_sel in self.runs : return # ignore selection of run
        self.accept()
        self.done(QDialog.Accepted)


    def event(self, e):
        #logger.debug('event.type %s' % str(e.type()))
        """Reject the dialog on ``QEvent.WindowDeactivate``, then return ``QDialog.event(self, e)``."""
        if e.type() == QEvent.WindowDeactivate:
            logger.debug('intercepted mouse click outside popup window')
            self.reject()
            self.done(QDialog.Rejected)
        return QDialog.event(self, e)


    def closeEvent(self, event):
        """Log a debug message and reject the dialog."""
        logger.debug('closeEvent')
        self.reject()
        self.done(QDialog.Rejected)


    def selectedName(self):
        """Return the last clicked item text, or None if nothing was clicked."""
        return self.name_sel


def select_experiment(parent, lst_exp, show_frame=False):
    """Show a modal ``PSPopupSelectExp`` for ``lst_exp`` and return ``selectedName()``.

    The ``exec_()`` result is only logged; the return value is None if nothing was clicked.
    """
    w = PSPopupSelectExp(parent, lst_exp, show_frame)
    resp=w.exec_()
    logger.debug('responce from w.exec_(): %s' % str(resp))
    return w.selectedName()


#def select_instrument_experiment(parent=None, dir_instr='/cds/data/psdm', show_frame=False):
def select_instrument_experiment(parent=None, dir_instr='/sdf/data/lcls/ds/', show_frame=False):
    """Let the user pick an instrument directory and then an experiment in it.

    Instrument names come from ``list_of_instruments(dir_instr)`` and experiment names from ``list_of_experiments`` (both in ``psana.pyalgos.generic.PSUtils``).

    Returns
    -------
    tuple
        ``(instr, exp)``; ``(None, None)`` if the instrument selection is cancelled, and ``exp`` may be None.
    """
    from psana.graphqt.QWPopupSelectItem import popup_select_item_from_list
    from psana.pyalgos.generic.PSUtils import list_of_instruments, list_of_experiments
    instrs = sorted(list_of_instruments(dir_instr))
    instr = popup_select_item_from_list(parent, instrs, min_height=250, dx=10, dy=-100, show_frame=show_frame)
    if instr is None:
       logger.debug('instrument selection is cancelled')
       return None, None
    dir_exp = os.path.join(dir_instr, instr)
    logger.debug('direxp:%s' % dir_exp)
    lst_exp = list_of_experiments(dir_exp) # os.listdir(dir_exp))
    return instr, select_experiment(parent, lst_exp, show_frame)


if __name__ == "__main__":
  logging.basicConfig(format='[%(levelname).1s] L%(lineno)04d: %(message)s', level=logging.DEBUG)

  def test_all(tname):
    """Print years, years and runs, and the 2016 experiments for the names in /sdf/data/lcls/ds/MFX/, then open ``select_experiment`` if ``tname == '1'`` (otherwise exit).

    Defined only when the module runs as a script.
    """
    lst_exp = sorted(os.listdir('/sdf/data/lcls/ds/MFX/'))
    print('years form the list of experiments', years(lst_exp))
    print('years and runs form the list of experiments', str(years_and_runs(lst_exp)))
    print('experiments for 2016:', lst_exp_for_year(lst_exp, '2016'))

    app = QApplication(sys.argv)

    exp_name = 'N/A'
    if tname == '1': exp_name = select_experiment(None, lst_exp)
    else: sys.exit('not inplemented test: %s' % tname)
    print('exp_name = %s' % exp_name)

    del app


if __name__ == "__main__":
    import sys; global sys
    os.environ['LIBGL_ALWAYS_INDIRECT'] = '1'
    tname = sys.argv[1] if len(sys.argv) > 1 else '1'
    print(50*'_', '\nTest %s' % tname)
    test_all(tname)
    sys.exit('End of Test %s' % tname)

# EOF
