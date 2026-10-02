"""Add Python directories of the '$SUBMODULEDIR/epixuhr-3x2-readout-testing/' submodule to the pyrogue library path when imported.

Directories passed to `pr.addLibraryPath`: 'firmware/submodules/AsicRegMapping/python', 'firmware/submodules/axi-pcie-core/python', 'firmware/submodules/pixel-camera-readout-common/python', 'firmware/submodules/lcls-timing-core/python', 'firmware/submodules/l2si-core/python', 'firmware/submodules/surf/python', 'firmware/submodules/ePixViewer/python', 'firmware/submodules/hdl-cores-lib-dev/firmware/python', 'firmware/submodules/lcls2-pgp-fw-lib/python', 'firmware/python'.
The `sys.path` entry it appends is the literal string '%s/firmware/python', because the
code calls ``.format`` on a '%s' template.
"""
import pyrogue as pr
import os
import sys

submoduledir = os.environ["SUBMODULEDIR"]

top_level = submoduledir + "/epixuhr-3x2-readout-testing/"

sys.path.append("%s/firmware/python".format(top_level))

pr.addLibraryPath(top_level+'firmware/submodules/AsicRegMapping/python')
pr.addLibraryPath(top_level+'firmware/submodules/axi-pcie-core/python')
pr.addLibraryPath(top_level+'firmware/submodules/pixel-camera-readout-common/python')
pr.addLibraryPath(top_level+'firmware/submodules/lcls-timing-core/python')
pr.addLibraryPath(top_level+'firmware/submodules/l2si-core/python')
pr.addLibraryPath(top_level+'firmware/submodules/surf/python')
pr.addLibraryPath(top_level+'firmware/submodules/ePixViewer/python')
pr.addLibraryPath(top_level+'firmware/submodules/hdl-cores-lib-dev/firmware/python')
pr.addLibraryPath(top_level+'firmware/submodules/lcls2-pgp-fw-lib/python')
pr.addLibraryPath(top_level+'firmware/python')

