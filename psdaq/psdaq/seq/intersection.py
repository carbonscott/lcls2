"""Find where several series with constant intervals and offsets coincide, using sympy's `diop_solve`."""
import numpy as np
from sympy.solvers.diophantine import diop_solve
from sympy.abc import x,y
from sympy import symbols

#
#  Given several series with constant intervals and offsets, find the interval and offset
#  where they all coincidece.
#  Returns (None,None) if no intersection exists.
#
def intersection(offsets, intervals):

    """Return the (offset, interval) at which all series coincide.

    The series are reduced pairwise with linear Diophantine solutions; the interval is the
    LCM and the offset is reduced into [0, interval).

    Returns
    -------
    tuple
        (offset, interval), or (None, None) if a pair has no solution.

    Raises
    ------
    ValueError
        If fewer than 2 series are given or the lists differ in length.
    """
    if len(offsets) < 2:
        raise ValueError(f'intersection requires at least 2 series')

    if len(offsets) != len(intervals):
        raise ValueError(f'offsets ({len(offsets)}) and intervals ({len(intervals)}) lists are not equal length')

    itv = intervals[0]
    off = offsets  [0]
    syms = (x,y)
    t_0 = symbols("t_0", integer=True)

    #  Reduce the first pair into one, then reduce with the next, and so on
    for i in range(1,len(offsets)):
        eqn = offsets[i]-off+intervals[i]*y-itv*x
        sol = diop_solve(eqn)
        itv = np.lcm.reduce([itv,intervals[i]])

        if sol[0] is None:
            return (None,None)
            #raise ValueError(f'No intersection found')

        #  Get the first offset >= 0
        off = sol.subs(t_0,0)[1]*intervals[i]+offsets[i]
        off = off - int(off/itv)*itv

    return (off,itv)

def main():
    """Print ``intersection([0, 0, 364*12], [280, 364, 4732])``."""
    result = intersection([0,0,364*12],[280,364,4732])
    print(f'result {result}')

if __name__ == '__main__':
    main()
