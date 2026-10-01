#!/usr/bin/env python

"""Manual test of the `UtilsMask` shape masks: `python test_UtilsMask.py <test-name> <loglevel>`.

Tests 1 to 9 show a random image, circle, ring, rectangle, polygon, three half-planes and an arc.
The code runs at import time and ends with `sys.exit`.
"""
import sys
SCRNAME = sys.argv[0].rsplit('/')[-1]
STRLOGLEV = sys.argv[2] if len(sys.argv)>2 else 'INFO'

import logging
INTLOGLEV = logging._nameToLevel[STRLOGLEV]
logger = logging.getLogger(__name__)
logging.basicConfig(format='[%(levelname).1s] L%(lineno)04d %(filename)s: %(message)s', level=INTLOGLEV)

from psana.detector.NDArrUtils import info_ndarr
#from psana.detector.calibconstants import CalibConstants
#from psana.detector.mask_algos import DTYPE_MASK  # MaskAlgos
import psana.detector.UtilsGraphics as ug
import psana.detector.UtilsMask as um

def test_mask_select(tname):
    """Return the test mask for `tname`, or None for unknown names, and log it.

    '1' random values, '2' circle, '3' ring, '4' rectangle, '5' polygon, '6' to '8' half-planes
    bounded by a tilted, horizontal and vertical line (100x120 image), '9' arc on a 1024x1024 image.
    """
    mask = None
    shape = (100, 120)
    dtype=um.np.uint8

    if tname == '1':
        import psana.pyalgos.generic.NDArrGenerators as ag
        mask = ag.random_standard(shape=shape, mu=0, sigma=0.5, dtype=float)

    elif tname == '2':
        rowc, colc, radius = 30, 40, 35
        mask = um.mask_circle(shape, rowc, colc, radius, dtype=dtype)

    elif tname == '3':
        rowc, colc, radmin, radmax = 30, 50, 35, 45
        mask = um.mask_ring(shape, rowc, colc, radmin, radmax, dtype=dtype)

    elif tname == '4':
        #xmin, ymin, w, h = 30, 40, 35, 45
        cmin, rmin, cols, rows = 20, 40, 60, 30
        mask = um.mask_rectangle(shape, cmin, rmin, cols, rows, dtype=dtype)

    elif tname == '5':
        poly_colrows = [(10,20), (80,90), (110,50), (100,10), (50,40)]
        mask = um.mask_poly(shape, poly_colrows, dtype=um.np.uint8)

    elif tname == '6':
        #r1, c1, r2, c2, rm, cm = 10, 10, 50, 50, 50, 10
        r1, c1, r2, c2, rm, cm = 10, 10, 50, 50, 10, 50
        mask = um.mask_halfplane(shape, r1, c1, r2, c2, rm, cm, dtype=dtype)

    elif tname == '7':
        r1, c1, r2, c2, rm, cm = 50, 10, 50, 90, 10, 10
        mask = um.mask_halfplane(shape, r1, c1, r2, c2, rm, cm, dtype=dtype)

    elif tname == '8':
        r1, c1, r2, c2, rm, cm = 10, 50, 90, 50, 10, 10
        mask = um.mask_halfplane(shape, r1, c1, r2, c2, rm, cm, dtype=dtype)

    elif tname == '9':
        #shape = (1000, 1200)
        #cx, cy, ro, ri, ao, ai = 500, 500, 250, 200, -30, 280
        shape = (1024, 1024)
        cx, cy, ro, ri, ao, ai = 200., 200., 442., 153., 13., 107.
        #cx, cy, ro, ri, ao, ai = 200, 200, 442, 153, 13, 107
        mask = um.mask_arc(shape, cx, cy, ro, ri, ao, ai, dtype=dtype)

    else:
        mask = None

    logger.info(info_ndarr(mask, 'mask'))
    return mask


def test_UtilsMask(tname):
    """Show the mask from `test_mask_select(tname)` with `fleximagespec` (limits 0 to 2) and return True.

    Returns False if there is no mask for `tname`.
    """

    img = test_mask_select(tname)

    if img is None: return False

    logger.info(info_ndarr(img, 'img'))

    flimg = ug.fleximagespec(img, arr=None, amin=0, amax=2) # nneg=6, npos=6)  #fraclo=0.01, frachi=0.99) #, amin=0, amax=2)
    flimg.axtitle(title='test_mask %s' % tname)
    #   ug.gr.show(mode='DO NOT HOLD')
    ug.gr.show()

    return True


USAGE = '\nUsage:'\
      + '\n  python %s <test-name> <loglevel e.g. DEBUG or INFO>' % SCRNAME\
      + '\n  where test-name: '\
      + '\n   1 - random image'\
      + '\n   2 - mask_circle'\
      + '\n   3 - mask_ring'\
      + '\n   4 - mask_rectangle'\
      + '\n   5 - mask_poly'\
      + '\n   6 - mask_hemiplane - tilted line'\
      + '\n   7 - mask_hemiplane - horizontal line'\
      + '\n   8 - mask_hemiplane - vertical line'\
      + '\n   9 - mask_arc'\


TNAME = sys.argv[1] if len(sys.argv)>1 else '0'

logging.info(USAGE)
isok = test_UtilsMask(TNAME)
sys.exit('TEST %s IS %s' % (TNAME, 'COMPLETED' if isok else 'NOT IMPLEMENTED'))

#if __name__ == "__main__":
# EOF
