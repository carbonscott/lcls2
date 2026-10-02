
"""
:py:class:`QWLoggerStd` - GUI for python logger
===============================================

Usage::
    # Test: python lcls2/psana/psana/graphqt/QWLoggerStd.py

    # Import
    from psana.graphqt.QWLoggerStd import QWLoggerStd

    # Methods - see test

See:
    - :py:class:`QWLoggerStd`
    - `lcls2 on github <https://github.com/slac-lcls/lcls2>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.

Created on 2018-04-11 by Mikhail Dubrovin
"""

import logging
logger = logging.getLogger() # need in root to intercept messages from all other loggers
#logger = logging.getLogger(__name__)

import os
import sys
from random import randint

from PyQt5.QtWidgets import QApplication, QWidget, QTextEdit, QLabel, QPushButton, QComboBox,\
                            QHBoxLayout, QVBoxLayout, QFileDialog
from PyQt5.QtGui import QTextCursor
from psana.graphqt.Styles import style
import psana.pyalgos.generic.Utils as gu
scrname = sys.argv[0].rsplit('/')[-1]


class QWFilter(logging.Filter):
    """logging.Filter that copies every record, formatted with ``qwlogger.formatter``, into the QWLoggerStd text window.

    ``__init__`` does not call ``logging.Filter.__init__``.
    """
    def __init__(self, qwlogger):
        #logging.Filter.__init__(self)#, name='')
        self.qwl = qwlogger

    def filter(self, rec):
        """Format ``rec`` with the widget formatter, append it to the widget with ``append_qwlogger`` and return True (the record is never filtered out)."""
        msg = self.qwl.formatter.format(rec)
        self.qwl.append_qwlogger(msg)
        #self.print_filter_attributes(rec)
        return True


    def print_filter_attributes(self, rec):
        """Log at debug level the type and attribute names of ``rec`` and of the root logger, then some record fields.

        The last call passes the fields as extra positional arguments to ``logger.debug``, which does not match its format string.
        """
        logger.debug('type(rec): %s'%type(rec))
        logger.debug('dir(rec): %s'%dir(rec))
        logger.debug('dir(logger): %s'%dir(logger))
        #logger.debug('dir(syslog): %s'%dir(self.syslog))
        logger.debug(rec.created, rec.name, rec.levelname, rec.msg)


class QWLoggerStd(QWidget):

    """QWidget that displays messages of the root Python logger in a read-only text box.

    ``config_logger`` adds a handler (FileHandler for ``logfname`` if ``cp.save_log_at_exit`` is set, else StreamHandler) with a ``QWFilter`` that forwards every record to this widget. Level, prefix and file parameters are taken from ``cp``; the instance registers itself as ``cp.qwloggerstd``.
    """
    _name = 'QWLoggerStd'

    def __init__(self, cp, show_buttons=True, logfname='log-calibman.txt'):

        QWidget.__init__(self, parent=None)

        self.save_log_at_exit = cp.save_log_at_exit.value()
        self.log_level  = cp.log_level
        self.log_prefix = cp.log_prefix
        self.log_file   = cp.log_file # DEPRICATED

        self.show_buttons = show_buttons
        cp.qwloggerstd = self

        logger.debug('logging._levelToName: ', logging._levelToName) # {0: 'NOTSET', 50: 'CRITICAL', 20: 'INFO',...
        logger.debug('logging._nameToLevel: ', logging._nameToLevel) # {'NOTSET': 0, 'ERROR': 40, 'WARNING': 30,...

        self.dict_level_to_name = logging._levelToName
        self.dict_name_to_level = logging._nameToLevel
        self.level_names = list(logging._levelToName.values())

        self.edi_txt   = QTextEdit('Logger window')
        self.lab_level = QLabel('Log level:')
        self.but_close = QPushButton('&Close')
        self.but_save  = QPushButton('&Save log-file')
        self.but_rand  = QPushButton('&Random')
        self.cmb_level = QComboBox(self)
        self.cmb_level.addItems(self.level_names)
        self.cmb_level.setCurrentIndex(self.level_names.index(self.log_level.value()))

        self.hboxM = QHBoxLayout()
        self.hboxM.addWidget(self.edi_txt)

        self.hboxB = QHBoxLayout()
        self.hboxB.addStretch(4)
        self.hboxB.addWidget(self.lab_level)
        self.hboxB.addWidget(self.cmb_level)
        self.hboxB.addWidget(self.but_rand)
        self.hboxB.addStretch(1)
        self.hboxB.addWidget(self.but_save)
        self.hboxB.addWidget(self.but_close)

        self.vbox = QVBoxLayout()
        self.vbox.addLayout(self.hboxM)
        self.vbox.addLayout(self.hboxB)
        self.setLayout(self.vbox)

        if self.show_buttons: self.connect_buttons()

        self.set_style()
        self.set_tool_tips()

        self.config_logger(logfname)


    def config_logger(self, logfname='log.txt'):

        """Attach a handler with a ``QWFilter`` to the root logger and set the level from ``self.log_level``.

        The format includes a timestamp unless the level is DEBUG. If ``self.save_log_at_exit`` is true the directories of ``logfname`` are created with ``gu.create_path`` and a FileHandler opened in 'w' mode is used; otherwise a StreamHandler.
        """
        self.append_qwlogger('Start logger\nLog file: %s' % logfname)

        levname = self.log_level.value()
        level = self.dict_name_to_level[levname] # e.g. logging.DEBUG

        tsfmt='%Y-%m-%dT%H:%M:%S'
        fmt = '[%(levelname).1s] %(name)s:L%(lineno)04d %(message)s' if level==logging.DEBUG else\
              '[%(levelname).1s] %(asctime)s %(name)s:L%(lineno)04d %(message)s' # %(filename)s

        #sys.stdout = sys.stderr = open('/dev/null', 'w')

        self.formatter = logging.Formatter(fmt, datefmt=tsfmt)
        #logger.addFilter(QWFilter(self)) # register self for callback from filter

        # TRICK: add filter to handler to intercept ALL messages

        if self.save_log_at_exit:
            depth = 6 if logfname[0]=='/' else 1
            gu.create_path(logfname, depth, mode=0o0777)
            self.handler = logging.FileHandler(logfname, 'w')
        else:
            self.handler = logging.StreamHandler()

        self.handler.addFilter(QWFilter(self))
        #self.handler.setLevel(logging.NOTSET) # level
        self.handler.setFormatter(self.formatter)
        logger.addHandler(self.handler)
        self.set_level(levname) # pass level name

        #logger.debug('dir(self.handler):' , dir(self.handler))
        logger.info('log file: %s\n%s SAVED AT EXIT' % (logfname, 'IS' if self.save_log_at_exit else 'IS NOT'))



    def set_level(self, level_name='DEBUG'):
        #self.append_qwlogger('Set logger layer: %s' % level_name)
        #logger.setLevel(level_name) # {0: 'NOTSET'}
        """Set the root logger level from the level name ``level_name`` and log an info message; an unknown name raises KeyError."""
        level = self.dict_name_to_level[level_name]
        logger.setLevel(level)
        #logging.getLogger().setLevel(level)
        #msg = 'Set logger level %s of the list: %s' % (level_name, ', '.join(self.level_names))
        #logger.debug(msg)
        logger.info('Set logger level %s' % level_name)


    def connect_buttons(self):
        """Connect the Close, Save and Random buttons and the level combo box to their handlers."""
        self.but_close.clicked.connect(self.on_but_close)
        self.but_save.clicked.connect(self.on_but_save)
        self.but_rand.clicked.connect(self.on_but_rand)
        self.cmb_level.currentIndexChanged[int].connect(self.on_cmb_level)


    def disconnect_buttons(self):
        """Disconnect the handlers connected by ``connect_buttons``."""
        self.but_close.clicked.disconnect(self.on_but_close)
        self.but_save.clicked.disconnect(self.on_but_save)
        self.but_rand.clicked.disconnect(self.on_but_rand)
        self.cmb_level.currentIndexChanged[int].disconnect(self.on_cmb_level)


    def set_tool_tips(self):
        #self           .setToolTip('This GUI is for browsing log messages')
        """Set tool tips on the text box, buttons and level combo box."""
        self.edi_txt    .setToolTip('Window for log messages')
        self.but_close  .setToolTip('Close this window')
        self.but_save   .setToolTip('Save logger content in file')#: '+os.path.basename(self.fname_log.value()))
        self.but_rand   .setToolTip('Inject random message')
        self.cmb_level  .setToolTip('Select logger level of messages to display')


    def set_style(self):
        """Apply style sheets, make the text box read-only, show or hide the controls according to ``self.show_buttons`` and zero the layout margins."""
        self.           setStyleSheet(style.styleBkgd)
        #self.lab_title.setStyleSheet(style.styleTitleBold)
        self.lab_level .setStyleSheet(style.styleTitle)
        self.but_close .setStyleSheet(style.styleButton)
        self.but_save  .setStyleSheet(style.styleButton)
        self.but_rand  .setStyleSheet(style.styleButton)
        self.cmb_level .setStyleSheet(style.styleButton)
        self.edi_txt   .setReadOnly(True)
        self.edi_txt   .setStyleSheet(style.styleWhiteFixed)
        #self.edi_txt   .ensureCursorVisible()
        #self.lab_title.setAlignment(QtCore.Qt.AlignCenter)
        #self.titTitle.setBold()

        self.lab_level .setVisible(self.show_buttons)
        self.cmb_level .setVisible(self.show_buttons)
        self.but_save  .setVisible(self.show_buttons)
        self.but_rand  .setVisible(self.show_buttons)
        self.but_close .setVisible(self.show_buttons)

        #if not self.show_buttons:
        self.layout().setContentsMargins(0,0,0,0)
        #self.setMinimumSize(300,50)
        #self.setBaseSize(500,200)


    #def setParent(self,parent):
    #    self.parent = parent


    #def resizeEvent(self, e):
        #logger.debug('resizeEvent')
        #pass


    #def moveEvent(self, e):
        #logger.debug('moveEvent')
        #self.cp.posGUIMain = (self.pos().x(),self.pos().y())
        #pass


    def closeEvent(self, e):
        """Log a debug message, close the logging handler and forward the event to ``QWidget.closeEvent``."""
        logger.debug('closeEvent')
        #logger.info('%s.closeEvent' % self._name)
        #self.save_log_total_in_file() # It will be saved at closing of GUIMain

        #logger.addHandler(self.handler)
        self.handler.close()
        QWidget.closeEvent(self, e)


    def on_but_close(self):
        """Log a debug message and close the widget."""
        logger.debug('on_but_close')
        self.close()


    def on_but_save(self):
        """Log a debug message and call ``save_log_in_file``."""
        logger.debug('on_but_save:')
        self.save_log_in_file()


    def on_but_rand(self):
        """Pick a random level name, append a note to the text box and log a test message at that level to the root logger."""
        levels = self.level_names
        level_name = levels[randint(0, len(levels)-1)]
        self.append_qwlogger('===> Inject in logger random message of level %s' % level_name)
        ind = self.dict_name_to_level[level_name]
        logger.log(ind, 'This is a random message of level %s' % level_name)


    def on_cmb_level(self):
        """Store the level selected in the combo box in ``self.log_level`` and apply it with ``set_level``."""
        selected = str(self.cmb_level.currentText())
        msg = 'on_cmb_level set %s %s' % (self.lab_level.text(), selected)
        logger.debug(msg)
        #logger.log(0,msg)
        self.log_level.setValue(selected)
        self.set_level(selected)

        #self.edi_txt.setText('Start logging messages in QWLoggerStd') #logger.getLogContent())


    def save_log_in_file(self):
        """Ask for a file name and store it in ``self.log_file``; no log content is written by this method.

        The PyQt5 dialog result (a tuple) is passed through ``str()``, so the cancel check ``path == ''`` never matches and the stored value is the text of that tuple.
        """
        logger.info('save_log_in_file ' + self.log_file.value())
        path = str(QFileDialog.getSaveFileName(self,
                                               caption   = 'Select the file to save log',
                                               directory = self.log_file.value(),
                                               filter    = '*.txt'
                                               ))
        if path == '':
            logger.debug('Log saving is cancelled.')
            return
        self.log_file.setValue(path)
        logger.info('Log saved in: %s' % str(path))


    #def save_log_total_in_file(self):
    #    logger.info('save_log_total_in_file' + self.fname_log_total, self._name)
    #    logger.save_log_total_in_file(self.fname_log_total)


    def append_qwlogger(self, msg='...'):
        """Append ``msg`` to the text box and scroll to the end."""
        self.edi_txt.append(msg)
        self.scrollDown()


    def scrollDown(self):
        #logger.debug('scrollDown')
        #scrol_bar_v = self.edi_txt.verticalScrollBar() # QScrollBar
        #scrol_bar_v.setValue(scrol_bar_v.maximum())
        """Move the text box cursor to the end and repaint it."""
        self.edi_txt.moveCursor(QTextCursor.End)
        self.edi_txt.repaint()
        #self.raise_()
        #self.edi_txt.update()


if __name__ == "__main__":
    import sys
    from psana.pyalgos.generic.PSConfigParameters import PSConfigParameters

    cp = PSConfigParameters()

    app = QApplication(sys.argv)
    w = QWLoggerStd(cp)
    w.setWindowTitle(w._name)
    w.setGeometry(200, 400, 600, 300)

    from psana.graphqt.QWIcons import icon # should be imported after QApplication
    icon.set_icons()
    w.setWindowIcon(icon.icon_logviewer)

    w.show()
    app.exec_()
    sys.exit(0)

# EOF
