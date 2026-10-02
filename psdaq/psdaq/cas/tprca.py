"""PyQt5 GUI for the PVs of one TPR under a PV prefix: an 'Input' tab and one tab per readout channel.

The widget classes use `psdaq.cas.pvedit.Pv`; their `update` methods do a synchronous
`get` when the monitor fires.
"""
import sys
import logging
import argparse
from PyQt5 import QtCore, QtGui, QtWidgets
from psdaq.cas.pvedit import Pv
from psdaq.configdb.tsdef import *

logger = logging.getLogger(__name__)

NReadoutChannels = 14
NTriggerChannels = 12

accSel =     ['LCLS-I','LCLS-II']
linkStates = ['Down','Up']
rxpols     = ['Normal','Inverted']
RowHdrLen = 110
modes      = ['Disable','Trigger','+Readout','+BSA']
modesTTL   = ['Disable','Trigger']
polarities = ['Neg','Pos']
dstsel     = ['Any','Exclude','Include']
evtsel     = ['Fixed Rate','AC Rate','Sequence','Partition']
seqIdxs    = ['s%u'%i for i in range(18)]
seqBits    = ['b%u'%i for i in range(16)]
partitions = ['P%u'%i for i in range(8)]
ndestn     = 16

class PvTextDisplay(QtWidgets.QLineEdit):

    """QLineEdit (initial text '0', minimum width 60) with a `valueSet` string signal connected to `setText`."""
    valueSet = QtCore.pyqtSignal('QString',name='valueSet')

    def __init__(self):
        super(PvTextDisplay, self).__init__("0")
        self.setMinimumWidth(60)

    def connect_signal(self):
        """Connect `valueSet` to `setValue`."""
        self.valueSet.connect(self.setValue)

    def setValue(self,value):
        """Set the line-edit text to `value`."""
        self.setText(value)


class PvComboDisplay(QtWidgets.QComboBox):

    """QComboBox with `choices` and a `valueSet` signal (declared as QString) connected to `setValue`."""
    valueSet = QtCore.pyqtSignal('QString',name='valueSet')

    def __init__(self, choices):
        super(PvComboDisplay, self).__init__()
        self.addItems(choices)

    def connect_signal(self):
        """Connect `valueSet` to `setValue`."""
        self.valueSet.connect(self.setValue)

    def setValue(self,value):
        """Set the current index to `value`."""
        self.setCurrentIndex(value)

class PvEditTxt(PvTextDisplay):

    """`PvTextDisplay` monitoring PV `pv`; editingFinished calls `setPv`, defined by subclasses."""
    def __init__(self, pv):
        super(PvEditTxt, self).__init__()
        self.connect_signal()
        self.editingFinished.connect(self.setPv)

        self.pv = Pv(pv, self.update)

class PvEditInt(PvEditTxt):

    """Line edit for an integer PV."""
    def __init__(self, pv):
        super(PvEditInt, self).__init__(pv)

    def setPv(self):
        """Put ``int(text)`` to the PV; a ValueError is not caught."""
        value = int(self.text())
        self.pv.put(value)

    def update(self, err):
        """Get the PV and emit it as an int string, or as ' %f' values for an array; print `err` if set."""
        q = self.pv.get()
        if err is None:
            s = 'fail'
            try:
                s = str(int(q))
            except:
                v = ''
                for i in range(len(q)):
                    v = v + ' %f'%q[i]
                s = v

            self.valueSet.emit(s)
        else:
            print(err)


class PvInt(PvEditInt):

    """Disabled (read-only) `PvEditInt`."""
    def __init__(self,pv):
        super(PvInt, self).__init__(pv)
        self.setEnabled(False)


class PvEditDbl(PvEditTxt):

    """Line edit for a floating-point PV, displayed with format string `fmt` (default '{:g}')."""
    def __init__(self, pv,fmt='{:g}'):
        super(PvEditDbl, self).__init__(pv)
        self.fmt = fmt

    def setPv(self):
        """Put ``float(text)`` to the PV; a ValueError is not caught."""
        value = float(self.text())
        self.pv.put(value)

    def update(self, err):
        """Get the PV and emit it formatted with `fmt` (array elements joined if scalar formatting fails, with the exception logged); print `err` if set."""
        q = self.pv.get()
        if err is None:
            s = 'fail'
            try:
                s = self.fmt.format(q)
            except:
                logger.exception("Excetion in pv edit double")
                v = ''
                for i in range(len(q)):
                    v = v + ' ' + self.fmt.format(q[i])
                s = v

            self.valueSet.emit(s)
        else:
            print(err)

class PvDbl(PvEditDbl):

    """Disabled (read-only) `PvEditDbl`."""
    def __init__(self,pv,fmt='{:g}'):
        super(PvDbl, self).__init__(pv,fmt)
        self.setEnabled(False)


class PvEditCmb(PvComboDisplay):

    """Combo box bound to PV `pvname`; the current index is the PV value."""
    def __init__(self, pvname, choices):
        super(PvEditCmb, self).__init__(choices)
        self.connect_signal()
        self.currentIndexChanged.connect(self.setValue)

        self.pv = Pv(pvname, self.update)

    def setValue(self):
        """Put the current index to the PV unless a synchronous get shows it already has that value."""
        value = self.currentIndex()
        if self.pv.get() != value:
            self.pv.put(value)
        else:
            logger.debug("Skipping updating PV for edit combobox as the value of the pv %s is the same as the current value", self.pv.pvname)

    def update(self, err):
        """Get the PV, set the current index to it and emit `valueSet` with its string; print `err` if set."""
        q = self.pv.get()
        if err is None:
            self.setCurrentIndex(q)
            self.valueSet.emit(str(q))
        else:
            print(err)


class PvCmb(PvEditCmb):

    """Disabled (read-only) `PvEditCmb`."""
    def __init__(self, pvname, choices):
        super(PvCmb, self).__init__(pvname, choices)
        self.setEnabled(False)


class PvEvtTab(QtWidgets.QStackedWidget):

    """Stacked widget of event-selection combos whose page follows `evtcmb`.

    Pages: <pvname>FRATE (`fixedRates`); <pvname>ARATE and <pvname>ATS (`acRates`,
    `acTS`); <pvname>SEQIDX and <pvname>SEQBIT; <pvname>XPART ('P0'..'P7'). The rate lists
    come from `psdaq.configdb.tsdef`.
    """
    def __init__(self, pvname, evtcmb):
        super(PvEvtTab,self).__init__()

        self.addWidget(PvEditCmb(pvname+'FRATE',fixedRates))

        acw = QtWidgets.QWidget()
        acl = QtWidgets.QVBoxLayout()
        acl.addWidget(PvEditCmb(pvname+'ARATE',acRates))
        acl.addWidget(PvEditCmb(pvname+'ATS'  ,acTS))
        acw.setLayout(acl)
        self.addWidget(acw)

        sqw = QtWidgets.QWidget()
        sql = QtWidgets.QVBoxLayout()
        sql.addWidget(PvEditCmb(pvname+'SEQIDX',seqIdxs))
        sql.addWidget(PvEditCmb(pvname+'SEQBIT',seqBits))
        sqw.setLayout(sql)
        self.addWidget(sqw)

        self.addWidget(PvEditCmb(pvname+'XPART',partitions))

        evtcmb.currentIndexChanged.connect(self.setCurrentIndex)

class PvEditEvt(QtWidgets.QWidget):

    """Widget with a <pvname>RSEL combo (Fixed Rate/AC Rate/Sequence/Partition) above a `PvEvtTab`."""
    def __init__(self, pvname):
        super(PvEditEvt, self).__init__()
        vbox = QtWidgets.QVBoxLayout()
        evtcmb = PvEditCmb(pvname+'RSEL',evtsel)
        vbox.addWidget(evtcmb)
        vbox.addWidget(PvEvtTab(pvname,evtcmb))
        self.setLayout(vbox)

class PvDstTab(QtWidgets.QWidget):

    """Grid of 'D0'..'D15' check boxes; clicking a box puts the bitmask of checked boxes to PV `pvname`.

    Grid positions are computed with ``i/4`` (a float).
    """
    def __init__(self, pvname):
        super(PvDstTab,self).__init__()

        self.pv = Pv(pvname)

        self.chkBox = []
        layout = QtWidgets.QGridLayout()
        for i in range(ndestn):
            layout.addWidget( QtWidgets.QLabel('D%d'%i), i/4, 2*(i%4) )
            chkB = QtWidgets.QCheckBox()
            layout.addWidget( chkB, i/4, 2*(i%4)+1 )
            chkB.clicked.connect(self.update)
            self.chkBox.append(chkB)
        self.setLayout(layout)

    def update(self):
        """Put the bitmask of checked boxes (bit i for 'Di') to the PV."""
        v = 0
        for i in range(ndestn):
            if self.chkBox[i].isChecked():
                v |= (1<<i)
        self.pv.put(v)

class PvEditDst(QtWidgets.QWidget):

    """Widget with a <pvname>DSTSEL combo (Any/Exclude/Include) and a `PvDstTab` on <pvname>DESTNS."""
    def __init__(self, pvname):
        super(PvEditDst, self).__init__()
        vbox = QtWidgets.QVBoxLayout()
        selcmb = PvEditCmb(pvname+'DSTSEL',dstsel)

        vbox.addWidget(selcmb)
        vbox.addWidget(PvDstTab(pvname+'DESTNS'))
        self.setLayout(vbox)

def PvRowDbl(row, layout, prefix, pv, label, ncols=NReadoutChannels, fmt='{}'):
    """Add label `label` and `ncols` `PvEditDbl` widgets for '<prefix>:CH<i>:<pv>' to grid row `row`; returns None."""
    qlabel = QtWidgets.QLabel(label)
    qlabel.setMinimumWidth(RowHdrLen)
    layout.addWidget(qlabel,row,0)

    for i in range(ncols):
        qedit = PvEditDbl(prefix+':CH%u:'%i+pv, fmt)
        layout.addWidget(qedit,row,i+1)
    row += 1

def PvRowInt(row, layout, prefix, pv, label, ncols=NReadoutChannels):
    """Add label `label` and `ncols` `PvEditInt` widgets for '<prefix>:CH<i>:<pv>' to grid row `row`; returns None."""
    qlabel = QtWidgets.QLabel(label)
    qlabel.setMinimumWidth(RowHdrLen)
    layout.addWidget(qlabel,row,0)

    for i in range(ncols):
        qedit = PvEditInt(prefix+':CH%u:'%i+pv)
        layout.addWidget(qedit,row,i+1)
    row += 1

def PvRowCmb(row, layout, prefix, pv, label, choices, ncols=NReadoutChannels):
    """Add label `label` and `ncols` `PvEditCmb` widgets for '<prefix>:CH<i>:<pv>' to grid row `row`; returns None."""
    qlabel = QtWidgets.QLabel(label)
    qlabel.setMinimumWidth(RowHdrLen)
    layout.addWidget(qlabel,row,0)

    for i in range(ncols):
        qedit = PvEditCmb(prefix+':CH%u:'%i+pv, choices)
        layout.addWidget(qedit,row,i+1)
    row += 1

def PvRowMod(row, layout, prefix, pv, label):
    """Add label `label` and one `modes` `PvEditCmb` per readout channel for '<prefix>:CH<i>:<pv>' to grid row `row`; returns None."""
    qlabel = QtWidgets.QLabel(label)
    qlabel.setMinimumWidth(RowHdrLen)
    layout.addWidget(qlabel,row,0)

    for i in range(NReadoutChannels):
        qedit = PvEditCmb(prefix+':CH%u:'%i+pv, modes)
        layout.addWidget(qedit,row,i+1)
    row += 1

def PvRowEvt(row, layout, prefix, ncols=NReadoutChannels):
    """Add an 'Event' label and `ncols` `PvEditEvt` widgets for '<prefix>:CH<i>:' to grid row `row`; returns None."""
    qlabel = QtWidgets.QLabel('Event')
    qlabel.setMinimumWidth(RowHdrLen)
    layout.addWidget(qlabel,row,0)

    for i in range(ncols):
        qedit = PvEditEvt(prefix+':CH%u:'%i)
        layout.addWidget(qedit,row,i+1)
    row += 1

def PvRowDst(row, layout, prefix, ncols=NReadoutChannels):
    """Add a 'Destn' label and `ncols` `PvEditDst` widgets for '<prefix>:CH<i>:' to grid row `row`; returns None."""
    qlabel = QtWidgets.QLabel('Destn')
    qlabel.setMinimumWidth(RowHdrLen)
    layout.addWidget(qlabel,row,0)

    for i in range(ncols):
        qedit = PvEditDst(prefix+':CH%u:'%i)
        layout.addWidget(qedit,row,i+1)
    row += 1

class Ui_MainWindow(object):
    """Builder for the TPR window."""
    def setupUi(self, MainWindow, pvname):
        """Create a QTabWidget (parent `MainWindow`) with the 'Input' and 'CH0'..'CH13' tabs.

        'Input' edits/shows <pvname>:ACCSEL, LINKSTATE, RXERRS, RXPOL, FRAMERATE, RXCLKRATE,
        IRQENA and EVTCNT. Each channel tab edits Event, Destn, RATE, MODE, DELAY, WIDTH and
        POL under '<pvname>:CH<i>:'. The tab widget is not set as the window's central widget.
        """
        MainWindow.setObjectName("MainWindow")

        tw = QtWidgets.QTabWidget(MainWindow)

        layout = QtWidgets.QGridLayout()

        row = 0
        layout.addWidget( QtWidgets.QLabel('ACCSEL'), row, 0 )
        layout.addWidget( PvEditCmb(pvname+':ACCSEL', accSel), row, 1 )
        row += 1
        layout.addWidget( QtWidgets.QLabel('LINKSTATE'), row, 0 )
        layout.addWidget( PvCmb(pvname+':LINKSTATE', linkStates), row, 1 )
        row += 1
        layout.addWidget( QtWidgets.QLabel('RXERRS'), row, 0 )
        layout.addWidget( PvInt(pvname+':RXERRS'), row, 1 )
        row += 1
        layout.addWidget( QtWidgets.QLabel('RXPOL'), row, 0 )
        layout.addWidget( PvEditCmb(pvname+':RXPOL', rxpols), row, 1 )
        row += 1
        layout.addWidget( QtWidgets.QLabel('FRAME RATE [Hz]'), row, 0 )
        layout.addWidget( PvDbl(pvname+':FRAMERATE'), row, 1 )
        row += 1
        layout.addWidget( QtWidgets.QLabel('RXCLK RATE [MHz]'), row, 0 )
        layout.addWidget( PvDbl(pvname+':RXCLKRATE'), row, 1 )
        row += 1
        layout.addWidget( QtWidgets.QLabel('IRQENA'), row, 0 )
        layout.addWidget( PvEditInt(pvname+':IRQENA'), row, 1 )
        row += 1
        layout.addWidget( QtWidgets.QLabel('EVTCNT'), row, 0 )
        layout.addWidget( PvEditInt(pvname+':EVTCNT'), row, 1 )
        row += 1
        layout.setColumnStretch(2,1)
        layout.setRowStretch(row,1)

        w = QtWidgets.QWidget()
        w.setLayout(layout)
        tw.addTab(w, 'Input')

        prefix = pvname
        for i in range(NReadoutChannels):
            lor = QtWidgets.QGridLayout()
            row = 0
            lor.addWidget(QtWidgets.QLabel('Event'),row,0)
            lor.addWidget(PvEditEvt(prefix+':CH%u:'%i),row,1)
            row += 1
            lor.addWidget(QtWidgets.QLabel('Destn'),row,0)
            lor.addWidget(PvEditDst(prefix+':CH%u:'%i),row,1)
            row += 1
            lor.addWidget(QtWidgets.QLabel('Rate'),row,0)
            lor.addWidget(PvEditDbl(prefix+':CH%u:RATE'%i, fmt='{:.2f}'),row,1)
            row += 1
            lor.addWidget(QtWidgets.QLabel('Mode'),row,0)
            lor.addWidget(PvEditCmb(prefix+':CH%u:MODE'%i, modes),row,1)
            row += 1
            lor.addWidget(QtWidgets.QLabel('Delay [sec]'),row,0)
            lor.addWidget(PvEditDbl(prefix+':CH%u:DELAY'%i),row,1)
            row += 1
            lor.addWidget(QtWidgets.QLabel('Width [sec]'),row,0)
            lor.addWidget(PvEditDbl(prefix+':CH%u:WIDTH'%i),row,1)
            row += 1
            lor.addWidget(QtWidgets.QLabel('Polarity'),row,0)
            lor.addWidget(PvEditCmb(prefix+':CH%u:POL'%i, polarities),row,1)
            w = QtWidgets.QWidget()
            w.setLayout(lor)
            tw.addTab( w, 'CH%u'%i )

        self.centralWidget = tw
        self.centralWidget.setObjectName("centralWidget")
        self.centralWidget.resize(600,600)
        MainWindow.resize(600,600)


def main():
    """Parse the PV prefix (and -v), set a palette that draws disabled text like enabled text, and run the window."""
    print(QtCore.PYQT_VERSION_STR)

    parser = argparse.ArgumentParser(description='simple pv monitor gui')
    parser.add_argument('-v', '--verbose', action='store_true', help='be verbose')
    parser.add_argument("pv", help="pv to monitor")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    app = QtWidgets.QApplication([])
    #  Make disabled widgets just as visible as enabled widgets
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Disabled,
                     QtGui.QPalette.WindowText,
                     palette.color(QtGui.QPalette.Active,
                                   QtGui.QPalette.WindowText))
    palette.setBrush(QtGui.QPalette.Disabled,
                     QtGui.QPalette.WindowText,
                     palette.brush(QtGui.QPalette.Active,
                                   QtGui.QPalette.WindowText))
    app.setPalette(palette)
    MainWindow = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow,args.pv)
    MainWindow.updateGeometry()

    MainWindow.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
