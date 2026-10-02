# this sys.path.append is a hack to allow each package to import its
# own version of device-specific submodules (surf/axi-pcie-core etc.) that
# have been placed as subdirectories here by setup.py.  ryan herbst
# thinks of these packages as a device-specific "board support package".
# this allows one to put multiple devices in the same conda env.
# a cleaner approach would be to use relative imports everywhere, but
# that would be a lot of work for the tid-air people - cpo.
"""Package `psdaq.pyhpsbld`: importing it inserts this package's directory at the front of `sys.path`.

Per the comments here, this lets the package import its own copies of device-specific
submodules by their top-level names.
"""
import sys
import os
sys.path.insert(0,os.path.dirname(os.path.realpath(__file__)))
