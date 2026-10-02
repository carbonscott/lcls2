
#--------------------------------
"""
:py:class:`ConfigParameters` - base class for application configuration parameters
==========================================================================================

Usage ::

   from psdaq.control_gui.CConfigParameters import ConfigParameters

   class PSConfigParameters(ConfigParameters) :
       def __init__(self, fname=None) :
           ConfigParameters.__init__(self)

           self.instr_dir       = self.declareParameter(name='INSTRUMENT_DIR',  val_def='/reg/d/psdm', type='str') 
           self.instr_name      = self.declareParameter(name='INSTRUMENT_NAME', val_def='SXR',         type='str')
           self.exp_name        = self.declareParameter(name='EXPERIMENT_NAME', val_def='Select',      type='str') # sxr12316'
           self.str_runnum      = self.declareParameter(name='STR_RUN_NUMBER',  val_def='Select',      type='str')
 
   def test_PSConfigParameters() :
        #from expmon.Logger import log
        #log.setPrintBits(0377)

        cpb = PSConfigParameters()

        p = cpb.instr_dir.value()
        cpb.instr_dir.setValue(v)

        cpb.readParametersFromFile()
        cpb.printParameters()
        cpb.saveParametersInFile()

See:
    - :py:class:`ConfigParameters`
    - `matplotlib <https://matplotlib.org/contents.html>`_.

This software was developed for the LCLS2 project.
If you use all or part of it, please give an appropriate acknowledgment.


Created on 2017-02-18 by Mikhail Dubrovin
Adopted for LCLS2 on 2018-02-12
Copied to psdaq/control_gui on 2019-06-18
"""
#--------------------------------

import os
import logging
logger = logging.getLogger(__name__)

#------------------------------

class Parameter :
    """Single parameters.
    """
    dicBool = {'false':False, 'true':True}

    _name      = 'EMPTY'
    _type      = None
    _value     = None
    _value_def = None
    _index     = None


    def __init__(self, name='EMPTY', val=None, val_def=None, type='str', index=None) :
        """Constructor.
        - name    parameter name
        - val     parameter value
        - val_def parameter default value
        - type    parameter type, implemented types: 'str', 'int', 'long', 'float', 'bool'
        - index   parameter index the list
        """
        self.setParameter(name, val, val_def, type, index) 


    def setParameter(self, name='EMPTY', val=None, val_def=None, type='str', index=None) :
        """Set the default value, name, type and index, then set the value with `setValue(val)`."""
        self._value_def = val_def
        self._name      = name
        self._type      = type
        self._index     = index
        self.setValue(val)


    def setValue(self, val=None) :
        """Set the value, converting it according to the declared type.

        None sets the default value. Types 'str', 'int', 'float' and 'bool' use the matching
        built-in; 'long' calls `long`, which is undefined in Python 3 (NameError); any other
        type stores `val` unchanged.
        """
        if val is None :
            self._value = self._value_def
        else :
            if   self._type == 'str' :
                self._value = str(val)
        
            elif self._type == 'int' :
                self._value = int(val)
        
            elif self._type == 'long' :
                self._value = long(val)
        
            elif self._type == 'float' :
                self._value = float(val)
        
            elif self._type == 'bool' :
                self._value = bool(val)
            else : 
                self._value = val


    def setDefaultValue(self) :
        """Set the value to the default value."""
        self._value = self._value_def


    def setDefault(self) :
        """Set the value to the default value."""
        self._value = self._value_def


    def setValueFromString(self, str_val) :
        """Set parameter value fron string based on its declared type: 'str', 'int', 'long', 'float', 'bool' """

        if str_val.lower() == 'none' :
            self._value = self._value_def

        elif self._type == 'str' :
            self._value = str(str_val)

        elif self._type == 'int' :
            self._value = int(str_val)

        elif self._type == 'long' :
            self._value = long(str_val)

        elif self._type == 'float' :
            self._value = float(str_val)

        elif self._type == 'bool' :
            self._value = self.dicBool[str_val.lower()]

        else :
            msg = 'Parameter.setValueForType: Requested parameter type %s is not supported\n' % type
            msg+= 'WARNING! The parameter value is left unchanged...\n'
            logger.warning(msg)
            #print(msg)


    def setType(self, type='str') :
        """Set the parameter type string (default 'str')."""
        self._type = type


    def setName(self, name='EMPTY') :
        """Set the parameter name (default 'EMPTY')."""
        self._name = name


    def value(self) :
        """Return the current value."""
        return self._value


    def value_def(self) :
        """Return the default value."""
        return self._value_def


    def is_default(self) :
        """Return True if the current value equals the default value."""
        return self._value == self._value_def


    def name(self) :
        """Return the parameter name."""
        return self._name


    def type(self) :
        """Return the parameter type string."""
        return self._type


    def index(self) :
        """Return the parameter index."""
        return self._index


    def strParInfo(self) :
        """Return a one-line 'Par: <name> <value> <type> <index>' string with padded columns."""
        s = 'Par: %s %s %s %s' % (self.name().ljust(32), str(self.value()).ljust(32), self.type().ljust(8), str(self.index()).ljust(8))
        return s


    def printParameter(self) :
        """Log `strParInfo()` at info level."""
        s = self.strParInfo()
        logger.info(s)
        #print(s)


    def __cmp__(self, other) :
        """used in list.sort()"""
        #print('In __cmp__ comparing', self._name, other._name)
        if self._name  < other._name : return -1
        if self._name  > other._name : return  1
        if self._name == other._name : return  0

#------------------------------
#------------------------------

class ConfigParameters :
    """Is intended as a storage for configuration parameters.
    """

    dict_pars  = {} # Dictionary for all configuration parameters, containing pairs {<parameter-name>:<parameter-object>, ... } 
    dict_lists = {} # Dictionary for declared lists of configuration parameters:    {<list-name>:<list-of-parameters>, ...}

    def __init__(self, fname=None) :
        """Constructor.
           - fname - the file name with configuration parameters,
           if not specified then it will be set to the default value at declaration.
        """
        self.name = 'ConfigParameters' #self.__class__.__name__
        self.fname_cp = 'confpars.txt'


#    def __del__(self) :
#        logger.debug('XXX: In d-tor')
#        #print('XXX: In ConfigParameters d-tor')


    def declareParameter(self, name='EMPTY', val=None, val_def=None, type='str', index=None) :
        """Create a `Parameter`, store it in `dict_pars` under `name` and return it.

        `dict_pars` is a class attribute, so it is shared by all instances.
        """
        par = Parameter(name, val, val_def, type, index)
        #self.dict_pars[name] = par
        self.dict_pars.update({name:par})
        return par


    def declareListOfPars(self, list_name='EMPTY_LIST', list_val_def_type=None) :
        """Create one `Parameter` per (val, val_def, type) record and register them.

        Each parameter is named '<list_name>:<index as %03d>' and added to `dict_pars`; the
        list is stored in `dict_lists` under `list_name`.

        Returns
        -------
        list of Parameter or None
            The new parameters, or None if `list_val_def_type` is None.
        """
        list_of_pars = []

        if list_val_def_type is None : return None

        for index,rec in enumerate(list_val_def_type) :
            #name = list_name + ':' + str(index)
            name = '%s:%03d'%(list_name, index)
            val, val_def, type = rec

            #par = self.declareParameter(name, val, val_def, type, index)
            par = Parameter(name, val, val_def, type, index)
            list_of_pars.append(par)
            self.dict_pars.update({name:par})

        self.dict_lists.update({list_name:list_of_pars})
        return list_of_pars


    def getListOfPars(self, name) :
        """Return the parameter list registered under `name` in `dict_lists` (KeyError if absent)."""
        return self.dict_lists[name]


    def printListOfPars(self, name) :
        """Print a header for list `name` and log each of its parameters."""
        list_of_pars = self.getListOfPars(name)

        print('Parameters for list:', name)
        for par in list_of_pars :
            par.printParameter()


    def printParameters(self) :
        """Log `getTextParameters()` at info level."""
        msg = self.getTextParameters()
        logger.info(msg)


    def getTextParameters(self) :
        """Return the number of declared parameters followed by one `strParInfo()` line per parameter."""
        txt = 'Number of declared parameters: %d\n' % len(self.dict_pars)
        lpars = list(self.dict_pars.values())
        #lpars.sort() # sort "in situ" - it does not return anything so can't use it any other way....
        list_of_recs = [par.strParInfo() for par in lpars]
        return txt + '  ' + '\n  '.join(list_of_recs)


    def setDefaultValues(self) :
        """Reset every declared parameter to its default value."""
        for par in self.dict_pars.values() :
            par.setDefaultValue()


    def setParsFileName(self, fname=None) :
        """Set `self.fname` to `fname`, or to `fname_cp` ('confpars.txt') if `fname` is None."""
        if fname is None :
            self.fname = self.fname_cp
        else :
            self.fname = fname


    def getParsFileName(self) :
        """Return `self.fname` (set by `setParsFileName`)."""
        return self.fname


    def saveParametersInFile(self, fname=None) :
        """Write each parameter as '<name padded to 32> <value>' lines to the parameters file.

        The file name is set first with `setParsFileName(fname)`.
        """
        self.setParsFileName(fname)        
        logger.debug('Save configuration parameters in file: %s' % self.fname)
        f=open(self.fname,'w')

        lpars = list(self.dict_pars.values())
        #lpars.sort() # sort "in situ" - it does not return anything so can't use it any other way....
        for par in lpars :
            v = par.value()
            s = '%s %s\n' % (par.name().ljust(32), str(v))
            f.write(s)
        f.close() 


    def saveParametersInFileV0(self, fname=None) :
        """Write each parameter as '<name padded to 32> <value>' lines to the parameters file.

        Same output as `saveParametersInFile`; the file name is set with `setParsFileName(fname)`.
        """
        self.setParsFileName(fname)        
        logger.debug('Save configuration parameters in file: %s' % self.fname)
        f=open(self.fname,'w')
        for par in self.dict_pars.values() :
            v = par.value()
            s = '%s %s\n' % (par.name().ljust(32), str(v))
            f.write(s)
        f.close() 


    def setParameterValueByName(self, name, str_val) :

        """Set parameter `name` from the string `str_val` via `setValueFromString`.

        Logs a warning and does nothing if `name` was not declared.
        """
        if not (name in self.dict_pars.keys()) :
            msg  = 'The parameter name %s is unknown in the dictionary.\n' % name
            msg += 'WARNING! Parameter needs to be declared first. Skip this parameter initialization.\n' 
            logger.warning(msg)
            #print(msg)
            return

        self.dict_pars[name].setValueFromString(str_val)


    def readParametersFromFile(self, fname=None) :
        """Read '<name> <value>' lines from the parameters file and set the declared parameters.

        The file name is set with `setParsFileName(fname)`; if the file does not exist,
        nothing is changed. Lines of length 1 are skipped.
        """
        self.setParsFileName(fname)        
        msg = 'Read configuration parameters from file: ' + self.fname
        logger.debug(msg)

        if not os.path.exists(self.fname) :
            msg = 'The file %s is not found, use default parameters.' % self.fname
            logger.debug(msg)
            return
 
        f=open(self.fname,'r')
        for line in f :
            if len(line) == 1 : continue # line is empty
            fields = line.rstrip('\n').split(' ',1)
            self.setParameterValueByName(name=fields[0], str_val=fields[1].strip(' '))
        f.close() 

#------------------------------

def usage() :
    """Log a usage message as a warning.

    It uses `sys.argv`, but `sys` is not imported in this module, so calling it raises NameError.
    """
    msg  = 'Use command: %s [<configuration-file-name>]\n'\
           'with a single or without arguments.' % sys.argv[0]
    msg = '\n%s\n%s\n%s' % (51*'-', msg, 51*'-')
    logger.warning(msg)
    #print(msg)


def getConfigFileFromInput() :
    """DO NOT PARSE INPUT PARAMETERS IN THIS APPLICATION
    This is interfere with other applications which really need to use input pars,
    for example maskeditor...
    """
    return None

    msg = 'Input pars sys.argv: '
    for par in sys.argv :  msg += par
    logger.debug(msg)
    #print(msg)

    if len(sys.argv) > 2 : 
        usage()
        sys.exit('Too many arguments ...\nEXIT application ...\n')

    elif len(sys.argv) == 1 : 
        return None

    else :
        path = sys.argv[1]        
        if os.path.exists(path) :
            return path
        else :
            usage()
            msg  = 'Requested configuration file "%s" does not exist.\nEXIT application ...\n' % path
            sys.exit (msg)

#------------------------------
# confpars = ConfigParameters () # is moved
#------------------------------

