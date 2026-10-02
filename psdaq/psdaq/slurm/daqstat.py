"""PyQt5 status window ('daqstat') that periodically shows the status of the processes in a DAQ config file using `psdaq.slurm.main.Runner`."""
import sys
import os
import platform
import time
import getopt
import _thread
import locale
import traceback
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import (
    PYQT_VERSION_STR,
    QT_VERSION_STR,
    Qt,
    QVariant,
    QObject,
    pyqtSignal,
    pyqtSlot,
)
from PyQt5.QtGui import QCursor, QBrush, QColor
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox, QTableWidgetItem
import subprocess


from psdaq.slurm.main import Runner
from psdaq.slurm import ui_procStat

__version__ = "0.6"

# OutDir Full Path Example: daq-sxr-ana01: /u2/pcds/pds/sxr/e19/e19-r0026-s00-c00.xtc
sOutDirPrefix1 = "/u2/pcds/pds/"
sOutFileExtension = ""
bProcMgrThreadError = False
sErrorOutDirNotExist = "Output Dir Not Exist"


class CustomIOError(Exception):
    """Exception subclass with no added behavior."""
    pass


def printStackTrace():
    """Print the current exception's traceback to stdout between separator lines."""
    print("---- Printing program call stacks for debug ----")
    traceback.print_exc(file=sys.stdout)
    print("------------------------------------------------")
    return


def daqmgrThreadWrapper(
    win,
    sConfigFile,
    fQueryInterval,
    evgProcMgr,
):
    """Run `daqmgrThread`; on any exception print an error and traceback and emit ``win.UnknownError`` with the error text."""
    try:
        daqmgrThread(
            win,
            sConfigFile,
            fQueryInterval,
            evgProcMgr,
        )
    except:
        sErrorReport = (
            "daqmgrThreadWrapper(): daqmgrThread(ConfigFile = %s, Query Interval = %f ) Failed"
            % (sConfigFile, float(fQueryInterval))
        )
        print(sErrorReport)
        printStackTrace()
        bProcMgrThreadError = True
        win.UnknownError.emit(
            sErrorReport
        )  # Send out the signal to notify the main window
    return


def daqmgrThread(
    win,
    sConfigFile,
    fQueryInterval,
    evgProcMgr,
):

    """Loop forever: get process status with ``Runner(sConfigFile).show_status(quiet=True)`` and emit ``win.Updated`` every `fQueryInterval` seconds.

    The Runner is created once and stored as ``win.runner``; status goes to
    ``win.ldProcStatus``. On IOError or other errors an empty list is used and
    ``ProcMgrIOError``/``ProcMgrGeneralError`` is emitted with only the file name, although
    those signals are declared with (str, int).
    """
    locale.setlocale(
        locale.LC_ALL, ""
    )  # set locale for printing formatted numbers later

    runner = None
    while True:
        # refresh ProcMgr status
        global bProcMgrThreadError

        try:
            if runner is None:
                runner = Runner(sConfigFile)
            win.runner = runner
            ldProcStatus = runner.show_status(quiet=True)
            win.ldProcStatus = ldProcStatus

        except IOError:
            ldProcStatus = list()  # default to empty list
            print("daqmgrThread(): ProcMgr(%s): I/O error" % (sConfigFile))
            printStackTrace()
            # Send out the signal to notify the main window
            win.ProcMgrIOError.emit(sConfigFile)

        except:
            ldProcStatus = list()  # default to empty list
            print("daqmgrThread(): ProcMgr(%s) Failed" % (sConfigFile))
            printStackTrace()
            # Send out the signal to notify the main window
            win.ProcMgrGeneralError.emit(sConfigFile)

        if True:
            # Send out the signal to notify the main window
            # TODO: We should only need to send ldProcStatus
            win.Updated.emit(ldProcStatus, [], 0, "None")
        time.sleep(fQueryInterval)

    return


class WinProcStat(QtWidgets.QMainWindow, ui_procStat.Ui_mainWindow):

    # define 'Updated' signal
    """Main window (from `ui_procStat.Ui_mainWindow`) with a process ID/status table and Console, Logfile and Restart toggle buttons.

    Defines the Updated, UnknownError, ProcMgrIOError, ProcMgrGeneralError,
    ThreadGeneralError and OutputDirError signals.
    """
    Updated = pyqtSignal(list, list, int, str)

    # define 'UnknownError' signal
    UnknownError = pyqtSignal(str)

    # define 'ProcMgrIOError' signal
    ProcMgrIOError = pyqtSignal(str, int)

    # define 'ProcMgrGeneralError' signal
    ProcMgrGeneralError = pyqtSignal(str, int)

    # define 'ThreadGeneralError' signal
    ThreadGeneralError = pyqtSignal(str, int)

    # define 'OutputDirError' signal
    OutputDirError = pyqtSignal(str)

    def __init__(self, evgProcMgr, parent=None):
        super(WinProcStat, self).__init__(parent)

        self.sCurKey = ""
        self.setupUi(self)

        # setup message box for displaying warning messages
        self.msgBox = QMessageBox(
            QMessageBox.Warning, "Warning", "", QMessageBox.Ok, self
        )
        self.msgBox.setWindowModality(Qt.NonModal)

        # adjust GUI settings
        self.bFirstSort = False

        # setup signal handlers

        # built-in signals
        self.pushButtonConsole.clicked.connect(self.onClickConsole)
        self.pushButtonLogfile.clicked.connect(self.onClickLogfile)
        self.pushButtonRestart.clicked.connect(self.onClickRestart)
        self.tableProcStat.cellClicked.connect(self.onProcCellClicked)

        # new signals defined using pyqtSignal()
        self.Updated.connect(self.onProcMgrUpdated)
        self.ProcMgrIOError.connect(self.onProcMgrIOError)
        self.ThreadGeneralError.connect(self.onThreadGeneralError)
        self.ProcMgrGeneralError.connect(self.onProcMgrGeneralError)
        self.OutputDirError.connect(self.onProcMgrOutputDirError)
        self.UnknownError.connect(self.onProcMgrUnknownError)

        self.iShowConsole = (
            0  # 0: Don't show console, 1: Show console, 2: Show logfile, 3: Restart
        )
        self.runner = None
        return

    def closeEvent(self, event):
        """Close the warning message box (the event is otherwise not handled here)."""
        self.msgBox.close()
        return

    def onProcMgrUpdated(self, ldProcStatus, ldOutputFileStatus):
        """Refill the table with each process's 'showId' and 'status', coloring the status cell by state.

        COMPLETED/COMPLETING are blue, RUNNING green, PENDING yellow, FAILED/PREEMPTED/
        SUSPENDED/STOPPED red; other states raise KeyError. The table is sorted by status the
        first time and the previously current row is reselected.
        """
        self.statusbar.showMessage("Refreshing ProcMgr status...")

        self.tableProcStat.clear()
        self.tableProcStat.setSortingEnabled(False)
        self.tableProcStat.setRowCount(len(ldProcStatus))
        self.tableProcStat.setColumnCount(2)
        self.tableProcStat.setHorizontalHeaderLabels(["ID", "Status"])

        itemCur = None

        for iRow, dProcStatus in enumerate(ldProcStatus):

            # col 1 : UniqueID
            if isinstance(dProcStatus["showId"], str):
                # str
                showId = dProcStatus["showId"]
            else:
                # bytes
                showId = dProcStatus["showId"].decode()
            item = QTableWidgetItem(showId)
            item.setData(Qt.UserRole, QVariant(showId))
            self.tableProcStat.setItem(iRow, 0, item)

            if showId == self.sCurKey:
                itemCur = item

            # col 2 : Status
            sStatus = dProcStatus["status"]
            item = QTableWidgetItem()
            brush1 = QBrush(QColor.fromRgb(255, 255, 255))
            item.setForeground(brush1)
            bluColor = (0, 0, 192)
            grnColor = (0, 192, 0)
            ylwColor = (192, 192, 0)
            redColor = (255, 0, 0)
            statusColors = {
                "COMPLETED": bluColor,
                "COMPLETING": bluColor,
                "FAILED": redColor,
                "PENDING": ylwColor,
                "PREEMPTED": redColor,
                "RUNNING": grnColor,
                "SUSPENDED": redColor,
                "STOPPED": redColor,
            }
            item.setData(0, QVariant(sStatus))
            item.setBackground(QBrush(QColor.fromRgb(*statusColors[sStatus])))

            self.tableProcStat.setItem(iRow, 1, item)

        # end for iRow, key in enumerate( sorted(procMgr.d.iterkeys()) ):

        self.tableProcStat.setColumnWidth(0, 160)
        self.tableProcStat.setColumnWidth(1, 100)

        if not self.bFirstSort:
            self.bFirstSort = True
            self.tableProcStat.sortItems(1, Qt.AscendingOrder)

        self.tableProcStat.setSortingEnabled(True)
        if itemCur != None:
            self.tableProcStat.setCurrentItem(itemCur)

        self.statusbar.clearMessage()
        return

    @pyqtSlot(int, int)
    def onProcCellClicked(self, iRow, iCol):
        """For the clicked row's ID, spawn a console, open the log file or restart it, depending on which toggle is active.

        Does nothing if no runner exists yet or no toggle is active.
        """
        if self.runner == None:
            return
        if self.iShowConsole == 0:
            return

        item = self.tableProcStat.item(iRow, 0)
        showId = item.data(Qt.UserRole)
        if self.iShowConsole == 1:
            self.runner.spawnConsole(showId, self.ldProcStatus, False)
        elif self.iShowConsole == 2:
            self.runner.spawnLogfile(showId, self.ldProcStatus, False)
        elif self.iShowConsole == 3:
            # override cursor
            QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
            self.runner.restart(unique_ids=showId)
            # restore cursor
            QApplication.restoreOverrideCursor()
        return

    def onClickConsole(self, bChecked):
        """Make Console the active toggle (mode 1) or clear the mode, unchecking the other buttons."""
        self.pushButtonLogfile.setChecked(False)
        self.pushButtonRestart.setChecked(False)
        if bChecked:
            self.iShowConsole = 1
        else:
            self.iShowConsole = 0

    def onClickLogfile(self, bChecked):
        """Make Logfile the active toggle (mode 2) or clear the mode, unchecking the other buttons."""
        self.pushButtonConsole.setChecked(False)
        self.pushButtonRestart.setChecked(False)
        if bChecked:
            self.iShowConsole = 2
        else:
            self.iShowConsole = 0

    def onClickRestart(self, bChecked):
        """Make Restart the active toggle (mode 3) or clear the mode, unchecking the other buttons."""
        self.pushButtonConsole.setChecked(False)
        self.pushButtonLogfile.setChecked(False)
        if bChecked:
            self.iShowConsole = 3
        else:
            self.iShowConsole = 0

    @pyqtSlot(str, int)
    def onProcMgrIOError(self, sConfigFile):
        """Show an 'IO Error' warning about config file `sConfigFile`."""
        self.showWarningWindow(
            "IO Error",
            "<p>config file <b>%s</b> cannot be processed correctly, due to an IO Error.<p>"
            % (sConfigFile)
            + "<p>Please check the input file format, or specify a new config file instead.",
        )
        return

    @pyqtSlot(str, int)
    def onProcMgrGeneralError(self, sConfigFile):
        """Show a 'General Error' warning about config file `sConfigFile`."""
        self.showWarningWindow(
            "General Error",
            "<p>config file <b>%s</b> cannot be processed correctly, due to a general Error.<p>"
            % (sConfigFile)
            + "<p>Please check the input file content, and the target machine status.",
        )
        return

    @pyqtSlot(str)
    def onProcMgrOutputDirError(self, sOutDirPrefix1):
        """Show a warning that output directory `sOutDirPrefix1` is not accessible."""
        self.showWarningWindow(
            "Output Directory Does Not Exist",
            "<p>Please check if the system has access to output directory <i>%s</i>.<p>"
            % (sOutDirPrefix1),
        )
        return

    @pyqtSlot(str)
    def onThreadGeneralError(self, sErrorReport):
        """Show a 'Thread General Error' warning containing `sErrorReport`."""
        self.showWarningWindow(
            "Thread General Error",
            "<p><i>%s</i><p>" % (sErrorReport)
            + "<p>thread had a general error. Please check the log file for more details.\n",
        )
        return

    @pyqtSlot(str)
    def onProcMgrUnknownError(self, sErrorReport):
        """Show a critical 'Unknown Error' dialog with `sErrorReport`, then close the window."""
        QMessageBox.critical(
            self,
            "Unknown Error",
            "<p><i>%s</i><p>" % (sErrorReport)
            + "<p>Not able to update the process status. Please check the log file for more details.\n",
        )
        self.close()
        return

    def showWarningWindow(self, title, text):
        """Show the non-modal warning box with `title` and `text`."""
        self.msgBox.setWindowTitle(title)
        self.msgBox.setText(text)
        self.msgBox.show()
        return

    @pyqtSlot(int, int, int, int)
    def on_tableProcStat_currentCellChanged(self, iCurRow, iCurCol, iPrevRow, iPrevCol):
        """Remember the ID of the newly current row in `sCurKey` (ignored for invalid rows)."""
        if iCurRow < 0:
            return

        itemCur = self.tableProcStat.item(iCurRow, 0)
        if itemCur == None:
            return

        self.sCurKey = itemCur.data(Qt.UserRole)
        return

    @pyqtSlot()
    def on_actionOpen_triggered(self):
        """Show an open-file dialog for a .py config file; the chosen name is not used."""
        sFnConfig = str(
            QFileDialog.getOpenFileName(self, "Config File", ".", "config files (*.py)")
        )
        return

    @pyqtSlot()
    def on_actionQuit_triggered(self):
        """Close the window."""
        self.close()
        return

    @pyqtSlot()
    def on_actionAbout_triggered(self):
        """Show the About dialog with the version and Python/Qt/PyQt/platform versions."""
        QMessageBox.about(
            self,
            "About daqstat",
            """<b>Status Monitor</b> v %s
            <p>Copyright &copy; 2009 SLAC PCDS
            <p>This application is used to monitor daq process status and report output file status.
            <p>Python %s - Qt %s - PyQt %s on %s"""
            % (
                __version__,
                platform.python_version(),
                QT_VERSION_STR,
                PYQT_VERSION_STR,
                platform.system(),
            ),
        )
        return


def showUsage():
    """Print the command-line usage and program version."""
    print(
        """\
Usage: %s  [-i | --interval <Query Interval>]  <Config file>
  -i | --interval   <Query Interval>       Query interval in seconds (default: 5 seconds)

Program Version %s\
"""
        % (__file__, __version__)
    )
    return


def main():
    """Parse -i/--interval (default 5 s) and the config file, show `WinProcStat` and start `daqmgrThreadWrapper` in a thread.

    Returns
    -------
    int or None
        0 after printing usage for -v/-h, 1 if no config file is given, else None after
        the event loop exits.
    """
    fProcmgrQueryInterval = 5.0

    (llsOptions, lsRemainder) = getopt.getopt(
        sys.argv[1:],
        "vhi:",
        [
            "version",
            "help",
            "interval=",
        ],
    )

    for (sOpt, sArg) in llsOptions:
        if sOpt in ("-v", "-h", "--version", "--help"):
            showUsage()
            return 0
        elif sOpt in ("-i", "--interval"):
            fProcmgrQueryInterval = float(sArg)

    if len(lsRemainder) < 1:
        print(__file__ + ": Config file is not specified")
        showUsage()
        return 1

    sConfigFile = lsRemainder[0]

    evgProcMgr = QObject()

    app = QApplication([])
    app.setOrganizationName("SLAC")
    app.setOrganizationDomain("slac.stanford.edu")
    app.setApplicationName("daqstat")
    win = WinProcStat(evgProcMgr)
    win.show()

    _thread.start_new_thread(
        daqmgrThreadWrapper,
        (
            win,
            sConfigFile,
            fProcmgrQueryInterval,
            evgProcMgr,
        ),
    )

    app.exec_()

    return


# Main Entry
def _do_main():
    iRet = 0

    try:
        iRet = main()
    except:
        iRet = 101
        print(__file__ + ": %s" % (sys.exc_info()[1]))
        print("---- Printing program call stacks for debug ----")
        traceback.print_exc(file=sys.stdout)
        print("------------------------------------------------")
        showUsage()

    sys.exit(iRet)


if __name__ == "__main__":
    _do_main()
