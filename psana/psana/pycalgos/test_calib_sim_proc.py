#!/usr/bin/env python

"""Script: read timing text files from a hard-coded directory (one file per CPU, records 'num t,s: time dt,us: dt'), compute the median dt per file, plot each file's start and end time, and repeat the median within a common time window; the file name pattern is selected by the test number."""
import os
import sys
import logging
import numpy as np
from time import time
#import psana.detector.UtilsGraphics as ug
#gr = ug.gr
import psana.detector.Utils as ut
from psana.detector.NDArrUtils import info_ndarr

global STRLOGLEV # sys.argv[2] if len(sys.argv)>2 else 'INFO'
global INTLOGLEV # logging._nameToLevel[STRLOGLEV]
SCRNAME = sys.argv[0].rsplit('/')[-1]
logger = logging.getLogger(__name__)

#DIRNAME = '/sdf/home/d/dubrovin/LCLS/con-lcls2/2024-10-18-test-calib-mpi/'
#DIRNAME = '/sdf/home/d/dubrovin/LCLS/con-lcls2/2024-10-23-test-calib-mpi/'
DIRNAME = '/sdf/home/d/dubrovin/LCLS/con-lcls2/2024-10-29-test-calib-mpi/'

def parse_record(rec):
    """Return ``(num, time_s, dt_us)`` parsed from fields 0, 2 and 4 of record ``rec``, or None for an empty record."""
    if not rec: return None
    flds = rec.split()   # 484 t,s:   8480.583884 dt,us:       5207
    num, time_s, dt_us = int(flds[0]), float(flds[2]), int(flds[4])
    return num, time_s, dt_us


def number_of_records(recs):
    """Return the number of records in ``recs`` before the first empty one."""
    nrecs = 0
    for r in recs:
        if not r: break
        nrecs += 1
    return nrecs


def arr_records(recs):
    """Return an (n, 3) array of ``parse_record`` values for the first n non-empty records of ``recs`` (n from ``number_of_records``, which is also printed)."""
    nrecs = number_of_records(recs)
    print('number of records %d' % nrecs)
    arr3v = np.empty((nrecs,3))
    for i,r in enumerate(recs):
        #print('  %s' % r)
        flds = parse_record(r)
        if flds is None: break
        #print('  ', flds)
        arr3v[i,:] = flds
    return arr3v


def proc_file(fname, tmin=None, tmax=None):
    """Load the records of text file ``fname`` and return ``(dt_med, tmin, tmax, ntsel)``.

    ``tmin``/``tmax`` default to the minimum/maximum record time; ``dt_med`` is the median dt of records with time inside [tmin, tmax] and ``ntsel`` their count. Intermediate arrays are printed.
    """
    print('proc_ile: %s' % fname)
    s = ut.load_textfile(fname)
    recs = s.split('\n')
    arr_n_t_dt = arr_records(recs)
    rnums = arr_n_t_dt[:,0]
    times = arr_n_t_dt[:,1]
    dt_us = arr_n_t_dt[:,2]
    print(info_ndarr(rnums, 'rnums:'))
    print(info_ndarr(times, 'times:'))
    print(info_ndarr(dt_us, 'dt_us:'))
    _tmin = times.min() if tmin is None else tmin
    _tmax = times.max() if tmax is None else tmax
    print('tmin: %.6f tmax: %.6f' % (_tmin, _tmax))
    print('tmin: %.6f tmax: %.6f' % (times[0], times[-1]))
    dt_sel = [dt for dt,t in zip(dt_us, times) if t>=_tmin and t<=_tmax]
    print(info_ndarr(dt_sel, 'dt_sel:'))
    dt_med = np.median(dt_sel)
    ntsel = len(dt_sel)
    print('dt [us] median within [tmin, tmax] time range: %.6f number of selected times: %d' % (dt_med, ntsel))
    return dt_med, _tmin, _tmax, ntsel


#def plotGraph(x,y, figsize=(5,10), window=(0.15, 0.10, 0.78, 0.86), pfmt='b-', lw=1):
#    fig = plt.figure(figsize=figsize, dpi=80, facecolor='w', edgecolor='w', frameon=True)
#    ax = fig.add_axes(window)
#    ax.plot(x, y, pfmt, linewidth=lw)
#    return fig, ax

def plot_tmin_tmax(atmin, atmax, ptrn='-vNN.txt'):
    """Plot the start times ``atmin`` and end times ``atmax`` (relative to the earliest start) against the file index, show the figure, save it as an image in ``DIRNAME`` and return ``(tmin, tmax)`` (earliest start, latest end)."""
    import psana.detector.UtilsGraphics as ug
    gr = ug.gr

    tmin = atmin.min()
    tmax = atmax.max()
    ncpus = len(atmin)
    print('graphics tmin: %.6f tmax: %.6f ncpus: %d' % (tmin, tmax, ncpus))
    #fig, ax = gr.plotGraph(x,y, figsize=(5,10), window=(0.15, 0.10, 0.78, 0.86), pfmt='b-', lw=1)
    tit = 'number of cpus: %d' % ncpus
    x = atmin - tmin
    y = np.arange(0, ncpus)
    fig, ax = gr.plotGraph(x,y, figsize=(12,10), lw=3) #, window=(0.10, 0.15, 0.78, 0.86))
    gr.set_win_title(fig, titwin=tit) #, **kwa)
    gr.add_title_labels_to_axes(ax, title=tit, xlabel='CPU start-stop time, s', ylabel='CPU index', fslab=18, fstit=20) #, color='k', **kwa):
    x = atmax - tmin
    ax.plot(x, y, 'r-', linewidth=3)
    gr.show() #mode=None)
    fname = os.path.join(DIRNAME, 'img%s' % ptrn.strip('.txt'))
    gr.save_fig(fig, fname=fname, verb=True)
    #gr.save_fig(fig, fname='img.png', prefix=None, suffix='.png', verb=True)
    return tmin, tmax

def test_proc(dirname=DIRNAME, ptrn='-v80.txt', dtmin=None, dtmax=None):
    """Process all files in ``dirname`` whose names contain ``ptrn`` with ``proc_file``, plot their time ranges with ``plot_tmin_tmax``, then process them again within [tmin(+dtmin), tmin+dtmax or tmax] and print the median of the per-file medians (NaN values excluded)."""
    print('test_proc')
    fnames = sorted([name for name in os.listdir(dirname) if ptrn in name])
    nfiles = len(fnames)
    print('number of files: %d' % nfiles)
    arr_tmed_min_max_nsel = np.empty((nfiles, 4))

    for i,fn in enumerate(fnames):
        os.path.join(dirname, fn)
        arr_tmed_min_max_nsel[i,:] = proc_file(os.path.join(dirname, fn))

    print('arr_tmed_min_max:\n', arr_tmed_min_max_nsel)

    #arr_tmed = arr_tmed_min_max_nsel[:,0]
    arr_tmin = arr_tmed_min_max_nsel[:,1]
    arr_tmax = arr_tmed_min_max_nsel[:,2]
    #arr_nsel = arr_tmed_min_max_nsel[:,3]

    tmin, tmax = plot_tmin_tmax(arr_tmin, arr_tmax, ptrn)

    print('number of files: %d' % nfiles)

    print('tmin: %.6f tmax: %.6f' % (tmin, tmax))

    _tmin = tmin if dtmin is None else tmin + dtmin
    _tmax = tmax if dtmax is None else tmin + dtmax

    print('=== repeat processing with time limits - tmin: %.6f tmax: %.6f' % (tmin, tmax))

    for i,fn in enumerate(fnames):
        os.path.join(dirname, fn)
        #dt_med, tmin, tmax = proc_file(os.path.join(dirname, fn))
        arr_tmed_min_max_nsel[i,:] = proc_file(os.path.join(dirname, fn), tmin=_tmin, tmax=_tmax)

    print('arr_tmed_min_max:\n', arr_tmed_min_max_nsel)
    arr_tmed_sel = arr_tmed_min_max_nsel[:,0]
    print('arr_tmed_sel:\n', arr_tmed_sel)

    arr_tmed_sel = [v for v in arr_tmed_sel if not np.isnan(v)]

    tmed_sel = np.median(arr_tmed_sel)
    print('vers%s tmed_sel: %.3f us' % (ptrn.strip('.txt'), tmed_sel))



def argument_parser():
    """Build and return an ArgumentParser with positional ``tname`` and options -k/--dskwargs, -d/--detname and -L/--loglevel (the DataSource and detector options are not used by the tests)."""
    from argparse import ArgumentParser
    d_tname = '0'
    d_dskwargs = 'exp=rixc00121,run=140,dir=/sdf/data/lcls/drpsrcf/ffb/rix/rixc00121/xtc'  # None
    d_detname  = 'archon' # None
    d_loglevel = 'INFO' # 'DEBUG'
    h_tname    = 'test name, usually numeric number, default = %s' % d_tname
    h_dskwargs = '(str) dataset kwargs for DataSource(**kwargs), default = %s' % d_dskwargs
    h_detname  = 'detector name, default = %s' % d_detname
    h_loglevel = 'logging level, one of %s, default = %s' % (', '.join(tuple(logging._nameToLevel.keys())), d_loglevel)
    parser = ArgumentParser(description='%s is a bunch of tests for annual issues' % SCRNAME, usage=usage())
    parser.add_argument('tname',            default=d_tname,    type=str, help=h_tname)
    parser.add_argument('-k', '--dskwargs', default=d_dskwargs, type=str, help=h_dskwargs)
    parser.add_argument('-d', '--detname',  default=d_detname,  type=str, help=h_detname)
    parser.add_argument('-L', '--loglevel', default=d_loglevel, type=str, help=h_loglevel)
    return parser

def usage():
    """Return a usage string made of the script name and the test-selection lines of the ``selector`` source code."""
    import inspect
    return '\n  %s <tname>\n' % sys.argv[0].split('/')[-1]\
    + '\n'.join([s for s in inspect.getsource(selector).split('\n') if "tname ==" in s or "tnum in" in s])

def selector():
    """Parse the command line, configure logging and run ``test_proc`` with the file pattern selected by ``tname`` ('0'-'6' for '-vNN.txt', '10'-'16' for '-sNN.txt'), then exit.

    Without arguments it prints the usage and exits; an unknown test name prints the usage and exits with a message.
    """
    if len(sys.argv) < 2:
        print(usage())
        sys.exit('EXIT due to MISSING PARAMETERS')

    parser = argument_parser()
    args = parser.parse_args()
    #args = Namespace(tname='1', dskwargs='exp=rixc00121,run=140,dir=/sdf/data/lcls/drpsrcf/ffb/rix/rixc00121/xtc', detname='archon', loglevel='INFO')
    #sys.exit('TEST EXIT')

    STRLOGLEV = args.loglevel
    INTLOGLEV = logging._nameToLevel[STRLOGLEV]
    logging.basicConfig(format='[%(levelname).1s] L%(lineno)04d %(filename)s: %(message)s', level=INTLOGLEV)

    tname = args.tname  # sys.argv[1] if len(sys.argv)>1 else '0'
    tnum = int(tname)

    if   tname ==  '0': test_proc(ptrn='-v04.txt') # , dtmin=.25, dtmax=0.4)
    elif tname ==  '1': test_proc(ptrn='-v08.txt') # , dtmin=.25, dtmax=.35)
    elif tname ==  '2': test_proc(ptrn='-v16.txt') # , dtmin=0.2, dtmax=0.7)
    elif tname ==  '3': test_proc(ptrn='-v32.txt') # , dtmin=0.8, dtmax=1.4)
    elif tname ==  '4': test_proc(ptrn='-v64.txt') # , dtmin=1.5, dtmax=5.0)
    elif tname ==  '5': test_proc(ptrn='-v80.txt') # , dtmin=3.0, dtmax=8.0)
    elif tname ==  '6': test_proc(ptrn='-v96.txt') # , dtmin=5.0, dtmax=6.0)
    elif tname == '10': test_proc(ptrn='-s04.txt')
    elif tname == '11': test_proc(ptrn='-s08.txt')
    elif tname == '12': test_proc(ptrn='-s16.txt')
    elif tname == '13': test_proc(ptrn='-s32.txt')
    elif tname == '14': test_proc(ptrn='-s64.txt')
    elif tname == '15': test_proc(ptrn='-s80.txt')
    elif tname == '16': test_proc(ptrn='-s96.txt')
    else:
        print(usage())
        exit('\nTEST "%s" IS NOT IMPLEMENTED'%tname)
    sys.exit(0)


if __name__ == "__main__":
    selector()

# EOF
