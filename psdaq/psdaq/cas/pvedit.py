"""PyQt5 widgets bound to PVA PVs through the p4p client, plus layout helper functions.

The `Pv` class wraps a module-level p4p 'pva' `Context` (`pvactx`). Widgets monitor
their PV via `initPvMon` and display/edit its value; the module flag `nogui` makes
update methods print instead of updating widgets.
"""
from PyQt5 import QtCore, QtGui, QtWidgets
from p4p.client.thread import Context
from psdaq.configdb.tsdef import *
import logging

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

logger = logging.getLogger(__name__)

NBeamSeq = 16

interval   = 14./13.
dstsel     = ['Include','DontCare']
evtsel     = ['Fixed Rate','AC Rate','EventCode','Sequence']
seqBits     = ['b%u'%i for i in range(16)]
# Sequence 16 is programmed for rates stepping at 10kHz
seqIdxs     = ['s%u'%i for i in range(18)]
seqBursts   = ['%u x %.2fus'%(2<<(i%4),float(int(i/4+1))*interval) for i in range(16)]
seqRates    = ['%u0kHz'%(i+1) for i in range(16)]
seqLocal    = ['%u0kHz'%(4*i+4) for i in range(16)]
seqGlobal   = ['GLT %d'%(i) for i in range(16)]

frLMH       = { 'L':0, 'H':1, 'M':2, 'm':3 }
toLMH       = { 0:'L', 1:'H', 2:'M', 3:'m' }
pvactx      = Context('pva')

nogui       = False
xtpg        = False

def setCuMode(v):
    """Print and set the module-global `xtpg` flag to `v`."""
    global xtpg
    print('CuMode',v)
    xtpg = v

def getCuMode():
    """Return the module-global `xtpg` flag."""
    return xtpg

class Pv(object):
    """Wrapper around one PVA PV using the module context `pvactx`.

    If `callback` is given, a monitor is started; on each update the converted value is
    stored in `__value__` and ``callback(err=None)`` is called. A TimeoutError while
    subscribing is logged. With `isStruct` the whole received structure is kept.
    """
    def __init__(self, pvname, callback=None, isStruct=False):
        self.pvname = pvname
        self.__value__ = None
        self.isStruct = isStruct
        if callback:
            logger.debug("Monitoring PV %s", self.pvname)
            def monitor_cb(newval):
                self.__value__ = self.to_value(newval)
                logger.debug("Received monitor event for PV %s, received %s", self.pvname, self.__value__)
                callback(err=None)
            try:
                self.subscription = pvactx.monitor(self.pvname, monitor_cb)
                self.__value__ = None
            except TimeoutError as e:
                logger.error("Timeout exception connecting to PV %s", pvname)
        else:
            self.__value__ = None
            logger.debug("PV %s created without a callback", self.pvname) # Call get explictly for an sync get or use for put

    def to_value(self,newval):
        """Convert a received p4p value: the object itself if `isStruct`, else its `.value` or `.raw.value`.

        Returns None (and logs an error) if conversion raises.
        """
        result = None
        try:
            if self.isStruct:
                result = newval
            elif hasattr(newval,"value"):
                result = newval.value
            else:
                result = newval.raw.value
        except Exception as e:
            logger.error(f'Exception in monitor_cb for {self.pvname} {e} [{newval}]')
        return result

    def get(self, useCached=True, timeout=5.0):
        """Do a synchronous get of the PV, store and return the converted value.

        `useCached` is ignored. A TimeoutError is logged and re-raised.
        """
        try:
            self.__value__ = self.to_value(pvactx.get(self.pvname,timeout=timeout))
        except TimeoutError as e:
            logger.error("Timeout exception getting from PV %s", self.pvname)
            raise
        logger.debug("Current value of PV %s Value %s", self.pvname, self.__value__)
        return self.__value__

    def put(self, newval, wait=None):
        """Put `newval` to the PV, store it as the cached value and return the result of ``pvactx.put``.

        A TimeoutError is logged and re-raised.
        """
        logger.debug("Putting to PV %s current value %s new value %s", self.pvname, self.__value__, newval)
        try:
            ret =  pvactx.put(self.pvname, newval, wait=wait)
        except TimeoutError as e:
            logger.error("Timeout exception putting to PV %s", self.pvname)
            raise
        self.__value__ = newval
        return ret

    def monitor(self, callback):
        """Start a monitor that stores each update (whole value if `isStruct`, else ``.raw.value``) and calls ``callback(err=None)``.

        Does nothing if `callback` is falsy.
        """
        if callback:
            logger.debug("Monitoring PV %s", self.pvname)
            def monitor_cb(newval):
                if self.isStruct:
                    self.__value__ = newval
                else:
                    self.__value__ = newval.raw.value
                logger.debug("Received monitor event for PV %s, received %s", self.pvname, self.__value__)
                callback(err=None)
            self.subscription = pvactx.monitor(self.pvname, monitor_cb)


def initPvMon(mon, pvname, isStruct=False):
    """Set ``mon.pv = Pv(pvname, mon.update, isStruct=isStruct)``."""
    logger.debug("Monitoring PV %s", pvname)
    mon.pv = Pv(pvname, mon.update, isStruct=isStruct)

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

class PvLabel(QtWidgets.QWidget):
    """Name label plus `PvDisplay` showing the value of PV ``pvbase + name``.

    The widget adds itself to `parent` and to ``owner._pvlabels``. Optional `dName` PV is
    monitored too; `isInt`, `isTime`, `scale` and `units` control formatting in `update`.
    """
    def __init__(self, owner, parent, pvbase, name, dName=None, isInt=False, isTime=False, scale=None, units=None):
        super(PvLabel,self).__init__()
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        label  = QtWidgets.QLabel(name)
        label.setMinimumWidth(100)
        layout.addWidget(label)
        #layout.addStretch()
        self.__display = PvDisplay()
        self.__display.connect_signal()
        layout.addWidget(self.__display)
        self.setLayout(layout)
        parent.addWidget(self)

        pvname = pvbase+name
        print(pvname)
        if dName is not None:
            dPvName = pvbase+dName
            self.dPv = Pv(dPvName)
            self.dPv.monitor(self.update)
        else:
            self.dPv = None
        self.isInt = isInt
        self.isTime = isTime
        self.scale = scale
        self.units = units
        initPvMon(self,pvname)

        owner._pvlabels.append(self)

    def update(self, err):
        """Format the PV value and emit it to the display (or print it when `nogui`).

        isTime: seconds since 1990-01-01 UTC shown as local 'yyyy-MMM-dd HH:mm:ss'; isInt:
        '1,234 (0x4d2)'; otherwise the value (times `scale`) plus `units`. If formatting
        raises, the value is shown as an array of '%5.2f' entries (value*scale), 8 per line.

        Notes
        -----
        When `dName` was given the code reads `self.dpv`, but the attribute is `dPv`, so this
        raises AttributeError.
        """
        q = self.pv.__value__
        if self.dPv is not None:
            dq = self.dpv.__value__
        else:
            dq = None
        if err is None:
            s = QString('fail')
            try:
                if self.isTime:
                    dat = QtCore.QDateTime(QtCore.QDate(1990,1,1),QtCore.QTime(0,0,0),QtCore.Qt.UTC).addSecs(int(q)).toLocalTime()
                    s = QString(dat.toString("yyyy-MMM-dd HH:mm:ss"))
                elif self.isInt:
                    s = QString("%s (0x%s)") % ((QString('{:,}'.format(int(q)))),QString(format(int(q)&0xffffffff, 'x')))
                    if dq is not None:
                        s = s + QString(" [%s (0x%s)]") % ((QString(int(dq))),(format(int(dq)&0xffffffff, 'x')))
                else:
                    if self.scale is None:
                        s = QString('{:,}'.format(q))
                        if dq is not None:
                            s = s + QString(" [%s]") % (QString(dq))
                    else:
                        s = '{0:.4f}'.format(q*self.scale)
                        if dq is not None:
                            s = s + ' [{0:.4f}]'.format(dq*self.scale)
                    if self.units is not None:
                        s = s + self.units
            except:
#                logger.error('Exception in pvLable')
                v = ''
                for i in range(len(q)):
                    #v = v + ' %f'%q[i]
#                    v = v + ' ' + QString(q[i]*self.scale)
                    v = v + " %5.2f" % (q[i]*self.scale)
                    if dq is not None:
#                        v = v + QString(" [%s]") % (QString(dq[i]*self.scale))
                        v = v + " %5.2f" % (dq[i]*self.scale)
                        #v = v + ' [' + '%f'%dq[i] + ']'
                    if ((i%8)==7):
                        v = v + '\n'
                if self.units is not None:
                    v = v + self.units
                s = QString(v)

            if nogui:
                print(self.pv.pvname,str(s))
            else:
                self.__display.valueSet.emit(s)
        else:
            print(err)

class PvPushButton(QtWidgets.QPushButton):

    """QPushButton (width 8 px per label character, minimum 25) that writes to PV `pvname` when clicked."""
    valueSet = QtCore.pyqtSignal('QString',name='valueSet')

    def __init__(self, pvname, label):
        super(PvPushButton, self).__init__(label)
        sz = len(label)*8
        if sz < 25:
            sz = 25
        self.setMaximumWidth(sz) # Revisit

        self.clicked.connect(self.buttonClicked)

        self.pv = Pv(pvname)

    def buttonClicked(self):
        """Put 1 and then 0 to the PV."""
        self.pv.put(1)
        self.pv.put(0)

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

    """`CheckBox` bound to PV `pvname`: clicking writes 1/0 and PV updates set the box."""
    def __init__(self, pvname, label):
        super(PvCheckBox, self).__init__(label)
        self.connect_signal()
        self.clicked.connect(self.pvClicked)
        initPvMon(self,pvname)

    def pvClicked(self):
        """Put 1 if the box is checked, else 0, to the PV."""
        q = self.isChecked()
        self.pv.put(1 if q else 0)
        #print "PvCheckBox.clicked: pv %s q %x" % (self.pv.name, q)

    def update(self, err):
        #print ("PvCheckBox.update:  pv %s, i %s, v %x, err %s" % (self.pv.name, self.text(), self.pv.get(), err))
        """Emit `valueSet` with ``value != 0`` if it differs from the box state (print it when `nogui`)."""
        q = self.pv.__value__ != 0
        if err is None:
            if nogui:
                print(self.pv.pvname,q)
            else:
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

    #valueSet = QtCore.pyqtSignal('QString',name='valueSet')
    """QComboBox with `choices` and an int `valueSet` signal that sets the current index."""
    valueSet = QtCore.pyqtSignal(int ,name='valueSet')

    def __init__(self, choices):
        super(PvComboDisplay, self).__init__()
        self.addItems(choices)

    def connect_signal(self):
        """Connect `valueSet` to `setValue`."""
        self.valueSet.connect(self.setValue)

    def setValue(self,value):
        """Set the current index to `value`."""
        self.setCurrentIndex(value)

class PvTableDisplay(QtWidgets.QWidget):

    """Grid of QLabels showing a structured (table) PV: rows from `rowNames`, columns from the PV's `labels`.

    The constructor does a synchronous get to build the grid. Values equal to
    ``colEmpty[j]`` are shown as '-'.
    """
    def __init__(self, pvname, rowNames=None, colEmpty=None):
        super(PvTableDisplay, self).__init__()
        self.ready = False
        self.colEmpty = colEmpty
        initPvMon(self,pvname,isStruct=True)

        v = self.pv.get()

        grid = QtWidgets.QGridLayout()
        for j,r in enumerate(rowNames):
            grid.addWidget(QtWidgets.QLabel(r),j+1,0)
        for j,r in enumerate(v.labels):
            grid.addWidget(QtWidgets.QLabel(r),0,j+1)
            w = [QtWidgets.QLabel('-') for i in range(len(rowNames))]
            setattr(self,r,w)
            for i in range(len(rowNames)):
                grid.addWidget(w[i],i+1,j+1)
        grid.setRowStretch(grid.rowCount(),1)

        self.setLayout(grid)
        self.ready = True

    def update(self,err):
        """Set each grid label from the cached table value; does nothing until construction finished."""
        if not self.ready:
            return
        v = self.pv.__value__
        for j,r in enumerate(v.labels):
            w = getattr(self,r)
            q = getattr(v.value,r)
            e = self.colEmpty[j] if self.colEmpty else None
            for i,qv in enumerate(q):
                sqv = str(qv) if qv != e else '-'
                w[i].setText(sqv)

class PvEditTxt(PvTextDisplay):

    """`PvTextDisplay` bound to PV `pv`; editingFinished calls `setPv`, which subclasses define."""
    def __init__(self, pv, label):
        super(PvEditTxt, self).__init__(label)
        self.connect_signal()
        self.editingFinished.connect(self.setPv)
        initPvMon(self,pv)

class PvEditInt(PvEditTxt):

    """Line edit for an integer PV."""
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
#        print 'Update '+pv  #  This print is evil.
        """Emit the PV value as an int string, or as space-separated '%f' values for an array (print when `nogui`)."""
        q = self.pv.__value__
        if err is None:
            s = QString('fail')
            try:
                s = QString("%s") % (QString(int(q)))
            except:
                v = ''
                for i in range(len(q)):
                    v = v + ' %f'%q[i]
                s = QString(v)

            if nogui:
                print(self.pv.pvname,str(s))
            else:
                self.valueSet.emit(s)
        else:
            print(err)


class PvInt(PvEditInt):

    """`PvEditInt` with an empty label whose `setPv` does nothing (edits are not written)."""
    def __init__(self,pv):
        super(PvInt, self).__init__(pv, '')
#        self.setEnabled(False)

    def setPv(self):
        """Do nothing; body is `pass`."""
        pass

class PvIntArrayW(QtWidgets.QLabel):

    """QLabel (initial text '-') with a `valueSet` string signal connected to `setText`."""
    valueSet = QtCore.pyqtSignal('QString',name='valueSet')

    def __init__(self):
        super(PvIntArrayW, self).__init__('-')
        self.connect_signal()

    def connect_signal(self):
        """Connect `valueSet` to `setValue`."""
        self.valueSet.connect(self.setValue)

    def setValue(self,value):
        """Set the label text to `value`."""
        self.setText(value)

class PvIntArray:

    """Monitor array PV `pv` and show element i in ``widgets[i]``."""
    def __init__(self, pv, widgets):
        self.widgets = widgets
        initPvMon(self,pv)

    def update(self, err):
        """Set the text of ``widgets[i]`` to element i of the value formatted as an integer."""
        q = self.pv.__value__
        if err is None:
            for i in range(len(q)):
#                self.widgets[i].valueSet.emit(QString(format(q[i], 'd')))
                self.widgets[i].setText(QString(format(q[i], 'd')))
        else:
            print(err)

class PvEditHML(PvEditTxt):

    """Line edit for a PV packed as 2-bit codes written as letters L/H/M/m (0/1/2/3)."""
    def __init__(self, pv, label):
        super(PvEditHML, self).__init__(pv, label)

    def setPv(self):
        """Convert the text to an int, 2 bits per letter with the first letter most significant, and put it.

        Prints a message if a character is not one of L, H, M, m.
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
        """Convert the value to its L/H/M/m letter string (2 bits per letter) and emit it (print when `nogui`)."""
        q = self.pv.__value__
        if err is None:
            v = toLMH[q & 0x3]
            q >>= 2
            while q:
                v = toLMH[q & 0x3] + v
                q >>= 2
            s = QString(v)

            if nogui:
                print(self.pv.pvname,str(s))
            else:
                self.valueSet.emit(s)
        else:
            print(err)

class PvHML(PvEditHML):

    """Disabled (read-only) `PvEditHML`."""
    def __init__(self, pv, label):
        super(PvHML, self).__init__(pv, label)
        self.setEnabled(False)

class PvEditDbl(PvEditTxt):

    """Line edit for a floating-point PV."""
    def __init__(self, pv, label):
        super(PvEditDbl, self).__init__(pv, label)

    def setPv(self):
        """Put ``float(text)`` to the PV; a ValueError is not caught."""
        value = float(self.text())
        self.pv.put(value)

    def update(self, err):
        """Emit the value as '{:.4f}', or array elements as ' {:4f}' (print when `nogui`)."""
        q = self.pv.__value__
        if err is None:
            s = QString('fail')
            try:
                s = QString('{:.4f}'.format(q))
            except:
                v = ''
                for i in range(len(q)):
                    v = v + ' {:4f}'.format(q[i])
                s = QString(v)

            if nogui:
                print(self.pv.pvname,str(s))
            else:
                self.valueSet.emit(s)
        else:
            print(err)

class PvDbl(PvEditDbl):

    """Disabled `PvEditDbl` with an empty label."""
    def __init__(self,pv):
        super(PvDbl, self).__init__(pv, '')
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

    """Monitor array PV `pv` and show element i in ``widgets[i]``."""
    def __init__(self, pv, widgets):
        self.widgets = widgets
        initPvMon(self,pv)

    def update(self, err):
        """Emit element i formatted '.4f' to ``widgets[i].valueSet``; with `nogui`, print the array instead."""
        q = self.pv.__value__
        if err is None:
            for i in range(len(q)):
                if nogui==False:
                    self.widgets[i].valueSet.emit(QString(format(q[i], '.4f')))
            if nogui:
                print(self.pv.pvname,q)
        else:
            print(err)


class PvEditCmb(PvComboDisplay):

    """Combo box bound to PV `pvname`; the index (optionally mapped through `imap`) is the PV value.

    Optional `cb` is called after each PV update.
    """
    def __init__(self, pvname, choices, cb=None, imap=None):
        super(PvEditCmb, self).__init__(choices)
        self.cb = cb
        self.imap = imap
        self.connect_signal()
        self.currentIndexChanged.connect(self.setValue)
        initPvMon(self,pvname)

    def setValue(self):
        """Put the current index (mapped through `imap` if given) unless it equals the cached PV value."""
        value = self.currentIndex()
        if self.imap is not None:
            value = self.imap[value]
        if self.pv.__value__ != value:
            self.pv.put(value)
        else:
            logger.debug("Skipping updating PV for edit combobox as the value of the pv %s is the same as the current value", self.pv.pvname)

    def update(self, err):
        """Set the current index from the PV value and emit `valueSet` (print when `nogui`), then call `cb` if set."""
        q = self.pv.__value__
        if err is None:
            if nogui:
                print(self.pv.pvname,q)
            else:
                self.setCurrentIndex(q)
                self.valueSet.emit(q)
            if self.cb != None:
                self.cb()
        else:
            print(err)


class PvCmb(PvEditCmb):

    """Disabled (read-only) `PvEditCmb`."""
    def __init__(self, pvname, choices):
        super(PvCmb, self).__init__(pvname, choices)
        self.setEnabled(False)

class PvIntRow(object):
    """One grid row: a name label in column 0 and `length` value labels fed by array PV `pvname`."""
    def __init__(self, layout, name, pvname, row, length):
        layout.addWidget( QtWidgets.QLabel(name), row, 0 )
        self.cells = []
        for j in range(length):
            lbl = QtWidgets.QLabel()
            layout.addWidget( lbl, row, j+1 )
            self.cells.append(lbl)
        initPvMon(self,pvname)

    def update(self, err):
        """Set each cell to '%d' for int elements, else '{0:.4f}'."""
        q = self.pv.__value__
        for i in range(len(q)):
            if type(q[i]) == int:
                self.cells[i].setText('%d'%q[i])
            else:
                self.cells[i].setText('{0:.4f}'.format(q[i]))

class PvIntTable(QtWidgets.QGroupBox):
    """QGroupBox with one `PvIntRow` per name, using PV ``pvbase + pvlist[i]``."""
    def __init__(self, title, pvbase, pvlist, names, length):
        super(PvIntTable, self).__init__(title)

        lo = QtWidgets.QGridLayout()
        for i,name in enumerate(names):
            PvIntRow( lo, name, pvbase+pvlist[i], i, length )
        self.setLayout(lo)


class PvCString(QtWidgets.QWidget):
    """Name label plus word-wrapping display of a character-array PV ``pvbase + name``."""
    def __init__(self, parent, pvbase, name, dName=None, isStruct=False):
        super(PvCString,self).__init__()
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        label  = QtWidgets.QLabel(name)
        label.setMinimumWidth(100)
        layout.addWidget(label)
        #layout.addStretch()
        self.__display = PvDisplay()
        self.__display.setWordWrap(True)
        self.__display.connect_signal()
        layout.addWidget(self.__display)
        self.setLayout(layout)
        parent.addWidget(self)

        pvname = pvbase+name
        initPvMon(self,pvname,isStruct)

    def update(self, err):
        """Synchronously get the PV (its `.value` if `isStruct`), print it, and emit the characters up to the first 0."""
        if self.pv.isStruct:
            q = self.pv.get().value
        else:
            q = self.pv.get()
        print(q)
        if err is None:
            s = QString()
            slen = len(q)
#            if slen > 64:
#                slen = 64
            for i in range(slen):
                if q[i]==0:
                    break
                s += QChar(ord(q[i]))
            self.__display.valueSet.emit(s)
        else:
            print(err)


class PvMask(object):

    """Row of `bits` disabled check boxes added to `parent`, showing the bits of PV `pvname`."""
    def __init__(self, parent, pvname, bits):
        super(PvMask,self).__init__()

        self.chkBox = []
        for i in range(bits):
            chkB = QtWidgets.QCheckBox()
            parent.addWidget( chkB )
            self.chkBox.append(chkB)
            chkB.setEnabled(False)
        initPvMon(self, pvname)

    def update(self, err):
        """Check box i if bit i of the PV value is set, else uncheck it."""
        v = self.pv.__value__
        for i in range(len(self.chkBox)):
            if v & (1<<i):
                self.chkBox[i].setChecked(True)
            else:
                self.chkBox[i].setChecked(False)

class PvMaskTab(QtWidgets.QWidget):

    """Grid of labelled check boxes (one per name) editing the bits of PV `pvname`.

    Optional `cb` is called after each PV update.
    """
    def __init__(self, pvname, names, cb=None):
        super(PvMaskTab,self).__init__()

        self.cb = cb
        initPvMon(self,pvname)

        self.chkBox = []
        layout = QtWidgets.QGridLayout()
        rows = (len(names)+3)/4
        cols = (len(names)+rows-1)/rows
        for i in range(len(names)):
            layout.addWidget( QtWidgets.QLabel(names[i]), int(i/cols), int(2*(i%cols)) )
            chkB = QtWidgets.QCheckBox()
            layout.addWidget( chkB, int(i/cols), int(2*(i%cols)+1) )
            chkB.clicked.connect(self.setValue)
            self.chkBox.append(chkB)
        self.setLayout(layout)

    def setValue(self):
        """Put the bitmask of checked boxes (bit i for box i) to the PV."""
        v = 0
        for i in range(len(self.chkBox)):
            if self.chkBox[i].isChecked():
                v |= (1<<i)
        self.pv.put(v)

    def update(self, err):
        """Set box i from bit i of the PV value (print when `nogui`), then call `cb` if set."""
        q = self.pv.__value__
        if err is None:
            if nogui:
                print(self.pv.pvname,q)
            else:
                for i in range(len(self.chkBox)):
                    self.chkBox[i].setChecked(q&(1<<i))
            if self.cb != None:
                self.cb()
        else:
            print(err)

    #  Reassert PV when window is shown
    def showEvent(self,QShowEvent):
#        self.QWidget.showEvent()
        """Re-put the current check-box bitmask when the widget is shown."""
        self.setValue()

class PvDefSeq(QtWidgets.QWidget):
    """Sequence selector: a combo of 'Global_0'..'Global_16' and 'Local' writing PV ``pvname + '_Sequence'``.

    A stacked set of `PvEditCmb` widgets on ``pvname + '_SeqBit'`` follows the selection.
    """
    valueSet = QtCore.pyqtSignal(int,name='valueSet')

    def __init__(self, pvname):
        super(PvDefSeq,self).__init__()

        lo = QtWidgets.QVBoxLayout()
        self.seqsel = QtWidgets.QComboBox()
        self.seqsel.addItems(['Global_%d'%i for i in range(17)]+['Local'])
        self.seqsel.currentIndexChanged.connect(self.setValue)
        lo.addWidget(self.seqsel)

        seqstack = QtWidgets.QStackedWidget()
        for i in range(17):
            seqstack.addWidget(PvEditCmb(pvname+'_SeqBit', seqGlobal))
#        seqstack.addWidget(PvEditCmb(pvname+'_SeqBit'  ,seqBursts))
#        seqstack.addWidget(PvEditCmb(pvname+'_SeqBit'  ,seqRates))
        seqstack.addWidget(PvEditCmb(pvname+'_SeqBit'  ,seqLocal))
        self.seqsel.currentIndexChanged.connect(seqstack.setCurrentIndex)
        lo.addWidget(seqstack)

        self.setLayout(lo)

        initPvMon(self,pvname+'_Sequence')

    def setValue(self):
        """Put the selected combo index to the '_Sequence' PV."""
        value = self.seqsel.currentIndex()
#        self.pv.put(value+15)  # Defined sequences start at 15
        self.pv.put(value)

    def update(self,err):
        """Set the combo index from the '_Sequence' PV value and emit `valueSet`."""
        q = self.pv.__value__
        if err is None:
            self.seqsel.setCurrentIndex(q)
            self.valueSet.emit(q)
        else:
            print(err)

class MonFwd(object):
    """Monitor PV `pvname` and forward each update to ``parent.update(err)``."""
    def __init__(self,parent,pvname):
        self._parent = parent
        initPvMon(self,pvname)

    def update(self,err):
        """Call ``self._parent.update(err)``."""
        self._parent.update(err)

class PvDefCuSeq(QtWidgets.QWidget):

    """Widget with one `PvEditInt` for PV ``pvname + '_EventCode'``."""
    def __init__(self, pvname):
        super(PvDefCuSeq,self).__init__()

        lo = QtWidgets.QHBoxLayout()
        lo.addWidget(PvEditInt(pvname+'_EventCode','EventCode'))
        self.setLayout(lo)

    def update(self,err):
        """Do nothing; body is `pass`."""
        pass

class PvEvtTab(QtWidgets.QStackedWidget):

    """Stacked widget of event-selection editors whose page follows combo box `evtcmb`.

    Pages: '_FixedRate' combo (`fixedRates`); '_ACRate' combo plus '_ACTimeslot' mask
    (`acTS`); `PvDefCuSeq`; `PvDefSeq`. The lists come from `psdaq.configdb.tsdef`.
    """
    def __init__(self, pvname, evtcmb):
        super(PvEvtTab,self).__init__()

        self.ok_palette = QtGui.QPalette()
        self.errpalette = QtGui.QPalette()
        self.errpalette.setColor(QtGui.QPalette.Window, QtGui.QColor.fromRgb(255,0,0))

        self.addWidget(PvEditCmb(pvname+'_FixedRate',fixedRates))

        self.evtcmb = evtcmb
        acw = QtWidgets.QWidget()
        acl = QtWidgets.QVBoxLayout()
        acl.addWidget(PvEditCmb(pvname+'_ACRate'    ,acRates))
        self.actsmask = PvMaskTab(pvname+'_ACTimeslot',acTS   ,self.validate)
        acl.addWidget(self.actsmask)
        acw.setLayout(acl)
        self.addWidget(acw)

#        sqw = QtGui.QWidget()
#        sql = QtGui.QVBoxLayout()
##        sql.addWidget(PvEditCmb(pvname+'_Sequence',seqIdxs))
##        sql.addWidget(PvEditCmb(pvname+'_SeqBit',seqBits))
#        sql.addWidget(PvEditCmb(pvname+'_SeqBit'  ,seqRates))
#        sqw.setLayout(sql)
        self.addWidget(PvDefCuSeq(pvname))
        self.addWidget(PvDefSeq  (pvname))

        self.setCurrentIndex(evtcmb.currentIndex())
        evtcmb.currentIndexChanged.connect(self.setCurrentIndex)

    #
    #  Validate the selections and indicate error if timeslot mask is required
    #  and timeslot mask is empty
    #
    def validate(self,idx=None):
        """Give the AC timeslot mask a red palette if its cached PV value is 0, else the normal palette."""
        if self.actsmask.pv.__value__==0:
            self.actsmask.setPalette(self.errpalette)
        else:
            self.actsmask.setPalette(self.ok_palette)

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

    """4x4 grid of 'D0'..'D15' check boxes editing the bitmask PV `pvname`; optional `cb` runs after updates."""
    def __init__(self, pvname, cb=None):
        super(PvDstTab,self).__init__()

        self.cb = cb
        initPvMon(self,pvname)

        self.chkBox = []
        layout = QtWidgets.QGridLayout()
        for i in range(NBeamSeq):
            layout.addWidget( QtWidgets.QLabel('D%d'%i), int(i/4), int(2*(i%4)) )
            chkB = QtWidgets.QCheckBox()
            layout.addWidget( chkB, int(i/4), int(2*(i%4)+1) )
            chkB.clicked.connect(self.setValue)
            self.chkBox.append(chkB)
        self.setLayout(layout)

    def setValue(self):
        """Put the bitmask of checked boxes (bit i for 'Di') to the PV."""
        v = 0
        for i in range(NBeamSeq):
            if self.chkBox[i].isChecked():
                v |= (1<<i)
        self.pv.put(v)

    def update(self, err):
        """Set each box from its bit in the PV value (print when `nogui`), then call `cb` if set."""
        q = self.pv.__value__
        if err is None:
            if nogui:
                print(self.pv.pvname,q)
            else:
                for i in range(NBeamSeq):
                    self.chkBox[i].setChecked(q&(1<<i))
            if self.cb != None:
                self.cb()
        else:
            print(err)

class PvEditDst(QtWidgets.QWidget):

    """Destination editor: `PvEditCmb` on `pvname` (Include/DontCare) and a `PvDstTab` on ``pvname + '_Mask'``.

    `idx` is unused.
    """
    def __init__(self, pvname, idx):
        super(PvEditDst, self).__init__()

        self.ok_palette = QtGui.QPalette()
        self.errpalette = QtGui.QPalette()
        self.errpalette.setColor(QtGui.QPalette.Window, QtGui.QColor.fromRgb(255,0,0))

        vbox = QtWidgets.QVBoxLayout()
        self.selcmb = PvEditCmb(pvname,dstsel,self.validate)
        vbox.addWidget(self.selcmb)
        self.selmask = PvDstTab(pvname+'_Mask',self.validate)
        vbox.addWidget(self.selmask)
        self.setLayout(vbox)

    #
    #  Validate the selections and indicate error if destination is required
    #  and no destination is selected
    #
    def validate(self):
        """Give both widgets a red palette when both cached PV values are 0, else the normal palette."""
        if self.selcmb.pv.__value__==0 and self.selmask.pv.__value__==0:
            self.selcmb .setPalette(self.errpalette)
            self.selmask.setPalette(self.errpalette)
        else:
            self.selcmb .setPalette(self.ok_palette)
            self.selmask.setPalette(self.ok_palette)

class PvEditTS(PvEditCmb):

    """`PvEditCmb` with choices '0'..'15'; `idx` is unused."""
    def __init__(self, pvname, idx):
        super(PvEditTS, self).__init__(pvname, ['%u'%i for i in range(16)])

def PvInput(widget, parent, pvbase, name, count=1, start=0, istart=0, enable=True, horiz=True, width=None):
    """Add a labelled row (or column) of PV widgets to layout `parent`; returns None.

    With `count` 1 one ``widget(pvbase + name, '')`` is made; otherwise `count` widgets
    for PVs ``pvbase + name + str(i + start)`` labelled ``str(i + istart)``. Each widget
    is enabled per `enable` and limited to `width` if given.
    """
    pvname = pvbase+name
    print(pvname)

    if horiz:
        layout = QtWidgets.QHBoxLayout()
    else:
        layout = QtWidgets.QVBoxLayout()
    label  = QtWidgets.QLabel(name)
    label.setMinimumWidth(100)
    layout.addWidget(label)
    #layout.addStretch
    if count == 1:
        w = widget(pvname, '')
        if width:
            w.setMaximumWidth(width)
        w.setEnabled(enable)
        layout.addWidget(w)
    else:
        for i in range(count):
            w = widget(pvname+'%d'%(i+start), QString(i+istart))
            if width:
                w.setMaximumWidth(width)
            w.setEnabled(enable)
            layout.addWidget(w)
    #layout.addStretch
    parent.addLayout(layout)

def LblPushButton(parent, pvbase, name, count=1):
    """Call `PvInput` with `PvPushButton`; returns None."""
    return PvInput(PvPushButton, parent, pvbase, name, count)

def LblCheckBox(parent, pvbase, name, count=1, start=0, istart=0, enable=True, horiz=True):
    """Call `PvInput` with `PvCheckBox`; returns None."""
    return PvInput(PvCheckBox, parent, pvbase, name, count, start, istart, enable, horiz=horiz)

def LblEditInt(parent, pvbase, name, count=1, horiz=True):
    """Call `PvInput` with `PvEditInt`; returns None."""
    return PvInput(PvEditInt, parent, pvbase, name, count, horiz=horiz)

def LblEditDbl(parent, pvbase, name, count=1, horiz=True):
    """Call `PvInput` with `PvEditDbl`; returns None."""
    return PvInput(PvEditDbl, parent, pvbase, name, count, horiz=horiz)

def LblEditHML(parent, pvbase, name, count=1):
    """Call `PvInput` with `PvEditHML`; returns None."""
    return PvInput(PvEditHML, parent, pvbase, name, count)

def LblEditTS(parent, pvbase, name, count=1):
    """Call `PvInput` with `PvEditTS`; returns None."""
    return PvInput(PvEditTS, parent, pvbase, name, count)

def LblEditEvt(parent, pvbase, name, count=1):
    """Call `PvInput` with `PvEditEvt`; returns None."""
    return PvInput(PvEditEvt, parent, pvbase, name, count)

def LblEditDst(parent, pvbase, name, count=1):
    """Call `PvInput` with `PvEditDst`; returns None."""
    return PvInput(PvEditDst, parent, pvbase, name, count)

def LblMask(pvbase, label, bits=1):
    """Return a QHBoxLayout with a label and a `PvMask` of `bits` boxes for PV ``pvbase + label``."""
    hbox = QtWidgets.QHBoxLayout()
    hbox.addWidget( QtWidgets.QLabel(label) )
    PvMask(hbox, pvbase+label, bits)
    hbox.addStretch(1)
    return hbox

def to_mask(lista):
    """Return the int with bit l set for each l in `lista`."""
    v = 0
    for l in lista:
        v |= (1<<l)
    return v
