
"""Class :py:class:`DMQWMain` is a QWidget for File Manager of LCLS1
========================================================================

Usage ::

    # Run test: python lcls2/psana/psana/graphqt/DMQWMain.py

    from psana.graphqt.DMQWMain import DMQWMain

See method:

Created on 2021-08-10 by Mikhail Dubrovin
"""

import logging
logger = logging.getLogger(__name__)
import sys

from PyQt5.QtWidgets import QApplication, QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QTextEdit
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextCursor
from psana.graphqt.CMConfigParameters import cp, dir_calib, expname_def
from psana.graphqt.DMQWList import DMQWList, uws
from psana.graphqt.DMQWControl import DMQWControl
from psana.graphqt.QWInfoPanel import QWInfoPanel

class DMQWMain(QWidget):

    """Data-manager main widget: ``DMQWControl`` above ``DMQWList`` on the left of a splitter, ``QWInfoPanel`` on the right.

    The constructor registers the instance as ``cp.dmqwmain``, sets ``append_info`` to
    ``winfo.append`` and copies ``uws.is_lcls2`` into ``self.is_lcls2``.
    """
    def __init__(self, **kwa):

        parent = kwa.get('parent', None)
        kwa.setdefault('parent', None)

        QWidget.__init__(self, parent)

        cp.dmqwmain = self

        self.proc_kwargs(**kwa)

        self.winfo = QWInfoPanel()
        self.wlist = DMQWList(**kwa)
        self.wctrl = DMQWControl(**kwa)

        self.vbox1 = QVBoxLayout()
        self.vbox1.addWidget(self.wctrl)
        self.vbox1.addWidget(self.wlist)
        self.wleft = QWidget()
        self.wleft.setLayout(self.vbox1)

        self.hspl = QSplitter(Qt.Horizontal)
        self.hspl.addWidget(self.wleft)
        self.hspl.addWidget(self.winfo)
        self.vbox = QVBoxLayout()
        self.vbox.addWidget(self.hspl)
        self.setLayout(self.vbox)

        self.set_style()
        self.set_tool_tips()

        self.append_info = self.winfo.append # shotcut
        self.is_lcls2 = uws.is_lcls2


    def proc_kwargs(self, **kwa):
        """Read ``loglevel``, ``logdir`` and ``savelog`` from the keyword arguments into local variables; they are not used further."""
        loglevel   = kwa.get('loglevel', 'DEBUG').upper()
        logdir     = kwa.get('logdir', './')
        savelog    = kwa.get('savelog', False)


    def set_tool_tips(self):
        """Set the widget tool tip to ``'File Manager for LCLS1'``."""
        self.setToolTip('File Manager for LCLS1')


    def set_style(self):
        """Set layout margins of the sub-widgets, fix the control height to 60 and put the splitter at 280 pixels."""
        self.layout().setContentsMargins(0,0,0,0)
        self.wleft.layout().setContentsMargins(0,0,0,0)
        self.winfo.layout().setContentsMargins(0,0,0,0)
        self.wctrl.layout().setContentsMargins(2,2,2,0)
        self.winfo.hbox.layout().setContentsMargins(2,2,2,0)
        self.wctrl.setFixedHeight(60)
        spl_pos = 280
        self.wleft.setMinimumWidth(spl_pos)
        self.hspl.setSizes((spl_pos, self.size().width()-spl_pos,))


    def closeEvent(self, e):
        """Pass the event to ``QWidget.closeEvent`` and set ``cp.dmqwmain`` to None."""
        logger.debug('closeEvent')
        QWidget.closeEvent(self, e)
        cp.dmqwmain = None


    def fname_info(self, expname, runnum):
        """Return the info file name ``'info-<expname>-r<run>.txt'``.

        The run is formatted as ``%04d`` if ``runnum`` is an int, otherwise with ``str``.
        """
        srun = '%04d' % runnum if isinstance(runnum,int) else str(runnum)
        return 'info-%s-r%s.txt' % (expname, srun)


    def dump_info_exp_run_1(self, expname, runnum):
        """Append to the info panel the "Scan Table" run-table record whose ``'num'`` equals ``runnum``.

        The list comes from ``uws.run_table_data(expname)`` (web service request); if it is None a
        "missing" note is appended instead. The text is passed with the file name from :meth:`fname_info`.
        """
        s = 'dump_info_exp_run_1 %s run %s info:' % (expname, str(runnum))
        lst = uws.run_table_data(expname)
        if lst is None: s += ' list of run info dicts is missing'
        else:
          for d in lst:
            if d['num']==runnum:
              s += '\n' + uws.json.dumps(d, indent=2)
              break
        self.append_info(s, self.fname_info(expname, runnum))


    def dump_info_exp_run_2(self, expname, runnum):
        """Append to the info panel the ``uws.json_runs(expname)`` record with ``'run_num' == runnum`` and the experiment tags.

        Both lists come from web service requests (``uws.json_runs``, ``uws.exp_tags``); a "missing"
        note is added if the run list is None.
        """
        s = 'dump_info_exp_run_2 %s run %s info:' % (expname, str(runnum))
        lst = uws.json_runs(expname)#, location)
        if lst is None: s += ' list of run info dicts is missing'
        else:
          for d in lst:
            if d['run_num']==runnum:
              s += '\n' + uws.json.dumps(d, indent=2)
              break

        tags = uws.exp_tags(expname)
        s += '\n exp: %s tags %s' % (expname, tags)
        self.append_info(s, self.fname_info(expname, runnum))


    def dump_info_files(self, expname, runnum):
        """Append to the info panel the JSON returned by ``uws.run_files(expname, runnum)`` (web service request)."""
        s = 'dump_info_files %s run %s info:' % (expname, str(runnum))
        jo = uws.run_files(expname, runnum)
        s += uws.json.dumps(jo, indent=2)
        self.append_info(s, self.fname_info(expname, runnum))


    def dump_all_run_parameters(self, expname, runnum):
        """Append to the info panel the JSON returned by ``uws.run_parameters(expname, runnum)`` (web service request).

        The header uses ``%d`` for ``runnum``, so ``runnum`` must be an integer.
        """
        s = 'dump_all_run_parameters for %s run %d\n' % (expname, runnum)
        jo = uws.run_parameters(expname, runnum)
        s += uws.json.dumps(jo, indent=2)
        self.append_info(s, self.fname_info(expname, runnum))


    def dump_info_exp_run(self, expname, runnum):
        """Call :meth:`dump_all_run_parameters`, :meth:`dump_info_exp_run_1`, :meth:`dump_info_exp_run_2` and :meth:`dump_info_files` in that order."""
        self.dump_all_run_parameters(expname, runnum)
        self.dump_info_exp_run_1(expname, runnum)
        self.dump_info_exp_run_2(expname, runnum)
        self.dump_info_files(expname, runnum)


    def on_selected_exp_run(self, expname, runnum): # called from DMQWList
        """Dump all info for the selected experiment/run and forward the selection to ``wctrl.on_selected_exp_run``."""
        self.dump_info_exp_run(expname, runnum)
        self.wctrl.on_selected_exp_run(expname, runnum)


def data_manager(**kwa):
    """Configure logging, create a ``QApplication`` and show a ``DMQWMain`` titled ``'Data Manager'``.

    Parameters
    ----------
    **kwa
        Passed to ``DMQWMain``; ``loglevel`` (default ``'DEBUG'``) sets the logging level.
    """
    loglevel = kwa.get('loglevel', 'DEBUG').upper()
    intlevel = logging._nameToLevel[loglevel]
    logging.basicConfig(format='[%(levelname).1s] %(name)s L%(lineno)04d: %(message)s', level=intlevel)

    a = QApplication(sys.argv)
    w = DMQWMain(**kwa)
    w.setGeometry(10, 100, 1000, 800)
    w.move(50,20)
    w.show()
    w.setWindowTitle('Data Manager')
    a.exec_()
    del w
    del a


if __name__ == "__main__":
    import os
    os.environ['LIBGL_ALWAYS_INDIRECT'] = '1'
    kwa = {\
      'loglevel':'DEBUG',\
      'expname':expname_def(),\
    }
    tname = sys.argv[1] if len(sys.argv) > 1 else '0'
    if tname == '0': data_manager(**kwa)
    else: logger.debug('Not-implemented test "%s"' % tname)

# EOF
