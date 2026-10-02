"""PyQt5 window showing the array PV '<base>:XPM:<shelf>:PART:<partition>:DeadFLnk' per link.

Link names come from '<base>:XPM:<shelf>:LinkLabel<i>' PVs. The module also defines
PV widget classes similar to those in `psdaq.cas.pvedit`, several of which reference
names not defined here (noted per item).
"""
import sys
import argparse
import logging
from PyQt5 import QtCore, QtGui, QtWidgets
import time
from psdaq.cas.pvedit import Pv

logger = logging.getLogger(__name__)


try:
    QString = unicode
except NameError:
    # Python 3
    QString = str

NBeamSeq = 16

dstsel     = ['Include','DontCare']
bmsel      = ['D%u'%i for i in range(NBeamSeq)]
evtsel      = ['Fixed Rate','AC Rate','Sequence']
seqIdxs     = ['s%u'%i for i in range(18)]
seqBits     = ['b%u'%i for i in range(32)]

class PvDisplay(QtWidgets.QLabel):

    """QLabel (initial text '-') with a `valueSet` string signal connected to `setText`."""
    valueSet = QtCore.pyqtSignal('QString',name='valueSet')

    def __init__(self):
        QtWidgets.QLabel.__init__(self, "-")
        self.setMinimumWidth(100)

    def connect_signal(self):
        """Connect `valueSet` to `setValue`."""
        self.valueSet.connect(self.setValue)

    def setValue(self,value):
        """Set the label text to `value`."""
        self.setText(value)

class PvLabel:
    """Name label plus `PvDisplay` added to layout `parent`, monitoring PV ``pvbase + name`` (and optional ``pvbase + dName``)."""
    def __init__(self, parent, pvbase, name, dName=None, isInt=False):
        layout = QtWidgets.QHBoxLayout()
        label  = QtWidgets.QLabel(name)
        label.setMinimumWidth(100)
        layout.addWidget(label)
        #layout.addStretch()
        self.__display = PvDisplay()
        self.__display.connect_signal()
        layout.addWidget(self.__display)
        parent.addLayout(layout)

        pvname = pvbase+name
        print(pvname)
        self.pv = Pv(pvname, self.update)
        if dName is not None:
            dPvName = pvbase+dName
            self.dPv = Pv(dPvName, self.update)
        else:
            self.dPv = None
        self.isInt = isInt

    def update(self, err):
        """Get the PV value(s) synchronously, format and emit them to the display.

        Integers (`isInt`) show as 'n (0xhex)', other values as strings, with the `dName`
        value in brackets; if formatting raises, the value is shown as an array, 8 per line.
        If `err` is not None it is printed instead.
        """
        q = self.pv.get()
        if self.dPv is not None:
            dq = self.dPv.get()
        else:
            dq = None
        if err is None:
            s = QString('fail')
            try:
                if self.isInt:
                    s = QString("%s (0x%s)") % (QString(int(q)),QString(format(int(q), 'x')))
                    if dq is not None:
                        s = s + QString(" [%s (0x%s)]") % (QString(int(dq)), QString(format(int(dq), 'x')))
                else:
                    s = QString(q)
                    if dq is not None:
                        s = s + QString(" [%s]") % (QString(dq))
            except:
                v = ''
                for i in range(len(q)):
                    #v = v + ' %f'%q[i]
                    v = v + ' ' + QString(q[i])
                    if dq is not None:
                        v = v + QString(" [%s]") % (QString(dq[i]))
                        #v = v + ' [' + '%f'%dq[i] + ']'
                    if ((i%8)==7):
                        v = v + '\n'
                s = QString(v)

            self.__display.valueSet.emit(s)
        else:
            print(err)

class PvPushButton(QtWidgets.QPushButton):

    """QPushButton (max width 25) that puts 1 to PV `pvname` when clicked; the PV is monitored with a no-op `update`."""
    valueSet = QtCore.pyqtSignal('QString',name='valueSet')

    def __init__(self, pvname, label):
        super(PvPushButton, self).__init__(label)
        self.setMaximumWidth(25) # Revisit

        self.clicked.connect(self.buttonClicked)

        self.pv = Pv(pvname, self.update)

    def update(self, err):
        """Do nothing; body is `pass`."""
        pass

    def buttonClicked(self):
        """Put 1 to the PV."""
        self.pv.put(1)          # Value is immaterial

class CheckBox(QtWidgets.QCheckBox):

    """QCheckBox with an int `valueSet` signal that sets the checked state."""
    valueSet = QtCore.pyqtSignal(int, name='valueSet')

    def __init__(self, label):
        super(CheckBox, self).__init__(label)

    def connect_signal(self):
        """Connect `valueSet` to `boxClicked`."""
        self.valueSet.connect(self.boxClicked)

    def boxClicked(self, state):
        #print "CheckBox.clicked: state:", state
        """Set the checked state to `state`."""
        self.setChecked(state)

class PvCheckBox(CheckBox):

    """`CheckBox` bound to PV `pvname`: clicks write the checked state and PV updates set the box."""
    def __init__(self, pvname, label):
        super(PvCheckBox, self).__init__(label)
        self.connect_signal()
        self.clicked.connect(self.pvClicked)

        self.pv = Pv(pvname)
        self.pv.monitor(self.update)

    def pvClicked(self):
        """Put the checked state (bool) to the PV."""
        q = self.isChecked()
        self.pv.put(q)
        #print "PvCheckBox.clicked: pv %s q %x" % (self.pv.name, q)

    def update(self, err):
        #print "PvCheckBox.update:  pv %s, i %s, v %x, err %s" % (self.pv.name, self.text(), self.pv.get(), err)
        """Get the PV synchronously and emit `valueSet` with ``value != 0`` if it differs from the box; print `err` if set."""
        q = self.pv.get() != 0
        if err is None:
            if q != self.isChecked():  self.valueSet.emit(q)
        else:
            print(err)

class PvTextDisplay(QtWidgets.QLineEdit):

    """QLineEdit (initial text '-') with a `valueSet` string signal connected to `setText`; `label` is unused."""
    valueSet = QtCore.pyqtSignal('QString',name='valueSet')

    def __init__(self, label):
        super(PvTextDisplay, self).__init__("-")
        #self.setMinimumWidth(60)

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

class PvTxt(PvTextDisplay):

    """`PvTextDisplay` monitoring PV `pv`."""
    def __init__(self, pv, label):
        super(PvTxt, self).__init__(label)
        self.connect_signal()

        self.pv = Pv(pv, self.update)

    def update(self, err):
        """Intended to emit the PV value as text.

        It first prints ``'Update ' + pv``, but `pv` is not defined in this method, so it raises NameError.
        """
        print('Update '+pv)
        q = self.pv.get()
        if err is None:
            s = QString(q)
            self.valueSet.emit(s)
        else:
            print(err)

    def setPv(self):
        """Do nothing; body is `pass`."""
        pass

class PvEditTxt(PvTextDisplay):

    """`PvTextDisplay` monitoring PV `pv`; editingFinished calls `setPv`."""
    def __init__(self, pv, label):
        super(PvEditTxt, self).__init__(label)
        self.connect_signal()
        self.editingFinished.connect(self.setPv)

        self.pv = Pv(pv, self.update)

    def update(self, err):
        """Intended to emit the PV value as text.

        It first prints ``'Update ' + pv``, but `pv` is not defined in this method, so it raises NameError.
        """
        print('Update '+pv)
        q = self.pv.get()
        if err is None:
            s = QString(q)
            self.valueSet.emit(s)
        else:
            print(err)

    def setPv(self):
        """Do nothing; body is `pass`."""
        pass

class PvEditInt(PvEditTxt):

    """`PvEditTxt` for an integer PV."""
    def __init__(self, pv, label):
        super(PvEditInt, self).__init__(pv, label)

    def setPv(self):
        """Put ``int(text)`` to the PV; text that is not an int is ignored."""
        try:
            value = int(self.text())
        except ValueError:
            # ignore input that fails to convert to int
            pass
        else:
            self.pv.put(value)

    def update(self, err):
        """Intended to emit the PV value as an int string.

        It first prints ``'Update ' + pv``, but `pv` is not defined in this method, so it raises NameError.
        """
        print('Update '+pv)
        q = self.pv.get()
        if err is None:
            s = QString('fail')
            try:
                s = QString("%s") % (QString(int(q)))
            except:
                v = ''
                for i in range(len(q)):
                    v = v + ' %f'%q[i]
                s = QString(v)

            self.valueSet.emit(s)
        else:
            print(err)


class PvInt(PvEditInt):

    """Disabled `PvEditInt`.

    The constructor calls ``super().__init__(pv)`` without the required `label` argument, so it raises TypeError.
    """
    def __init__(self,pv):
        super(PvInt, self).__init__(pv)
        self.setEnabled(False)

class PvEditHML(PvEditTxt):

    """`PvEditTxt` for a value written as L/H/M/m letters (2 bits each).

    `frLMH` and `toLMH` are used but not defined or imported in this module.
    """
    def __init__(self, pv, label):
        super(PvEditHML, self).__init__(pv, label)

    def setPv(self):
        """Convert the text to an int with 2 bits per letter via `frLMH` and put it; prints a message on KeyError.

        `frLMH` is not defined in this module, so this raises NameError.
        """
        value = self.text()
        try:
            q = 0
            for i in range(len(value)):
                q |= frLMH[str(value[i])] << (2 * (len(value) - 1 - i))
            self.pv.put(q)
        except KeyError:
            print("Invalid character in string:", value)

    def update(self, err):
        """Convert the PV value to letters via `toLMH` and emit it.

        `toLMH` is not defined in this module, so this raises NameError.
        """
        q = self.pv.get()
        if err is None:
            v = toLMH[q & 0x3]
            q >>= 2
            while q:
                v = toLMH[q & 0x3] + v
                q >>= 2
            s = QString(v)

            self.valueSet.emit(s)
        else:
            print(err)

class PvHML(PvEditHML):

    """Disabled `PvEditHML`."""
    def __init__(self, pv, label):
        super(PvHML, self).__init__(pv, label)
        self.setEnabled(False)

class PvEditDbl(PvEditTxt):

    """`PvEditTxt` for a floating-point PV."""
    def __init__(self, pv, label):
        super(PvEditDbl, self).__init__(pv, label)

    def setPv(self):
        """Intended to put the text as a double.

        It calls ``self.text().toDouble()``; `text()` returns a Python str, which has no `toDouble`, so this raises AttributeError.
        """
        value = self.text().toDouble()
        self.pv.put(value)

    def update(self, err):
        """Get the PV synchronously and emit it as a string (array elements as ' %f' on failure); print `err` if set."""
        q = self.pv.get()
        if err is None:
            s = QString('fail')
            try:
                s = QString(q)
            except:
                v = ''
                for i in range(len(q)):
                    v = v + ' %f'%q[i]
                s = QString(v)

            self.valueSet.emit(s)
        else:
            print(err)

class PvDbl(PvEditDbl):

    """Disabled `PvEditDbl`.

    The constructor calls ``super().__init__(pv)`` without the required `label` argument, so it raises TypeError.
    """
    def __init__(self,pv):
        super(PvDbl, self).__init__(pv)
        self.setEnabled(False)

class PvDblArrayW(QtWidgets.QLabel):

    """QLabel (initial text '-') with a `valueSet` string signal connected to `setText`."""
    valueSet = QtCore.pyqtSignal('QString',name='valueSet')

    def __init__(self):
        super(PvDblArrayW, self).__init__('-')
        self.connect_signal()

    def connect_signal(self):
        """Connect `valueSet` to `setValue`."""
        self.valueSet.connect(self.setValue)

    def setValue(self,value):
        """Set the label text to `value`."""
        self.setText(value)

class PvDblArray:

    """Monitor array PV `pv` and send element i to ``widgets[i]``."""
    def __init__(self, pv, widgets):
        self.widgets = widgets
        self.pv = Pv(pv, self.update)

    def update(self, err):
        """Get the PV synchronously and emit each element, formatted with '4f', to ``widgets[i].valueSet``; print `err` if set."""
        q = self.pv.get()
        if err is None:
            for i in range(len(q)):
                self.widgets[i].valueSet.emit(QString(format(q[i], '4f')))
        else:
            print(err)

class PvEditCmb(PvComboDisplay):

    """Combo box bound to PV `pvname`: the current index is written on change and set from PV updates."""
    def __init__(self, pvname, choices):
        super(PvEditCmb, self).__init__(choices)
        self.connect_signal()
        self.currentIndexChanged.connect(self.setValue)

        self.pv = Pv(pvname, self.update)

    def setValue(self):
        """Put the current index to the PV."""
        value = self.currentIndex()
        self.pv.put(value)

    def update(self, err):
        """Get the PV synchronously, set the current index to it and emit `valueSet`; print `err` if set."""
        q = self.pv.get()
        if err is None:
            self.setCurrentIndex(q)
            self.valueSet.emit(q)
        else:
            print(err)


class PvCmb(PvEditCmb):

    """Disabled `PvEditCmb`."""
    def __init__(self, pvname, choices):
        super(PvCmb, self).__init__(pvname, choices)
        self.setEnabled(False)


class PvEvtTab(QtWidgets.QStackedWidget):

    """Stacked widget of event-selection combos whose page follows `evtcmb`.

    It uses `fixedRates`, `acRates` and `acTS`, which are not defined or imported in this
    module, so construction raises NameError.
    """
    def __init__(self, pvname, evtcmb):
        super(PvEvtTab,self).__init__()

        self.addWidget(PvEditCmb(pvname+'_FixedRate',fixedRates))

        acw = QtWidgets.QWidget()
        acl = QtWidgets.QVBoxLayout()
        acl.addWidget(PvEditCmb(pvname+'_ACRate',acRates))
        acl.addWidget(PvEditCmb(pvname+'_ACTimeslot',acTS))
        acw.setLayout(acl)
        self.addWidget(acw)

        sqw = QtWidgets.QWidget()
        sql = QtWidgets.QVBoxLayout()
        sql.addWidget(PvEditCmb(pvname+'_Sequence',seqIdxs))
        sql.addWidget(PvEditCmb(pvname+'_SeqBit',seqBits))
        sqw.setLayout(sql)
        self.addWidget(sqw)

        evtcmb.currentIndexChanged.connect(self.setCurrentIndex)

class PvEditEvt(QtWidgets.QWidget):

    """Widget with a `PvEditCmb` on `pvname` (choices `evtsel`) above a `PvEvtTab`; `idx` is unused."""
    def __init__(self, pvname, idx):
        super(PvEditEvt, self).__init__()
        vbox = QtWidgets.QVBoxLayout()
        evtcmb = PvEditCmb(pvname,evtsel)
        vbox.addWidget(evtcmb)
        vbox.addWidget(PvEvtTab(pvname,evtcmb))
        self.setLayout(vbox)

class PvDstTab(QtWidgets.QWidget):

    """Grid of 'D0'..'D15' check boxes; clicking any box puts the bitmask of checked boxes to PV `pvname`.

    The grid positions are computed with ``i/4`` (a float).
    """
    def __init__(self, pvname):
        super(PvDstTab,self).__init__()

        self.pv = Pv(pvname)

        self.chkBox = []
        layout = QtWidgets.QGridLayout()
        for i in range(NBeamSeq):
            layout.addWidget( QtWidgets.QLabel('D%d'%i), i/4, 2*(i%4) )
            chkB = QtWidgets.QCheckBox()
            layout.addWidget( chkB, i/4, 2*(i%4)+1 )
            chkB.clicked.connect(self.update)
            self.chkBox.append(chkB)
        self.setLayout(layout)

    def update(self):
        """Put the bitmask of checked boxes (bit i for 'Di') to the PV."""
        v = 0
        for i in range(NBeamSeq):
            if self.chkBox[i].isChecked():
                v |= (1<<i)
        self.pv.put(v)

class PvEditDst(QtWidgets.QWidget):

    """Widget with a `PvEditCmb` on `pvname` (Include/DontCare) and a `PvDstTab` on ``pvname + '_Mask'``; `idx` is unused."""
    def __init__(self, pvname, idx):
        super(PvEditDst, self).__init__()
        vbox = QtWidgets.QVBoxLayout()
        selcmb = PvEditCmb(pvname,dstsel)

        vbox.addWidget(selcmb)
        vbox.addWidget(PvDstTab(pvname+'_Mask'))
        self.setLayout(vbox)

class PvEditTS(PvEditCmb):

    """`PvEditCmb` with choices '0'..'15'; `idx` is unused."""
    def __init__(self, pvname, idx):
        super(PvEditTS, self).__init__(pvname, ['%u'%i for i in range(16)])

class PvInput:
    """Build a labelled row of `count` PV widgets of class `widget` and add it to layout `parent`.

    With `count` 1 the PV is ``pvbase + name``; otherwise ``pvbase + name + str(i)`` for each i.
    """
    def __init__(self, widget, parent, pvbase, name, count=1):
        pvname = pvbase+name
        print(pvname)

        layout = QtWidgets.QHBoxLayout()
        label  = QtWidgets.QLabel(name)
        label.setMinimumWidth(100)
        layout.addWidget(label)
        #layout.addStretch
        if count == 1:
            layout.addWidget(widget(pvname, ''))
        else:
            for i in range(count):
                layout.addWidget(widget(pvname+'%d'%i, QString(i)))
        #layout.addStretch
        parent.addLayout(layout)

def LblPushButton(parent, pvbase, name, count=1):
    """Return a `PvInput` row of `PvPushButton` widgets."""
    return PvInput(PvPushButton, parent, pvbase, name, count)

def LblCheckBox(parent, pvbase, name, count=1):
    """Return a `PvInput` row of `PvCheckBox` widgets."""
    return PvInput(PvCheckBox, parent, pvbase, name, count)

def LblEditInt(parent, pvbase, name, count=1):
    """Return a `PvInput` row of `PvEditInt` widgets."""
    return PvInput(PvEditInt, parent, pvbase, name, count)

def LblEditHML(parent, pvbase, name, count=1):
    """Return a `PvInput` row of `PvEditHML` widgets."""
    return PvInput(PvEditHML, parent, pvbase, name, count)

def LblEditTS(parent, pvbase, name, count=1):
    """Return a `PvInput` row of `PvEditTS` widgets."""
    return PvInput(PvEditTS, parent, pvbase, name, count)

def LblEditEvt(parent, pvbase, name, count=1):
    """Return a `PvInput` row of `PvEditEvt` widgets."""
    return PvInput(PvEditEvt, parent, pvbase, name, count)

def LblEditDst(parent, pvbase, name, count=1):
    """Return a `PvInput` row of `PvEditDst` widgets."""
    return PvInput(PvEditDst, parent, pvbase, name, count)

class Ui_MainWindow(object):
    """Builder for the window that shows the 'DeadFLnk' array per link."""
    def setupUi(self, MainWindow, base, partn, shelf):
        r"""Build the main window for XPM `shelf` and partition `partn` under PV prefix `base`.

        After a 2 s sleep, links 0-13 and 16-20 get a label from a synchronous get of
        '<base>:XPM:<shelf>:LinkLabel<i>', and entries 28-31 are labelled 'INH-0'..'INH-3';
        all are fed by the array PV '<...>:PART:<partn>:DeadFLnk'. The title is
        'XPM:<shelf>\tPART:<partn>'.
        """
        MainWindow.setObjectName("MainWindow")
        self.centralWidget = QtWidgets.QWidget(MainWindow)
        self.centralWidget.setObjectName("centralWidget")

        pvbase = base+':XPM:'+shelf+':'
        ppvbase = pvbase+'PART:'+partn+':'
        print('pvbase : '+pvbase)
        print('ppvbase: '+ppvbase)

        grid = QtWidgets.QGridLayout()

        textWidgets = []
        for i in range(32):
            textWidgets.append( PvDblArrayW() )

        # Need to wait for pv.get()
        time.sleep(2)

        for i in range(14):
            pv = Pv(pvbase+'LinkLabel%d'%i)
            grid.addWidget( QtWidgets.QLabel(pv.get()), i, 0 )
            grid.addWidget( textWidgets[i], i, 1 )

        for j in range(16,21):
            i = j-16
            pv = Pv(pvbase+'LinkLabel%d'%j)
            grid.addWidget( QtWidgets.QLabel(pv.get()), i, 2 )
            grid.addWidget( textWidgets[j], i, 3 )

        for j in range(28,32):
            i = j-22
            grid.addWidget( QtWidgets.QLabel('INH-%d'%(j-28)), i, 2 )
            grid.addWidget( textWidgets[j], i, 3 )

        self.deadflnk = PvDblArray( ppvbase+'DeadFLnk', textWidgets )

        self.centralWidget.setLayout(grid)
        self.centralWidget.resize(240,340)

        title = 'XPM:'+shelf+'\tPART:'+partn
        MainWindow.setWindowTitle(title)
        MainWindow.resize(240,340)
        MainWindow.setCentralWidget(self.centralWidget)

def main():
    """Parse base, partition and shelf (and -v) from the command line and run the window."""
    print(QtCore.PYQT_VERSION_STR)

    parser = argparse.ArgumentParser(description='simple pv monitor gui')
    parser.add_argument('-v', '--verbose', action='store_true', help='be verbose')
    parser.add_argument("base", help="pv base to monitor", default="DAQ:LAB2")
    parser.add_argument("partition", help="partition to monitor")
    parser.add_argument("shelf", help="shelf to monitor")
    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)


    app = QtWidgets.QApplication([])
    MainWindow = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow,args.base,args.partition,args.shelf)
    MainWindow.updateGeometry()

    MainWindow.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
