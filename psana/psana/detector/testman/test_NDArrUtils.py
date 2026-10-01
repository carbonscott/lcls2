#!/usr/bin/env python

"""Manual check script: imports everything from `psana.detector.NDArrUtils`, prints the import time
and the names now defined, then calls `sys.exit`. The code runs at import time (no main guard).
"""
from time import time
t0_sec = time()
from psana.detector.NDArrUtils import *
print('import psana.detector.NDArrUtils time = %.6f sec' % (time()-t0_sec))
print('available methods:\n', dir())
import sys
sys.exit('END OF %s' % sys.argv[0].rsplit('/')[-1])

# EOF
