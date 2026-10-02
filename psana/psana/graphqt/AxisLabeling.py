
"""
:py:class:`Extended` - method best_label_locs returns list of best labels
=========================================================================

An alpha version of the Talbot, Lin, Hanrahan tick mark generator for matplotlib.
Described in "An Extension of Wilkinson's Algorithm for Positioning Tick Labels on Axes"
by Justin Talbot, Sharon Lin, and Pat Hanrahan, InfoVis 2010.

Implementation by Justin Talbot
This implementation is in the public domain.
Report bugs to jtalbot@stanford.edu

A shortcoming:
   The weights used in the paper were designed for static plots where the extent of
   the tick marks unioned with the extent of the data defines the extent of the plot.
   In a plot where the extent of the plot is defined by the user (e.g. an interactive
   plot supporting panning and zooming), the weights don't work as well. In particular,
   you would want to retune them assuming that the tick labels must be inside
   the provided view range. You probably want higher weighting on simplicity and lower
   on coverage and possibly density. But I haven't experimented in any detail with this.

   If you do intend on using this for static plots in matplotlib, you should set
   only_inside to False in the call to Extended.extended. And then you should
   manually set your view extent to include the min and max ticks if they are outside
   the data range. This should produce the same results as the paper.

Usage::

    # Import
    from psana.graphqt.AxisLabeling import best_label_locs

    # Methods (see test)
    locs = best_label_locs(vmin, vmax, size, density=1, steps=None)

from http://www.justintalbot.com/research/axis-labeling/
Authors: Talbot, Lin, Hanrahan
Created 2015-12-05 by Mikhail Dubrovin
Adopted for LCLS2 on 2018-02-16
"""

import math
import numpy as np


class Extended():

    """Tick-label position search after Talbot, Lin and Hanrahan ("extended Wilkinson" algorithm).

    The constructor stores ``density`` and ``steps`` (default ``[1, 5, 2, 2.5, 4, 3]``) in
    ``_density`` and ``_steps``; :meth:`extended` does not read them and uses its own ``Q`` argument.
    """
    def __init__(self, density = 1, steps = None):
        """
        Keyword args:
        """
        self._density = density

        if steps is None:
            self._steps = [1, 5, 2, 2.5, 4, 3]
        else:
            self._steps = steps


    def coverage(self, dmin, dmax, lmin, lmax):
        """Return the coverage score ``1 - 0.5*((dmax-lmax)**2 + (dmin-lmin)**2) / (0.1*(dmax-dmin))**2``.

        Raises ZeroDivisionError if ``dmax == dmin``.
        """
        drange = dmax-dmin
        return 1 - 0.5 * (math.pow(dmax-lmax, 2)+math.pow(dmin-lmin, 2)) / math.pow(0.1 * drange, 2)


    def coverage_max(self, dmin, dmax, span):
        """Return the upper bound of the coverage score for a label span ``span``.

        Returns 1 if ``span`` does not exceed the data range, otherwise
        ``1 - ((span-drange)/2)**2 / (0.1*drange)**2``; a zero range is replaced by 1e-10.
        """
        drange = dmax-dmin
        if drange == 0: drange = 1e-10
        if span > drange:
            half = (span-drange)/2.0
            return 1 - math.pow(half, 2) / math.pow(0.1*drange, 2)
        else:
            return 1


    def density(self, k, m, dmin, dmax, lmin, lmax):
        """Return the density score ``2 - max(r/rt, rt/r)``.

        ``r = (k-1)/(lmax-lmin)`` is the label density and ``rt = (m-1)/(max(lmax, dmax) - min(lmin, dmin))``
        the target density.
        """
        r = (k-1.0) / (lmax-lmin)
        rt = (m-1.0) / (max(lmax, dmax) - min(lmin, dmin))
        return 2 - max( r/rt, rt/r )


    def density_max(self, k, m):
        """Return ``2 - (k-1)/(m-1)`` if ``k >= m``, otherwise 1."""
        if k >= m:
            return 2 - (k-1.0)/(m-1.0)
        else:
            return 1


    def simplicity(self, q, Q, j, lmin, lmax, lstep):
        """Return the simplicity score ``(n-i)/(n-1) + v - j``.

        ``n = len(Q)``, ``i`` is the 1-based index of ``q`` in ``Q``, and ``v`` is 1 if ``lmin`` is a
        multiple of ``lstep`` (within 1e-10) and the range ``[lmin, lmax]`` contains 0, else 0.
        """
        eps = 1e-10
        n = len(Q)
        i = Q.index(q)+1
        v = 1 if ((lmin % lstep < eps or (lstep - lmin % lstep) < eps) and lmin <= 0 and lmax >= 0) else 0
        return (n-i)/(n-1.0) + v - j


    def simplicity_max(self, q, Q, j):
        """Return the upper bound of the simplicity score, ``(n-i)/(n-1) + 1 - j`` with ``i`` the 1-based index of ``q`` in ``Q``."""
        n = len(Q)
        i = Q.index(q)+1
        v = 1
        return (n-i)/(n-1.0) + v - j


    def legibility(self, lmin, lmax, lstep):
        """Return 1; legibility is not evaluated."""
        return 1


    def legibility_max(self, lmin, lmax, lstep):
        """Return 1; legibility is not evaluated."""
        return 1


    def extended(self, dmin, dmax, m, Q=[1,5,2,2.5,4,3], only_inside=False, w=[0.25,0.2,0.5,0.05]):
        #n = len(Q)
        """Search label sets and return the one with the highest weighted score.

        Loops over skip factor ``j``, step ``q`` in ``Q``, label count ``k`` and power of ten ``z``, pruning
        with the ``*_max`` bounds; the score is ``w[0]*simplicity + w[1]*coverage + w[2]*density + w[3]*legibility``.

        Parameters
        ----------
        dmin, dmax : float
            Data range.
        m : float
            Target number of labels.
        Q : list
            Preferred step multipliers.
        only_inside : bool
            If True, only label sets with ``lmin >= dmin`` and ``lmax <= dmax`` are accepted.
        w : list of float
            Four score weights.

        Returns
        -------
        tuple
            ``(lmin, lmax, lstep, q, k)`` of the best set; ``(dmin, dmax, dmax-dmin, 1, 2)`` if none scores above -2.
        """
        best_score = -2.0
        best = (dmin, dmax, (dmax-dmin), 1, 2)

        j = 1.0
        while j < float('infinity'):
            for q in Q:
                sm = self.simplicity_max(q, Q, j)

                if w[0] * sm + w[1] + w[2] + w[3] < best_score:
                    j = float('infinity')
                    break

                k = 2.0
                while k < float('infinity'):
                    dm = self.density_max(k, m)

                    if w[0] * sm + w[1] + w[2] * dm + w[3] < best_score:
                        break

                    delta = (dmax-dmin)/(k+1.0)/j/q
                    if delta<=0: delta = 1e-6
                    z = math.ceil(math.log(delta, 10))

                    while z < float('infinity'):
                        step = j*q*math.pow(10,z)
                        cm = self.coverage_max(dmin, dmax, step*(k-1.0))

                        if w[0] * sm + w[1] * cm + w[2] * dm + w[3] < best_score:
                            break

                        min_start = math.floor(dmax/step)*j - (k-1.0)*j
                        max_start = math.ceil(dmin/step)*j

                        if min_start > max_start:
                            z = z+1
                            break

                        for start in range(int(min_start), int(max_start)+1):
                            lmin = start * (step/j)
                            lmax = lmin + step*(k-1.0)
                            lstep = step

                            s = self.simplicity(q, Q, j, lmin, lmax, lstep)
                            c = self.coverage(dmin, dmax, lmin, lmax)
                            d = self.density(k, m, dmin, dmax, lmin, lmax)
                            l = self.legibility(lmin, lmax, lstep)

                            score = w[0] * s + w[1] * c + w[2] * d + w[3] * l

                            if score > best_score and (not only_inside or (lmin >= dmin and lmax <= dmax)):
                                best_score = score
                                best = (lmin, lmax, lstep, q, k)
                        z = z+1
                    k = k+1
            j = j+1
        return best


def best_label_locs(vmin, vmax, size_inches, density=1, steps=None):
    """Return tick label positions for the range ``vmin``..``vmax``.

    Calls ``Extended(density, steps).extended`` with target count ``density*size_inches + 1``,
    ``only_inside=True`` and weights ``[0.25, 0.2, 0.5, 0.05]``.

    Returns
    -------
    numpy.ndarray
        ``lmin + lstep*arange(k)`` from the best label set.
    """
    size = size_inches

    # density * size gives target number of intervals,
    # density * size + 1 gives target number of tick marks,
    # the density function converts this back to a density in data units (not inches)
    # should probably make this cleaner.

    axlab = Extended(density, steps)
    best = axlab.extended(vmin, vmax, density * size + 1.0, only_inside=True, w=[0.25, 0.2, 0.5, 0.05])
    locs = np.arange(best[4]) * best[2] + best[0]
    return locs # ex.: [-20. -10.   0.  10.  20.]


def test():

    """Print the label positions from :func:`best_label_locs` for three hard-coded ranges and sizes."""
    list_of_tests = ((-27.3, 55.4, 4.125),\
                     (25.1, 31.6, 6.125),\
                     (0.1, 0.2, 2.5))

    for i,(vmin, vmax, size) in enumerate(list_of_tests):
      print('\nTest# %d:  vmin, vmax, size ='%i, vmin, vmax, size,)
      locs = best_label_locs(vmin, vmax, size, density=1, steps=None)
      print('   best locs:', locs)


if __name__ == '__main__':
    test()

# EOF
