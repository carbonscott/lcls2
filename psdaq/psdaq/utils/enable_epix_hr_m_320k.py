"""Add Python directories of the '$SUBMODULEDIR/epix-hr-m-320k/' submodule to the pyrogue library path when imported.

Directories passed to `pr.addLibraryPath`: 'firmware/submodules/epix-hr-leap-common/python', 'firmware/submodules/epix-hr-core/python', 'firmware/submodules/lcls-timing-core/python', 'firmware/submodules/l2si-core/python', 'firmware/submodules/surf/python', 'firmware/python', 'firmware/submodules/axi-pcie-core/python', 'firmware/submodules/AsicRegMapping/python'.
The `sys.path` entry it appends is the literal string '%s/firmware/python', because the
code calls ``.format`` on a '%s' template.
"""
import pyrogue as pr
import os
import sys

submoduledir = os.environ["SUBMODULEDIR"]

top_level = submoduledir + "/epix-hr-m-320k/"

sys.path.append("%s/firmware/python".format(top_level))

pr.addLibraryPath(top_level+'firmware/submodules/epix-hr-leap-common/python')
pr.addLibraryPath(top_level+'firmware/submodules/epix-hr-core/python')
pr.addLibraryPath(top_level+'firmware/submodules/lcls-timing-core/python')
pr.addLibraryPath(top_level+'firmware/submodules/l2si-core/python')
pr.addLibraryPath(top_level+'firmware/submodules/surf/python')
pr.addLibraryPath(top_level+'firmware/python')


# Modified by psdm

#pr.addLibraryPath(top_level+'firmware/python/ePixViewer/software')
pr.addLibraryPath(top_level+'firmware/submodules/axi-pcie-core/python/')
pr.addLibraryPath(top_level+'firmware/submodules/AsicRegMapping/python/')

