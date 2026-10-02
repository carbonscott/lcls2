#!/usr/bin/env python
"""Example: write test constants to a text file and print the ``cdb add`` command that would upload them.

Run as a script with test name ``'0'`` (``delayed_denom`` array) or ``'1'`` (``fir_coefficients`` dict).
"""

import numpy as np
from psana.pyalgos.generic.NDArrUtils import print_ndarr
from psana.pscalib.calib.NDArrIO import save_txt
from psana.pyalgos.generic.Utils import save_textfile

#----------

def fir_coefficients() : 
    """Return a hard-coded dict of FIR coefficient strings and the ctype name ``'fir_coefficients'``."""
    return {'CoefficientSet0': '7f7f7f7f', 'CoefficientSet1': '7f7f7f7f', 'CoefficientSet2': '7f7f7f7f', 'CoefficientSet3': '7f7f7f7f', 'CoefficientSet4': '81818181', 'CoefficientSet5': '81818181', 'CoefficientSet6': '81818181', 'CoefficientSet7': '81818181', 'LoadCoefficients': '1'}, 'fir_coefficients'

#----------

def delayed_denom() : 
    """Return ``numpy.ones((2048,), dtype=numpy.uint8)`` and the ctype name ``'delayed_denom'``."""
    return np.ones((2048,), dtype=np.uint8), 'delayed_denom'

#----------

def save_constants_in_file(tname, fname='0-end.txt') : 
    """Save test constants to ``fname`` and print a reminder with the matching ``cdb add`` command.

    ``tname='0'`` saves the ``delayed_denom`` array with ``NDArrIO.save_txt``; ``'1'`` saves the string form
    of the ``fir_coefficients`` dict with ``save_textfile``. Any other ``tname`` leaves ``cmd`` undefined and
    raises NameError.
    """
    if tname == '0' :
        nda, ctype = delayed_denom()
        print_ndarr(nda, 'nda for ctype: %s' % ctype)
        save_txt(fname, nda, cmts=(), fmt='%d', verbos=True, addmetad=True)
        cmd = 'cdb add -e tmo -d tmott -c %s -r 1 -f %s -u dubrovin' % (ctype, fname)

    elif tname == '1' :
        d, ctype = fir_coefficients()
        print('dict:',d)
        save_textfile(str(d), fname, mode='w', verb=True) 
        cmd = 'cdb add -e tmo -d tmott -c %s -r 1 -f %s -i txt -u dubrovin' % (ctype, fname)

    msg = 'DO NOT FORGET ADD CONSTS TO DB: %s' % cmd
    print(msg)

#----------

if __name__ == "__main__" :
    import sys
    scrname = sys.argv[0]
    tname = sys.argv[1] if len(sys.argv) > 1 else '0'
    print(50*'_', '\nTest %s:' % tname)
    if tname in ('0','1') : save_constants_in_file(tname);
    else : print('Not-recognized test name: %s' % tname)
    sys.exit('End of test %s %s' % (scrname, tname))
 
#----------
