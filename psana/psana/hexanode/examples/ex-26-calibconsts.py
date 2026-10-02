#!/usr/bin/env python

"""Example: print the calibration constants of detector 'tmo_quadanode' for a test xtc2 file, both from the calibration DB web service and from ``det.calibconst``, and the times and waveforms of the first three events."""
import logging
logger = logging.getLogger(__name__)
logging.basicConfig(format='%(levelname)s: %(message)s', datefmt='%Y-%m-%dT%H:%M:%S', level=logging.INFO)

from psana import DataSource
from psana.pyalgos.generic.NDArrUtils import print_ndarr
import psana.pscalib.calib.MDBWebUtils as wu
from psana.hexanode.examples.ex_test_data import DIR_DATA_TEST

FNAME = '%s/%s' % (DIR_DATA_TEST, 'data-amox27716-r0100-acqiris-e000100.xtc2')

def test_calibconst() :

    """Open the test file with ``DataSource``, print run info, constants from ``MDBWebUtils.calib_constants_all_types`` and ``det.calibconst``, then print ``det.raw.times`` and ``det.raw.waveforms`` for events 0-2."""
    DETNAME = 'tmo_quadanode'

    ds = DataSource(files=FNAME) # '/sdf/group/lcls/ds/ana/detector/data2_test/xtc/data-amox27716-r0100-acqiris-e000100.xtc2'
    orun = next(ds.runs())
    print('\nruninfo expt: %s  runnum: %d' % (orun.expt, orun.runnum))

    cc0 = wu.calib_constants_all_types(DETNAME, exp=orun.expt, run=orun.runnum) # , time_sec=None, vers=None, url=cc.URL)
    print(' >>>> calib constants direct access:\n', cc0)

    det = orun.Detector(DETNAME)

    cc = det.calibconst
    print(' >>>> det.calibconst:\n', cc)

    for nev,evt in enumerate(orun.events()):
        if nev>2 : break
        print('Event %d'%nev)
        print_ndarr(det.raw.times(evt),     '  times : ', last=4)
        print_ndarr(det.raw.waveforms(evt), '  wforms: ', last=4)


if __name__ == "__main__" :
    test_calibconst()

# EOF
