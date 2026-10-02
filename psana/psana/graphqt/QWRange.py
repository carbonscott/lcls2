
"""Defines ``QWRange``, a QWidget with 'from' and 'to' line edits for a range of numbers.

The 'from' field accepts 0-9999 and the 'to' field 1-9999 or 'end' (the tool tips call them run numbers); edits emit the ``field_is_changed`` signal.
"""
import logging
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QHBoxLayout, QVBoxLayout
from PyQt5.QtCore import Qt, QMargins, QRegExp, pyqtSignal
from PyQt5.QtGui import QIntValidator, QRegExpValidator

from psana.graphqt.Styles import style


class QWRange(QWidget):
    """Range setting GUI
    """
    field_is_changed = pyqtSignal('QString')

    def __init__(self, parent=None, str_from=None, str_to=None, txt_from='valid from', txt_to='to'):

        QWidget.__init__(self, None)
        self.parent = parent

        if txt_from == '':
            self.setGeometry(10, 25, 140, 40)
            self.use_lab_from = False
        else:
            self.setGeometry(10, 25, 200, 40)
            self.use_lab_from = True

        self.set_params(str_from, str_to)

        self.txt_from = txt_from
        if self.use_lab_from: self.lab_from = QLabel(txt_from)
        self.lab_to         = QLabel(txt_to)
        self.edi_from       = QLineEdit  ( self.str_from )
        self.edi_to         = QLineEdit  ( self.str_to )

        self.set_edi_validators()

        self.hboxC = QHBoxLayout()
        self.hboxC.addStretch(1)
        if self.use_lab_from: self.hboxC.addWidget( self.lab_from )
        self.hboxC.addWidget( self.edi_from )
        self.hboxC.addWidget( self.lab_to )
        self.hboxC.addWidget( self.edi_to )
        self.hboxC.addStretch(1)

        self.vboxW = QVBoxLayout()
        self.vboxW.addStretch(1)
        self.vboxW.addLayout( self.hboxC )
        self.vboxW.addStretch(1)

        self.setLayout(self.vboxW)

        self.edi_from.editingFinished.connect(self.on_edi_from)
        self.edi_to  .editingFinished.connect(self.on_edi_to)

        self.set_tool_tips()
        self.set_style()

        # cp.guirange = self # DO NOT REGISTER THIS OBJECT! There may be many instances in the list of runs...

    def set_edi_validators(self):
        """Set validators: integers 0-9999 for the 'from' field and a regular expression for 1-9999 or 'end' for the 'to' field."""
        self.edi_from.setValidator(QIntValidator(0,9999,self))
        self.edi_to  .setValidator(QRegExpValidator(QRegExp("[1-9]|[1-9][0-9]|[1-9][0-9][0-9]|[1-9][0-9][0-9][0-9]|end$"),self))
        #self.edi_to  .setValidator(QRegExpValidator(QRegExp("[0-9]\\d{0,3}|end$"),self))


    def set_tool_tips(self):
        """Set tool tips on the 'from' and 'to' fields."""
        self.edi_from.setToolTip('Enter run number in range [0,9999]')
        self.edi_to  .setToolTip('Enter run number in range [1,9999] or "end"')


    def set_style(self):
        """Apply style sheets, minimum size (200x32 with the 'from' label, else 100x32), zero margins, 40 px right-aligned fields, then ``set_style_buttons``."""
        self.setStyleSheet(style.styleBkgd)

        if self.use_lab_from:
            self.setMinimumSize(200,32)
        else:
            self.setMinimumSize(100,32)

        #self.setFixedHeight(40)
        self.layout().setContentsMargins(0,0,0,0)

        self.edi_from.setFixedWidth(40)
        self.edi_to  .setFixedWidth(40)

        self.edi_from.setAlignment(Qt.AlignRight)
        self.edi_to  .setAlignment(Qt.AlignRight)

        if self.use_lab_from: self.lab_from  .setStyleSheet(style.styleLabel)
        self.lab_to.setStyleSheet(style.styleLabel)

        self.set_style_buttons()


    def status_buttons_is_good(self):
        """Return True if ``str_to`` is 'end' or ``int(str_from) <= int(str_to)``, otherwise False."""
        if self.str_to == 'end': return True

        if int(self.str_from) > int(self.str_to):
            #msg  = 'Begin number %s exceeds the end number %s' % (self.str_from, self.str_to)
            #msg += '\nRANGE SEQUENCE SHOULD BE FIXED !!!!!!!!'
            #logger.warning(msg)
            return False

        return True


    def set_style_buttons(self):
        """Give both fields the normal edit style if ``status_buttons_is_good()``, otherwise the 'bad' edit style."""
        if self.status_buttons_is_good():
            self.edi_from.setStyleSheet(style.styleEdit)
            self.edi_to  .setStyleSheet(style.styleEdit)
        else:
            self.edi_from.setStyleSheet(style.styleEditBad)
            self.edi_to  .setStyleSheet(style.styleEditBad)


    def emit_field_is_changed_signal(self,msg):
        """Emit ``field_is_changed(msg)``."""
        self.field_is_changed.emit(msg)


    def on_edi_from(self):
        #logger.debug('on_edi_from')
        """If the 'from' text changed, store it in ``str_from``, update field styles and emit ``field_is_changed('from:<value>')``."""
        txt = str( self.edi_from.text() )
        if txt == self.str_from: return # if text has not changed
        self.str_from = txt
        #msg = 'Set the range from "%s"' % self.str_from
        #logger.info(msg)
        self.set_style_buttons()
        self.emit_field_is_changed_signal('from:%s'%self.str_from)


    def on_edi_to(self):
        #logger.debug('on_edi_to')
        """If the 'to' text changed, store it in ``str_to``, update field styles and emit ``field_is_changed('to:<value>')``."""
        txt = str( self.edi_to.text() )
        if txt == self.str_to: return # if text has not changed
        self.str_to = txt
        #msg = 'Set the range up to "%s"' % self.str_to
        #logger.info(msg)
        self.set_style_buttons()
        self.emit_field_is_changed_signal('to:%s'%self.str_to)


    def set_fields_enable(self, is_enabled=True):
        """Interface method enabling/disabling the edit fields"""
        if is_enabled:
            self.set_style_buttons()
            #self.edi_from.setStyleSheet(style.styleEdit)
            #self.edi_to  .setStyleSheet(style.styleEdit)
        else:
            self.edi_from.setStyleSheet(style.styleEditInfo)
            self.edi_to  .setStyleSheet(style.styleEditInfo)

        self.edi_from.setEnabled(is_enabled)
        self.edi_to  .setEnabled(is_enabled)

        self.edi_from .setReadOnly(not is_enabled)
        self.edi_to   .setReadOnly(not is_enabled)


    def set_params(self, str_from=None, str_to=None):
        """Set ``str_from`` (default '0') and ``str_to`` (default 'end') from the arguments."""
        self.str_from = str_from if str_from is not None else '0'
        self.str_to   = str_to   if str_to is not None else 'end'


    def reset_fields(self, str_from=None, str_to=None):
        """Interface method resetting the range fields to default"""
        self.set_params(str_from, str_to)
        self.set_fields()


    def set_fields(self):
        """Write ``str_from`` and ``str_to`` into the fields and update their styles."""
        self.edi_from.setText(self.str_from)
        self.edi_to  .setText(self.str_to)
        self.set_style_buttons()


    def range(self):
        """Interface method returning range string, for example '123-end' """
        if self.status_buttons_is_good():
            return '%d-%s' % ( int(self.str_from),
                                   self.str_to.lstrip('0') )
        else:
            return '%d-%d' % ( int(self.str_from), int(self.str_from) )

        #return self.str_from + '-' + self.str_to


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    w  = QWRange(None,'0','end','')
    w.setWindowTitle('Range setting GUI')
    w.move(10,25)
    w.show()
    app.exec_()

# EOF
