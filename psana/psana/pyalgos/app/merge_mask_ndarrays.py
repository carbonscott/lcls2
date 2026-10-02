####!/usr/bin/env python

"""Command-line script: merge text arrays by element-wise maximum.

Usage: ``merge_mask_ndarrays.py f1.txt f2.txt ... fout``; the result is written to '<fout>.txt'.
"""
import numpy as np
import sys
import os


def print_exit(case) :

    """Exit via ``sys.exit`` with the used command and, for ``case`` 1, a usage message."""
    msg = 'Used command: %s' % ' '.join(sys.argv)
    usg = 'Usage:  %s f1.txt f2.txt ... fout.txt  (At least 3 file names should be specified!)\n' % os.path.basename(sys.argv[0])

    if case == 1 : msg += '\nWrong number of arguments.\n%s' % (usg)

    sys.exit('%s\nMERGING ABORTED' % msg)


def parse_input_pars() :

    #print('len(sys.argv)', len(sys.argv))
    #print(sys.argv)

    """Return ``(list_of_files, ofname)``: all arguments except the last, and the last argument.

    Exits via ``print_exit(1)`` if fewer than three file names are given.
    """
    if len(sys.argv)<4 : print_exit(1)

    list_of_files = [fname for fname in sys.argv[1:-1]]
    ofname = sys.argv[-1]

    #print('Input files:')
    #for fname in list_of_files : print(fname)
    #print('Output file: %s' % ofname)

    return list_of_files, ofname


def do_main() :

    """Load each input text file as float32, combine them with ``np.maximum`` and save the result to '<ofname>.txt' with format '%i'.

    The printed message also names '<ofname>.npy', but only the .txt file is written.
    """
    list_of_files, ofname = parse_input_pars()

    nda = None

    for i, file in enumerate(list_of_files) :
        print('Load array from file %s' % file)
        if i<1 : nda = np.loadtxt(file, dtype=np.float32)
        else   : nda = np.maximum(nda, np.loadtxt(file, dtype=np.float32))
        #    nda2 = np.loadtxt(file, dtype=np.float32)
        #    print(nda [0,0:5])
        #    print(nda2[0,0:5])
        #    nda = np.maximum(nda, nda2)
        #    print(nda [0,0:5])

    print('nda.shape =\n', nda.shape)

    print('Save files %s.txt and %s.npy' % (ofname, ofname))

    np.savetxt('%s.txt' % ofname, nda, fmt = "%i")

    #nda.shape = (32,185,388)
    #np.save   ('%s.npy' % ofname, nda)


if __name__ == '__main__':

    do_main()

    sys.exit('End of script')

# EOF

