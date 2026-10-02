#!/usr/bin/env python

#import h5py                    
"""Command-line script: convert a numpy .npy array file to a text file with ``np.savetxt``.

Usage: ``convert_npy_to_txt.py fname.npy fname.txt``.
"""
import numpy as np             
import sys
import os

##-----------------------------------------------------

def print_exit(case) :
    """Exit via ``sys.exit`` with the used command and a message for ``case`` (1: wrong arguments, 2: input extension is not '.npy')."""
    msg = 'Used command: %s' % ' '.join(sys.argv)
    if case == 1 : msg += '\nExpected command: %s fname.npy fname.txt' % (os.path.basename(sys.argv[0]))
    if case == 2 : msg += '\nExpected extension for file %s is ".npy"' % (os.path.basename(sys.argv[1]))
    sys.exit('%s\nCONVERSION ABORTED' % msg)

##-----------------------------------------------------

def parse_input_pars() :
    #print('len(sys.argv)', len(sys.argv))
    #print(sys.argv)
    
    """Return ``(finp, fout)`` from ``sys.argv``; exits via ``print_exit`` unless there are exactly two arguments and the first ends with '.npy'."""
    if len(sys.argv)!=3 : print_exit(1) 

    finp = sys.argv[1]
    fout = sys.argv[2]

    if os.path.splitext(finp)[1] != '.npy' : print_exit(2) 

    return finp, fout

##-----------------------------------------------------

def do_main() :

    """Load the input .npy array, reshape it to 2-d or 1-d and write it as text with format '%f'.

    Arrays of size 32*185*388 become (32*185, 388); arrays of size 2*185*388 become (185*388, 2) or (2, 185*388) depending on whether the last dimension is 2 or 388 (otherwise unchanged); all others are flattened.
    """
    finp, fout = parse_input_pars()

    nda =  np.load(finp)

    print('Convert %s to %s' % (finp, fout))

    if   nda.size == 32*185*388 : nda.shape = (32*185, 388)
    elif nda.size ==  2*185*388 :
        if nda.shape[-1] ==   2 : nda.shape = (185*388, 2)
        if nda.shape[-1] == 388 : nda.shape = (2, 185*388)
    else                        : nda.shape = (nda.size,)

    np.savetxt('%s' % fout, nda, fmt = "%f")

##-----------------------------------------------------

if __name__ == '__main__':
    do_main()
    sys.exit()

##-----------------------------------------------------

