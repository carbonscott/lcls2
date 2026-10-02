#####!/usr/bin/env python
#------------------------------
"""Command ``proc_info``: print information about experiments and runs in xtc directories and the auto-processing status, using ``psana.pscalib.proc.RunProcUtils``."""
import os
import sys
from time import time
import psana.pscalib.proc.RunProcUtils as rpu
#import PSCalib.RunProcUtils as rpu

#------------------------------

def proc_info(parser) :
    """Parse the command line with ``parser`` and run the print mode given by the single positional argument (default ``'0'``).

    Modes call ``RunProcUtils`` functions: 0 ``print_all_experiments``, 1 ``print_datasets_new_under_control``,
    2 ``print_datasets_new``, 3 ``print_experiments``, 4 ``print_datasets_old``, 5
    ``print_experiments_count_runs`` (processor name ``'pixel_status'`` for 1, 2 and 4). An unknown mode calls
    ``sys.exit`` with a message; otherwise the elapsed time is printed.
    """
    (popts, pargs) = parser.parse_args()
    ins      = popts.ins
    procname = popts.pro
    app      = popts.app

    if app :
        print('arguments: %s' % str(pargs))
        print('options  : %s' % str(popts))

    INS = None if ins is None else ins.upper()
    t0_sec = time()

    tname = pargs[0] if len(pargs)==1 else '0'

    if   tname=='0' : rpu.print_all_experiments()
    elif tname=='1' : rpu.print_datasets_new_under_control(procname='pixel_status', add_to_log=app)
    elif tname=='2' : rpu.print_datasets_new(INS, procname='pixel_status', add_to_log=app)
    elif tname=='3' : rpu.print_experiments(INS) # all
    elif tname=='4' : rpu.print_datasets_old(INS, procname='pixel_status', move_to_archive=app)
    elif tname=='5' : rpu.print_experiments_count_runs()

    else : sys.exit ('Not recognized command "%s"' % tname)
    print('Command "%s" consumed time (sec) = %.3f' % (tname, time()-t0_sec))

    if len(sys.argv)<2 : print(usage())

#------------------------------

def usage() : 
    """Return the usage/help text listing the print modes and command examples."""
    return '\n  proc_info <arg> [-i <instrument-name> -p <process-name> -m]'\
           '\n    where argument switches between print modes:'\
           '\n    arg = 0 - print all experiments'\
           '\n        = 1 - print new datasets for experiments under control (in the list .../run_proc/<process-name>/experiments.txt)'\
           '\n        = 2 - print new datasets (not listed in the experiment log files)'\
           '\n        = 3 - print experiments'\
           '\n        = 4 - print old datasets removed from xtc directories'\
           '\n        = 5 - print about all experiments and runs available in xtc directories'\
           '\n\n  Command examples:'\
           '\n    proc_info 1'\
           '\n    proc_info 2'\
           '\n    proc_info 2 -a'\
           '\n    proc_info 2 -i CXI -p pixel_status'\
           '\n    proc_info 4'\
           '\n    proc_info 4 -a'\
           '\n'
 
#------------------------------

def input_option_parser() :

    """Return an ``optparse.OptionParser`` with options ``-i/--ins`` (instrument, default None), ``-p/--pro`` (processor name, default ``'pixel_status'``) and ``-a/--app`` (flag, default False)."""
    from optparse import OptionParser
    d_ins = None # 'CXI'
    d_pro = 'pixel_status'
    d_app = False

    h_ins = 'instrument name, default = %s' % d_ins
    h_pro = 'data processor name, default = %s' % d_pro
    h_app = 'append information about new rums in log files, default = %s' % d_app

    parser = OptionParser(description='Print info about experiments and runs in xtc directories and auto-processing status', usage=usage())
    parser.add_option('-i', '--ins', default=d_ins, action='store', type='string', help=h_ins)
    parser.add_option('-p', '--pro', default=d_pro, action='store', type='string', help=h_pro)
    parser.add_option('-a', '--app', default=d_app, action='store_true',           help=h_app)
 
    return parser

#------------------------------

def do_main() :

    """Build the option parser (printing help and a warning if no arguments are given), call :func:`proc_info` and exit with status 0."""
    parser = input_option_parser()

    if len(sys.argv) == 1 : 
        parser.print_help()
        print('WARNING: using ALL default parameters...')

    proc_info(parser)
    sys.exit(0)
  
#------------------------------

if __name__ == "__main__" :
    do_main()

#------------------------------
