#!/usr/bin/env python

"""Standalone PyQt5 screen-grabber application in a single module.

Contains a list-based ``Logger``, file-dialog helpers, ``Parameter`` and ``ConfigParameters`` classes, the ``GUILogger`` log window, the ``GUIImage`` image label and the ``GUIScreenGrabber`` main widget. Importing the module creates the module-level ``logger`` and ``cp`` objects; ``cp`` reads 'confpars-screen-grabber.txt' from the current directory if that file exists.
"""
import sys
import os
import pwd
import tempfile
from time import localtime, strftime
import PyQt5.QtCore as QtCore
from PyQt5.QtGui     import QColor, QPen, QPainter, QPalette, QPixmap, QImage, QBitmap,\
                            QIcon, QTextCursor
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QComboBox, QCheckBox,\
                            QPushButton, QFileDialog, QMessageBox, QTextEdit, QHBoxLayout,\
                            QVBoxLayout, QFrame, QSizePolicy, QGridLayout

class Logger:
    """Is intended as a log-book keeper.
    """
    name = 'Logger'

    def __init__ (self, fname=None, level='info'):
        """Constructor.
        - param fname  the file name for output log file
        """
        self.levels = ['debug','info','warning','error','crytical']
        self.setLevel(level)
        self.selectionIsOn = True # It is used to get total log content

        self.log = []
        self.startLog(fname)


    def setLevel(self, level):
        """Sets the threshold level of messages for record selection algorithm"""
        self.level_thr     = level
        self.level_thr_ind = self.levels.index(level)


    def getListOfLevels(self):
        """Return the list of level names ('debug', 'info', 'warning', 'error', 'crytical')."""
        return self.levels


    def getLevel(self):
        """Return the current threshold level name."""
        return self.level_thr


    def getLogFileName(self):
        """Return the log file name set by ``startLog``."""
        return self.fname


    def getLogTotalFileName(self):
        """Return the total-log file name set by ``startLog``."""
        return self.fname_total


    def getStrStartTime(self):
        """Return the session start time string set by ``startLog``."""
        return self.str_start_time


    def debug   (self, msg, name=None):
        """Record ``msg`` at level 'debug' (index 0) with optional source ``name``."""
        self._message(msg, 0, name)
    def info    (self, msg, name=None):
        """Record ``msg`` at level 'info' (index 1) with optional source ``name``."""
        self._message(msg, 1, name)
    def warning (self, msg, name=None):
        """Record ``msg`` at level 'warning' (index 2) with optional source ``name``."""
        self._message(msg, 2, name)
    def error   (self, msg, name=None):
        """Record ``msg`` at level 'error' (index 3) with optional source ``name``."""
        self._message(msg, 3, name)
    def crytical(self, msg, name=None):
        """Record ``msg`` at level 'crytical' (index 4) with optional source ``name``."""
        self._message(msg, 4, name)

    def _message (self, msg, index, name=None):
        """Store input message the 2D tuple of records, send request to append GUI.
        """
        tstamp    = self.timeStamp()
        level     = self.levels[index]
        rec       = [tstamp, level, index, name, msg]
        self.log.append(rec)

        if self.recordIsSelected(rec):
            str_msg = self.stringForRecord(rec)
            self.appendGUILog(str_msg)
            #print str_msg


    def recordIsSelected(self, rec):
        """Apply selection algorithms for each record:
           returns True if the record is passed,
                   False - the record is discarded from selected log content.
        """
        if not self.selectionIsOn      : return True
        if rec[2] < self.level_thr_ind : return False
        else                           : return True


    def stringForRecord(self, rec):
        """Returns the strind presentation of the log record, which intrinsically is a tuple."""
        tstamp, level, index, name, msg = rec
        self.msg_tot = ''
        if name is not None:
            self.msg_tot  = tstamp
            self.msg_tot += ' (' + level + ') '
            self.msg_tot += name + ': '
        else:
            self.msg_tot += ': '
        self.msg_tot += msg
        return self.msg_tot


    def appendGUILog(self, msg=''):
        """Append message in GUI, if it is available"""
        try   : self.guilogger.appendGUILog(msg)
        except: pass


    def setGUILogger(self, guilogger):
        """Receives the reference to GUI"""
        self.guilogger = guilogger


    def timeStamp(self, fmt='%Y-%m-%d %H:%M:%S'): # '%Y-%m-%d %H:%M:%S %Z'
        """Return the current local time formatted with ``fmt`` (default '%Y-%m-%d %H:%M:%S')."""
        return strftime(fmt, localtime())


    def startLog(self, fname=None):
        """Logger initialization at start"""
        self.str_start_time = self.timeStamp(fmt='%Y-%m-%d-%H:%M:%S')
        if  fname == None:
            self.fname       = self.str_start_time + '-log.txt'
            self.fname_total = self.str_start_time + '-log-total.txt'
        else:
            self.fname       = fname
            self.fname_total = self.fname + '-total'

        self.info ('Start session log file: ' + self.fname,       self.name)
        self.debug('Total log file name: '    + self.fname_total, self.name)


    def getLogContent(self):
        """Return the text content of the selected log records"""
        self.log_txt = ''
        for rec in self.log:
            if self.recordIsSelected(rec):
                self.log_txt += self.stringForRecord(rec) + '\n'
        return  self.log_txt


    def getLogContentTotal(self):
        """Return the text content of all log records"""
        self.selectionIsOn = False
        log_txt = self.getLogContent()
        self.selectionIsOn = True
        return log_txt


    def saveLogInFile(self, fname=None):
        """Save content of the selected log records in the text file"""
        if fname == None: fname_log = self.fname
        else            : fname_log = fname
        self._saveTextInFile(self.getLogContent(), fname_log)


    def saveLogTotalInFile(self, fname=None):
        """Save content of all log records in the text file"""
        if fname == None: fname_log = self.fname_total
        else            : fname_log = fname
        self._saveTextInFile(self.getLogContentTotal(), fname_log)


    def _saveTextInFile(self, text, fname='log.txt'):
        self.debug('saveTextInFile: ' + fname, self.name)
        f=open(fname,'w')
        f.write(text)
        f.close()


logger = Logger (fname=None)


def test_Logger():

    #logger.setLevel('debug')
    """Set the module logger to level 'warning', record one message at each level and print the selected and total log content."""
    logger.setLevel('warning')

    logger.debug   ('This is a test message 1', __name__)
    logger.info    ('This is a test message 2', __name__)
    logger.warning ('This is a test message 3', __name__)
    logger.error   ('This is a test message 4', __name__)
    logger.crytical('This is a test message 5', __name__)
    logger.crytical('This is a test message 6')

    #logger.saveLogInFile()
    #logger.saveLogTotalInFile()

    print('getLogContent():\n',      logger.getLogContent())
    print('getLogContentTotal():\n', logger.getLogContentTotal())


#------ GlobalUtils.py -------

def stringOrNone(value):
    """Return 'None' if ``value`` is None, otherwise ``str(value)``."""
    if value == None: return 'None'
    else            : return str(value)

def intOrNone(value):
    """Return None if ``value`` is None, otherwise ``int(value)``."""
    if value == None: return None
    else            : return int(value)


def get_save_fname_through_dialog_box(parent, path0, dial_title, filter='*.txt'):

    """Open a save-file dialog and return the selected path.

    Parameters
    ----------
    parent : QWidget or None
        Dialog parent.
    path0 : str
        Initial directory or file path.
    dial_title : str
        Dialog caption.
    filter : str
        File filter, default '*.txt'.

    Returns
    -------
    str or None
        The selected path, or None (logged) if the dialog was cancelled.
    """
    path,filt = QFileDialog.getSaveFileName(parent,
                                caption   = dial_title,
                                directory = path0,
                                filter    = filter
                               )
    if path == '':
        logger.debug('Saving is cancelled.', 'get_save_fname_through_dialog_box')
        #print('Saving is cancelled.')
        return None
    logger.info('Output file: ' + path, 'get_save_fname_through_dialog_box')
    #print('Output file: ' + path)
    return path


def get_open_fname_through_dialog_box(parent, path0, dial_title, filter='*.txt'):

    """Open an open-file dialog and return the selected path.

    Returns None (with an info log) if the directory or file part of the selected path is empty, for example when the dialog is cancelled.

    Returns
    -------
    str or None
    """
    path, filt = QFileDialog.getOpenFileName(parent, dial_title, path0, filter=filter)
    dname, fname = os.path.split(path)
    if dname == '' or fname == '':
        logger.info('Input directiry name or file name is empty... keep file path unchanged...')
        #print('Input directiry name or file name is empty... keep file path unchanged...')
        return None
    logger.info('Input file: ' + path, 'get_open_fname_through_dialog_box')
    #print('Input file: ' + path)
    return path


def confirm_dialog_box(parent=None, text='Please confirm that you aware!', title='Please acknowledge'):
        """Pop-up MODAL box for confirmation"""

        mesbox = QMessageBox(parent, windowTitle=title,
                                           text=text,
                                           standardButtons=QMessageBox.Ok)
        style = "background-color: rgb(255, 255, 220); color: rgb(0, 0, 0);" # Yellowish
        mesbox.setStyleSheet (style)

        clicked = mesbox.exec_() # DISPLAYS THE QMessageBox HERE

        logger.info('You acknowkeged that saw the message:\n' + text, 'confirm_dialog_box')
        return


def help_dialog_box(parent=None, text='Help message goes here', title='Help'):
        """Pop-up NON-MODAL box for help etc."""

        messbox = QMessageBox(parent, windowTitle=title,
                              text=text,
                              standardButtons=QMessageBox.Close)
        messbox.setStyleSheet (cp.styleBkgd)
        messbox.setWindowModality (QtCore.Qt.NonModal)
        messbox.setModal (False)
        #clicked = messbox.exec_() # For MODAL dialog
        clicked = messbox.show()  # For NON-MODAL dialog
        logger.info('Help window is open' + text, 'help_dialog_box')
        return messbox


class Parameter:
    """Single parameters.
    #@see OtherClass ConfigParameters
    #@see OtherClass ConfigParametersForApp
    """

    dicBool = {'false':False, 'true':True}

    _name      = 'EMPTY'
    _type      = None
    _value     = None
    _value_def = None
    _index     = None


    def __init__ (self, name='EMPTY', val=None, val_def=None, type='str', index=None):
        """Constructor.
        - param name    parameter name
        - param val     parameter value
        - param val_def parameter default value
        - param type    parameter type, implemented types: 'str', 'int', 'long', 'float', 'bool'
        - param index   parameter index the list
        """
        self.setParameter (name, val, val_def, type, index)


    def setParameter (self, name='EMPTY', val=None, val_def=None, type='str', index=None):
        """Set the default value, name, type and index of the parameter, then set its value with ``setValue(val)``."""
        self._value_def = val_def
        self._name      = name
        self._type      = type
        self._index     = index
        self.setValue (val)


    def setValue (self, val=None):
        """Set the parameter value, converting ``val`` according to the declared type.

        If ``val`` is None the default value is used. Types 'str', 'int', 'float' and 'bool' use the matching built-in; type 'long' calls ``long``, which does not exist in Python 3; any other type stores ``val`` unchanged.
        """
        if val == None:
            self._value = self._value_def
        else:
            if   self._type == 'str':
                self._value = str(val)

            elif self._type == 'int':
                self._value = int(val)

            elif self._type == 'long':
                self._value = long(val)

            elif self._type == 'float':
                self._value = float(val)

            elif self._type == 'bool':
                self._value = bool(val)
            else:
                self._value = val


    def setDefaultValue (self):
        """Reset the parameter value to its default value."""
        self._value = self._value_def


    def setDefault (self):
        """Reset the parameter value to its default value (same as ``setDefaultValue``)."""
        self._value = self._value_def


    def setValueFromString (self, str_val):
        """Set parameter value fron string based on its declared type: 'str', 'int', 'long', 'float', 'bool' """

        if str_val.lower() == 'none':
            self._value = self._value_def

        if self._type == 'str':
            self._value = str(str_val)

        elif self._type == 'int':
            self._value = int(str_val)

        elif self._type == 'long':
            self._value = long(str_val)

        elif self._type == 'float':
            self._value = float(str_val)

        elif self._type == 'bool':
            self._value = self.dicBool[str_val.lower()]

        else:
            msg = 'Parameter.setValueForType: Requested parameter type ' + type + ' is not supported\n'
            msg+= 'WARNING! The parameter value is left unchanged...\n'
            logger.warning(msg)
            #print(msg)


    def setType (self, type='str'):
        """Set the declared parameter type string."""
        self._type = type

    def setName (self, name='EMPTY'):
        """Set the parameter name."""
        self._name = name

    def value (self):
        """Return the current parameter value."""
        return self._value

    def value_def (self):
        """Return the parameter default value."""
        return self._value_def

    def name (self):
        """Return the parameter name."""
        return self._name

    def type (self):
        """Return the declared parameter type string."""
        return self._type

    def index(self):
        """Return the parameter index (None unless declared in a list)."""
        return self._index


    def strParInfo(self):
        """Return a one-line string with the parameter name, value, type and index in padded columns."""
        s = 'Par: %s %s %s %s' % (self.name().ljust(32), str(self.value()).ljust(32), self.type().ljust(8), str(self.index()).ljust(8))
        return s


    def printParameter(self):
        """Log the ``strParInfo()`` line at info level through the module logger."""
        s = self.strParInfo()
        logger.info(s)
        #print(s)


class ConfigParameters:
    """Is intended as a storage for configuration parameters.
    #@see OtherClass ConfigParametersCorana
    """

    name = 'ConfigParameters'

    dict_pars  = {} # Dictionary for all configuration parameters, containing pairs {<parameter-name>:<parameter-object>, ... }
    dict_lists = {} # Dictionary for declared lists of configuration parameters:    {<list-name>:<list-of-parameters>, ...}

    def __init__ (self, fname=None):
        """Constructor.
        - param fname  the file name with configuration parameters, if not specified then it will be set to the default value at declaration.
        """

        self.fname_cp = 'confpars.txt'


    def declareParameter(self, name='EMPTY', val=None, val_def=None, type='str', index=None):
        """Create a ``Parameter``, store it in the class-level ``dict_pars`` under ``name`` and return it."""
        par = Parameter(name, val, val_def, type, index)
        #self.dict_pars[name] = par
        self.dict_pars.update({name:par})
        return par


    def declareListOfPars(self, list_name='EMPTY_LIST', list_val_def_type=None):
        """Declare a list of parameters named '<list_name>:<index>'.

        Each record of ``list_val_def_type`` is a (val, val_def, type) tuple; every created ``Parameter`` is added to ``dict_pars`` and the list is stored in ``dict_lists`` under ``list_name``.

        Returns
        -------
        list of Parameter or None
            The created parameters, or None if ``list_val_def_type`` is None.
        """
        list_of_pars = []

        if list_val_def_type == None: return None

        for index,rec in enumerate(list_val_def_type):
            name = list_name + ':' + str(index)
            val, val_def, type = rec

            #par = self.declareParameter(name, val, val_def, type, index)
            par = Parameter(name, val, val_def, type, index)
            list_of_pars.append(par)
            self.dict_pars.update({name:par})

        self.dict_lists.update({list_name:list_of_pars})

        return list_of_pars


    def getListOfPars(self, name):
        """Return the parameter list stored in ``dict_lists`` under ``name``; raises KeyError if it was not declared."""
        return self.dict_lists[name]


    def printListOfPars(self, name):
        """Print the list name and log every parameter of that list."""
        list_of_pars = self.getListOfPars(name)

        print('Parameters for list:', name)
        for par in list_of_pars:
            par.printParameter()


    def printParameters(self):
        """Log the number of declared parameters and one ``strParInfo`` line per parameter."""
        msg = 'printParameters - Number of declared parameters in the dict: %d' % len(self.dict_pars)
        logger.info(msg, self.name)
        #print(msg)

        for par in self.dict_pars.values():
            s = par.strParInfo()
            logger.info(s)
            #print(s)


    def setDefaultValues(self):
        """Reset every declared parameter to its default value."""
        for par in self.dict_pars.values():
            par.setDefaultValue()


    def setParsFileName(self, fname=None):
        """Set ``self.fname`` to ``fname``, or to ``self.fname_cp`` if ``fname`` is None."""
        if fname == None:
            self.fname = self.fname_cp
        else:
            self.fname = fname


    def saveParametersInFile (self, fname=None):
        """Write every declared parameter as a 'name value' line to a text file.

        The file name is chosen by ``setParsFileName(fname)``.
        """
        self.setParsFileName(fname)
        logger.info('Save configuration parameters in file: ' + self.fname, self.name)
        f=open(self.fname,'w')
        for par in self.dict_pars.values():
            v = par.value()
            s = '%s %s\n' % (par.name().ljust(32), str(v))
            f.write(s)
        f.close()


    def setParameterValueByName (self, name, str_val):

        """Set a declared parameter from a string with ``setValueFromString``.

        If ``name`` is not declared, log a warning and return without change.
        """
        if not (name in self.dict_pars.keys()):
            msg  = 'The parameter name ' + name + ' is unknown in the dictionary.\n'
            msg += 'WARNING! Parameter needs to be declared first. Skip this parameter initialization.\n'
            logger.warning(msg)
            #print(msg)
            return

        self.dict_pars[name].setValueFromString(str_val)


    def readParametersFromFile (self, fname=None):
        """Read 'name value' lines from the configuration file and set the matching parameters.

        The file name is chosen by ``setParsFileName(fname)``; if the file does not exist a debug message is logged and defaults are kept. Single-character lines are skipped.
        """
        self.setParsFileName(fname)
        msg = 'Read configuration parameters from file: ' + self.fname
        logger.info(msg, self.name)
        #print(msg)

        if not os.path.exists(self.fname):
            msg = 'The file ' + self.fname + ' is not found, use default parameters.'
            logger.debug(msg, self.name)
            #print(msg)
            return

        f=open(self.fname,'r')
        for line in f:
            if len(line) == 1: continue # line is empty
            fields = line.rstrip('\n').split(' ',1)
            self.setParameterValueByName (name=fields[0], str_val=fields[1].strip(' '))
        f.close()


def usage():
    """Log a usage message for the command line.

    The function refers to ``self.name`` although it is a module-level function, so calling it raises NameError.
    """
    msg  = 'Use command: ' + sys.argv[0] + ' [<configuration-file-name>]\n'
    msg += 'with a single or without arguments.'
    msg = '\n' + 51*'-' + '\n' + msg + '\n' + 51*'-'
    logger.warning(msg, self.name)
    #print(msg)


def getConfigFileFromInput():
    """DO NOT PARSE INPUT PARAMETERS IN THIS APPLICATION
    This is interfere with other applications which really need to use input pars,
    for example maskeditor...
    """

    return None

    msg = 'Input pars sys.argv: '
    for par in sys.argv:  msg += par
    logger.debug(msg, self.name)
    #print(msg)

    if len(sys.argv) > 2:
        usage()
        msg  = 'Too many arguments ...\n'
        msg += 'EXIT application ...\n'
        sys.exit (msg)

    elif len(sys.argv) == 1:
        return None

    else:
        path = sys.argv[1]
        if os.path.exists(path):
            return path
        else:
            usage()
            msg  = 'Requested configuration file "' + path + '" does not exist.\n'
            msg += 'EXIT application ...\n'
            sys.exit (msg)


class ConfigParametersForApp (ConfigParameters):
    """Is intended as a storage for configuration parameters for CorAna project.
    #@see BaseClass ConfigParameters
    #@see OtherClass Parameters
    """
    name = 'ConfigParametersForApp'

    list_pars = []

    def __init__ (self, fname=None):
        """Constructor.
        - param fname  the file name with configuration parameters, if not specified then it will be set to the default value at declaration.
        """
        ConfigParameters.__init__(self)
        self.fname_cp = 'confpars-screen-grabber.txt' # Re-define default config file name

        self.declareAllParameters()
        self.readParametersFromFile (fname)
        self.initRunTimeParameters()
        self.defineStyles()

    def initRunTimeParameters(self):
        """Initialize run-time attributes: ``iconsAreLoaded`` False and ``guilogger``, ``guihelp`` None."""
        self.iconsAreLoaded  = False
        #self.char_expand = u' \u25BE' # down-head triangle
        self.guilogger = None
        self.guihelp   = None


    def setIcons(self):

        """Load QIcon objects from the 'icons/' directory next to ``sys.argv[0]``, once.

        Sets attributes such as ``icon_save``, ``icon_exit`` and ``icon_monitor``, and the aliases ``icon_logger``, ``icon_help`` and ``icon_reset``; returns immediately if icons are already loaded.
        """
        if self.iconsAreLoaded: return

        self.iconsAreLoaded = True

        path = "%s/icons/" % os.path.dirname(sys.argv[0])

        logger.info('Load icons from directory: '+path, self.name)

        self.icon_contents      = QIcon(path + 'contents.png'     )
        self.icon_mail_forward  = QIcon(path + 'mail-forward.png' )
        self.icon_button_ok     = QIcon(path + 'button_ok.png'    )
        self.icon_button_cancel = QIcon(path + 'button_cancel.png')
        self.icon_exit          = QIcon(path + 'exit.png'         )
        self.icon_home          = QIcon(path + 'home.png'         )
        self.icon_redo          = QIcon(path + 'redo.png'         )
        self.icon_undo          = QIcon(path + 'undo.png'         )
        self.icon_reload        = QIcon(path + 'reload.png'       )
        self.icon_save          = QIcon(path + 'save.png'         )
        self.icon_save_cfg      = QIcon(path + 'fileexport.png'   )
        self.icon_edit          = QIcon(path + 'edit.png'         )
        self.icon_browser       = QIcon(path + 'fileopen.png'     )
        self.icon_monitor       = QIcon(path + 'icon-monitor.png' )
        self.icon_unknown       = QIcon(path + 'icon-unknown.png' )
        self.icon_logviewer     = QIcon(path + 'logviewer.png'    )
        self.icon_lock          = QIcon(path + 'locked-icon.png'  )
        self.icon_unlock        = QIcon(path + 'unlocked-icon.png')

        self.icon_logger        = self.icon_edit
        self.icon_help          = self.icon_unknown
        self.icon_reset         = self.icon_reload


    def declareAllParameters(self):
        # Possible typs for declaration: 'str', 'int', 'long', 'float', 'bool'

        # GUILogger.py
        """Declare the application parameters LOG_LEVEL_OF_MSGS, LOG_FILE_NAME, CBX_SHOW_MORE_OPTIONS, IMG_INPUT_FNAME and IMG_OUTPUT_FNAME with their defaults."""
        self.log_level      = self.declareParameter(name='LOG_LEVEL_OF_MSGS',  val_def='info',         type='str')
        self.log_file       = self.declareParameter(name='LOG_FILE_NAME',      val_def='./log_screem_grabber.txt',   type='str')
        #self.log_file_total = self.declareParameter(name='LOG_FILE_TOTAL',     val_def='./log_total.txt',           type='str')

        # GUIGrabSubmitELog.py
        self.cbx_more_options    = self.declareParameter(name='CBX_SHOW_MORE_OPTIONS',   val_def=False,             type='bool')
        self.img_infname         = self.declareParameter(name='IMG_INPUT_FNAME',  val_def='./img-1.ppm',            type='str')
        self.img_oufname         = self.declareParameter(name='IMG_OUTPUT_FNAME', val_def='./img-1.png',            type='str')


    def defineStyles(self):
        """Define Qt style-sheet strings (backgrounds, text colors, button and status styles) and three QColor attributes."""
        self.styleYellowish = "background-color: rgb(255, 255, 220); color: rgb(0, 0, 0);" # Yellowish
        self.stylePink      = "background-color: rgb(255, 200, 220); color: rgb(0, 0, 0);" # Pinkish
        self.styleYellowBkg = "background-color: rgb(255, 255, 120); color: rgb(0, 0, 0);" # Pinkish
        self.styleGreenMy   = "background-color: rgb(150, 250, 230); color: rgb(0, 0, 0);" # My
        self.styleGray      = "background-color: rgb(230, 240, 230); color: rgb(0, 0, 0);" # Gray
        self.styleGreenish  = "background-color: rgb(100, 255, 200); color: rgb(0, 0, 0);" # Greenish
        self.styleGreenPure = "background-color: rgb(150, 255, 150); color: rgb(0, 0, 0);" # Green
        self.styleBluish    = "background-color: rgb(200, 200, 255); color: rgb(0, 0, 0);" # Bluish
        self.styleWhite     = "background-color: rgb(255, 255, 255); color: rgb(0, 0, 0);"
        self.styleRedBkgd   = "background-color: rgb(255,   0,   0); color: rgb(0, 0, 0);" # Red background
        self.styleTransp    = "background-color: rgb(255,   0,   0, 100);"
        self.styleBlue   = "color: rgb(000, 000, 255);"
        self.styleBuriy  = "color: rgb(150, 100, 50);"
        self.styleRed    = "color: rgb(255, 0, 0);"
        self.styleGreen  = "color: rgb(0, 150, 0);"
        self.styleYellow = "color: rgb(0, 150, 150);"

        self.styleBkgd         = self.styleGreenMy # styleYellowish
        self.styleTitle        = self.styleBuriy
        self.styleLabel        = self.styleBlue
        self.styleEdit         = self.styleWhite
        self.styleEditInfo     = self.styleBkgd # self.styleGreenish
        self.styleEditBad      = self.styleRedBkgd
        self.styleButton       = self.styleGray
        self.styleButtonOn     = self.styleBluish
        self.styleButtonClose  = self.stylePink
        self.styleButtonWarning= self.styleYellowBkg
        self.styleButtonGood   = self.styleGreenPure
        self.styleButtonBad    = self.stylePink
        self.styleBox          = self.styleGray
        self.styleCBox         = self.styleYellowish
        self.styleStatusGood   = self.styleGreen
        self.styleStatusWarning= self.styleYellow
        self.styleStatusAlarm  = self.styleRed
        self.styleTitleBold    = self.styleTitle + 'font-size: 18pt; font-family: Courier; font-weight: bold;'
        self.styleWhiteFixed   = self.styleWhite + 'font-family: Fixed;'

        self.colorEditInfo     = QColor(100, 255, 200)
        self.colorEditBad      = QColor(255,   0,   0)
        self.colorEdit         = QColor('white')

    def printParsDirectly(self):
        """Log the name and value of ``self.fname_ped`` and ``self.fname_dat``.

        These attributes are not declared in this class, so the call raises AttributeError.
        """
        logger.info('Direct use of parameter:' + self.fname_ped.name() + ' ' + self.fname_ped.value(), self.name)
        logger.info('Direct use of parameter:' + self.fname_dat.name() + ' ' + self.fname_dat.value(), self.name)


confpars = ConfigParametersForApp ()
cp = confpars


def test_ConfigParametersForApp():
    """Log all parameters of the module ``confpars`` object and save them to its default file."""
    confpars.printParameters()
    #confpars.printParsDirectly()
    confpars.saveParametersInFile()


class GUILogger(QWidget):
    """GUI for Logger"""

    name = 'GUILogger'

    def __init__(self, parent=None):

        QWidget.__init__(self, parent)

        self.setGeometry(200, 400, 900, 500)
        self.setWindowTitle('GUI Logger')
        self.setWindowIcon(cp.icon_logger)

        self.setFrame()

        self.box_txt    = QTextEdit()

        #self.tit_title  = QLabel('Logger')
        self.tit_status = QLabel('Status:')
        self.tit_level  = QLabel('Verbosity level:')
        self.but_close  = QPushButton('&Close')
        self.but_save   = QPushButton('&Save log-file')

        self.list_of_levels = logger.getListOfLevels()
        self.box_level = QComboBox(self)
        self.box_level.addItems(self.list_of_levels)
        self.box_level.setCurrentIndex(self.list_of_levels.index(cp.log_level.value()))

        self.hboxM = QHBoxLayout()
        self.hboxM.addWidget(self.box_txt)

        self.hboxB = QHBoxLayout()
        self.hboxB.addWidget(self.tit_status)
        self.hboxB.addStretch(4)
        self.hboxB.addWidget(self.tit_level)
        self.hboxB.addWidget(self.box_level)
        self.hboxB.addStretch(1)
        self.hboxB.addWidget(self.but_save)
        self.hboxB.addWidget(self.but_close)

        self.vbox = QVBoxLayout()
        self.vbox.addLayout(self.hboxM)
        self.vbox.addLayout(self.hboxB)
        self.setLayout(self.vbox)

        self.but_close.clicked.connect(self.onClose)
        self.but_save .clicked.connect(self.onSave)
        self.box_level.currentIndexChanged[int].disconnect(self.onBox)

        self.startGUILog()

        self.showToolTips()
        self.setStyle()


    def showToolTips(self):
        #self           .setToolTip('This GUI is for browsing log messages')
        """Set tool tips on the text box, buttons, status label and level combo box."""
        self.box_txt    .setToolTip('Window for log messages')
        self.but_close  .setToolTip('Close this window')
        self.but_save   .setToolTip('Save current content of the GUI Logger\nin work directory file: '+os.path.basename(self.fname_log))
        self.tit_status .setToolTip('The file name, where this log \nwill be saved at the end of session')
        self.box_level  .setToolTip('Click on this button and \nselect the level of messages \nwhich will be displayed')


    def setFrame(self):
        """Create a sunken box QFrame covering the widget rectangle and store it in ``self.frame``."""
        self.frame = QFrame(self)
        self.frame.setFrameStyle(QFrame.Box | QFrame.Sunken)
        self.frame.setLineWidth(0)
        self.frame.setMidLineWidth(1)
        self.frame.setGeometry(self.rect())
        #self.frame.setVisible(False)


    def setStyle(self):
        """Apply the ``cp`` style sheets to the widget, labels, buttons and combo box, and make the text box read-only."""
        self.           setStyleSheet (cp.styleBkgd)
        #self.tit_title.setStyleSheet (cp.styleTitleBold)
        self.tit_status.setStyleSheet (cp.styleTitle)
        self.tit_level .setStyleSheet (cp.styleTitle)
        self.but_close .setStyleSheet (cp.styleButton)
        self.but_save  .setStyleSheet (cp.styleButton)
        self.box_level .setStyleSheet (cp.styleButton)
        self.box_txt   .setReadOnly(True)
        self.box_txt   .setStyleSheet (cp.styleWhiteFixed)


    def setParent(self,parent):
        """Store ``parent`` in ``self.parent``; Qt parenting is not changed."""
        self.parent = parent


    def resizeEvent(self, e):
        #logger.debug('resizeEvent', self.name)
        """Resize ``self.frame`` to the widget rectangle."""
        self.frame.setGeometry(self.rect())


    def moveEvent(self, e):
        #logger.debug('moveEvent', self.name)
        #cp.posGUIMain = (self.pos().x(),self.pos().y())
        """Do nothing; the body is ``pass``."""
        pass


    def closeEvent(self, event):
        """Log a debug message; the event is not passed to the base class."""
        logger.debug('closeEvent', self.name)


    def onClose(self):
        """Log a debug message and close the window.

        Connected to the Close button.
        """
        logger.debug('onClose', self.name)
        self.close()


    def onSave(self):
        """Log a debug message and call ``saveLogInFile``.

        Connected to the 'Save log-file' button.
        """
        logger.debug('onSave:', self.name)
        self.saveLogInFile()


    def onBox(self):
        """Apply the level selected in the combo box.

        Stores it in ``cp.log_level``, sets the module logger threshold and reloads the text box with the selected log content. ``__init__`` calls ``disconnect`` (not ``connect``) for this slot, so it is not connected to the combo box.
        """
        level_selected = self.box_level.currentText()
        cp.log_level.setValue(level_selected)
        logger.info('onBox - selected ' + self.tit_level.text() + ' ' + cp.log_level.value(), self.name)
        logger.setLevel(cp.log_level.value())
        self.box_txt.setText(logger.getLogContent())


    def saveLogInFile(self):
        """Ask for a file name and save the selected log records there.

        On cancel it logs and returns; otherwise it saves through ``logger.saveLogInFile``, updates ``self.fname_log`` and ``cp.log_file`` and shows the file name in the status label.
        """
        logger.info('saveLogInFile ' + self.fname_log, self.name)
        path,filt = QFileDialog.getSaveFileName(self,
                                               caption   = 'Select the file to save log',
                                               directory = self.fname_log,
                                               filter    = '*.txt'
                                              )
        if path == '':
            logger.debug('Saving is cancelled.', self.name)
            return
        logger.info('Output file: ' + path, self.name)
        logger.saveLogInFile(path)
        self.fname_log = path
        cp.log_file.setValue(path)
        self.setStatus(0, 'Log-file: ' + os.path.basename(self.fname_log))


    def saveLogTotalInFile(self):
        """Save all log records to ``self.fname_log_total``.

        ``fname_log_total`` is never assigned in this class (the line in ``startGUILog`` is commented out), so this raises AttributeError unless set externally.
        """
        logger.info('saveLogTotalInFile' + self.fname_log_total, self.name)
        logger.saveLogTotalInFile(self.fname_log_total)


    def getConfirmation(self):
        """Pop-up box for confirmation"""
        msg = QMessageBox(self, windowTitle='Confirm closing!',
            text='You are about to close GUI Logger...\nIf the log-file is not saved it will be lost.',
            standardButtons=QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        msg.setDefaultButton(msg.Save)

        clicked = msg.exec_()

        if   clicked == QMessageBox.Save:
            logger.info('Saving is requested', self.name)
        elif clicked == QMessageBox.Discard:
            logger.info('Discard is requested', self.name)
        else:
            logger.info('Cancel is requested', self.name)
        return clicked


    def onShow(self):
        """Log that the method is not implemented; does nothing else."""
        logger.info('onShow - is not implemented yet...', self.name)


    def startGUILog(self):
        #self.fname_log = cp.log_file.value()
        """Initialize the log view.

        Sets ``self.fname_log`` from ``logger.fname``, shows it in the status label, applies ``cp.log_level`` to the logger, fills the text box with the selected log content and registers this widget as the logger's GUI.
        """
        self.fname_log = logger.fname

        #self.fname_log_total = cp.log_file_total.value()
        self.setStatus(0, 'Log-file: ' + os.path.basename(self.fname_log))

        logger.setLevel(cp.log_level.value())
        self.box_txt.setText(logger.getLogContent())

        logger.setGUILogger(self)
        logger.debug('GUILogger is open', self.name)
        self.box_txt.moveCursor(QTextCursor.End)


    def appendGUILog(self, msg='...'):
        """Append ``msg`` to the text box and scroll to the end."""
        self.box_txt.append(msg)
        self.scrollDown()


    def scrollDown(self):
        """Move the text box cursor to the end and repaint it."""
        self.box_txt.moveCursor(QTextCursor.End)
        self.box_txt.repaint()


    def setStatus(self, status_index=0, msg=''):
        """Set the status label text to ``msg`` and its style by ``status_index`` (0 good, 1 warning, 2 alarm; other values keep the style)."""
        list_of_states = ['Good','Warning','Alarm']
        if status_index == 0: self.tit_status.setStyleSheet(cp.styleStatusGood)
        if status_index == 1: self.tit_status.setStyleSheet(cp.styleStatusWarning)
        if status_index == 2: self.tit_status.setStyleSheet(cp.styleStatusAlarm)
        self.tit_status.setText(msg)


def test_GUILogger():
    """Create a QApplication, show a ``GUILogger`` and run the event loop."""
    app = QApplication(sys.argv)
    widget = GUILogger()
    widget.show()
    app.exec_()


class GUIImage(QLabel):
    """Main GUI of the Screen Grabber
    """

    name = 'GUIImage'

    def __init__ (self, parent=None, app=None):

        self.myapp = app
        QLabel.__init__(self, parent)

        self.setGeometry(200, 100, 100, 100)
        self.setWindowTitle('Image For Grabber')
        self.palette = QPalette()
        self.resetColorIsSet = False

        self.setFrame()

        self.poi1  = QtCore.QPoint(0,0)
        self.poi2  = QtCore.QPoint(0,0)
        self.rect1 = QtCore.QRect()
        self.rect2 = QtCore.QRect()

        self.pen1 = QPen(QtCore.Qt.black)
        self.pen2 = QPen(QtCore.Qt.white)
        self.pen1.setStyle(QtCore.Qt.DashLine)
        self.pen2.setStyle(QtCore.Qt.DashLine)
        self.pen1.setWidthF(1)
        self.pen2.setWidthF(1)


        self.o_pixmap_list = [] # list of old pixmap
        self.r_pixmap = None # raw pixmap
        self.s_pixmap = None # scailed for image pixmap

        self.qp = QPainter()
        #self.pixmap_item = None
        self.counter = 0

        self.showToolTips()
        self.setStyle()


    def grabImage(self):
        """Grab a screen region with the external ImageMagick ``import`` command and display it.

        Runs ``import -trim -frame -border`` into a temporary .xpm file via ``os.system``; if the command returns 0 the file is loaded into ``r_pixmap`` and shown.
        """
        fname = tempfile.NamedTemporaryFile(mode='r+b',suffix='.xpm')
        #print(fname.name)
        #logger.info('Use temporary file: %s' % (fname.name), self.name)
        if(0 == os.system('import -trim -frame -border %s' % (fname.name))):
            self.r_pixmap = QPixmap(QImage(fname.name,'XPM'))
            self.setPixmapForImage()


    def grabEntireWindow(self):
        """Grab the desktop window with ``QPixmap.grabWindow``, store it in ``r_pixmap`` and display it."""
        self.r_pixmap = QPixmap.grabWindow(QApplication.desktop().winId())
        self.setPixmapForImage()


    def resetImage(self):
        """Clear ``r_pixmap`` and the displayed image."""
        self.r_pixmap = None
        self.setPixmapForImage()


    def loadImageFromFile(self, fname): #Read formats: bmp, jpg, jpeg, png, ppm, xbm, xpm + gif, pbm, pgm,
        """Load image file ``fname`` into ``r_pixmap`` and display it."""
        self.r_pixmap = QPixmap(QImage(fname))
        self.setPixmapForImage()


    def setPixmapForImage(self):
        """Display ``r_pixmap`` scaled to the label size, keeping the aspect ratio.

        If ``r_pixmap`` is None the scaled pixmap is set to None and the label is cleared; otherwise the scaled pixmap is aligned top-left and ``setScailedMask`` is called.
        """
        if self.r_pixmap == None:
            self.s_pixmap = None
            self.clear()
        else:
            #self.s_pixmap = self.r_pixmap.scaled(self.size())
            self.s_pixmap = self.r_pixmap.scaled(self.size(), QtCore.Qt.KeepAspectRatio)
            self.setPixmap(self.s_pixmap)
            self.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
            self.setScailedMask()


    def setScailedMask(self):
        """Create an all-zero monochrome mask with the size of the scaled pixmap and set it on ``s_pixmap``."""
        size = self.s_pixmap.size()
        #print('Scaled pixmap size: %d x %d' % (size.width(), size.height()))

        self.qimage_mask = QImage(size, QImage.Format_Mono)
        self.qimage_mask.fill(0)
        self.qbitmap_mask = QBitmap.fromImage(self.qimage_mask)
        self.s_pixmap.setMask(self.qbitmap_mask)


    def saveImageInFile(self, fname='test.png'): #Write formats: bmp, jpg, jpeg, png, pbm, pgm, ppm, xbm, xpm
        """Save ``r_pixmap`` to ``fname`` (default 'test.png') if it is not None."""
        if self.r_pixmap is not None:
            self.r_pixmap.save(fname, format=None)


    def showToolTips(self):
        """Set the label tool tip to 'Window for image'."""
        self.setToolTip('Window for image')


    def setFrame(self):
        """Create a transparent sunken box QFrame covering the label and store it in ``self.frame``."""
        self.frame = QFrame(self)
        self.frame.setFrameStyle(QFrame.Box | QFrame.Sunken)
        self.frame.setLineWidth(0)
        self.frame.setMidLineWidth(1)
        self.frame.setGeometry(self.rect())
        #self.frame.setVisible(False)
        self.frame.setStyleSheet('background: transparent;')


    def setStyle(self):
        """Apply the white style sheet, a 150x150 minimum size and an expanding size policy."""
        self               .setStyleSheet(cp.styleWhite)
        self.setMinimumSize(150, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)


    def resizeEvent(self, e):
        """Resize ``self.frame`` to the label size and redisplay the scaled image."""
        s = self.size()
        self.frame.setGeometry(QtCore.QRect(0,0,s.width(),s.height()))
        self.setPixmapForImage()
        #self.update()
        #print('resizeEvent')


    def onExit(self):
        #logger.debug('onExit', self.name)
        """Close the label widget."""
        self.close()


    def mouseMoveEvent(self, e):
        #print('mouseMoveEvent: x, y = %d, %d' % (e.pos().x(), e.pos().y()))
        """Store the mouse position in ``self.poi2``."""
        self.poi2.setX(e.pos().x())
        self.poi2.setY(e.pos().y())

        #self.line.setLine(0, 0, e.pos().x(), e.pos().y())
        #self.line.setP2(pos)
        #self.rect.setCoords(5, 5, e.pos().x(), e.pos().y())
        #self.update()

    def mousePressEvent(self, e):
        """Store the press position in ``poi1`` and ``poi2``.

        If the button value is 4 (Qt.MiddleButton) and earlier pixmaps are stored, the last one is popped back into ``r_pixmap`` and displayed (undo zoom).
        """
        if e.button() == 4 and len(self.o_pixmap_list)>0: # Undo last zoom-in
            self.r_pixmap = self.o_pixmap_list.pop()
            self.setPixmapForImage()
        #else: self.o_pixmap_list = []


        self.poi1.setX(e.pos().x())
        self.poi1.setY(e.pos().y())
        self.poi2.setX(e.pos().x())
        self.poi2.setY(e.pos().y())
        #print('mousePressEvent: e.x, e.y, e.button =', str(e.x()), str(e.y()), str(e.button()))


    def mouseReleaseEvent(self, e):
        """Store the release position in ``poi2`` and call ``zoomInImage``."""
        self.poi2.setX(e.pos().x())
        self.poi2.setY(e.pos().y())
        #print('mouseReleaseEvent: e.x, e.y, e.button =', str(e.x()), str(e.y()), str(e.button()))
        self.zoomInImage()


    def zoomInImage(self):
        """Crop ``r_pixmap`` to the rectangle between ``poi1`` and ``poi2`` and display it.

        The points are reset first; nothing is cropped if there is no image or the rectangle is under 10 pixels in either direction. The previous pixmap is pushed to ``o_pixmap_list``, which keeps at most 10 entries.
        """
        if self.r_pixmap == None:
            self.resetRectPoints()
            return

        s_size = self.s_pixmap.size()
        r_size = self.r_pixmap.size()
        sw, sh = s_size.width(), s_size.height()
        rw, rh = r_size.width(), r_size.height()
        sclx, scly = float(rw)/sw, float(rh)/sh

        p1x, p1y = self.poi1.x(), self.poi1.y()
        p2x, p2y = self.poi2.x(), self.poi2.y()

        self.resetRectPoints()

        if p2x < 0 : p2x = 0
        if p2y < 0 : p2y = 0
        if p2x > sw: p2x = sw
        if p2y > sh: p2y = sh

        R=10
        if abs(p2x-p1x) < R: return
        if abs(p2y-p1y) < R: return

        #print('zoomInImage: p1: x, y = %d, %d' % (p1x, p1y))
        #print('zoomInImage: p2: x, y = %d, %d' % (p2x, p2y))

        x1, y1, x2, y2 = int(p1x*sclx), int(p1y*scly), int(p2x*sclx), int(p2y*scly)
        #print('zoomInImage: x1, y1, x2, y2  = %d, %d, %d, %d' % (x1, y1, x2, y2))

        xmin, xmax = min(x1, x2), max(x1, x2)
        ymin, ymax = min(y1, y2), max(y1, y2)
        self.o_pixmap_list.append(self.r_pixmap)
        self.r_pixmap = self.r_pixmap.copy(xmin, ymin, xmax-xmin, ymax-ymin)
        self.setPixmapForImage()
        # return and remove the oldest list, Keeps 10 latest images only.
        if len(self.o_pixmap_list) > 10: list = self.o_pixmap_list.pop(0)


    def resetRectPoints(self):
        """Set ``poi1`` and ``poi2`` to (0, 0)."""
        self.poi1.setX(0)
        self.poi1.setY(0)
        self.poi2.setX(0)
        self.poi2.setY(0)


    def paintEvent(self, e):
        """Paint the label, then draw the selection rectangle with ``drawRect`` and call ``self.update()``.

        Calling ``update()`` inside ``paintEvent`` schedules another repaint each time.
        """
        super(GUIImage,self).paintEvent(e)
        #self.counter+=1
        #print(self.counter)
        #qp = QtGui.QPainter()
        qp = self.qp
        qp.begin(self)
        #self.drawPixmap(qp)
        self.drawRect(qp)
        qp.end()
        self.update()


    def setPen(self, qp):
        """Set dash style and width 1 on ``self.pen``.

        ``self.pen`` is never assigned in this class, so the call raises AttributeError; ``qp`` is unused.
        """
        self.pen.setStyle(QtCore.Qt.DashLine)
        self.pen.setWidthF(1)


    def drawRect(self, qp):
        """Draw the selection rectangle between ``poi1`` and ``poi2`` with ``qp``.

        Draws a black dashed rectangle and a white dashed one inset by 1 pixel; does nothing if there is no image or the points coincide in x or y.
        """
        if self.r_pixmap == None:
            return

        p1x, p1y = self.poi1.x(), self.poi1.y()
        p2x, p2y = self.poi2.x(), self.poi2.y()

        R=1
        if abs(p2x-p1x) < R: return
        if abs(p2y-p1y) < R: return

        self.rect1.setCoords(p1x,   p1y,   p2x,   p2y)
        self.rect2.setCoords(p1x+1, p1y+1, p2x-1, p2y-1)
        qp.setPen  (self.pen1)
        qp.drawRect(self.rect1);
        qp.setPen  (self.pen2)
        qp.drawRect(self.rect2);


    def drawPixmap(self, qp):
        """Draw ``s_pixmap`` at (0, 0) with ``qp`` if ``r_pixmap`` is not None."""
        if self.r_pixmap != None:
            qp.drawPixmap(0,0,self.s_pixmap)


#http://doc.qt.nokia.com/4.6/qt.html#Key-enum
    def keyPressEvent(self, event):
        #print('event.key() = %s' % (event.key()))
        """Set ``self.SHowIsOn = False`` on Esc; the B, Return and Home branches do nothing."""
        if event.key() == QtCore.Qt.Key_Escape:
            #self.close()
            self.SHowIsOn = False
            pass

        if event.key() == QtCore.Qt.Key_B:
            #print('event.key() = %s' % (QtCore.Qt.Key_B))
            pass

        if event.key() == QtCore.Qt.Key_Return:
            #print('event.key() = Return')
            pass

        if event.key() == QtCore.Qt.Key_Home:
            #print('event.key() = Home')
            pass


def test_GUIImage():
    """Create a QApplication, show a ``GUIImage`` with a grab of the desktop window and run the event loop."""
    app = QApplication(sys.argv)
    ex  = GUIImage()
    ex.grabEntireWindow()
    ex.show()
    app.exec_()


class LocalParameter ():
    """This helper class allows to access local parameters through the reference in the list."""
    _val=None

    def __init__ (self, val=None):
        self._val = val

    def setValue (self, val):
        """Set the stored value to ``val``."""
        self._val = val

    def getValue (self):
        """Return the stored value."""
        return self._val

    def value (self):
        """Return the stored value."""
        return self._val


class GUIScreenGrabber(QWidget):
    """GUI sets fields for ScreenGrabber"""

    name = 'GUIScreenGrabber' # for logger

    def __init__ (self, parent=None, cfname=None, ifname=None, ofname=None, help_msg=None):
        QWidget.__init__(self)
        self.setGeometry(50, 10, 500, 500)
        self.setWindowTitle('Screen Grabber')
        self.setFrame()

        self.setConfigPars(cfname)

        if ifname is None: self.ifname = cp.img_infname.value()
        else             : self.ifname = ifname

        if ofname is None: self.ofname = cp.img_oufname.value()
        else             : self.ofname = ofname

        self.parent    = parent

        if help_msg==None: self.help_msg = self.help_message()
        else             : self.help_msg = help_msg

        cp.printParameters()

        self.wimg    = GUIImage(self)

        self.cbx_more = QCheckBox('More options', self)
        self.cbx_more.setChecked(cp.cbx_more_options.value())

        #self.box_tag  = QtGui.QComboBox(self)
        #self.box_tag.addItems(self.list_of_tags)
        #self.box_tag.setCurrentIndex(0) # self.list_of_tags.index(cp.elog_post_tag.value()))

        self.lab_status   = QLabel('ScreenGrabber is started')
        #self.lab_status  = QLineEdit('Last submitted message ID: ' + self.res.value())
        #self.lab_status  = QPushButton('Last submitted message ID: ' + self.res.value())

        self.but_grab     = QPushButton('Grab')
        self.but_load     = QPushButton('Load')
        self.but_clear    = QPushButton('Clear')
        self.but_save     = QPushButton('Save img')
        self.but_logger   = QPushButton('Logger')
        self.but_help     = QPushButton('&Help')
        self.but_quit     = QPushButton('&Exit')
        self.but_save_cfg = QPushButton('Save cfg')

        self.setHBox1Layout()
        self.setHBox2Layout()

        #self.edi_res.setValidator(QtGui.QIntValidator(0,9000000,self))

        self.grid = QGridLayout()
        self.grid_row = 0
        self.grid.addWidget(self.lab_status, self.grid_row, 0, 1, 3)

        self.vbox2 = QVBoxLayout()
        self.vbox2.addLayout(self.grid)
        self.vbox2_widg = QWidget(self)
        self.vbox2_widg.setLayout(self.vbox2)
        self.vbox2_widg.setFixedHeight(50)

        self.vbox = QVBoxLayout()
        self.vbox.addLayout(self.hbox1)
        #self.vbox.addLayout(self.vbox2)
        self.vbox.addWidget(self.vbox2_widg)
        self.vbox.addWidget(self.wimg)
        self.vbox.addLayout(self.hbox2)

        self.setLayout(self.vbox)

        self.but_grab    .clicked.connect(self.on_but_grab   )
        self.but_clear   .clicked.connect(self.on_but_clear  )
        self.but_load    .clicked.connect(self.on_but_load   )
        self.but_save    .clicked.connect(self.on_but_save   )
        self.but_logger  .clicked.connect(self.on_but_logger )
        self.but_help    .clicked.connect(self.on_but_help   )
        self.but_quit    .clicked.connect(self.on_but_quit   )
        self.but_save_cfg.clicked.connect(self.on_but_save_cfg)

        self.cbx_more.stateChanged[int].connect(self.on_cbx_more)

        self.setIcons()
        self.setStyle()
        self.on_cbx_more()
        self.set_but_save_visibility()
        self.setToolTips()

        self.setStatus(0, 'Status: started')


    def setConfigPars(self, cfname):
        """Read configuration parameters from ``cfname`` if given.

        If ``cfname`` is None it returns. Otherwise it sets ``cp.fname_cp`` and ``self.cfname`` to it and reads the file if it exists.
        """
        if cfname is None:
            return # use default config parameters
        else:
            cp.fname_cp = self.cfname = cfname # in order to save parameters at exit
            logger.info('Re-define cofiguration pars from file: '+cfname, self.name)
            if os.path.exists(cfname):
                cp.readParametersFromFile(cfname)



    def setToolTips(self):

        """Log a message and set tool tips on the buttons and the check box."""
        logger.info('Set tool-tips for all fields', self.name)

        #self              .setToolTip('Screen grabber GUI')
        self.but_clear    .setToolTip('Clear image window')
        self.but_grab     .setToolTip('Grab image using mouse')
        self.but_load     .setToolTip('Load image from file')
        self.but_save     .setToolTip('Save image in file')
        self.but_save_cfg .setToolTip('Save current configuration \nparameters in file')
        self.but_logger   .setToolTip('Open/Close logger window')
        self.but_quit     .setToolTip('Exit this application')
        self.but_help     .setToolTip('Open/Close  help window')
        self.cbx_more     .setToolTip('Show more control buttons')



    def setIcons(self):
        """Load the ``cp`` icons and set them on the buttons."""
        cp.setIcons()
        self.but_load    .setIcon(cp.icon_browser)
        self.but_save    .setIcon(cp.icon_save)
        self.but_save_cfg.setIcon(cp.icon_save_cfg)
        self.but_grab    .setIcon(cp.icon_monitor)
        self.but_clear   .setIcon(cp.icon_reset)
        self.but_logger  .setIcon(cp.icon_contents)
        self.but_help    .setIcon(cp.icon_help)
        self.but_quit    .setIcon(cp.icon_exit)


    def setHBox1Layout(self):
        """Create ``self.hbox1`` with the Grab, Load and Clear buttons, a stretch and the Save button."""
        self.hbox1 = QHBoxLayout()
        self.hbox1.addWidget(self.but_grab)
        self.hbox1.addWidget(self.but_load)
        self.hbox1.addWidget(self.but_clear)
        self.hbox1.addStretch(1)
        self.hbox1.addWidget(self.but_save)
        #self.setLayout(self.hbox1)


    def setHBox2Layout(self):
        """Create ``self.hbox2`` with the check box, Help and Logger buttons, a stretch, and the Save cfg and Exit buttons."""
        self.hbox2 = QHBoxLayout()
        self.hbox2.addWidget(self.cbx_more)
        self.hbox2.addWidget(self.but_help)
        self.hbox2.addWidget(self.but_logger)
        self.hbox2.addStretch(1)
        self.hbox2.addWidget(self.but_save_cfg)
        self.hbox2.addWidget(self.but_quit)
        #self.setLayout(self.hbox2)


    def setFrame(self):
        """Create a sunken box QFrame covering the widget rectangle and store it in ``self.frame``."""
        self.frame = QFrame(self)
        self.frame.setFrameStyle(QFrame.Box | QFrame.Sunken)
        self.frame.setLineWidth(0)
        self.frame.setMidLineWidth(1)
        self.frame.setGeometry(self.rect())
        #self.frame.setVisible(False)


    def setStyle(self):
        #self.setMinimumWidth(400)
        #self.setMinimumHeight(320)
        #self.setFixedHeight(350)
        """Set a 500x500 minimum size and apply the ``cp`` style sheets to the widget, buttons and check box."""
        self.setMinimumSize(500, 500)

        self.setStyleSheet(cp.styleBkgd)

        self.but_grab    .setStyleSheet (cp.styleButton)
        self.but_clear   .setStyleSheet (cp.styleButton)
        self.but_load    .setStyleSheet (cp.styleButton)
        self.but_save    .setStyleSheet (cp.styleButton)
        self.but_logger  .setStyleSheet (cp.styleButtonBad)
        self.but_help    .setStyleSheet (cp.styleButton)
        self.but_save_cfg.setStyleSheet (cp.styleButton)
        self.but_quit    .setStyleSheet (cp.styleButtonBad)
        self.cbx_more    .setStyleSheet (cp.styleLabel)


    def setParent(self,parent):
        """Store ``parent`` in ``self.parent``; Qt parenting is not changed."""
        self.parent = parent


    def resizeEvent(self, e):
        #logger.debug('resizeEvent', self.name)
        """Resize ``self.frame`` to the widget rectangle."""
        self.frame.setGeometry(self.rect())


    def moveEvent(self, e):
        """Do nothing; the body is ``pass``."""
        pass


    def closeEvent(self, event):
        """Close and clear ``cp.guilogger`` and ``cp.guihelp`` if they are open.

        The event is not passed to the base class.
        """
        logger.debug('closeEvent', self.name)
        if  cp.guilogger != None:
            cp.guilogger.close()
            #del cp.guilogger
            cp.guilogger = None

        if  cp.guihelp   != None:
            cp.guihelp.close()
            #del cp.guihelp
            cp.guihelp = None

        #try   : cp.guilogger.close()
        #except: pass


    def on_but_quit(self):
        """Log a debug message and close the widget.

        Connected to the Exit button.
        """
        logger.debug('on_but_quit', self.name)
        #self.on_but_save_cfg()
        self.close()


    def set_but_save_visibility(self):
        """Show the 'Save img' button only if the image widget holds a pixmap."""
        if self.wimg.r_pixmap is None:
            self.but_save.setVisible(False)
        else:
            self.but_save.setVisible(True) # self.cbx_more.isChecked())


    def on_cbx_more(self):
        """Apply the 'More options' check box state.

        Shows or hides the Logger, Help and Save cfg buttons, stores the state in ``cp.cbx_more_options`` and updates the status label.
        """
        is_visible = self.cbx_more.isChecked()
        dic_stat = {False:'less', True:'more'}

        msg = 'Show %s options' % (dic_stat[is_visible])
        logger.info('Check box status is changed: '+msg, self.name)
        self.setStatus(0, msg)
        cp.cbx_more_options.setValue(is_visible)

        self.but_logger  .setVisible(is_visible)
        self.but_help    .setVisible(is_visible)
        self.but_save_cfg.setVisible(is_visible)


    def on_but_grab(self):
        """Grab a screen region into the image widget with ``wimg.grabImage()`` and update the Save button and status label."""
        logger.info('Grab image from monitor', self.name)

        if self.wimg != None:
            self.setStatus(1, 'Waiting for image grabbing by the mouse...')
            self.wimg.grabImage()
            self.set_but_save_visibility()

            self.setStatus(0, 'Image is grabbed')
        else:
            self.setStatus(1, 'Image is NOT grabbed')


    def on_but_clear(self):
        """Clear the image widget, hide the Save button and update the status label."""
        logger.info('Clear image', self.name)
        self.wimg.resetImage()
        self.set_but_save_visibility()
        self.setStatus(0, 'Image is cleared')


    def on_but_load(self):
        """Ask for an image file and load it into the image widget.

        On cancel it sets a warning status and returns; otherwise it updates ``self.ifname``, ``cp.img_infname``, the status label and the Save button visibility.
        """
        logger.info('Select file name and Load image from file', self.name)
        self.setStatus(1, 'Waiting for file name...')
        path = get_open_fname_through_dialog_box(self, self.ifname, 'Select file with text image',
                                                 filter='*.ppm *.bmp *.jpg *.jpeg *.png *.xbm *.xpm *.gif *.pbm *.pgm')
        if path == None or path == '':
            logger.info('File name is empty, loading is cancelled...', self.name)
            self.setStatus(1, 'File loading is cancelled...')
            return

        self.wimg.loadImageFromFile(path)
        self.ifname = path
        cp.img_infname.setValue(path)

        msg = 'Loaded image from file: ' + os.path.basename(path)
        logger.info(msg, self.name)
        self.setStatus(0, msg)

        self.set_but_save_visibility()


    def on_but_save(self):

        """Ask for a file name and save the raw image there.

        Returns with a warning log if there is no image or the dialog is cancelled; otherwise it saves via ``wimg.saveImageInFile`` and updates ``self.ofname`` and ``cp.img_oufname``.
        """
        if self.wimg.r_pixmap is None:
            path = ''
            logger.warning('Image is empty, there is nothing to save. Saving is cancelled...', self.name)
            return

        self.setStatus(1, 'Waiting for file name...')

        path0 = self.ofname
        #dir, fname = os.path.split(path0)
        path, filt  = QFileDialog.getSaveFileName(self,
                            caption='Select file to save the plot',
                            directory = path0,
                            filter = 'Images (*.ppm *.bmp *.jpg *.jpeg *.png *.pbm *.pgm *.xbm *.xpm)'
                     )
        #print('XXX in on_but_save path=', path)

        if path == '':
            logger.warning('File name is empty, saving is cancelled.', self.name)
            return

        msg = 'Save image in file: ' + os.path.basename(path)
        logger.info(msg, self.name)
        self.setStatus(0, msg)

        self.wimg.saveImageInFile(path)
        self.ofname = path
        cp.img_oufname.setValue(path)


    def on_but_save_cfg(self):
        """Ask for a file name and save the configuration parameters there.

        On cancel it logs a warning and sets the status; otherwise it calls ``cp.saveParametersInFile(path)`` and sets ``cp.fname_cp`` to the path.
        """
        logger.debug('on_but_save_cfg',  self.name)
        #cp.elog_post_tag.setValue(self.tag.value())
        #cp.elog_post_des.setValue(self.des.value())


        self.setStatus(1, 'Waiting for file name...')
        path = cp.fname_cp
        #dir, fname = os.path.split(path)
        path,filt  = QFileDialog.getSaveFileName(self,
                                            caption='Select config. file',
                                            directory = path,
                                            filter = '*.txt'
                                           )
        if path == '':
            logger.warning('File name is empty, saving is cancelled.', self.name)
            self.setStatus(1, 'Saving of config file is cancelled...')
            return

        msg = 'Save config. pars in file: ' + os.path.basename(path)
        logger.info(msg, self.name)
        self.setStatus(0, msg)

        cp.saveParametersInFile(path)
        cp.fname_cp = path


    def on_but_logger (self):
        """Toggle the ``GUILogger`` window stored in ``cp.guilogger``.

        If it is open it is closed and cleared; otherwise a new one is created, placed to the right of this widget and shown. The button style and status label are updated.
        """
        logger.debug('on_but_logger',  self.name)
        #try :
        if cp.guilogger!=None:
            cp.guilogger.close()
            self.but_logger.setStyleSheet(cp.styleButtonBad)
            cp.guilogger=None
            msg = 'Logger window is closed'
            logger.info(msg, self.name)
            self.setStatus(0, msg)
        #except:
        else:
            self.but_logger.setStyleSheet(cp.styleButtonGood)
            cp.guilogger = GUILogger()
            cp.guilogger.move(self.pos().__add__(QtCore.QPoint(self.size().width()+10,0))) # open window with offset w.r.t. parent
            cp.guilogger.show()
            msg = 'Logger window is open'
            logger.info(msg, self.name)
            self.setStatus(0, msg)


    def on_but_help(self):
        """Toggle the non-modal help message box stored in ``cp.guihelp`` and update the status label."""
        msg = str(self.help_msg)
        if  cp.guihelp is None:
            cp.guihelp = help_dialog_box(self, text=msg)
            self.setStatus(0, 'Help window is open')
        else:
            cp.guihelp.close()
            #del cp.guihelp
            cp.guihelp = None
            self.setStatus(0, 'Help window is closed')

        #logger.info('Help message:' + msg, self.name)
        #print(msg)


    def help_message(self):
        """Return the default help text describing the mouse controls and the Clear button."""
        msg  = '\n' + '='*60
        msg += '\nMouse control functions in graphical window:'
        msg += '\nZoom-in image: left/right mouse button click, move, and release in another image position.'
        msg += '\nUndo:          middle mouse button click on image - undo up to 10 latest zoom-ins.'
        msg += '\n"Clear" button - clears the image.'
        return msg


    def setStatus(self, ind=None, msg=''):
        """Set the status label text to ``str(msg)`` and its style by ``ind`` (0 good, 1 warning, 2 alarm), then repaint."""
        if   ind == 0: self.lab_status.setStyleSheet(cp.styleStatusGood)
        elif ind == 1: self.lab_status.setStyleSheet(cp.styleStatusWarning)
        elif ind == 2: self.lab_status.setStyleSheet(cp.styleStatusAlarm)
        self.lab_status.setText(str(msg))
        self.enforceStatusRepaint()

    def enforceStatusRepaint(self):
        """Repaint the status label and the widget immediately."""
        self.lab_status.repaint()
        self.repaint()


def test_GUIScreenGrabber():
    """Create a QApplication, show a ``GUIScreenGrabber`` and run the event loop."""
    app = QApplication(sys.argv)
    widget = GUIScreenGrabber()
    widget.show()
    app.exec_()


from optparse import OptionParser

def input_option_parser():

    """Parse the command line options -c/--cfg, -i/--inp and -o/--out with optparse.

    Returns
    -------
    tuple
        ``(opts, args)`` from ``OptionParser.parse_args()``.
    """
    parser = OptionParser(description='Optional input parameters.', usage ='usage: %prog [options] args')
    parser.add_option('-c', '--cfg', dest='cfname', default=None, action='store', type='string', help='file name with configuration parameters')
    parser.add_option('-i', '--inp', dest='ifname', default=None, action='store', type='string', help='input file name with image')
    parser.add_option('-o', '--out', dest='ofname', default=None, action='store', type='string', help='output file name with image')

    (opts, args) = parser.parse_args()
    return (opts, args)


def run_GUIScreenGrabber():

    """Parse the command line, show a ``GUIScreenGrabber`` with the given file names, run the event loop and print an exit message."""
    (opts, args) = input_option_parser()

    app = QApplication(sys.argv)
    w = GUIScreenGrabber(cfname=opts.cfname, ifname=opts.ifname, ofname=opts.ofname)
    w.show()
    app.exec_()
    print('Exit application...')


if __name__ == "__main__":
    run_GUIScreenGrabber()
    sys.exit (0)

# EOF
