
"""Example: print a message and call ``ctest_resort()`` from the compiled extension ``psana.hexanode_ext``; the work is done in the extension and is not visible here."""
import sys
from psana.hexanode_ext import ctest_resort
print('In hexanode/examples/ex-02-ctest_resort.py')
ctest_resort()

#------------------------------
