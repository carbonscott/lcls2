"""PyQt5 GUI for DTI PVs: per-slot (3-7) allocation and status tabs under a PV base."""
import sys
import argparse
from PyQt5 import QtCore, QtGui, QtWidgets
from psdaq.cas.pvedit import *
from p4p.client.thread import Context

NUsLinks = 7
NDsLinks = 7
NPartitions = 8

try:
    QString = unicode
except NameError:
    # Python 3
    QString = str

try:
    QChar = unichr
except NameError:
    # Python 3
    QChar = chr

class PvPushButtonX(QtWidgets.QPushButton):

    """QPushButton (max width 25) that puts 1 to PV `pvname` when clicked; the PV is monitored with a no-op `update`."""
    valueSet = QtCore.pyqtSignal('QString',name='valueSet')

    def __init__(self, pvname, label):
        super(PvPushButtonX, self).__init__(label)
        self.setMaximumWidth(25) # Revisit

        self.clicked.connect(self.buttonClicked)

        self.pv = Pv(pvname, self.update)

    def update(self, err):
        """Do nothing; body is `pass`."""
        pass

    def buttonClicked(self):
        """Put 1 to the PV."""
        self.pv.put(1)          # Value is immaterial

class PvEditIntX(PvEditInt):

    """`PvEditInt` subclass with no changes."""
    def __init__(self, pv, label):
        super(PvEditIntX, self).__init__(pv, label)
#       self.setMaximumWidth(70)

class PvEditCheckList:

    """Row of `entries` exclusive check boxes in `grid` bound to PV `pv`: box k corresponds to PV value k-1."""
    def __init__(self, pv, grid, row, col, entries):
        self.boxes = QtWidgets.QButtonGroup()
        for i in range(entries):
            cb = QtWidgets.QCheckBox()
            grid.addWidget( cb, row, col+i,
                            QtCore.Qt.AlignHCenter )
            self.boxes.addButton(cb,i)
        self.boxes.buttonClicked.connect(self.buttonClicked)
        initPvMon(self,pv)

    def buttonClicked(self, button):
        """Put ``checkedId() - 1`` to the PV."""
        value = self.boxes.checkedId()-1
        self.pv.put(value)

    def update(self, err):
        """Check box ``value + 1`` (from a synchronous get), ignoring errors from a missing box; print `err` if set."""
        q = self.pv.get()+1
        if err is None:
            try:
                self.boxes.button(int(q)).setChecked(True)
            except:
                pass
        else:
            print(err)

class PvCmb(PvEditCmb):

    """Disabled (read-only) `PvEditCmb`."""
    def __init__(self, pvname, choices):
        super(PvCmb, self).__init__(pvname, choices)
        self.setEnabled(False)

def LblPushButtonX(parent, pvbase, name, count=1, start=0, istart=0):
    """Call `PvInput` with `PvPushButtonX`; returns None."""
    return PvInput(PvPushButtonX, parent, pvbase, name, count, start, istart)

def LblEditIntX(parent, pvbase, name, count=1, start=0, istart=0, enable=True):
    """Call `PvInput` with `PvEditIntX`; returns None."""
    return PvInput(PvEditIntX, parent, pvbase, name, count, start, istart, enable)

class DtiAllocMon(object):
    """Monitor PV `pvname` and call ``parent.updateTable(err)`` on each update."""
    def __init__(self, parent, pvname):
        self.parent = parent
        initPvMon(self,pvname)

    def update(self,err):
        """Call ``self.parent.updateTable(err)``."""
        self.parent.updateTable(err)

class DtiAllocation(QtWidgets.QWidget):

    """Grid editing, for each upstream link i, 'UsLinkPartition<i>' (via `PvEditCheckList`) and the bits of 'UsLinkFwdMask<i>'.

    Column j of the forward-mask boxes is an exclusive group across upstream links.
    """
    def __init__(self, pvbase):
        super(DtiAllocation, self).__init__()

        glo = QtWidgets.QGridLayout()

        row = 0
        colp = 2
        cold = 12
        glo.addWidget( QtWidgets.QLabel('US'), row, 0,
                       QtCore.Qt.AlignHCenter )
        glo.addItem  ( QtWidgets.QSpacerItem( 15, 5 ), row, colp-1 )
        glo.addWidget( QtWidgets.QLabel('Partition'), row, colp, 1, 9,
                       QtCore.Qt.AlignHCenter )
        glo.addItem  ( QtWidgets.QSpacerItem( 15, 5 ), row, cold-1 )
        glo.addWidget( QtWidgets.QLabel('DS Links') , row, cold, 1, NDsLinks,
                       QtCore.Qt.AlignHCenter )
        row += 1
        glo.addWidget( QtWidgets.QLabel('None'), row, colp,
                       QtCore.Qt.AlignHCenter )
        for i in range(NPartitions):
            glo.addWidget( QtWidgets.QLabel('%d'%i), row, i+colp+1,
                           QtCore.Qt.AlignHCenter )
        for i in range(NUsLinks):
            glo.addWidget( QtWidgets.QLabel('%d'%i), row, i+cold,
                           QtCore.Qt.AlignHCenter )

        self.pvbase = pvbase
        self.groups = []
        for j in range(NDsLinks):
            self.groups.append(QtWidgets.QButtonGroup())
        for i in range(NUsLinks):
            row += 1
            glo.addWidget( QtWidgets.QLabel('%d'%i), row, 0,
                           QtCore.Qt.AlignHCenter )
            PvEditCheckList(pvbase+'UsLinkPartition%d'%i, glo, row, colp, 9)
            for j in range(NDsLinks):
                cb = QtWidgets.QCheckBox()
                self.groups[j].addButton(cb,i)
                glo.addWidget( cb, row, j+cold,
                               QtCore.Qt.AlignHCenter )
                cb.clicked.connect(self.update)

        self.mon = []
        for i in range(NUsLinks):
            self.mon.append(DtiAllocMon(self,pvbase+'UsLinkFwdMask%d'%i))

        self.setLayout(glo)

    def updateTable(self,err):
        """Get every 'UsLinkFwdMask<i>' PV and check box (i, j) for each set bit j."""
        usmask = [0]*len(self.mon)
        for i,mon in enumerate(self.mon):
            usmask[i] = mon.pv.get()
            for j in range(NDsLinks):
                if ((usmask[i] & (1<<j))!=0):
                    self.groups[j].button(i).setChecked(True)

    def update(self):
        """Build each upstream link's mask from the checked box of every downstream-link column and put it to 'UsLinkFwdMask<i>'."""
        usmask = [0]*NUsLinks
        for j in range(NDsLinks):
            i = self.groups[j].checkedId()
            if i >=0:
                usmask[i] = usmask[i] | (1<<j)
        for i in range(NUsLinks):
            self.mon[i].pv.put(usmask[i])

class DtiStatistics(QtWidgets.QWidget):

    """Status widget: link-up masks, a CountClear button, upstream/downstream count tables and five PvLabel values.

    The labels are QpllLock, MonClkRate (x1e-6, 'MHz'), TimLinkUp, TimRefClk (x1e-6,
    'MHz') and TimFrRate (x1e-3, 'kHz').
    """
    def __init__(self, pvbase):
        super(DtiStatistics, self).__init__()
        self._pvlabels = []

        lor = QtWidgets.QVBoxLayout()
        if True:
            hbox = QtWidgets.QHBoxLayout()
            hbox.addLayout( LblMask(pvbase, 'BpLinkUp', 1) )
            hbox.addLayout( LblMask(pvbase, 'UsLinkUp', NUsLinks) )
            hbox.addLayout( LblMask(pvbase, 'DsLinkUp', NDsLinks) )
            lor.addLayout(hbox)

        lor.addWidget( PvPushButton(pvbase + "CountClear", "CountClear") )

        lor.addWidget(PvIntTable('Upstream Link Stats', pvbase,
                                 ['UsWrFifoD','UsRdFifoD','dUsIbEvt','UsObSent','UsObRecv','dUsRxFull','dUsRxInh','dUsRxErrs'],
                                 ['FifoWr'   ,'FifoRd'   ,'IbEvt'   ,'CtlOut'  ,'CtlIn'   ,'Full'     ,'InhEvts' ,'RxErrs'],
                                 NUsLinks))

        lor.addWidget(PvIntTable('Downstream Link Stats', pvbase,
                                 ['dDsRxErrs','dDsRxFull','dDsObSent'],
                                 ['RxErrs'   ,'Full' ,'MBytes'],
                                 NDsLinks))

        PvLabel(self, lor, pvbase, "QpllLock"    )
        PvLabel(self, lor, pvbase, "MonClkRate", scale=1.e-6, units='MHz' )
        PvLabel(self, lor, pvbase, "TimLinkUp"    )
        PvLabel(self, lor, pvbase, "TimRefClk" , scale=1.e-6, units='MHz' )
        PvLabel(self, lor, pvbase, "TimFrRate" , scale=1.e-3, units='kHz' )

        self.setLayout(lor)

class Ui_MainWindow(object):
    """Builder for the DTI window."""
    def setupUi(self, MainWindow, title):
        """Build 'Allocation' and 'Status' tab widgets with one tab per slot 3-7 (PV prefix '<title>:<slot>:') and set the window title to `title`."""
        MainWindow.setObjectName("MainWindow")
        self.centralWidget = QtWidgets.QWidget(MainWindow)
        self.centralWidget.setObjectName("centralWidget")

        lol = QtWidgets.QVBoxLayout()
        lol.addWidget( QtWidgets.QLabel('Allocation') )

        alloctab = QtWidgets.QTabWidget()
        for i in range(3,8):
            pvslot = title + ':%d:'%i
            alloctab.addTab( DtiAllocation(pvslot), 'Slot-%d'%i )
        lol.addWidget(alloctab)

        lol.addWidget( QtWidgets.QLabel('Status') )

        statstab = QtWidgets.QTabWidget()
        for i in range(3,8):
            pvslot = title + ':%d:'%i
            statstab.addTab( DtiStatistics(pvslot), 'Slot-%d'%i )
        lol.addWidget(statstab)

        self.centralWidget.setLayout(lol)

        MainWindow.resize(500,550)
        MainWindow.setWindowTitle(title)
        MainWindow.setCentralWidget(self.centralWidget)

def main():
    """Parse the PV base (and -v) from the command line and run the window."""
    print(QtCore.PYQT_VERSION_STR)

    parser = argparse.ArgumentParser(description='simple pv monitor gui')
    parser.add_argument("base", help="pv base to monitor", default="DAQ:LAB2:DTI")
    parser.add_argument('-v', '--verbose', action='store_true', help='be verbose')

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    app = QtWidgets.QApplication([])
    MainWindow = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow,args.base)
    MainWindow.updateGeometry()

    MainWindow.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
