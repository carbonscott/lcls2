"""PyQt5 table of integer PVs '<base>:<field>' for several bases (columns) and fields (rows)."""
import sys
import argparse
import logging
import socket
import numpy
from PyQt5 import QtCore, QtGui, QtWidgets
from psdaq.cas.pvedit import *
from p4p.client.thread import Context

class PvScalarTable(QtWidgets.QGroupBox):
    """QGroupBox grid of read-only `PvInt` widgets: columns are bases (common prefix removed), rows are field names (last ':' part)."""
    def __init__(self, bases, fields, edit=False):
        super(PvScalarTable,self).__init__('PvScalarTable')

        self.bases = bases
 
        print('bases {:}'.format(bases))

        #  Remove the greatest common prefix
        ncommon = len(bases[0])
        for i,base in enumerate(bases[1:]):
            while base[0:ncommon] != bases[0][0:ncommon]:
                ncommon -= 1

        names = []
        for i,base in enumerate(bases):
            names.append(base[ncommon:])

        print('names {:}'.format(names))

        print('fields {:}'.format(fields))

        self.fields = []
        for i,field in enumerate(fields):
            self.fields.append(field.split(':')[-1])

        print('self.fields {:}'.format(self.fields))

        self.pvnames = []
        for i,base in enumerate(bases):
            pvnames = []
            for j,field in enumerate(fields):
                pvnames.append(base+':'+field)
            self.pvnames.append(pvnames)

        print('pvnames {:}'.format(pvnames))

        glo = QtWidgets.QGridLayout()
        for i,ttl in enumerate(names):
            glo.addWidget(QtWidgets.QLabel(ttl),0,i+1)
        for i,ttl in enumerate(self.fields):
            glo.addWidget(QtWidgets.QLabel(ttl),i+1,0)

        self.widgets = []
        for i,field in enumerate(fields):
            for j,base in enumerate(bases):
                glo.addWidget(PvInt(base+':'+field),i+1,j+1)

        glo.setRowStretch(len(fields)+1,1)
        glo.setColumnStretch(len(bases),1)
        self.setLayout(glo)

class Ui_MainWindow(object):
    """Builder for the window."""
    def setupUi(self, MainWindow, bases, fields):
        """Put a `PvScalarTable(bases, fields)` in the window and set the title 'pvatable'."""
        MainWindow.setObjectName("MainWindow")
        self.centralWidget = QtWidgets.QWidget(MainWindow)
        self.centralWidget.setObjectName("centralWidget")

        lo = QtWidgets.QVBoxLayout()
        lo.addWidget(PvScalarTable(bases,fields))

        self.centralWidget.setLayout(lo)

        MainWindow.resize(500,550)
        MainWindow.setWindowTitle("pvatable")
        MainWindow.setCentralWidget(self.centralWidget)

def main():

    """Parse --bases, --fields and -v, then run the window.

    The defaults for --bases and --fields are plain strings, not lists, so without those
    options the table code iterates over characters.
    """
    print(QtCore.PYQT_VERSION_STR)

    parser = argparse.ArgumentParser(description='simple pv monitor gui')
    parser.add_argument("--bases", help="pv bases to monitor", nargs='+', default="DAQ:LAB2:HSD:DEV06_3E:A")
    parser.add_argument("--fields", help="pvs to monitor", nargs='+', default="Top:TimingFrameRx:sofCount")
    parser.add_argument('-v', '--verbose', action='store_true', help='be verbose')
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    app = QtWidgets.QApplication([])
    MainWindow = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow,args.bases,args.fields)
    MainWindow.updateGeometry()

    MainWindow.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
