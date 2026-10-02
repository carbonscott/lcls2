"""Print the rates obtained by dividing 1300e6/7 Hz by every product of the factors [2, 2, 5, 5, 13]."""
import sys
import argparse
import itertools
import numpy as np

def main():
    """Print a table of rate (Hz), divisor and the factors used, for divisor 1 and every combination product of the factors."""
    parser = argparse.ArgumentParser(description='Find all RF solutions')
    args = parser.parse_args()

    factors = [2,2,5,5,13] # product is 1300
    base = 1300.e6/7.

    iters = [itertools.combinations(factors,i+1) for i in range(len(factors))]
    f = set()
    d = {}
    for i in iters:
        for c in i:
            q = np.prod(np.array(c))
            f.add(q)
            d[q] = c

    f.add(1)
    d[1] = 1

    print(' rate, Hz  | factor | factors')
    for q in sorted(f):
        print(' {:6d}     {:6d}   {}'.format(int(base/float(q)),q,d[q]))
        

if __name__ == '__main__':
    main()
